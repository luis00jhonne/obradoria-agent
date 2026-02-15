"""
Schemas Pydantic para request/response da API
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# =============================================================================
# REQUEST
# =============================================================================

class BudgetRequest(BaseModel):
    """Request para gerar orçamento (modo não-conversacional)"""
    mensagem: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Texto descrevendo o orçamento desejado",
        json_schema_extra={
            "example": "Construir 2 casas residenciais padrão mínimo no Maranhão para janeiro de 2025"
        }
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider LLM a usar (ollama, openai, anthropic)"
    )
    nome_obra: Optional[str] = Field(
        default=None,
        description="Nome da obra para persistir (opcional)",
        json_schema_extra={"example": "Residencial Popular MA"}
    )


class RespostaCampo(BaseModel):
    """Resposta a uma pergunta sobre um campo específico"""
    campo: str = Field(
        ...,
        description="Nome do campo sendo respondido",
        json_schema_extra={"example": "uf"}
    )
    valor: Any = Field(
        ...,
        description="Valor da resposta",
        json_schema_extra={"example": "SP"}
    )


class ConversationRequest(BaseModel):
    """Request para fluxo conversacional"""
    mensagem: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Mensagem inicial ou vazia para continuação",
        json_schema_extra={
            "example": "quero construir uma casa"
        }
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID da sessão existente para continuação",
        json_schema_extra={"example": "550e8400-e29b-41d4-a716-446655440000"}
    )
    resposta: Optional[RespostaCampo] = Field(
        default=None,
        description="Resposta a uma pergunta pendente"
    )
    acao: Optional[str] = Field(
        default=None,
        description="Ação do usuário: 'confirmar' ou 'corrigir'",
        json_schema_extra={"example": "confirmar"}
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider LLM a usar (ollama, openai, anthropic)"
    )
    nome_obra: Optional[str] = Field(
        default=None,
        description="Nome da obra para persistir (opcional)",
        json_schema_extra={"example": "Residencial Popular MA"}
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
    erros: List[str] = []
    avisos: List[str] = []
    codigo_orcamento_criado: Optional[int] = None
    codigo_obra_criada: Optional[int] = None
    tempo_processamento: float = 0.0
    provider_usado: Optional[str] = None
    fonte_estrutura: str = "api"  # "api" ou "llm"


class ComponentHealthResponse(BaseModel):
    """Status de um componente"""
    status: str
    detalhes: Optional[str] = None


class HealthResponse(BaseModel):
    """Status de saúde da aplicação"""
    status: str
    components: Dict[str, ComponentHealthResponse]
    llm_providers: List[str]


class ProvidersResponse(BaseModel):
    """Lista de providers disponíveis"""
    providers: List[str]
    default: str


class ErrorResponse(BaseModel):
    """Resposta de erro"""
    erro: str
    detalhes: Optional[Any] = None


# =============================================================================
# CONVERSATION EVENTS (para documentação SSE)
# =============================================================================

class SessionEvent(BaseModel):
    """Evento de sessão criada/retomada"""
    etapa: str = Field(
        description="session_created | session_resumed | session_expired"
    )
    mensagem: str
    dados: Dict[str, Any] = Field(
        description="Contém session_id e opcionalmente fase atual",
        json_schema_extra={
            "example": {"session_id": "550e8400-e29b-41d4-a716-446655440000"}
        }
    )


class ExtractionEvent(BaseModel):
    """Evento de extração de informações"""
    etapa: str = Field(
        description="extraction_start | extraction_partial"
    )
    mensagem: str
    progresso: Optional[float] = None
    dados: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Campos extraídos, faltantes e com padrão",
        json_schema_extra={
            "example": {
                "session_id": "abc123",
                "extraidos": {"uf": {"valor": "SP", "fonte": "usuario"}},
                "faltantes": ["padrao_construtivo"],
                "com_padrao": {"quantidade": 1}
            }
        }
    )


class QuestionEvent(BaseModel):
    """Evento de pergunta ao usuário"""
    etapa: str = Field(
        default="question",
        description="Sempre 'question'"
    )
    mensagem: str = Field(
        description="A pergunta a ser feita ao usuário",
        json_schema_extra={"example": "Em qual estado será construída a obra?"}
    )
    dados: Dict[str, Any] = Field(
        description="Dados da pergunta",
        json_schema_extra={
            "example": {
                "session_id": "abc123",
                "campo": "uf",
                "tipo": "select",
                "opcoes": ["SP", "RJ", "MG"]
            }
        }
    )


class ConfirmDefaultsEvent(BaseModel):
    """Evento para confirmação de valores padrão"""
    etapa: str = Field(
        default="confirm_defaults",
        description="Sempre 'confirm_defaults'"
    )
    mensagem: str = Field(
        default="Confirme os valores padrão que serão utilizados:"
    )
    dados: Dict[str, Any] = Field(
        description="Valores padrão para confirmação",
        json_schema_extra={
            "example": {
                "session_id": "abc123",
                "defaults": {
                    "quantidade": {"valor": 1, "pode_alterar": True},
                    "mes_referencia": {"valor": 1, "pode_alterar": True},
                    "ano_referencia": {"valor": 2025, "pode_alterar": True}
                }
            }
        }
    )


class SummaryConfirmEvent(BaseModel):
    """Evento de resumo para confirmação final"""
    etapa: str = Field(
        default="confirm_summary",
        description="Sempre 'confirm_summary'"
    )
    mensagem: str = Field(
        default="Confirme os dados do orçamento:"
    )
    dados: Dict[str, Any] = Field(
        description="Resumo completo para confirmação",
        json_schema_extra={
            "example": {
                "session_id": "abc123",
                "resumo": {
                    "quantidade": 2,
                    "tipo_construtivo": "RESIDENCIAL",
                    "padrao_construtivo": "BASICO",
                    "uf": "SP",
                    "mes_referencia": 1,
                    "ano_referencia": 2025
                }
            }
        }
    )


class FieldUpdatedEvent(BaseModel):
    """Evento de campo atualizado"""
    etapa: str = Field(
        default="field_updated",
        description="Sempre 'field_updated'"
    )
    mensagem: str
    dados: Dict[str, Any] = Field(
        description="Campo e valor atualizados",
        json_schema_extra={
            "example": {
                "session_id": "abc123",
                "campo": "uf",
                "valor": "SP"
            }
        }
    )
