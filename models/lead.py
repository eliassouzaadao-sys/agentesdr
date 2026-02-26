"""
Modelos de Lead
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LeadCapture(BaseModel):
    """Dados recebidos do formulário de captura"""

    nome: str = Field(..., alias="Sem rótulo nome")
    whatsapp: str = Field(..., alias="Sem rótulo whatsapp")
    segmento: str = Field(..., alias="Sem rótulo field_689ee39")
    origem: str = Field(default="formulario", alias="lead_source")

    class Config:
        populate_by_name = True


class Lead(BaseModel):
    """Modelo completo de um lead"""

    nome: str
    whatsapp: str
    segmento: str
    origem: str
    data_criacao: datetime = Field(default_factory=datetime.now)
    status: str = "novo"
    qualificacao: Optional[str] = None  # quente, morno, frio
    etapa_spin: str = "situacao"  # situacao, problema, implicacao, necessidade
    vendedor_responsavel: Optional[str] = None

    def telefone_formatado(self) -> str:
        """Retorna telefone formatado com código do país"""
        numero = "".join(filter(str.isdigit, self.whatsapp))
        if not numero.startswith("55"):
            numero = f"55{numero}"
        return numero

    def remote_jid(self) -> str:
        """Retorna o remoteJid para WhatsApp"""
        return f"{self.telefone_formatado()}@s.whatsapp.net"
