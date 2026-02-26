"""
Serviço de Follow-up Automático
Gerencia tentativas de contato quando o lead não responde
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

from services.redis_service import redis_service
from services.whatsapp_service import create_whatsapp_service
from services.tts_service import tts_service
from config import get_settings

logger = logging.getLogger(__name__)

# Timezone Brasil
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")

# Horários de envio (hora local Brasil)
SCHEDULE_HOURS = {
    "morning": 9,      # 9h da manhã
    "afternoon": 14,   # 14h da tarde
    "night": 19,       # 19h da noite
}

# Máximo de tentativas (3 dias x 3 mensagens = 9)
MAX_FOLLOWUP_ATTEMPTS = 9


class FollowUpService:
    """Gerencia follow-ups automáticos para leads que não respondem"""

    def __init__(self):
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Inicia o scheduler de follow-ups"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler de follow-ups iniciado")

    async def stop(self):
        """Para o scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler de follow-ups parado")

    async def _scheduler_loop(self):
        """Loop principal do scheduler - verifica a cada 5 minutos"""
        while self._running:
            try:
                await self._process_pending_followups()
            except Exception as e:
                logger.error(f"Erro no scheduler de follow-ups: {e}")

            # Aguarda 5 minutos antes de verificar novamente
            await asyncio.sleep(300)

    async def _process_pending_followups(self):
        """Processa todos os follow-ups pendentes"""
        # Busca todas as chaves de follow-up no Redis
        keys = await redis_service.client.keys("*_followup")

        now = datetime.now(BRAZIL_TZ)
        current_hour = now.hour

        # Determina período atual
        current_period = self._get_current_period(current_hour)
        if not current_period:
            return  # Fora dos horários de envio

        for key in keys:
            try:
                sender = key.replace("_followup", "")
                await self._check_and_send_followup(sender, current_period, now)
            except Exception as e:
                logger.error(f"Erro ao processar follow-up para {key}: {e}")

    def _get_current_period(self, hour: int) -> Optional[str]:
        """Retorna o período atual se estiver no horário de envio"""
        # Janela de 1 hora para cada período
        if SCHEDULE_HOURS["morning"] <= hour < SCHEDULE_HOURS["morning"] + 1:
            return "morning"
        elif SCHEDULE_HOURS["afternoon"] <= hour < SCHEDULE_HOURS["afternoon"] + 1:
            return "afternoon"
        elif SCHEDULE_HOURS["night"] <= hour < SCHEDULE_HOURS["night"] + 1:
            return "night"
        return None

    async def _check_and_send_followup(self, sender: str, period: str, now: datetime):
        """Verifica e envia follow-up se necessário"""
        state = await self.get_followup_state(sender)
        if not state:
            return

        # Verifica se já atingiu o máximo de tentativas
        if state["attempts"] >= MAX_FOLLOWUP_ATTEMPTS:
            logger.info(f"Follow-up finalizado para {sender}: máximo de tentativas atingido")
            await self.cancel_followup(sender)
            return

        # Verifica se o lead respondeu (follow-up cancelado)
        if state.get("cancelled", False):
            return

        # Verifica se já enviou neste período hoje
        last_sent = state.get("last_sent")
        if last_sent:
            last_sent_dt = datetime.fromisoformat(last_sent)
            if last_sent_dt.date() == now.date():
                last_period = state.get("last_period")
                if last_period == period:
                    return  # Já enviou neste período hoje

        # Envia o follow-up
        await self._send_followup_message(sender, state, period)

    async def _send_followup_message(self, sender: str, state: Dict[str, Any], period: str):
        """Envia mensagem de follow-up"""
        from prompts.followup_prompt import get_followup_prompt
        from services.openai_service import openai_service

        # VERIFICAÇÃO DUPLA: Checa novamente se o lead respondeu antes de enviar
        # Isso evita race condition entre o scheduler e o webhook de resposta
        current_state = await self.get_followup_state(sender)
        if not current_state or current_state.get("cancelled", False):
            logger.info(f"Follow-up cancelado para {sender} (verificação dupla antes do envio)")
            return

        attempts = state["attempts"] + 1
        nome = state.get("nome", "")
        segmento = state.get("segmento", "")

        # Determina o dia (1, 2 ou 3)
        day = ((attempts - 1) // 3) + 1

        # Gera mensagem personalizada
        prompt = get_followup_prompt(
            nome=nome,
            segmento=segmento,
            attempt=attempts,
            day=day,
            period=period,
        )

        try:
            # Gera a mensagem com IA
            message = await openai_service.generate_completion(prompt)

            if not message:
                logger.error(f"Falha ao gerar mensagem de follow-up para {sender}")
                return

            # VERIFICAÇÃO FINAL: Antes de enviar, confirma que o lead não respondeu
            # (janela de tempo entre gerar mensagem e enviar)
            final_check = await self.get_followup_state(sender)
            if not final_check or final_check.get("cancelled", False):
                logger.info(f"Follow-up cancelado para {sender} (verificação final antes do WhatsApp)")
                return

            # Envia via WhatsApp
            whatsapp = create_whatsapp_service()

            # Alterna entre áudio e texto baseado no período/tentativa
            # Manhã: texto, Tarde: áudio, Noite: texto
            use_audio = period == "afternoon" and attempts % 2 == 0

            if use_audio:
                audio_bytes = await tts_service.text_to_audio(message)
                if audio_bytes:
                    audio_base64 = tts_service.audio_to_base64(audio_bytes)
                    await whatsapp.send_audio_with_presence(sender, audio_base64, duration=3.0)
                else:
                    await whatsapp.send_long_message(sender, message)
            else:
                await whatsapp.send_long_message(sender, message)

            # Atualiza estado
            now = datetime.now(BRAZIL_TZ)
            state["attempts"] = attempts
            state["last_sent"] = now.isoformat()
            state["last_period"] = period
            state["last_message"] = message

            await self._save_followup_state(sender, state)

            # Adiciona ao histórico de conversação
            await redis_service.add_to_history(sender, "assistant", message)

            logger.info(f"Follow-up #{attempts} enviado para {sender} (período: {period})")

        except Exception as e:
            logger.error(f"Erro ao enviar follow-up para {sender}: {e}")

    async def schedule_followup(
        self,
        sender: str,
        nome: str,
        segmento: str,
    ):
        """
        Agenda follow-ups para um novo lead
        Chamado após enviar a mensagem de boas-vindas
        """
        state = {
            "nome": nome,
            "segmento": segmento,
            "attempts": 0,
            "started_at": datetime.now(BRAZIL_TZ).isoformat(),
            "last_sent": None,
            "last_period": None,
            "cancelled": False,
        }

        await self._save_followup_state(sender, state)
        logger.info(f"Follow-up agendado para {sender} ({nome} - {segmento})")

    async def cancel_followup(self, sender: str):
        """
        Cancela follow-ups quando o lead responde
        Chamado quando recebemos uma mensagem do lead
        """
        state = await self.get_followup_state(sender)
        if state:
            state["cancelled"] = True
            await self._save_followup_state(sender, state)
            logger.info(f"Follow-up cancelado para {sender} (lead respondeu)")

    async def get_followup_state(self, sender: str) -> Optional[Dict[str, Any]]:
        """Recupera estado do follow-up"""
        import json
        key = f"{sender}_followup"
        data = await redis_service.client.get(key)
        return json.loads(data) if data else None

    async def _save_followup_state(self, sender: str, state: Dict[str, Any]):
        """Salva estado do follow-up"""
        import json
        key = f"{sender}_followup"
        # TTL de 4 dias (um pouco mais que os 3 dias de follow-up)
        await redis_service.client.set(key, json.dumps(state), ex=86400 * 4)


# Instância singleton
followup_service = FollowUpService()
