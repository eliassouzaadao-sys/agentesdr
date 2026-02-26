"""
Serviço Google Sheets para armazenamento de leads
"""
import gspread
from google.oauth2.service_account import Credentials
from typing import Optional, List
import logging
from datetime import datetime

from config import get_settings
from models import Lead

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsService:
    """Gerenciador de Google Sheets"""

    def __init__(self):
        self.settings = get_settings()
        self.client: Optional[gspread.Client] = None
        self.sheet = None
        self.enabled = False

    def connect(self):
        """Conecta ao Google Sheets (opcional)"""
        if self.client:
            return

        import os

        creds_file = self.settings.google_sheets_credentials_file

        # Verifica se o arquivo existe
        if not os.path.exists(creds_file):
            logger.warning(f"Google Sheets desabilitado: arquivo {creds_file} não encontrado")
            return

        try:
            creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(
                self.settings.google_sheets_document_id
            ).sheet1
            self.enabled = True
            logger.info("Conectado ao Google Sheets")
        except Exception as e:
            logger.warning(f"Google Sheets desabilitado: {e}")
            self.enabled = False

    def append_lead(self, lead: Lead) -> bool:
        """Adiciona um novo lead à planilha"""
        if not self.enabled:
            logger.debug("Google Sheets desabilitado, lead não salvo na planilha")
            return False

        try:
            if not self.sheet:
                self.connect()

            row = [
                lead.nome,
                lead.whatsapp,
                lead.segmento,
                lead.origem,
                lead.data_criacao.strftime("%Y-%m-%d %H:%M:%S"),
                lead.status,
                lead.qualificacao or "",
                lead.etapa_spin,
            ]

            self.sheet.append_row(row)
            logger.info(f"Lead {lead.nome} adicionado à planilha")
            return True

        except Exception as e:
            logger.error(f"Erro ao adicionar lead: {e}")
            return False

    def update_lead_status(
        self, whatsapp: str, status: str, qualificacao: Optional[str] = None
    ) -> bool:
        """Atualiza status de um lead existente"""
        if not self.enabled:
            return False

        try:
            if not self.sheet:
                self.connect()

            # Encontra a linha pelo WhatsApp (coluna B)
            cell = self.sheet.find(whatsapp)
            if cell:
                row = cell.row
                self.sheet.update_cell(row, 6, status)  # Coluna F (status)
                if qualificacao:
                    self.sheet.update_cell(row, 7, qualificacao)  # Coluna G
                logger.info(f"Lead {whatsapp} atualizado: {status}")
                return True

            return False

        except Exception as e:
            logger.error(f"Erro ao atualizar lead: {e}")
            return False

    def get_lead_by_whatsapp(self, whatsapp: str) -> Optional[Lead]:
        """Busca lead pelo WhatsApp"""
        if not self.enabled:
            return None

        try:
            if not self.sheet:
                self.connect()

            cell = self.sheet.find(whatsapp)
            if cell:
                row = self.sheet.row_values(cell.row)
                return Lead(
                    nome=row[0],
                    whatsapp=row[1],
                    segmento=row[2],
                    origem=row[3],
                    data_criacao=datetime.strptime(row[4], "%Y-%m-%d %H:%M:%S"),
                    status=row[5] if len(row) > 5 else "novo",
                    qualificacao=row[6] if len(row) > 6 else None,
                    etapa_spin=row[7] if len(row) > 7 else "situacao",
                )

            return None

        except Exception as e:
            logger.error(f"Erro ao buscar lead: {e}")
            return None

    def get_all_leads(self) -> List[Lead]:
        """Retorna todos os leads"""
        if not self.enabled:
            return []

        try:
            if not self.sheet:
                self.connect()

            records = self.sheet.get_all_records()
            leads = []

            for record in records:
                try:
                    lead = Lead(
                        nome=record.get("nome", ""),
                        whatsapp=record.get("whatsapp", ""),
                        segmento=record.get("segmento", ""),
                        origem=record.get("origem", ""),
                        status=record.get("status", "novo"),
                        qualificacao=record.get("qualificacao"),
                        etapa_spin=record.get("etapa_spin", "situacao"),
                    )
                    leads.append(lead)
                except Exception:
                    continue

            return leads

        except Exception as e:
            logger.error(f"Erro ao listar leads: {e}")
            return []


# Instância singleton
sheets_service = SheetsService()
