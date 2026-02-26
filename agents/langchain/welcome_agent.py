"""
Agente de Boas-Vindas usando LangChain
Gera a primeira mensagem de contato com o lead
"""
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
import logging

from config import get_settings
from prompts import get_welcome_prompt

logger = logging.getLogger(__name__)


class LangChainWelcomeAgent:
    """Agente para gerar mensagem de boas-vindas"""

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

            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content="Gere a mensagem de boas-vindas agora."),
            ]

            response = await self.llm.ainvoke(messages)
            message = self.parser.parse(response.content)

            logger.info(f"Mensagem de boas-vindas gerada para {nome}")
            return message

        except Exception as e:
            logger.error(f"Erro ao gerar boas-vindas: {e}")
            # Fallback para mensagem padrão
            return f"Oie {nome}, tudo bem? me chamo Luana, sou atendente aqui do Fyness\nvi que vc se interessou e, olhando aqui, vi que você atua no segmento de {segmento}\né isso mesmo?"

    def generate_welcome_sync(self, nome: str, segmento: str) -> str:
        """Versão síncrona para compatibilidade"""
        import asyncio

        return asyncio.run(self.generate_welcome(nome, segmento))


# Instância singleton
langchain_welcome_agent = LangChainWelcomeAgent()
