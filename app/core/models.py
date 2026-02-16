"""
Modelos de domínio do ObradorIA Agent
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Any
from datetime import datetime


# =============================================================================
# BUSCA SEMANTICA
# =============================================================================

class NivelConfianca(str, Enum):
    """Níveis de confiança para busca semântica"""
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


@dataclass
class ComposicaoSinapi:
    """Composição SINAPI encontrada na busca"""
    codigo: str
    nome: str
    descricao: str
    unidade_medida: str
    similaridade: float
    nivel_confianca: NivelConfianca


@dataclass
class ResultadoBusca:
    """Resultado da busca semântica com classificação de confiança"""
    nivel_confianca: NivelConfianca
    melhor_match: Optional[ComposicaoSinapi]
    alternativas: list[ComposicaoSinapi] = field(default_factory=list)
    requer_validacao: bool = True
    mensagem: str = ""


# =============================================================================
# STREAMING
# =============================================================================

@dataclass
class EventoStream:
    """Evento para streaming SSE"""
    etapa: str
    mensagem: str
    progresso: Optional[float] = None
    dados: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "etapa": self.etapa,
            "mensagem": self.mensagem,
            "progresso": self.progresso,
            "dados": self.dados,
            "timestamp": self.timestamp.isoformat()
        }
