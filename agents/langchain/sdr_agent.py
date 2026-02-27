"""
Agente SDR usando LangChain com memória Redis
Qualifica leads usando SPIN Selling
"""
from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
import logging

from config import get_settings
from prompts import get_sdr_prompt
from services.redis_service import redis_service
from services.tag_processor import process_tags

logger = logging.getLogger(__name__)


class LangChainSDRAgent:
    """Agente SDR com SPIN Selling e memória de conversação"""

    def __init__(self):
        self.settings = get_settings()
        self.llm = ChatOpenAI(
            model=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
            temperature=0.95,
            presence_penalty=0.6,
            frequency_penalty=0.4,
        )
        self.parser = StrOutputParser()

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
            ai_response, _ = await process_tags(
                ai_response,
                state or {},
                sender,
                get_summary_fn=self.get_conversation_summary
            )

            logger.info(f"Resposta SDR gerada para {sender}")
            return ai_response

        except Exception as e:
            logger.error(f"Erro no agente SDR: {e}")
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
