"""
Serviço de Text-to-Speech usando ElevenLabs
Otimizado para fala natural com emoções e pausas
"""
import httpx
import logging
import base64
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ElevenLabs Config
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_API_KEY = "sk_f49b273243ea6ef1fb71ac8e482d65a4a4639241a2da9c80"
ELEVENLABS_VOICE_ID = "GOkMqfyKMLVUcYfO2WbB"
ELEVENLABS_MODEL = "eleven_v3"


class TTSService:
    """Serviço de conversão texto para áudio usando ElevenLabs"""

    def __init__(self):
        self.api_key = ELEVENLABS_API_KEY
        self.voice_id = ELEVENLABS_VOICE_ID
        self.model_id = ELEVENLABS_MODEL

    def _process_audio_tags(self, text: str) -> str:
        """
        Converte tags de expressão para marcadores que ElevenLabs interpreta naturalmente.
        O ElevenLabs é bom em interpretar pontuação e interjeições como pausas e emoções.
        """
        # === PAUSAS - Converte para reticências/pontuação ===
        text = re.sub(r'\[pausa curta\]', '...', text, flags=re.IGNORECASE)
        text = re.sub(r'\[pausa longa\]', '...... ', text, flags=re.IGNORECASE)
        text = re.sub(r'\[pausa\]', '...', text, flags=re.IGNORECASE)

        # === RISOS - Converte para interjeições ===
        text = re.sub(r'\[riso leve\]', 'haha, ', text, flags=re.IGNORECASE)
        text = re.sub(r'\[riso\]', 'haha', text, flags=re.IGNORECASE)
        text = re.sub(r'\[risada\]', 'hahaha', text, flags=re.IGNORECASE)

        # === REAÇÕES - Converte para interjeições naturais ===
        text = re.sub(r'\[surpreso\]', 'nossa, ', text, flags=re.IGNORECASE)
        text = re.sub(r'\[concordando\]', 'uhum, ', text, flags=re.IGNORECASE)
        text = re.sub(r'\[pensando\]', 'hmm, ', text, flags=re.IGNORECASE)
        text = re.sub(r'\[pensativo\]', 'hmm... ', text, flags=re.IGNORECASE)

        # === EMOÇÕES - Remove pois ElevenLabs interpreta pelo contexto ===
        emotion_tags = [
            r'\[animado\]', r'\[entusiasmado\]', r'\[empolgado\]',
            r'\[curioso\]', r'\[interessado\]',
            r'\[sério\]', r'\[mais sério\]', r'\[voz mais séria\]',
            r'\[empático\]', r'\[compreensivo\]',
            r'\[leve\]', r'\[descontraído\]', r'\[casual\]',
            r'\[calmo\]', r'\[tranquilo\]',
            r'\[triste\]', r'\[preocupado\]',
            r'\[feliz\]', r'\[alegre\]',
            r'\[ênfase\]', r'\[enfase\]',
            r'\[ENVIAR_AUDIO\]',
        ]
        for tag in emotion_tags:
            text = re.sub(tag, '', text, flags=re.IGNORECASE)

        # === LIMPA qualquer tag restante entre colchetes ===
        text = re.sub(r'\[[^\]]*\]', '', text)

        # === LIMPA espaços extras ===
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    async def text_to_audio(self, text: str) -> Optional[bytes]:
        """
        Converte texto em áudio usando ElevenLabs

        Args:
            text: Texto para converter (pode conter tags de emoção)

        Returns:
            Bytes do áudio MP3 ou None se falhar
        """
        try:
            # Processa tags de emoção/pausa
            processed_text = self._process_audio_tags(text)

            logger.info(f"Gerando áudio ElevenLabs: {len(processed_text)} chars")

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{ELEVENLABS_API_URL}/{self.voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={
                        "text": processed_text,
                        "model_id": self.model_id,
                        "voice_settings": {
                            "stability": 0.5,        # Mais variação = mais natural
                            "similarity_boost": 0.75, # Mantém características da voz
                            "style": 0.4,            # Expressividade moderada
                            "use_speaker_boost": True,
                        },
                    },
                )

                if response.status_code == 200:
                    logger.info(f"Áudio ElevenLabs gerado: {len(response.content)} bytes")
                    return response.content
                else:
                    logger.error(f"Erro ElevenLabs: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Erro no TTS ElevenLabs: {e}")
            return None

    async def text_to_audio_emotional(
        self,
        text: str,
        emotion: str = "friendly"
    ) -> Optional[bytes]:
        """
        Converte texto em áudio com configurações de emoção

        Args:
            text: Texto para converter
            emotion: Emoção desejada (friendly, excited, calm, sincere)

        Returns:
            Bytes do áudio MP3 ou None se falhar
        """
        # Ajusta voice_settings baseado na emoção
        emotion_settings = {
            "friendly": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.4},
            "excited": {"stability": 0.3, "similarity_boost": 0.8, "style": 0.7},
            "calm": {"stability": 0.7, "similarity_boost": 0.7, "style": 0.2},
            "sincere": {"stability": 0.6, "similarity_boost": 0.75, "style": 0.5},
            "casual": {"stability": 0.4, "similarity_boost": 0.75, "style": 0.5},
        }

        settings = emotion_settings.get(emotion, emotion_settings["friendly"])

        try:
            processed_text = self._process_audio_tags(text)

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{ELEVENLABS_API_URL}/{self.voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={
                        "text": processed_text,
                        "model_id": self.model_id,
                        "voice_settings": {
                            **settings,
                            "use_speaker_boost": True,
                        },
                    },
                )

                if response.status_code == 200:
                    logger.info(f"Áudio emocional ({emotion}) gerado: {len(response.content)} bytes")
                    return response.content
                else:
                    logger.error(f"Erro ElevenLabs emocional: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Erro no TTS emocional: {e}")
            return None

    def audio_to_base64(self, audio_bytes: bytes) -> str:
        """Converte áudio para base64"""
        return base64.b64encode(audio_bytes).decode("utf-8")


def clean_text_tags(text: str) -> str:
    """
    Remove todas as tags de áudio do texto para mensagens de texto
    Usado quando a mensagem vai ser enviada como texto, não áudio
    """
    # Remove todas as tags entre colchetes
    text = re.sub(r'\[pausa curta\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[pausa longa\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[pausa\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[riso leve\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[riso\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[risada\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[entusiasmado\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[animado\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[curioso\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[voz mais séria\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[sério\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[calmo\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[triste\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[feliz\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[ênfase\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[enfase\]', '', text, flags=re.IGNORECASE)

    # Remove qualquer outra tag entre colchetes
    text = re.sub(r'\[[^\]]*\]', '', text)

    # Limpa espaços extras
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# Instância singleton
tts_service = TTSService()
