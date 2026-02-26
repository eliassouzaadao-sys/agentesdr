"""
Serviço WhatsApp via Evolution API
"""
import httpx
import asyncio
import random
import logging
from typing import List, Optional

from config import get_settings
from utils.message_splitter import split_message

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Gerenciador de envio de mensagens WhatsApp via Evolution API"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        instance: Optional[str] = None,
    ):
        self.settings = get_settings()
        self.base_url = base_url or self.settings.evolution_api_url
        self.api_key = api_key or self.settings.evolution_api_key
        self.instance = instance or self.settings.evolution_instance

    def _get_headers(self) -> dict:
        """Retorna headers para requisições"""
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def send_text(self, to: str, text: str) -> bool:
        """Envia uma mensagem de texto"""
        try:
            url = f"{self.base_url}/message/sendText/{self.instance}"

            # Formata o número se necessário
            if not to.endswith("@s.whatsapp.net"):
                number = "".join(filter(str.isdigit, to))
                if not number.startswith("55"):
                    number = f"55{number}"
                to = f"{number}@s.whatsapp.net"

            payload = {"number": to, "text": text}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=30.0
                )

                if response.status_code == 200 or response.status_code == 201:
                    logger.info(f"Mensagem enviada para {to}")
                    return True
                else:
                    logger.error(
                        f"Erro ao enviar mensagem: {response.status_code} - {response.text}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            return False

    async def send_messages_with_delay(
        self,
        to: str,
        messages: List[str],
        delay_min: Optional[float] = None,
        delay_max: Optional[float] = None,
    ) -> List[bool]:
        """Envia múltiplas mensagens com delay humanizado entre elas"""
        delay_min = delay_min or self.settings.message_delay_min
        delay_max = delay_max or self.settings.message_delay_max

        results = []

        for i, message in enumerate(messages):
            # Envia a mensagem
            success = await self.send_text(to, message)
            results.append(success)

            # Delay entre mensagens (exceto após a última)
            if i < len(messages) - 1:
                delay = random.uniform(delay_min, delay_max)
                await asyncio.sleep(delay)

        return results

    async def send_long_message(
        self, to: str, text: str, split: bool = True
    ) -> List[bool]:
        """Envia mensagem longa, opcionalmente dividindo em partes"""
        if split:
            messages = split_message(text)
        else:
            messages = [text]

        return await self.send_messages_with_delay(to, messages)

    async def get_base64_from_media(self, message_id: str) -> Optional[dict]:
        """Recupera mídia em base64 de uma mensagem"""
        try:
            url = f"{self.base_url}/chat/getBase64FromMediaMessage/{self.instance}"

            payload = {"message": {"key": {"id": message_id}}, "convertToMp4": True}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=60.0
                )

                if response.status_code in [200, 201]:
                    return response.json()
                else:
                    logger.error(f"Erro ao recuperar mídia: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Erro ao recuperar mídia: {e}")
            return None

    async def send_reaction(self, to: str, message_id: str, emoji: str) -> bool:
        """Envia reação a uma mensagem"""
        try:
            url = f"{self.base_url}/message/sendReaction/{self.instance}"

            payload = {
                "key": {"remoteJid": to, "id": message_id},
                "reaction": emoji,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=30.0
                )
                return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Erro ao enviar reação: {e}")
            return False

    async def send_presence(self, to: str, presence: str = "composing") -> bool:
        """
        Envia status de presença (digitando, gravando)

        Args:
            to: Destinatário
            presence: "composing" (digitando) ou "recording" (gravando áudio)
        """
        try:
            # Formata o número
            if not to.endswith("@s.whatsapp.net"):
                number = "".join(filter(str.isdigit, to))
                if not number.startswith("55"):
                    number = f"55{number}"
                to = f"{number}@s.whatsapp.net"

            url = f"{self.base_url}/chat/sendPresence/{self.instance}"

            payload = {
                "number": to,
                "presence": presence,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=10.0
                )
                return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Erro ao enviar presença: {e}")
            return False

    async def send_audio(self, to: str, audio_base64: str) -> bool:
        """
        Envia áudio via WhatsApp

        Args:
            to: Destinatário
            audio_base64: Áudio em base64
        """
        try:
            # Formata o número
            if not to.endswith("@s.whatsapp.net"):
                number = "".join(filter(str.isdigit, to))
                if not number.startswith("55"):
                    number = f"55{number}"
                to = f"{number}@s.whatsapp.net"

            url = f"{self.base_url}/message/sendWhatsAppAudio/{self.instance}"

            payload = {
                "number": to,
                "audio": audio_base64,
                "encoding": True,  # PTT (Push to Talk) style
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=60.0
                )

                if response.status_code in [200, 201]:
                    logger.info(f"Áudio enviado para {to}")
                    return True
                else:
                    logger.error(f"Erro ao enviar áudio: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Erro ao enviar áudio: {e}")
            return False

    async def send_audio_with_presence(self, to: str, audio_base64: str, duration: float = 3.0) -> bool:
        """
        Envia áudio com status de gravando antes

        Args:
            to: Destinatário
            audio_base64: Áudio em base64
            duration: Tempo para mostrar "gravando" antes de enviar
        """
        # Mostra "gravando áudio"
        await self.send_presence(to, "recording")

        # Aguarda um tempo para parecer mais real
        await asyncio.sleep(duration)

        # Envia o áudio
        return await self.send_audio(to, audio_base64)


# Factory para criar instância com credenciais dinâmicas
def create_whatsapp_service(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    instance: Optional[str] = None,
) -> WhatsAppService:
    """Cria instância do serviço WhatsApp"""
    return WhatsAppService(base_url, api_key, instance)


# Instância padrão
whatsapp_service = WhatsAppService()
