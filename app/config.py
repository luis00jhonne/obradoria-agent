"""
Configurações centralizadas do ObradorIA Agent
"""

from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings

# Raiz do projeto (um nivel acima de app/)
_BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configurações da aplicação via variáveis de ambiente"""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Banco de Dados (PostgreSQL + pgvector)
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "obradoria"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # API Spring Boot
    spring_api_url: str = "http://localhost:8891/api"
    spring_api_timeout: int = 30

    # Ollama (Local)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: int = 300  # 5 minutos para CoT

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_timeout: int = 60

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_timeout: int = 60

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Limiares de Confiança para Busca Semântica
    limite_alta_confianca: float = 0.75
    limite_media_confianca: float = 0.60
    limite_minimo_busca: float = 0.50

    # JWT
    jwt_secret: str = "REDACTED"

    # LLM padrão
    default_llm_provider: Literal["ollama", "openai", "anthropic"] = "ollama"

    class Config:
        env_file = str(_BASE_DIR / ".env")
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Retorna instância das configurações"""
    return Settings()
