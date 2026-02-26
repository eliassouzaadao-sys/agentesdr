"""
Processador de Mensagens
Gerencia fluxo de mensagens recebidas com debounce, bloqueio e processamento
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable
from datetime import datetime

from models import WhatsAppWebhook, WhatsAppMessage, MessageType
from services.redis_service import redis_service
from services.whatsapp_service import create_whatsapp_service
from services.openai_service import openai_service
from services.tts_service import tts_service
from config import get_settings
from utils.media_decision import should_use_audio, clean_audio_tags

logger = logging.getLogger(__name__)

# Armazena tasks de debounce ativas
_debounce_tasks: dict[str, asyncio.Task] = {}


class MessageProcessor:
    """Processa mensagens recebidas do WhatsApp"""

    def __init__(self):
        self.settings = get_settings()

    async def process_webhook(
        self,
        webhook: WhatsAppWebhook,
        on_message: Callable[[WhatsAppMessage], Awaitable[Optional[str]]],
    ) -> bool:
        """
        Processa webhook recebido da Evolution API

        Args:
            webhook: Dados do webhook
            on_message: Callback para processar a mensagem (recebe WhatsAppMessage, retorna resposta)

        Returns:
            True se a mensagem foi processada, False se foi ignorada
        """
        sender = webhook.sender

        # 1. Ignora mensagens próprias (fromMe)
        if webhook.is_from_me:
            logger.debug(f"Ignorando mensagem própria de {sender}")
            return False

        # 2. Verifica se é uma mensagem da IA (evita loop)
        text_content = webhook.get_text_content()
        if text_content and await redis_service.is_ai_message(sender, text_content):
            logger.debug(f"Ignorando mensagem da IA para {sender}")
            return False

        # 3. Verifica bloqueio (intervenção humana)
        if await redis_service.is_chat_blocked(sender):
            logger.info(f"Chat bloqueado para {sender}, ignorando")
            return False

        # 4. Processa tipo de mensagem
        message_type = webhook.get_message_type()
        final_text = await self._extract_message_content(webhook, message_type)

        if not final_text:
            logger.warning(f"Não foi possível extrair conteúdo da mensagem")
            return False

        # 5. Cria objeto de mensagem
        message = WhatsAppMessage.from_webhook(webhook, final_text)

        # 6. Aplica debounce e processa
        await self._process_with_debounce(message, on_message)

        return True

    async def _extract_message_content(
        self, webhook: WhatsAppWebhook, message_type: MessageType
    ) -> Optional[str]:
        """Extrai conteúdo da mensagem baseado no tipo"""

        if message_type == MessageType.CONVERSATION:
            return webhook.get_text_content()

        elif message_type == MessageType.EXTENDED_TEXT:
            return webhook.get_text_content()

        elif message_type == MessageType.AUDIO:
            # Transcreve áudio
            logger.info(f"Processando áudio: message_id={webhook.message_id}")
            whatsapp = create_whatsapp_service(
                webhook.server_url, webhook.apikey, webhook.instance
            )

            media = await whatsapp.get_base64_from_media(webhook.message_id)
            logger.info(f"Media response: {type(media)}, keys={media.keys() if media else 'None'}")

            if media and "base64" in media:
                logger.info(f"Transcrevendo áudio: {len(media['base64'])} chars")
                text = await openai_service.transcribe_audio_base64(
                    media["base64"], media.get("mimetype", "audio/ogg")
                )
                logger.info(f"Transcrição: {text}")
                return text
            else:
                logger.warning(f"Não foi possível obter base64 do áudio: {media}")

        elif message_type == MessageType.IMAGE:
            # Por enquanto, apenas log
            logger.info("Imagem recebida - processamento não implementado")
            return None

        elif message_type == MessageType.DOCUMENT:
            # Por enquanto, apenas log
            logger.info("Documento recebido - processamento não implementado")
            return None

        return None

    async def _process_with_debounce(
        self,
        message: WhatsAppMessage,
        on_message: Callable[[WhatsAppMessage], Awaitable[Optional[str]]],
    ):
        """Aplica debounce para concatenar mensagens"""
        sender = message.sender

        # Adiciona mensagem ao buffer
        await redis_service.add_to_buffer(sender, message.text)

        # Cancela task anterior se existir
        if sender in _debounce_tasks:
            _debounce_tasks[sender].cancel()

        # Cria nova task de debounce
        async def debounce_handler():
            try:
                await asyncio.sleep(self.settings.redis_ttl_debounce)

                # Verifica se não há novas mensagens
                messages = await redis_service.get_buffer_messages(sender)
                last_message = messages[-1] if messages else None

                if last_message and message.text in last_message:
                    # Concatena todas as mensagens
                    full_text = " ".join(messages)

                    # Limpa buffer
                    await redis_service.clear_buffer(sender)

                    # Cria mensagem consolidada
                    consolidated = WhatsAppMessage(
                        sender=message.sender,
                        text=full_text,
                        message_type=message.message_type,
                        message_id=message.message_id,
                        instance=message.instance,
                        server_url=message.server_url,
                        apikey=message.apikey,
                    )

                    # Chama callback (SDR agent adiciona mensagem ao contexto)
                    response = await on_message(consolidated)

                    # Adiciona mensagem do usuário ao histórico APÓS processamento
                    await redis_service.add_to_history(sender, "user", full_text)

                    # Envia resposta se houver
                    if response:
                        await self._send_response(consolidated, response)

            except asyncio.CancelledError:
                pass  # Task cancelada por nova mensagem
            except Exception as e:
                logger.error(f"Erro no debounce: {e}")
            finally:
                if sender in _debounce_tasks:
                    del _debounce_tasks[sender]

        _debounce_tasks[sender] = asyncio.create_task(debounce_handler())

    async def _send_response(self, message: WhatsAppMessage, response: str):
        """Envia resposta via WhatsApp com decisão inteligente entre áudio e texto"""
        from utils.message_splitter import split_message

        # Cria serviço com credenciais da mensagem original
        whatsapp = create_whatsapp_service(
            message.server_url, message.apikey, message.instance
        )

        # Verifica se tem tag de áudio e limpa
        has_audio_tag = "[ENVIAR_AUDIO]" in response
        clean_response = clean_audio_tags(response)

        # Decide se usa áudio ou texto
        use_audio, reason = should_use_audio(
            clean_response,
            is_first_contact=False,  # Já não é primeiro contato se está no SDR
            is_follow_up=False,
            has_audio_tag=has_audio_tag,
        )

        # Adiciona resposta ao histórico
        await redis_service.add_to_history(message.sender, "assistant", clean_response)

        if use_audio:
            logger.info(f"Enviando resposta como ÁUDIO para {message.sender} ({reason})")

            # Gera áudio
            audio_bytes = await tts_service.text_to_audio(clean_response)

            if audio_bytes:
                # Converte para base64 e envia com presença "gravando"
                audio_base64 = tts_service.audio_to_base64(audio_bytes)
                await whatsapp.send_audio_with_presence(
                    message.sender,
                    audio_base64,
                    duration=min(3.0, len(clean_response) / 100)  # Ajusta tempo baseado no tamanho
                )
                # Registra como mensagem da IA (para evitar loop)
                await redis_service.add_ai_message(message.sender, clean_response)
            else:
                # Fallback para texto se TTS falhar
                logger.warning("TTS falhou, enviando como texto")
                await self._send_as_text(whatsapp, message.sender, clean_response)
        else:
            logger.info(f"Enviando resposta como TEXTO para {message.sender} ({reason})")
            await self._send_as_text(whatsapp, message.sender, clean_response)

    async def _send_as_text(self, whatsapp, sender: str, response: str):
        """Envia resposta como texto com split e delay"""
        from utils.message_splitter import split_message

        # Divide resposta em partes
        parts = split_message(response)

        # Adiciona cada parte ao registro de mensagens da IA
        for part in parts:
            await redis_service.add_ai_message(sender, part)

        # Envia com delay
        await whatsapp.send_messages_with_delay(sender, parts)


# Instância singleton
message_processor = MessageProcessor()
