"""
Serviço WhatsApp via Evolution API
Com delay dinâmico baseado no tamanho da mensagem para parecer mais humano
"""
import httpx
import asyncio
import random
import logging
from typing import List, Optional

from config import get_settings
from utils.message_splitter import split_message

logger = logging.getLogger(__name__)

# Constantes para cálculo de delay dinâmico
MS_PER_CHAR_TYPING = 70  # 70ms por caractere para digitação
MS_PER_CHAR_AUDIO = 50   # 50ms por caractere para áudio (fala é mais rápida que digitar)
MIN_DELAY_SECONDS = 1.0  # Delay mínimo
MAX_DELAY_SECONDS = 15.0  # Delay máximo para não parecer travado


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

    def _format_number(self, number: str) -> str:
        """
        Formata número para o padrão WhatsApp (remoteJid).
        Adiciona código do país (55) e sufixo @s.whatsapp.net se necessário.
        """
        if number.endswith("@s.whatsapp.net"):
            return number

        digits = "".join(filter(str.isdigit, number))

        if not digits.startswith("55"):
            digits = f"55{digits}"

        return f"{digits}@s.whatsapp.net"

    def _get_digits_only(self, number: str) -> str:
        """
        Retorna apenas os dígitos do número (sem @s.whatsapp.net).
        Usado para endpoints que não aceitam o formato remoteJid.
        """
        if number.endswith("@s.whatsapp.net"):
            number = number.replace("@s.whatsapp.net", "")

        digits = "".join(filter(str.isdigit, number))

        if not digits.startswith("55"):
            digits = f"55{digits}"

        return digits

    def _calculate_typing_delay(self, text: str) -> float:
        """
        Calcula delay dinâmico baseado no tamanho do texto.
        Fórmula: caracteres * 70ms, com min/max para não parecer estranho.
        """
        delay = (len(text) * MS_PER_CHAR_TYPING) / 1000  # Converte para segundos
        # Adiciona variação aleatória de ±20% para parecer mais humano
        variation = delay * random.uniform(-0.2, 0.2)
        delay = delay + variation
        return max(MIN_DELAY_SECONDS, min(delay, MAX_DELAY_SECONDS))

    def _calculate_audio_delay(self, text: str) -> float:
        """
        Calcula delay para áudio baseado no texto que será falado.
        Fala é mais rápida que digitação, então usamos menos ms por caractere.
        """
        delay = (len(text) * MS_PER_CHAR_AUDIO) / 1000
        variation = delay * random.uniform(-0.1, 0.1)
        delay = delay + variation
        return max(MIN_DELAY_SECONDS, min(delay, MAX_DELAY_SECONDS))

    async def send_presence(self, to: str, presence: str = "composing", delay: int = 1000) -> bool:
        """
        Envia status de presença (digitando, gravando)

        Args:
            to: Destinatário
            presence: "composing" (digitando) ou "recording" (gravando áudio)
            delay: Duração da presença em milissegundos
        """
        try:
            url = f"{self.base_url}/chat/sendPresence/{self.instance}"
            # Endpoint sendPresence precisa do número SEM @s.whatsapp.net
            number = self._get_digits_only(to)

            # Formato Evolution API v2 - campos no nível raiz
            payload = {
                "number": number,
                "delay": delay,
                "presence": presence,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=10.0
                )
                if response.status_code not in [200, 201]:
                    logger.warning(f"Presença falhou: {response.status_code} - {response.text}")
                else:
                    logger.info(f"Presença '{presence}' enviada para {number} ({delay}ms)")
                return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Erro ao enviar presença: {e}")
            return False

    async def send_text(self, to: str, text: str) -> bool:
        """Envia uma mensagem de texto"""
        try:
            url = f"{self.base_url}/message/sendText/{self.instance}"
            to = self._format_number(to)

            payload = {"number": to, "text": text}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=30.0
                )

                if response.status_code in [200, 201]:
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

    async def send_text_with_presence(self, to: str, text: str) -> bool:
        """
        Envia texto com efeito "digitando..." antes.
        O tempo de digitação é calculado dinamicamente baseado no tamanho do texto.
        """
        # Calcula delay em segundos e converte para ms
        delay_seconds = self._calculate_typing_delay(text)
        delay_ms = int(delay_seconds * 1000)

        logger.info(f"Digitando por {delay_seconds:.1f}s para mensagem de {len(text)} chars")

        # Envia presença "digitando..." ANTES de enviar a mensagem
        await self.send_presence(to, "composing", delay=delay_ms)

        # Aguarda o tempo calculado
        await asyncio.sleep(delay_seconds)

        # Envia a mensagem (presença já foi enviada)
        return await self.send_text(to, text)

    async def send_messages_with_delay(
        self,
        to: str,
        messages: List[str],
        use_presence: bool = True,
    ) -> List[bool]:
        """
        Envia múltiplas mensagens com delay dinâmico e presença.

        Args:
            to: Destinatário
            messages: Lista de mensagens
            use_presence: Se True, mostra "digitando" antes de cada mensagem
        """
        results = []

        for i, message in enumerate(messages):
            if use_presence:
                success = await self.send_text_with_presence(to, message)
            else:
                success = await self.send_text(to, message)
            results.append(success)

            # Pequena pausa entre mensagens consecutivas
            if i < len(messages) - 1:
                await asyncio.sleep(random.uniform(0.5, 1.5))

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

    async def send_audio(self, to: str, audio_base64: str) -> bool:
        """Envia áudio via WhatsApp"""
        try:
            url = f"{self.base_url}/message/sendWhatsAppAudio/{self.instance}"
            to = self._format_number(to)

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

    async def send_video(self, to: str, video_url: str, caption: str = "") -> bool:
        """
        Envia vídeo via WhatsApp usando URL.

        Args:
            to: Destinatário
            video_url: URL do vídeo (deve ser acessível publicamente)
            caption: Legenda do vídeo (opcional)
        """
        try:
            url = f"{self.base_url}/message/sendMedia/{self.instance}"
            to = self._format_number(to)

            payload = {
                "number": to,
                "mediatype": "video",
                "media": video_url,
                "caption": caption,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=payload, headers=self._get_headers(), timeout=60.0
                )

                if response.status_code in [200, 201]:
                    logger.info(f"Vídeo enviado para {to}")
                    return True
                else:
                    logger.error(f"Erro ao enviar vídeo: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Erro ao enviar vídeo: {e}")
            return False

    async def send_video_with_presence(
        self,
        to: str,
        video_url: str,
        caption: str = "",
        delay_seconds: float = 2.0
    ) -> bool:
        """
        Envia vídeo com pequeno delay antes para parecer mais natural.

        Args:
            to: Destinatário
            video_url: URL do vídeo
            caption: Legenda do vídeo
            delay_seconds: Tempo de espera antes de enviar
        """
        # Pequeno delay antes de enviar o vídeo
        await asyncio.sleep(delay_seconds)

        return await self.send_video(to, video_url, caption)

    async def send_audio_with_presence(
        self,
        to: str,
        audio_base64: str,
        text_content: Optional[str] = None,
        duration: Optional[float] = None
    ) -> bool:
        """
        Envia áudio com status "gravando..." antes.
        O tempo é calculado dinamicamente baseado no texto que será falado.

        Args:
            to: Destinatário
            audio_base64: Áudio em base64
            text_content: Texto original que foi convertido em áudio (para calcular delay)
            duration: Tempo fixo em segundos (usado se text_content não for fornecido)
        """
        # Calcula delay baseado no texto ou usa valor fixo
        if text_content:
            delay_seconds = self._calculate_audio_delay(text_content)
            logger.info(f"Gravando por {delay_seconds:.1f}s para áudio de {len(text_content)} chars")
        else:
            delay_seconds = duration or 3.0

        delay_ms = int(delay_seconds * 1000)

        # Envia presença "gravando..." ANTES de enviar o áudio
        await self.send_presence(to, "recording", delay=delay_ms)

        # Aguarda o tempo calculado
        await asyncio.sleep(delay_seconds)

        # Envia o áudio (presença já foi enviada)
        return await self.send_audio(to, audio_base64)


def create_whatsapp_service(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    instance: Optional[str] = None,
) -> WhatsAppService:
    """Cria instância do serviço WhatsApp"""
    return WhatsAppService(base_url, api_key, instance)


# Instância padrão
whatsapp_service = WhatsAppService()
