"""
Agente de Boas-Vindas usando Agno
Framework alternativo ao LangChain - mais leve e moderno
"""
from agno.agent import Agent
from agno.models.openai import OpenAIChat
import logging

from config import get_settings
from prompts import get_welcome_prompt

logger = logging.getLogger(__name__)


class AgnoWelcomeAgent:
    """Agente de boas-vindas usando Agno"""

    def __init__(self):
        self.settings = get_settings()
        self.model = OpenAIChat(
            id=self.settings.openai_model,
            api_key=self.settings.openai_api_key,
        )

    async def generate_welcome(self, nome: str, segmento: str) -> str:
        """
        Gera mensagem de boas-vindas personalizada

        Args:
            nome: Nome do lead
            segmento: Segmento de atuação

        Returns:
            Mensagem de boas-vindas
        """
        try:
            prompt = get_welcome_prompt(nome, segmento)

            agent = Agent(
                model=self.model,
                instructions=prompt,
                markdown=False,
            )

            response = await agent.arun("Gere a mensagem de boas-vindas agora.")

            # Extrai texto da resposta
            message = response.content if hasattr(response, "content") else str(response)

            logger.info(f"[Agno] Mensagem de boas-vindas gerada para {nome}")
            return message

        except Exception as e:
            logger.error(f"[Agno] Erro ao gerar boas-vindas: {e}")
            # Fallback
            return f"Oie {nome}, tudo bem? me chamo Luana, sou atendente aqui do Fyness\nvi que vc se interessou e, olhando aqui, vi que você atua no segmento de {segmento}\né isso mesmo?"

    def generate_welcome_sync(self, nome: str, segmento: str) -> str:
        """Versão síncrona"""
        import asyncio

        return asyncio.run(self.generate_welcome(nome, segmento))


# Instância singleton
agno_welcome_agent = AgnoWelcomeAgent()
