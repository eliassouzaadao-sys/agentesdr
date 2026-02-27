"""
Agente SDR usando Agno com memória Redis unificada
Framework alternativo ao LangChain - usa redis_service para histórico
"""
from typing import Optional, Dict, Any, List
from agno.agent import Agent
from agno.models.openai import OpenAIChat
import logging

from config import get_settings
from prompts import get_sdr_prompt
from services.redis_service import redis_service
from services.tag_processor import process_tags

logger = logging.getLogger(__name__)


class AgnoSDRAgent:
    """Agente SDR com SPIN Selling usando Agno"""

    def __init__(self):
        self.settings = get_settings()
        self.model = OpenAIChat(
            id=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
            temperature=0.95,
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
                trigger_message = "Gere a mensagem de boas-vindas agora."
                logger.info(f"[Agno] Primeiro contato para {sender} | Lead: {lead_name} | Segmento: {lead_segmento}")
            else:
                history = await redis_service.get_conversation_history(sender, limit=30)
                trigger_message = message
                logger.info(f"[Agno] Histórico para {sender}: {len(history)} mensagens | Lead: {lead_name} | Segmento: {lead_segmento}")

            # Cria agente
            agent = Agent(
                model=self.model,
                instructions=system_prompt,
                markdown=False,
            )

            # Se tem histórico, adiciona como contexto
            if history:
                history_context = "HISTÓRICO DA CONVERSA (você já conversou com essa pessoa):\n"
                for msg in history:
                    role = "LEAD" if msg["role"] == "user" else "VOCÊ (Luana)"
                    history_context += f"{role}: {msg['content']}\n"
                history_context += f"\nAGORA O LEAD DISSE: {trigger_message}"
                trigger_message = history_context

            logger.info(f"[Agno] Contexto: {len(history)} msgs no histórico")

            # Processa mensagem
            response = await agent.arun(trigger_message)

            # Extrai texto
            ai_response = (
                response.content if hasattr(response, "content") else str(response)
            )

            # Processa tags e atualiza estado
            ai_response, _ = await process_tags(
                ai_response,
                state or {},
                sender,
                get_summary_fn=self.get_conversation_summary
            )

            logger.info(f"[Agno] Resposta SDR gerada para {sender}")
            return ai_response

        except Exception as e:
            logger.error(f"[Agno] Erro no agente SDR: {e}")
            return "Opa, me dá um segundo aqui que deu um probleminha\nJá te respondo!"

    async def get_conversation_summary(self, sender: str) -> Optional[str]:
        """Gera resumo da conversação para handoff"""
        try:
            history = await redis_service.get_conversation_history(sender, limit=40)

            if not history:
                return None

            conversation = "\n".join(
                [f"{msg['role'].upper()}: {msg['content']}" for msg in history]
            )

            agent = Agent(
                model=self.model,
                instructions="Você é um assistente que resume conversas de qualificação de leads.",
                markdown=False,
            )

            summary_prompt = f"""Resuma esta conversa em 3-5 bullet points.
Inclua: problema identificado, interesse demonstrado, próximos passos.

CONVERSA:
{conversation}"""

            response = await agent.arun(summary_prompt)
            return response.content if hasattr(response, "content") else str(response)

        except Exception as e:
            logger.error(f"[Agno] Erro ao gerar resumo: {e}")
            return None


# Instância singleton
agno_sdr_agent = AgnoSDRAgent()
