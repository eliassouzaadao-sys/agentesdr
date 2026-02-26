"""
Agente SDR usando LangChain com memória Redis
Qualifica leads usando SPIN Selling
"""
from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
import logging
import re

from config import get_settings
from prompts import get_sdr_prompt
from services.redis_service import redis_service
from services.supabase_service import supabase_service

logger = logging.getLogger(__name__)


class LangChainSDRAgent:
    """Agente SDR com SPIN Selling e memória de conversação"""

    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
            temperature=0.95,  # Alta temperatura para respostas mais naturais e variadas
            presence_penalty=0.6,  # Evita repetição de frases
            frequency_penalty=0.4,  # Incentiva vocabulário variado
        )
        self.parser = StrOutputParser()

    def _get_message_history(self, session_id: str) -> RedisChatMessageHistory:
        """Retorna histórico de mensagens do Redis"""
        return RedisChatMessageHistory(
            session_id=session_id, url=self.settings.redis_url, ttl=86400 * 7
        )

    async def process_message(
        self,
        sender: str,
        message: str,
        lead_name: str = "Lead",
        lead_segmento: str = "não especificado",
        lead_origem: str = "formulário",
        vendedor: str = "João",
        is_first_contact: bool = False,
    ) -> str:
        """
        Processa mensagem do lead e gera resposta

        Args:
            sender: ID do remetente (remoteJid)
            message: Mensagem recebida
            lead_name: Nome do lead
            lead_segmento: Segmento de atuação do lead
            lead_origem: Origem do lead
            vendedor: Nome do vendedor responsável
            is_first_contact: Se é o primeiro contato (True) ou conversa contínua (False)

        Returns:
            Resposta do agente
        """
        try:
            # Recupera estado atual do lead
            state = await redis_service.get_lead_state(sender)
            etapa_spin = state.get("etapa_spin", "situacao") if state else "situacao"

            # Cria prompt com contexto
            system_prompt = get_sdr_prompt(
                nome=lead_name,
                segmento=lead_segmento,
                origem=lead_origem,
                vendedor=vendedor,
                etapa_spin=etapa_spin,
                is_first_contact=is_first_contact,
            )

            # Se primeiro contato, não tem histórico ainda
            if is_first_contact:
                history = []
                logger.info(f"Primeiro contato para {sender} | Lead: {lead_name} | Segmento: {lead_segmento}")
            else:
                # Recupera histórico de conversação (últimas 30 mensagens)
                history = await redis_service.get_conversation_history(sender, limit=30)
                logger.info(f"Histórico para {sender}: {len(history)} mensagens | Lead: {lead_name} | Segmento: {lead_segmento}")

            # Monta mensagens
            messages = [SystemMessage(content=system_prompt)]

            # Adiciona histórico completo da conversa
            for msg in history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))

            # Adiciona mensagem atual do lead (ou trigger para primeiro contato)
            if is_first_contact:
                messages.append(HumanMessage(content="Gere a mensagem de boas-vindas agora."))
            else:
                messages.append(HumanMessage(content=message))

            logger.info(f"Contexto: {len(messages)} msgs (1 system + {len(history)} histórico + 1 atual)")

            # Gera resposta
            response = await self.llm.ainvoke(messages)
            ai_response = self.parser.parse(response.content)

            # Processa tags e atualiza estado
            ai_response, new_state = await self._process_tags(ai_response, state or {}, sender)
            if new_state:
                await redis_service.set_lead_state(sender, new_state)

            logger.info(f"Resposta SDR gerada para {sender}")
            return ai_response

        except Exception as e:
            logger.error(f"Erro no agente SDR: {e}")
            return "Opa, me dá um segundo aqui que deu um probleminha\nJá te respondo!"

    async def _process_tags(
        self, response: str, current_state: Dict[str, Any], sender: str
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        Processa tags especiais na resposta, atualiza estado e sincroniza com Supabase

        Returns:
            Tupla (resposta_limpa, novo_estado)
        """
        new_state = current_state.copy()
        tags_found = []

        # Define mapeamento de tags
        tag_mapping = {
            "[QUALIFICADO]": {"qualificacao": "quente", "etapa_spin": "completo"},
            "[NAO_QUALIFICADO]": {"qualificacao": "frio", "etapa_spin": "completo"},
            "[FOLLOW_UP_24H]": {"follow_up": True},
            "[TRANSFERIR_VENDEDOR]": {"transferir": True, "qualificacao": "quente"},
            "[ENVIAR_AUDIO]": {"audio": True},
        }

        # Detecta etapa SPIN baseado no conteúdo
        etapa_keywords = {
            "situacao": [
                "o que vocês fazem",
                "me conta",
                "qual é o",
                "como funciona",
            ],
            "problema": [
                "dor de cabeça",
                "dificuldade",
                "problema",
                "gargalo",
                "incomoda",
            ],
            "implicacao": ["continuar assim", "impacto", "perder", "consequência"],
            "necessidade": [
                "se existisse",
                "ideal",
                "conectar",
                "vendedor",
                "solução",
            ],
        }

        # Processa cada tag de qualificação
        for tag, updates in tag_mapping.items():
            if tag in response:
                tags_found.append(tag)
                new_state.update(updates)
                response = response.replace(tag, "").strip()

        # Processa tags de objeção: [OBJECAO: descrição]
        objecao_pattern = r'\[OBJECAO:\s*([^\]]+)\]'
        objecoes_encontradas = re.findall(objecao_pattern, response, re.IGNORECASE)

        if objecoes_encontradas:
            # Remove as tags de objeção da resposta
            response = re.sub(objecao_pattern, '', response, flags=re.IGNORECASE).strip()

            # Salva cada objeção no Supabase
            for objecao in objecoes_encontradas:
                objecao_limpa = objecao.strip()
                if objecao_limpa:
                    await supabase_service.add_objecao(sender, objecao_limpa)
                    logger.info(f"[Supabase] Objeção identificada para {sender}: {objecao_limpa}")

        # Infere etapa SPIN se não houver tags
        if not tags_found:
            response_lower = response.lower()
            for etapa, keywords in etapa_keywords.items():
                if any(kw in response_lower for kw in keywords):
                    new_state["etapa_spin"] = etapa
                    break

        # Processa tags no Supabase (CRM)
        if "[QUALIFICADO]" in tags_found or "[NAO_QUALIFICADO]" in tags_found:
            resumo = await self.get_conversation_summary(sender)
            qualificacao = "quente" if "[QUALIFICADO]" in tags_found else "frio"

            await supabase_service.update_lead_qualification(
                remote_jid=sender,
                qualificacao=qualificacao,
                resumo=resumo
            )
            logger.info(f"[Supabase] Lead {sender} qualificado como {qualificacao}")

        if "[TRANSFERIR_VENDEDOR]" in tags_found:
            resumo = await self.get_conversation_summary(sender)

            contato = await supabase_service.convert_lead_to_contact(
                remote_jid=sender,
                resumo=resumo
            )
            if contato:
                logger.info(f"[Supabase] Lead {sender} convertido para contato")

        return response, new_state if new_state != current_state else None

    async def get_conversation_summary(self, sender: str) -> Optional[str]:
        """Gera resumo da conversação para handoff"""
        try:
            history = await redis_service.get_conversation_history(sender, limit=40)

            if not history:
                return None

            # Formata histórico
            conversation = "\n".join(
                [f"{msg['role'].upper()}: {msg['content']}" for msg in history]
            )

            # Prompt para resumo
            summary_prompt = f"""Resuma esta conversa de qualificação de lead em 3-5 bullet points.
Inclua: problema identificado, interesse demonstrado, próximos passos.

CONVERSA:
{conversation}

RESUMO:"""

            messages = [HumanMessage(content=summary_prompt)]
            response = await self.llm.ainvoke(messages)

            return self.parser.parse(response.content)

        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {e}")
            return None


# Instância singleton
langchain_sdr_agent = LangChainSDRAgent()
