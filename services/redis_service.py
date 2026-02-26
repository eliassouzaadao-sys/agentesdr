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
        """Recupera estado do lead"""
        key = f"{sender}_state"
        state = await self.client.get(key)
        return json.loads(state) if state else None


# Instância singleton
redis_service = RedisService()
