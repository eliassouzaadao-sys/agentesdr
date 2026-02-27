"""
Middleware de Autenticação
Valida API Key para endpoints protegidos
Valida webhook signature para segurança de webhooks
"""
import hmac
import hashlib
import logging
from fastapi import Header, HTTPException, Request
from config import get_settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Valida assinatura do webhook para garantir que vem da Evolution API.
    A assinatura é um HMAC-SHA256 do body usando webhook_secret como chave.

    Args:
        body: Body da requisição em bytes
        signature: Valor do header x-webhook-signature

    Returns:
        True se válido

    Raises:
        HTTPException se inválido
    """
    settings = get_settings()

    # Se não tiver secret configurado, permite acesso (dev mode)
    if not settings.webhook_secret:
        return True

    if not signature:
        logger.warning("Webhook sem assinatura recebido")
        raise HTTPException(
            status_code=401,
            detail="Webhook signature não fornecida"
        )

    # Calcula assinatura esperada
    expected = hmac.new(
        settings.webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    # Compara de forma segura (timing-safe)
    if not hmac.compare_digest(signature, expected):
        logger.warning(f"Webhook com assinatura inválida: received={signature[:16]}...")
        raise HTTPException(
            status_code=401,
            detail="Webhook signature inválida"
        )

    logger.debug("Webhook signature válida")
    return True


async def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Valida API Key no header X-API-Key.
    Usado como dependency nos endpoints admin e api.
    """
    settings = get_settings()

    # Se não tiver chave configurada, permite acesso (dev mode)
    if not settings.admin_api_key:
        return True

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key não fornecida. Use o header X-API-Key."
        )

    if x_api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida"
        )

    return True
