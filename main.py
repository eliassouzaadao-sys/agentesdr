"""
Agente SDR - FastAPI Application
Webhooks para captura de leads e processamento de mensagens WhatsApp
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import get_settings
from middleware.auth import verify_api_key, verify_webhook_signature

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
from models import Lead, WhatsAppWebhook, WhatsAppMessage
from services.redis_service import redis_service
from services.sheets_service import sheets_service
from services.whatsapp_service import create_whatsapp_service
from services.message_processor import message_processor
from services.tts_service import tts_service
from services.followup_service import followup_service
from services.supabase_service import supabase_service
from utils.media_decision import should_use_audio, clean_audio_tags

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Lifecycle do app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown da aplicação"""
    # Startup
    logger.info("Iniciando Agente SDR...")
    await redis_service.connect()
    sheets_service.connect()
    supabase_service.connect()  # Conecta ao Supabase (CRM)
    await followup_service.start()  # Inicia scheduler de follow-ups
    logger.info("Agente SDR iniciado com sucesso!")

    yield

    # Shutdown
    logger.info("Encerrando Agente SDR...")
    await followup_service.stop()  # Para scheduler de follow-ups
    await redis_service.disconnect()


# Cria app FastAPI
app = FastAPI(
    title="Agente SDR",
    description="Sistema de SDR automatizado com IA para qualificação de leads via WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== MODELOS DE REQUEST ====================


class CapturaRequest(BaseModel):
    """Request do webhook de captura (formulário)"""

    body: dict


# ==================== ROTAS ====================


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "service": "Agente SDR"}


@app.get("/health")
async def health():
    """Health check detalhado"""
    return {
        "status": "healthy",
        "redis": "connected",
        "sheets": "connected",
    }


# ==================== WEBHOOK CAPTURA ====================


@app.post("/webhook/captura")
@limiter.limit("30/minute")
async def webhook_captura(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook para captura de leads do formulário
    Fluxo: Salva no Sheets → Gera boas-vindas → Envia WhatsApp
    Rate limit: 30 requisições por minuto
    """
    try:
        content_type = request.headers.get("content-type", "")

        # Suporta JSON e form-data
        if "application/json" in content_type:
            raw_body = await request.json()
        else:
            # Form data (application/x-www-form-urlencoded ou multipart/form-data)
            form = await request.form()
            raw_body = dict(form)

        logger.info(f"Captura recebida: {raw_body}")

        # Extrai dados - pode vir direto ou dentro de "body"
        data = raw_body.get("body", raw_body) if isinstance(raw_body, dict) else raw_body

        # Função helper para buscar campo com múltiplos aliases
        def get_field(keys: list, default=""):
            for key in keys:
                if key in data:
                    return data[key]
            return default

        # Extrai dados do lead (suporta múltiplos formatos de campo)
        lead = Lead(
            nome=get_field(["Sem rótulo nome", "Sem rotulo nome", "nome"]),
            whatsapp=get_field(["Sem rótulo whatsapp", "Sem rotulo whatsapp", "whatsapp"]),
            segmento=get_field(["Sem rótulo field_689ee39", "Sem rotulo field_689ee39", "segmento"]),
            origem=get_field(["lead_source", "origem"], "formulario"),
        )

        if not lead.whatsapp:
            raise HTTPException(status_code=400, detail="WhatsApp é obrigatório")

        # Salva no Google Sheets (síncrono)
        sheets_service.append_lead(lead)

        # Processa em background
        background_tasks.add_task(process_new_lead, lead)

        return {"status": "ok", "message": "Lead recebido e processando"}

    except Exception as e:
        logger.error(f"Erro no webhook de captura: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def process_new_lead(lead: Lead):
    """Processa novo lead em background"""
    try:
        settings = get_settings()

        # Salva lead no Supabase (CRM)
        await supabase_service.create_lead({
            "nome": lead.nome,
            "whatsapp": lead.whatsapp,
            "segmento": lead.segmento,
            "origem": lead.origem,
            "remote_jid": lead.remote_jid(),
        })

        # Importa agente SDR unificado (usado para boas-vindas e conversa)
        if settings.agent_framework == "agno":
            from agents.agno.sdr_agent import agno_sdr_agent as sdr_agent
        else:
            from agents.langchain.sdr_agent import langchain_sdr_agent as sdr_agent

        # Gera mensagem de boas-vindas usando SDR agent com flag is_first_contact
        message = await sdr_agent.process_message(
            sender=lead.remote_jid(),
            message="",  # Vazio no primeiro contato
            lead_name=lead.nome,
            lead_segmento=lead.segmento,
            lead_origem=lead.origem,
            is_first_contact=True,  # Flag para primeiro contato
        )

        # Salva estado inicial do lead (marca que já teve contato)
        await redis_service.set_lead_state(
            lead.remote_jid(),
            {
                "nome": lead.nome,
                "segmento": lead.segmento,
                "origem": lead.origem,
                "etapa_spin": "situacao",
                "primeiro_contato": True,  # Marca que já houve primeiro contato
            },
        )

        # Salva mensagem de boas-vindas no histórico
        await redis_service.add_to_history(lead.remote_jid(), "assistant", message)

        # Envia via WhatsApp
        whatsapp = create_whatsapp_service()

        # Primeiro contato - envia como áudio para ser mais pessoal
        use_audio, reason = should_use_audio(message, is_first_contact=True)

        if use_audio:
            logger.info(f"Enviando boas-vindas como ÁUDIO para {lead.nome} ({reason})")
            audio_bytes = await tts_service.text_to_audio(message)
            if audio_bytes:
                audio_base64 = tts_service.audio_to_base64(audio_bytes)
                await whatsapp.send_audio_with_presence(lead.remote_jid(), audio_base64, text_content=message)
            else:
                # Fallback para texto se TTS falhar
                logger.warning("TTS falhou, enviando como texto")
                await whatsapp.send_long_message(lead.remote_jid(), message)
        else:
            logger.info(f"Enviando boas-vindas como TEXTO para {lead.nome} ({reason})")
            await whatsapp.send_long_message(lead.remote_jid(), message)

        # Agenda follow-ups caso o lead não responda
        await followup_service.schedule_followup(
            sender=lead.remote_jid(),
            nome=lead.nome,
            segmento=lead.segmento,
        )

        logger.info(f"Lead {lead.nome} processado com sucesso (follow-ups agendados)")

    except Exception as e:
        logger.error(f"Erro ao processar lead: {e}")


# ==================== WEBHOOK WHATSAPP ====================


@app.post("/webhook/whatsapp")
@limiter.limit("60/minute")
async def webhook_whatsapp(request: Request):
    """
    Webhook para mensagens do WhatsApp (Evolution API)
    Fluxo: Valida Signature → Filtra → Debounce → Processa com AI → Responde
    Rate limit: 60 requisições por minuto
    """
    try:
        # Lê body e valida assinatura
        body_bytes = await request.body()
        signature = request.headers.get("x-webhook-signature") or request.headers.get("X-Webhook-Signature")
        verify_webhook_signature(body_bytes, signature)

        # Parse JSON
        body = json.loads(body_bytes)
        event = body.get("event", "")
        logger.info(f"Webhook WhatsApp: event={event}")

        # Loga body completo para debug
        if event == "messages.upsert":
            logger.info(f"Body messages.upsert: {body}")

        # Ignora eventos que não são mensagens novas
        if event not in ["messages.upsert", "message", "messages.set"]:
            return {"status": "ok", "ignored": True, "reason": f"event={event}"}

        # Parse do webhook
        webhook = WhatsAppWebhook(**body)

        logger.info(f"Webhook parsed: sender={webhook.sender}, fromMe={webhook.is_from_me}, type={webhook.get_message_type()}")

        # Processa mensagem
        async def handle_message(message: WhatsAppMessage) -> Optional[str]:
            """Callback para processar mensagem consolidada"""
            settings = get_settings()

            # IMPORTANTE: Cancela follow-ups quando o lead responde
            await followup_service.cancel_followup(message.sender)

            # Marca no Supabase que o lead respondeu
            await supabase_service.mark_lead_responded(message.sender)

            # Recupera estado do lead
            state = await redis_service.get_lead_state(message.sender)
            lead_name = state.get("nome", "Lead") if state else "Lead"
            lead_segmento = state.get("segmento", "não especificado") if state else "não especificado"
            lead_origem = state.get("origem", "formulário") if state else "formulário"

            # Importa agente SDR
            if settings.agent_framework == "agno":
                from agents.agno.sdr_agent import agno_sdr_agent as sdr_agent
            else:
                from agents.langchain.sdr_agent import langchain_sdr_agent as sdr_agent

            # Processa com agente
            response = await sdr_agent.process_message(
                sender=message.sender,
                message=message.text,
                lead_name=lead_name,
                lead_segmento=lead_segmento,
                lead_origem=lead_origem,
            )

            return response

        # Processa webhook (com debounce interno)
        processed = await message_processor.process_webhook(webhook, handle_message)

        return {"status": "ok", "processed": processed}

    except Exception as e:
        logger.error(f"Erro no webhook WhatsApp: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ENDPOINTS AUXILIARES ====================


@app.post("/admin/block/{sender}")
async def block_chat(sender: str, _: bool = Depends(verify_api_key)):
    """Bloqueia chat para intervenção humana"""
    await redis_service.block_chat(sender)
    return {"status": "blocked", "sender": sender}


@app.post("/admin/unblock/{sender}")
async def unblock_chat(sender: str, _: bool = Depends(verify_api_key)):
    """Desbloqueia chat"""
    await redis_service.unblock_chat(sender)
    return {"status": "unblocked", "sender": sender}


@app.get("/admin/lead/{sender}")
async def get_lead_state(sender: str, _: bool = Depends(verify_api_key)):
    """Retorna estado do lead"""
    state = await redis_service.get_lead_state(sender)
    history = await redis_service.get_conversation_history(sender)
    return {
        "sender": sender,
        "state": state,
        "history_count": len(history),
        "history": history[-5:] if history else [],  # Últimas 5 mensagens
    }


@app.get("/admin/summary/{sender}")
async def get_conversation_summary(sender: str, _: bool = Depends(verify_api_key)):
    """Gera resumo da conversação"""
    settings = get_settings()

    if settings.agent_framework == "agno":
        from agents.agno.sdr_agent import agno_sdr_agent as sdr_agent
    else:
        from agents.langchain.sdr_agent import langchain_sdr_agent as sdr_agent

    summary = await sdr_agent.get_conversation_summary(sender)
    return {"sender": sender, "summary": summary}


# ==================== FOLLOW-UP ENDPOINTS ====================


@app.get("/admin/followup/{sender}")
async def get_followup_status(sender: str, _: bool = Depends(verify_api_key)):
    """Retorna status do follow-up para um lead"""
    state = await followup_service.get_followup_state(sender)
    if not state:
        return {"sender": sender, "followup": None, "message": "Sem follow-up agendado"}

    return {
        "sender": sender,
        "followup": {
            "nome": state.get("nome"),
            "segmento": state.get("segmento"),
            "attempts": state.get("attempts", 0),
            "max_attempts": 9,
            "started_at": state.get("started_at"),
            "last_sent": state.get("last_sent"),
            "last_period": state.get("last_period"),
            "cancelled": state.get("cancelled", False),
        },
    }


@app.post("/admin/followup/{sender}/cancel")
async def admin_cancel_followup(sender: str, _: bool = Depends(verify_api_key)):
    """Cancela follow-ups para um lead"""
    await followup_service.cancel_followup(sender)
    return {"status": "cancelled", "sender": sender}


@app.post("/admin/followup/{sender}/trigger")
async def trigger_followup(sender: str, background_tasks: BackgroundTasks, _: bool = Depends(verify_api_key)):
    """Força envio de um follow-up imediatamente (para teste)"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    state = await followup_service.get_followup_state(sender)
    if not state:
        raise HTTPException(status_code=404, detail="Lead não tem follow-up agendado")

    if state.get("cancelled"):
        raise HTTPException(status_code=400, detail="Follow-up já foi cancelado")

    if state.get("attempts", 0) >= 9:
        raise HTTPException(status_code=400, detail="Máximo de tentativas atingido")

    # Envia em background
    async def send_now():
        now = datetime.now(ZoneInfo("America/Sao_Paulo"))
        hour = now.hour
        if hour < 12:
            period = "morning"
        elif hour < 18:
            period = "afternoon"
        else:
            period = "night"

        await followup_service._send_followup_message(sender, state, period)

    background_tasks.add_task(send_now)
    return {"status": "triggered", "sender": sender, "current_attempts": state.get("attempts", 0)}


# ==================== API CRM ====================


@app.get("/api/leads")
async def api_get_leads(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=100, ge=1),
    offset: int = Query(default=0, ge=0),
    _: bool = Depends(verify_api_key)
):
    """Retorna lista de leads para o CRM com paginação"""
    leads = await supabase_service.get_leads_paginated(status, limit, offset)
    total = await supabase_service.count_leads(status)
    return {
        "leads": leads,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/leads/{remote_jid}")
async def api_get_lead(remote_jid: str, _: bool = Depends(verify_api_key)):
    """Retorna um lead especifico pelo remote_jid"""
    lead = await supabase_service.get_lead_by_remote_jid(remote_jid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return {"lead": lead}


@app.get("/api/contatos")
async def api_get_contatos(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=100, ge=1),
    offset: int = Query(default=0, ge=0),
    _: bool = Depends(verify_api_key)
):
    """Retorna lista de contatos para o CRM com paginação"""
    contatos = await supabase_service.get_contatos_paginated(status, limit, offset)
    total = await supabase_service.count_contatos(status)
    return {
        "contatos": contatos,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/contatos/{remote_jid}")
async def api_get_contato(remote_jid: str, _: bool = Depends(verify_api_key)):
    """Retorna um contato especifico pelo remote_jid"""
    contato = await supabase_service.get_contato_by_remote_jid(remote_jid)
    if not contato:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    return {"contato": contato}


# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
