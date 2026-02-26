"""
Modelos de Mensagem WhatsApp
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any
from enum import Enum


class MessageType(str, Enum):
    """Tipos de mensagem suportados"""

    CONVERSATION = "conversation"
    EXTENDED_TEXT = "extendedTextMessage"
    AUDIO = "audioMessage"
    IMAGE = "imageMessage"
    DOCUMENT = "documentMessage"


class MessageKey(BaseModel):
    """Chave da mensagem WhatsApp"""

    id: str
    remoteJid: str
    fromMe: bool = False


class MessageData(BaseModel):
    """Dados da mensagem recebida - compatível com Evolution API v1 e v2"""

    key: Optional[MessageKey] = None
    keyId: Optional[str] = None  # Evolution API v2
    message: Optional[dict] = None
    messageType: Optional[str] = None
    pushName: Optional[str] = None
    # Campos extras da Evolution API v2
    remoteJid: Optional[str] = None
    fromMe: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_key(cls, values):
        """Normaliza o formato da key para compatibilidade"""
        if isinstance(values, dict):
            # Se tem key como objeto, usa diretamente
            if "key" in values and isinstance(values["key"], dict):
                return values
            # Se tem keyId (v2), cria key a partir dos campos
            if "keyId" in values:
                values["key"] = {
                    "id": values.get("keyId", ""),
                    "remoteJid": values.get("remoteJid", ""),
                    "fromMe": values.get("fromMe", False),
                }
        return values


class WhatsAppWebhook(BaseModel):
    """Payload completo do webhook da Evolution API"""

    event: Optional[str] = None
    instance: Optional[str] = None
    server_url: Optional[str] = None
    apikey: Optional[str] = None
    data: MessageData

    def get_message_type(self) -> MessageType:
        """Identifica o tipo da mensagem"""
        msg = self.data.message or {}

        if "audioMessage" in msg:
            return MessageType.AUDIO
        elif "extendedTextMessage" in msg:
            return MessageType.EXTENDED_TEXT
        elif "conversation" in msg:
            return MessageType.CONVERSATION
        elif "imageMessage" in msg:
            return MessageType.IMAGE
        elif self.data.messageType == "documentMessage":
            return MessageType.DOCUMENT

        return MessageType.CONVERSATION

    def get_text_content(self) -> Optional[str]:
        """Extrai o texto da mensagem"""
        msg = self.data.message or {}

        if "extendedTextMessage" in msg:
            return msg["extendedTextMessage"].get("text")
        elif "conversation" in msg:
            return msg["conversation"]

        return None

    @property
    def sender(self) -> str:
        """Retorna o remetente"""
        return self.data.key.remoteJid

    @property
    def is_from_me(self) -> bool:
        """Verifica se a mensagem foi enviada pelo bot"""
        return self.data.key.fromMe

    @property
    def message_id(self) -> str:
        """Retorna o ID da mensagem"""
        return self.data.key.id


class WhatsAppMessage(BaseModel):
    """Mensagem processada para uso interno"""

    sender: str
    text: str
    message_type: MessageType
    message_id: str
    is_from_me: bool = False
    instance: Optional[str] = None
    server_url: Optional[str] = None
    apikey: Optional[str] = None

    @classmethod
    def from_webhook(cls, webhook: WhatsAppWebhook, text: str) -> "WhatsAppMessage":
        """Cria mensagem a partir do webhook"""
        return cls(
            sender=webhook.sender,
            text=text,
            message_type=webhook.get_message_type(),
            message_id=webhook.message_id,
            is_from_me=webhook.is_from_me,
            instance=webhook.instance,
            server_url=webhook.server_url,
            apikey=webhook.apikey,
        )
