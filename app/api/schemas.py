"""
Schemas Pydantic para request/response da API
"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field


# =============================================================================
# REQUEST
# =============================================================================

class BudgetRequest(BaseModel):
    """Request para gerar orçamento"""
    mensagem: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Texto descrevendo o orçamento desejado"
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider LLM a usar (ollama, openai, anthropic)"
    )
    nome_obra: Optional[str] = Field(
        default=None,
        description="Nome da obra para persistir (opcional)"
    )


# =============================================================================
# RESPONSE
# =============================================================================

class DadosExtraidosResponse(BaseModel):
    """Dados extraídos do texto"""
    quantidade: int
    tipo_construtivo: str
    padrao_construtivo: str
    uf: str
    mes_referencia: int
    ano_referencia: int


class ItemResponse(BaseModel):
    """Item do orçamento"""
    nome: str
    descricao: str
    quantidade: float
    unidade: str
    preco_unitario: float
    preco_total: float
    codigo_sinapi: Optional[str] = None
    descricao_sinapi: Optional[str] = None
    similaridade: Optional[float] = None
    nivel_confianca: str
    problema: Optional[str] = None


class EtapaResponse(BaseModel):
    """Etapa do orçamento"""
    nome: str
    itens: List[ItemResponse]
    valor_total: float


class EstatisticasResponse(BaseModel):
    """Estatísticas do processamento"""
    total_itens: int
    itens_com_preco: int
    itens_sem_composicao: int
    itens_sem_preco: int
    alta_confianca: int
    media_confianca: int
    baixa_confianca: int
    taxa_sucesso: float


class BudgetResponse(BaseModel):
    """Response completo do orçamento"""
    sucesso: bool
    dados_extraidos: Optional[DadosExtraidosResponse] = None
    etapas: List[EtapaResponse] = []
    valor_total: float = 0.0
    estatisticas: Optional[EstatisticasResponse] = None
    avisos: List[str] = []
    codigo_orcamento_criado: Optional[int] = None
    codigo_obra_criada: Optional[int] = None
    tempo_processamento: float = 0.0
    provider_usado: Optional[str] = None


class HealthResponse(BaseModel):
    """Status de saúde da aplicação"""
    status: str
    llm_providers: List[str]
    database: str
    spring_api: str


class ProvidersResponse(BaseModel):
    """Lista de providers disponíveis"""
    providers: List[str]
    default: str


class ErrorResponse(BaseModel):
    """Resposta de erro"""
    erro: str
    detalhes: Optional[Any] = None
