"""
Serviço OpenAI para transcrição de áudio
"""
import openai
import base64
import tempfile
import os
import logging
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)


class OpenAIService:
    """Serviço para transcrição de áudio com OpenAI Whisper"""

    def __init__(self):
        self.settings = get_settings()
        self.client = openai.AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def transcribe_audio_base64(
        self, base64_audio: str, mimetype: str = "audio/ogg"
    ) -> Optional[str]:
        """Transcreve áudio a partir de base64"""
        try:
            # Determina extensão pelo mimetype
            extension_map = {
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
                "audio/wav": ".wav",
                "audio/webm": ".webm",
            }
            extension = extension_map.get(mimetype, ".ogg")

            # Decodifica base64
            audio_data = base64.b64decode(base64_audio)

            # Salva em arquivo temporário
            with tempfile.NamedTemporaryFile(
                suffix=extension, delete=False
            ) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            try:
                # Transcreve com Whisper
                with open(temp_path, "rb") as audio_file:
                    transcript = await self.client.audio.transcriptions.create(
                        model="whisper-1", file=audio_file, language="pt"
                    )

                logger.info("Áudio transcrito com sucesso")
                return transcript.text

            finally:
                # Remove arquivo temporário
                os.unlink(temp_path)

        except Exception as e:
            logger.error(f"Erro ao transcrever áudio: {e}")
            return None

    async def transcribe_audio_url(self, audio_url: str) -> Optional[str]:
        """Transcreve áudio a partir de URL"""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(audio_url, timeout=60.0)
                audio_data = response.content

            # Salva em arquivo temporário
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            try:
                with open(temp_path, "rb") as audio_file:
                    transcript = await self.client.audio.transcriptions.create(
                        model="whisper-1", file=audio_file, language="pt"
                    )

                return transcript.text

            finally:
                os.unlink(temp_path)

        except Exception as e:
            logger.error(f"Erro ao transcrever áudio de URL: {e}")
            return None

    async def generate_completion(
        self, prompt: str, max_tokens: int = 150
    ) -> Optional[str]:
        """
        Gera texto usando GPT
        Usado para mensagens de follow-up
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.8,  # Um pouco mais criativo para variar mensagens
            )

            text = response.choices[0].message.content.strip()
            logger.info(f"Completion gerado: {len(text)} caracteres")
            return text

        except Exception as e:
            logger.error(f"Erro ao gerar completion: {e}")
            return None


# Instância singleton
openai_service = OpenAIService()
