"""
Configurações do Agente SDR
Carrega variáveis de ambiente e define configurações globais
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Configurações carregadas do .env"""

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_ttl_block: int = 7200  # 2 horas em segundos
    redis_ttl_debounce: int = 20  # segundos para debounce

    # Evolution API (WhatsApp)
    evolution_api_url: str
    evolution_api_key: str
    evolution_instance: str

    # Google Sheets
    google_sheets_credentials_file: str = "credentials.json"
    google_sheets_document_id: str

    # Configurações do Bot
    bot_name: str = "Luana"
    message_delay_min: float = 1.0  # segundos
    message_delay_max: float = 3.0  # segundos

    # Agent Framework (langchain ou agno)
    agent_framework: str = "agno"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações"""
    return Settings()
