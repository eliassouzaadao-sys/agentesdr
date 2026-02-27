"""
Serviço Redis para:
- Buffer de mensagens (debounce)
- Bloqueio de chat (intervenção humana)
- Armazenamento de mensagens da IA
- Memória de conversação
"""
import redis.asyncio as redis
from typing import Optional, List
import json
import logging

from config import get_settings

logger = logging.getLogger(__name__)


class RedisService:
    """Gerenciador de estado com Redis"""

    def __init__(self):
        self.settings = get_settings()
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """Conecta ao Redis"""
        if not self.client:
            self.client = redis.from_url(
                self.settings.redis_url, encoding="utf-8", decode_responses=True
            )
            logger.info("Conectado ao Redis")

    async def disconnect(self):
        """Desconecta do Redis"""
        if self.client:
            await self.client.close()
            self.client = None

    # ==================== DEBOUNCE ====================

    async def add_to_buffer(self, sender: str, message: str) -> None:
        """Adiciona mensagem ao buffer de debounce"""
        key = f"{sender}_debounce"
        await self.client.rpush(key, message)
        await self.client.expire(key, self.settings.redis_ttl_debounce * 2)

    async def get_buffer_messages(self, sender: str) -> List[str]:
        """Recupera todas as mensagens do buffer"""
        key = f"{sender}_debounce"
        messages = await self.client.lrange(key, 0, -1)
        return messages or []

    async def clear_buffer(self, sender: str) -> None:
        """Limpa o buffer de mensagens"""
        key = f"{sender}_debounce"
        await self.client.delete(key)

    async def get_last_buffer_message(self, sender: str) -> Optional[str]:
        """Recupera a última mensagem do buffer"""
        key = f"{sender}_debounce"
        messages = await self.client.lrange(key, -1, -1)
        return messages[0] if messages else None

    # ==================== BLOQUEIO (INTERVENÇÃO HUMANA) ====================

    async def block_chat(self, sender: str) -> None:
        """Bloqueia o chat para intervenção humana"""
        key = f"{sender}_block"
        await self.client.set(key, "true", ex=self.settings.redis_ttl_block)
        logger.info(f"Chat bloqueado para {sender}")

    async def unblock_chat(self, sender: str) -> None:
        """Desbloqueia o chat"""
        key = f"{sender}_block"
        await self.client.delete(key)
        logger.info(f"Chat desbloqueado para {sender}")

    async def is_chat_blocked(self, sender: str) -> bool:
        """Verifica se o chat está bloqueado"""
        key = f"{sender}_block"
        result = await self.client.get(key)
        return result == "true"

    # ==================== MENSAGENS DA IA ====================

    async def add_ai_message(self, sender: str, message: str) -> None:
        """Adiciona mensagem enviada pela IA para rastreamento"""
        key = f"{sender}_ai_messages"
        await self.client.rpush(key, message)
        # Mantém apenas as últimas 50 mensagens
        await self.client.ltrim(key, -50, -1)
        await self.client.expire(key, 86400)  # 24 horas

    async def get_ai_messages(self, sender: str) -> List[str]:
        """Recupera mensagens enviadas pela IA"""
        key = f"{sender}_ai_messages"
        messages = await self.client.lrange(key, 0, -1)
        return messages or []

    async def is_ai_message(self, sender: str, message: str) -> bool:
        """Verifica se a mensagem foi enviada pela IA"""
        messages = await self.get_ai_messages(sender)
        message_clean = message.replace("\n", " ").strip()
        return any(message_clean in msg for msg in messages)

    # ==================== MEMÓRIA DE CONVERSAÇÃO ====================

    async def get_conversation_history(
        self, sender: str, limit: int = 20
    ) -> List[dict]:
        """Recupera histórico de conversação"""
        key = f"{sender}_history"
        history = await self.client.lrange(key, -limit, -1)
        return [json.loads(msg) for msg in history] if history else []

    async def add_to_history(self, sender: str, role: str, content: str) -> None:
        """Adiciona mensagem ao histórico"""
        key = f"{sender}_history"
        message = json.dumps({"role": role, "content": content})
        await self.client.rpush(key, message)
        # Mantém apenas as últimas 40 mensagens
        await self.client.ltrim(key, -40, -1)
        await self.client.expire(key, 86400 * 7)  # 7 dias

    async def add_to_history_with_summarization(
        self,
        sender: str,
        role: str,
        content: str,
        summarize_callback=None,
        max_messages: int = 30,
        keep_recent: int = 10
    ) -> None:
        """
        Adiciona mensagem ao histórico com sumarização automática.
        Quando o histórico excede max_messages, sumariza as mensagens antigas
        e mantém apenas as keep_recent mais recentes + o resumo.

        Args:
            sender: ID do remetente
            role: Role da mensagem (user/assistant)
            content: Conteúdo da mensagem
            summarize_callback: Função async que recebe lista de mensagens e retorna resumo
            max_messages: Número máximo antes de sumarizar
            keep_recent: Quantidade de mensagens recentes a manter
        """
        key = f"{sender}_history"
        summary_key = f"{sender}_summary"

        # Adiciona nova mensagem
        message = json.dumps({"role": role, "content": content})
        await self.client.rpush(key, message)

        # Verifica se precisa sumarizar
        history_len = await self.client.llen(key)

        if history_len > max_messages and summarize_callback:
            logger.info(f"Histórico de {sender} tem {history_len} msgs - sumarizando...")

            # Pega todas as mensagens
            all_messages = await self.client.lrange(key, 0, -1)
            all_messages = [json.loads(msg) for msg in all_messages]

            # Separa mensagens antigas para sumarizar
            messages_to_summarize = all_messages[:-keep_recent]
            recent_messages = all_messages[-keep_recent:]

            # Pega resumo anterior se existir
            previous_summary = await self.client.get(summary_key)

            try:
                # Gera novo resumo incluindo o anterior
                if previous_summary:
                    summary_context = f"Resumo anterior: {previous_summary}\n\nNovas mensagens para incluir:"
                    new_summary = await summarize_callback(messages_to_summarize, summary_context)
                else:
                    new_summary = await summarize_callback(messages_to_summarize)

                if new_summary:
                    # Salva novo resumo
                    await self.client.set(summary_key, new_summary, ex=86400 * 30)  # 30 dias

                    # Limpa histórico e adiciona mensagens recentes
                    await self.client.delete(key)
                    for msg in recent_messages:
                        await self.client.rpush(key, json.dumps(msg))

                    logger.info(f"Histórico de {sender} sumarizado: {len(messages_to_summarize)} msgs -> resumo + {len(recent_messages)} recentes")

            except Exception as e:
                logger.error(f"Erro ao sumarizar histórico: {e}")

        await self.client.expire(key, 86400 * 7)  # 7 dias

    async def get_conversation_summary(self, sender: str) -> Optional[str]:
        """Retorna o resumo armazenado da conversação"""
        summary_key = f"{sender}_summary"
        return await self.client.get(summary_key)

    async def get_history_with_summary(self, sender: str, limit: int = 20) -> List[dict]:
        """
        Retorna histórico de conversação incluindo resumo como contexto.
        Se houver resumo, adiciona como primeira mensagem de sistema.
        """
        summary = await self.get_conversation_summary(sender)
        history = await self.get_conversation_history(sender, limit)

        if summary:
            # Adiciona resumo como contexto no início
            summary_message = {
                "role": "system",
                "content": f"Resumo da conversa anterior: {summary}"
            }
            return [summary_message] + history

        return history

    async def clear_history(self, sender: str) -> None:
        """Limpa histórico de conversação"""
        key = f"{sender}_history"
        await self.client.delete(key)

    # ==================== ESTADO DO LEAD ====================

    async def set_lead_state(self, sender: str, state: dict) -> None:
        """Salva estado do lead (etapa SPIN, qualificação, etc.)"""
        key = f"{sender}_state"
        await self.client.set(key, json.dumps(state), ex=86400 * 30)  # 30 dias

    async def get_lead_state(self, sender: str) -> Optional[dict]:
        """
        Recupera estado do lead.
        Tenta múltiplos formatos de número brasileiro para garantir que encontre
        o estado mais completo (com segmento).
        """
        key = f"{sender}_state"
        state = await self.client.get(key)
        state_dict = json.loads(state) if state else None

        # Se encontrou estado completo (com segmento), retorna
        if state_dict and state_dict.get("segmento"):
            return state_dict

        # Tenta formato alternativo do número brasileiro
        digits = sender.replace("@s.whatsapp.net", "")
        alt_state_dict = None

        # Se tem 12 dígitos (55 + DDD + 8), tenta com 9 extra
        if len(digits) == 12 and digits.startswith("55"):
            alt_sender = f"55{digits[2:4]}9{digits[4:]}@s.whatsapp.net"
            alt_key = f"{alt_sender}_state"
            alt_state = await self.client.get(alt_key)
            if alt_state:
                alt_state_dict = json.loads(alt_state)
                logger.info(f"Estado encontrado com formato alternativo: {alt_sender}")

        # Se tem 13 dígitos (55 + DDD + 9 + 8), tenta sem o 9
        elif len(digits) == 13 and digits.startswith("55") and digits[4] == "9":
            alt_sender = f"55{digits[2:4]}{digits[5:]}@s.whatsapp.net"
            alt_key = f"{alt_sender}_state"
            alt_state = await self.client.get(alt_key)
            if alt_state:
                alt_state_dict = json.loads(alt_state)
                logger.info(f"Estado encontrado com formato alternativo: {alt_sender}")

        # Retorna o estado alternativo se for mais completo
        if alt_state_dict and alt_state_dict.get("segmento"):
            return alt_state_dict

        # Retorna o estado original se existir
        return state_dict


# Instância singleton
redis_service = RedisService()
