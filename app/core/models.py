"""
Modelos de domínio do ObradorIA Agent
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class NivelConfianca(str, Enum):
    """Níveis de confiança para busca semântica"""
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


class TipoObra(str, Enum):
    """Tipos de obra suportados"""
    RESIDENCIAL = "RESIDENCIAL"
    COMERCIAL = "COMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"


class PadraoObra(str, Enum):
    """Padrões construtivos suportados"""
    MINIMO = "MINIMO"
    BASICO = "BASICO"
    ALTO = "ALTO"


@dataclass
class DadosExtraidos:
    """Dados extraídos do texto do usuário"""
    quantidade: int
    tipo_construtivo: str
    padrao_construtivo: str
    uf: str
    mes_referencia: int
    ano_referencia: int
    descricao_original: str = ""


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


@dataclass
class ItemBase:
    """Item do orçamento base"""
    codigo: int
    nome: str
    descricao: str
    quantidade: float
    unidade: str


@dataclass
class ItemProcessado:
    """Item processado com match SINAPI e preço"""
    item_base: ItemBase
    etapa_nome: str
    busca_sinapi: ResultadoBusca
    quantidade_ajustada: float
    preco_unitario: float = 0.0
    preco_total: float = 0.0
    problema: Optional[str] = None


@dataclass
class EtapaProcessada:
    """Etapa com itens processados"""
    codigo: int
    nome: str
    descricao: str
    itens: list[ItemProcessado] = field(default_factory=list)
    valor_total: float = 0.0


@dataclass
class Estatisticas:
    """Estatísticas do processamento"""
    total_itens: int = 0
    itens_com_preco: int = 0
    itens_sem_composicao: int = 0
    itens_sem_preco: int = 0
    alta_confianca: int = 0
    media_confianca: int = 0
    baixa_confianca: int = 0

    @property
    def taxa_sucesso(self) -> float:
        if self.total_itens == 0:
            return 0.0
        return (self.itens_com_preco / self.total_itens) * 100


@dataclass
class ResultadoOrcamento:
    """Resultado completo do processamento"""
    sucesso: bool
    dados_extraidos: Optional[DadosExtraidos] = None
    etapas: list[EtapaProcessada] = field(default_factory=list)
    estatisticas: Estatisticas = field(default_factory=Estatisticas)
    valor_total: float = 0.0
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    codigo_orcamento_criado: Optional[int] = None
    codigo_obra_criada: Optional[int] = None
    tempo_processamento: float = 0.0


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
