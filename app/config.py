"""
Configurações centralizadas do ObradorIA Agent
"""

from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings


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
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_timeout: int = 60

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Limiares de Confiança para Busca Semântica
    limite_alta_confianca: float = 0.75
    limite_media_confianca: float = 0.60
    limite_minimo_busca: float = 0.50

    # LLM padrão
    default_llm_provider: Literal["ollama", "openai", "anthropic"] = "ollama"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Retorna instância singleton das configurações"""
    return Settings()


# =============================================================================
# MAPEAMENTOS DE DOMÍNIO
# =============================================================================

UF_MAPPING = {
    # Siglas
    'AC': 'AC', 'AL': 'AL', 'AP': 'AP', 'AM': 'AM', 'BA': 'BA', 'CE': 'CE',
    'DF': 'DF', 'ES': 'ES', 'GO': 'GO', 'MA': 'MA', 'MT': 'MT', 'MS': 'MS',
    'MG': 'MG', 'PA': 'PA', 'PB': 'PB', 'PR': 'PR', 'PE': 'PE', 'PI': 'PI',
    'RJ': 'RJ', 'RN': 'RN', 'RS': 'RS', 'RO': 'RO', 'RR': 'RR', 'SC': 'SC',
    'SP': 'SP', 'SE': 'SE', 'TO': 'TO',
    # Nomes completos
    'ACRE': 'AC', 'ALAGOAS': 'AL', 'AMAPA': 'AP', 'AMAZONAS': 'AM',
    'BAHIA': 'BA', 'CEARA': 'CE', 'DISTRITO FEDERAL': 'DF', 'ESPIRITO SANTO': 'ES',
    'GOIAS': 'GO', 'MARANHAO': 'MA', 'MATO GROSSO': 'MT', 'MATO GROSSO DO SUL': 'MS',
    'MINAS GERAIS': 'MG', 'PARA': 'PA', 'PARAIBA': 'PB', 'PARANA': 'PR',
    'PERNAMBUCO': 'PE', 'PIAUI': 'PI', 'RIO DE JANEIRO': 'RJ', 'RIO GRANDE DO NORTE': 'RN',
    'RIO GRANDE DO SUL': 'RS', 'RONDONIA': 'RO', 'RORAIMA': 'RR', 'SANTA CATARINA': 'SC',
    'SAO PAULO': 'SP', 'SERGIPE': 'SE', 'TOCANTINS': 'TO'
}

PADRAO_MAPPING = {
    'MINIMO': ['minimo', 'mínimo', 'simples', 'economico', 'econômico', 'popular', 'baixo'],
    'BASICO': ['basico', 'básico', 'intermediario', 'intermediário', 'padrao', 'padrão', 'medio', 'médio'],
    'ALTO': ['alto', 'luxo', 'premium', 'superior', 'fino', 'nobre']
}

TIPO_MAPPING = {
    'RESIDENCIAL_CASA': [
        'casa', 'casas', 'residencia', 'residência', 'residencias',
        'residências', 'moradia', 'moradias', 'habitacao', 'habitação',
        'habitacoes', 'habitações', 'casas populares', 'unidades habitacionais'
    ],
    'RESIDENCIAL_APARTAMENTO': [
        'apartamento', 'apartamentos', 'apto', 'aptos', 'apt',
        'unidade habitacional', 'flat', 'flats'
    ],
    'RESIDENCIAL_SOBRADO': [
        'sobrado', 'sobrados', 'casa de dois andares', 'casa duplex',
        'duplex', 'casa dois pavimentos'
    ],
    'RESIDENCIAL_KITNET': [
        'kitnet', 'kitnets', 'kitinete', 'kitinetes', 'quitinete',
        'quitinetes', 'studio', 'studios', 'conjugado', 'conjugados'
    ]
}

# Tipos não suportados - para aviso ao usuário
TIPOS_NAO_SUPORTADOS = {
    'ESPORTIVO': ['quadra', 'ginasio', 'ginásio', 'campo', 'piscina', 'academia', 'esporte'],
    'COMERCIAL': ['loja', 'galpao', 'galpão', 'escritorio', 'escritório', 'comercial', 'shopping'],
    'INDUSTRIAL': ['fabrica', 'fábrica', 'industria', 'indústria', 'barracao', 'barracão', 'armazem', 'armazém'],
    'INFRAESTRUTURA': ['ponte', 'estrada', 'viaduto', 'tunel', 'túnel', 'rodovia', 'ferrovia'],
    'INSTITUCIONAL': ['escola', 'hospital', 'igreja', 'predio publico', 'prédio público', 'prefeitura', 'forum', 'fórum']
}

# Lista de tipos residenciais disponíveis (para exibir ao usuário)
TIPOS_RESIDENCIAIS_DISPONIVEIS = ['Casa', 'Apartamento', 'Sobrado', 'Kitnet']

MESES_MAPPING = {
    'JANEIRO': 1, 'JAN': 1,
    'FEVEREIRO': 2, 'FEV': 2,
    'MARCO': 3, 'MAR': 3, 'MARÇO': 3,
    'ABRIL': 4, 'ABR': 4,
    'MAIO': 5, 'MAI': 5,
    'JUNHO': 6, 'JUN': 6,
    'JULHO': 7, 'JUL': 7,
    'AGOSTO': 8, 'AGO': 8,
    'SETEMBRO': 9, 'SET': 9,
    'OUTUBRO': 10, 'OUT': 10,
    'NOVEMBRO': 11, 'NOV': 11,
    'DEZEMBRO': 12, 'DEZ': 12
}
