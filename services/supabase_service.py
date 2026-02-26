"""
Servico Supabase para persistencia de leads e contatos
"""
from supabase import create_client, Client
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime

from config import get_settings

logger = logging.getLogger(__name__)


class SupabaseService:
    """Gerenciador de conexao com Supabase"""

    def __init__(self):
        self.settings = get_settings()
        self.client: Optional[Client] = None
        self.enabled = False

    def connect(self):
        """Conecta ao Supabase"""
        if self.client:
            return

        if not self.settings.supabase_url or not self.settings.supabase_key:
            logger.warning("Supabase nao configurado - variaveis vazias")
            self.enabled = False
            return

        try:
            self.client = create_client(
                self.settings.supabase_url,
                self.settings.supabase_key
            )
            self.enabled = True
            logger.info("Conectado ao Supabase")
        except Exception as e:
            logger.error(f"Erro ao conectar ao Supabase: {e}")
            self.enabled = False

    # ==================== LEADS ====================

    async def create_lead(self, lead_data: Dict[str, Any]) -> Optional[Dict]:
        """
        Cria um novo lead no Supabase
        Chamado quando pessoa preenche formulario (webhook/captura)
        """
        if not self.enabled:
            return None

        try:
            data = {
                "nome": lead_data.get("nome"),
                "whatsapp": lead_data.get("whatsapp"),
                "segmento": lead_data.get("segmento"),
                "origem": lead_data.get("origem", "formulario"),
                "status": "novo",
                "remote_jid": lead_data.get("remote_jid"),
                "etapa_spin": "situacao",
            }

            result = self.client.table("leads").insert(data).execute()
            logger.info(f"Lead criado: {lead_data.get('nome')}")
            return result.data[0] if result.data else None

        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                return await self.get_lead_by_whatsapp(lead_data.get("whatsapp"))
            logger.error(f"Erro ao criar lead: {e}")
            return None

    async def get_lead_by_whatsapp(self, whatsapp: str) -> Optional[Dict]:
        """Busca lead pelo numero de WhatsApp"""
        if not self.enabled:
            return None

        try:
            result = self.client.table("leads").select("*").eq("whatsapp", whatsapp).single().execute()
            return result.data
        except Exception as e:
            logger.error(f"Erro ao buscar lead: {e}")
            return None

    async def get_lead_by_remote_jid(self, remote_jid: str) -> Optional[Dict]:
        """Busca lead pelo remote_jid"""
        if not self.enabled:
            return None

        try:
            result = self.client.table("leads").select("*").eq("remote_jid", remote_jid).single().execute()
            return result.data
        except Exception:
            return None

    async def update_lead(self, lead_id: str, updates: Dict[str, Any]) -> bool:
        """Atualiza dados do lead"""
        if not self.enabled:
            return False

        try:
            updates["updated_at"] = datetime.utcnow().isoformat()
            self.client.table("leads").update(updates).eq("id", lead_id).execute()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar lead: {e}")
            return False

    async def update_lead_by_remote_jid(self, remote_jid: str, updates: Dict[str, Any]) -> bool:
        """Atualiza dados do lead pelo remote_jid"""
        if not self.enabled:
            return False

        try:
            updates["updated_at"] = datetime.utcnow().isoformat()
            self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar lead: {e}")
            return False

    async def update_lead_qualification(
        self,
        remote_jid: str,
        qualificacao: str,
        objecoes: List[str] = None,
        resumo: str = None
    ) -> bool:
        """
        Atualiza qualificacao do lead
        Chamado quando SDR identifica [QUALIFICADO] ou [NAO_QUALIFICADO]
        """
        if not self.enabled:
            return False

        try:
            updates = {
                "qualificacao": qualificacao,
                "status": "qualificado" if qualificacao == "quente" else "perdido",
                "updated_at": datetime.utcnow().isoformat(),
            }

            if objecoes:
                updates["objecoes"] = objecoes
            if resumo:
                updates["resumo_conversa"] = resumo

            self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()
            logger.info(f"Lead {remote_jid} qualificado como {qualificacao}")
            return True

        except Exception as e:
            logger.error(f"Erro ao atualizar qualificacao: {e}")
            return False

    async def mark_lead_responded(self, remote_jid: str) -> bool:
        """
        Marca que o lead respondeu uma mensagem.
        Na PRIMEIRA resposta, converte automaticamente o lead para contato.
        """
        if not self.enabled:
            return False

        try:
            # Primeiro verifica se ja respondeu
            lead = await self.get_lead_by_remote_jid(remote_jid)

            if not lead:
                logger.warning(f"Lead nao encontrado para marcar resposta: {remote_jid}")
                return False

            if lead.get("respondeu"):
                # Já respondeu antes - apenas atualiza ultima interacao
                updates = {
                    "ultima_interacao_at": datetime.utcnow().isoformat(),
                }
                self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()
            else:
                # PRIMEIRA RESPOSTA - converte para contato automaticamente
                logger.info(f"Primeira resposta de {remote_jid} - convertendo para contato")

                # Marca o lead como respondeu
                updates = {
                    "respondeu": True,
                    "primeira_resposta_at": datetime.utcnow().isoformat(),
                    "ultima_interacao_at": datetime.utcnow().isoformat(),
                }
                self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()

                # Converte para contato automaticamente
                await self.convert_lead_to_contact(remote_jid)

            return True
        except Exception as e:
            logger.error(f"Erro ao marcar resposta: {e}")
            return False

    async def update_lead_spin_stage(self, remote_jid: str, etapa: str) -> bool:
        """Atualiza a etapa SPIN do lead"""
        if not self.enabled:
            return False

        try:
            updates = {
                "etapa_spin": etapa,
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar etapa SPIN: {e}")
            return False

    async def add_objecao(self, remote_jid: str, objecao: str) -> bool:
        """
        Adiciona uma objeção identificada pelo SDR à lista de objeções do lead
        As objeções são exibidas no histórico do lead no CRM
        """
        if not self.enabled:
            return False

        try:
            # Busca o lead atual
            lead = await self.get_lead_by_remote_jid(remote_jid)
            if not lead:
                logger.warning(f"Lead nao encontrado para adicionar objecao: {remote_jid}")
                return False

            # Pega objeções existentes ou cria lista vazia
            objecoes_atuais = lead.get("objecoes") or []

            # Evita duplicatas (ignora case)
            objecao_lower = objecao.lower().strip()
            if any(o.lower().strip() == objecao_lower for o in objecoes_atuais):
                logger.info(f"Objecao ja existe para {remote_jid}: {objecao}")
                return True

            # Adiciona nova objeção
            objecoes_atuais.append(objecao.strip())

            # Atualiza no banco
            updates = {
                "objecoes": objecoes_atuais,
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.client.table("leads").update(updates).eq("remote_jid", remote_jid).execute()
            logger.info(f"Objecao adicionada para {remote_jid}: {objecao}")
            return True

        except Exception as e:
            logger.error(f"Erro ao adicionar objecao: {e}")
            return False

    # ==================== CONTATOS ====================

    async def convert_lead_to_contact(
        self,
        remote_jid: str,
        objecoes: List[str] = None,
        resumo: str = None
    ) -> Optional[Dict]:
        """
        Converte lead em contato
        Chamado quando SDR usa tag [TRANSFERIR_VENDEDOR]
        """
        if not self.enabled:
            return None

        try:
            # 1. Busca o lead
            lead = await self.get_lead_by_remote_jid(remote_jid)
            if not lead:
                logger.error(f"Lead nao encontrado para conversao: {remote_jid}")
                return None

            # 2. Cria o contato
            contato_data = {
                "nome": lead["nome"],
                "whatsapp": lead["whatsapp"],
                "empresa": lead.get("segmento"),
                "origem": lead.get("origem"),
                "status": "potencial_contato",
                "remote_jid": remote_jid,
                "lead_origem_id": lead["id"],
                "objecoes": objecoes or lead.get("objecoes"),
                "resumo_cliente": resumo or lead.get("resumo_conversa"),
            }

            result = self.client.table("contatos").insert(contato_data).execute()
            contato = result.data[0] if result.data else None

            if contato:
                # 3. Atualiza o lead marcando como convertido
                await self.update_lead(lead["id"], {
                    "status": "convertido",
                    "convertido_para_contato_id": contato["id"],
                })
                logger.info(f"Lead {lead['nome']} convertido para contato")

            return contato

        except Exception as e:
            logger.error(f"Erro ao converter lead: {e}")
            return None

    async def get_contato_by_remote_jid(self, remote_jid: str) -> Optional[Dict]:
        """Busca contato pelo remote_jid"""
        if not self.enabled:
            return None

        try:
            result = self.client.table("contatos").select("*").eq("remote_jid", remote_jid).single().execute()
            return result.data
        except Exception:
            return None

    async def update_contato(self, contato_id: str, updates: Dict[str, Any]) -> bool:
        """Atualiza dados do contato"""
        if not self.enabled:
            return False

        try:
            updates["updated_at"] = datetime.utcnow().isoformat()
            self.client.table("contatos").update(updates).eq("id", contato_id).execute()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar contato: {e}")
            return False

    # ==================== LISTAGEM ====================

    async def get_all_leads(self, status: str = None) -> List[Dict]:
        """Retorna todos os leads, opcionalmente filtrados por status"""
        if not self.enabled:
            return []

        try:
            query = self.client.table("leads").select("*").order("created_at", desc=True)
            if status:
                query = query.eq("status", status)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Erro ao listar leads: {e}")
            return []

    async def get_all_contatos(self, status: str = None) -> List[Dict]:
        """Retorna todos os contatos, opcionalmente filtrados por status"""
        if not self.enabled:
            return []

        try:
            query = self.client.table("contatos").select("*").order("created_at", desc=True)
            if status:
                query = query.eq("status", status)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Erro ao listar contatos: {e}")
            return []


# Instancia singleton
supabase_service = SupabaseService()
