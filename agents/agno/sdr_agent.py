"""
Agente SDR usando Agno com memória Redis unificada
Framework alternativo ao LangChain - usa redis_service para histórico
"""
from typing import Optional, Dict, Any, List
from agno.agent import Agent
from agno.models.openai import OpenAIChat
import logging
import re

from config import get_settings
from prompts import get_sdr_prompt
from services.redis_service import redis_service
from services.supabase_service import supabase_service

logger = logging.getLogger(__name__)


class AgnoSDRAgent:
    """Agente SDR com SPIN Selling usando Agno"""

    def __init__(self):
        self.settings = get_settings()
        self.model = OpenAIChat(
            id=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
            temperature=0.95,  # Alta temperatura para respostas mais naturais
        )

    def _build_messages_with_history(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        current_message: str,
    ) -> str:
        """
        Constrói contexto completo com histórico para o agente

        Returns:
            String formatada com todo o contexto
        """
        # Formata histórico como contexto
        history_text = ""
        if history:
            history_text = "\n\nHISTÓRICO DA CONVERSA:\n"
            for msg in history:
                role = "LEAD" if msg["role"] == "user" else "LUANA"
                history_text += f"{role}: {msg['content']}\n"

        # Combina tudo
        full_context = f"{system_prompt}{history_text}\n\nMENSAGEM ATUAL DO LEAD: {current_message}"
        return full_context

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
                # Recupera histórico de conversação (últimas 30 mensagens)
                history = await redis_service.get_conversation_history(sender, limit=30)
                trigger_message = message
                logger.info(f"[Agno] Histórico para {sender}: {len(history)} mensagens | Lead: {lead_name} | Segmento: {lead_segmento}")

            # Cria agente simples (sem memória interna - usamos redis_service)
            agent = Agent(
                model=self.model,
                instructions=system_prompt,
                markdown=False,
            )

            # Se tem histórico, adiciona como contexto
            if history:
                # Formata histórico como parte da mensagem
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
            ai_response, new_state = await self._process_tags(ai_response, state or {}, sender)

            logger.info(f"[Agno] Resposta SDR gerada para {sender}")
            return ai_response

        except Exception as e:
            logger.error(f"[Agno] Erro no agente SDR: {e}")
            return "Opa, me dá um segundo aqui que deu um probleminha\nJá te respondo!"

    async def _process_tags(
        self, response: str, current_state: Dict[str, Any], sender: str
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """Processa tags especiais, atualiza estado e sincroniza com Supabase"""
        new_state = current_state.copy()
        tags_found = []

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

        # Atualiza Redis se houver mudanças
        if new_state != current_state:
            await redis_service.set_lead_state(sender, new_state)

        # Processa tags no Supabase (CRM)
        if "[QUALIFICADO]" in tags_found or "[NAO_QUALIFICADO]" in tags_found:
            # Gera resumo da conversa
            resumo = await self.get_conversation_summary(sender)
            qualificacao = "quente" if "[QUALIFICADO]" in tags_found else "frio"

            await supabase_service.update_lead_qualification(
                remote_jid=sender,
                qualificacao=qualificacao,
                resumo=resumo
            )
            logger.info(f"[Supabase] Lead {sender} qualificado como {qualificacao}")

        if "[TRANSFERIR_VENDEDOR]" in tags_found:
            # Gera resumo e converte lead em contato
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
