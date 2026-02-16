"""
Schemas Pydantic para request/response da API
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# =============================================================================
# REQUEST
# =============================================================================

class AgentRequest(BaseModel):
    """Request para o endpoint agent-based com tool use"""
    mensagem: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Mensagem do usuario",
        json_schema_extra={
            "example": "Quero construir 2 casas padrao minimo no Maranhao para janeiro de 2025"
        }
    )
    session_id: Optional[str] = Field(
        default=None,
        description="ID da sessao para conversas multi-turno"
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider LLM a usar (ollama, openai, anthropic)"
    )


# =============================================================================
# RESPONSE
# =============================================================================

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
