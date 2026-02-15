"""
Modelos de domínio do ObradorIA Agent
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime


# =============================================================================
# ENUMS CONVERSACIONAIS
# =============================================================================

class TipoEventoConversacao(str, Enum):
    """Tipos de eventos SSE para fluxo conversacional"""
    # Eventos de sessão
    SESSION_CREATED = "session_created"
    SESSION_RESUMED = "session_resumed"
    SESSION_EXPIRED = "session_expired"

    # Eventos de extração
    EXTRACTION_START = "extraction_start"
    EXTRACTION_PARTIAL = "extraction_partial"

    # Eventos conversacionais
    QUESTION = "question"
    CONFIRM_DEFAULTS = "confirm_defaults"
    CONFIRM_SUMMARY = "confirm_summary"
    USER_CONFIRMED = "user_confirmed"
    CORRECTION_NEEDED = "correction_needed"
    FIELD_UPDATED = "field_updated"

    # Eventos de aviso
    UNSUPPORTED_TYPE = "unsupported_type"  # Tipo não suportado detectado

    # Eventos de processamento (existentes)
    EXTRACTION = "extraction"
    EXTRACTION_DONE = "extraction_done"
    LOAD_BASE = "load_base"
    LOAD_BASE_DONE = "load_base_done"
    GENERATE_STRUCTURE = "generate_structure"
    SEARCH = "search"
    SEARCH_DONE = "search_done"
    PRICING = "pricing"
    PRICING_DONE = "pricing_done"
    SYNTHESIZE = "synthesize"
    SYNTHESIZE_DONE = "synthesize_done"
    PERSIST = "persist"
    PERSIST_DONE = "persist_done"
    PERSIST_ERROR = "persist_error"
    COMPLETE = "complete"
    ERROR = "error"


class FonteCampo(str, Enum):
    """Fonte de onde o valor do campo foi obtido"""
    USUARIO = "usuario"       # Extraído do texto do usuário
    PADRAO = "padrao"         # Valor padrão do sistema
    INFERIDO = "inferido"     # Inferido pelo contexto
    CONFIRMADO = "confirmado" # Confirmado explicitamente pelo usuário


class FaseConversacao(str, Enum):
    """Fases do fluxo conversacional"""
    COLETA = "coleta"               # Coletando informações
    CONFIRMACAO = "confirmacao"     # Aguardando confirmação
    PROCESSAMENTO = "processamento" # Processando orçamento
    COMPLETO = "completo"           # Finalizado
    ERRO = "erro"                   # Erro no processamento


class TipoCampo(str, Enum):
    """Tipos de entrada para campos"""
    SELECT = "select"   # Seleção de opções
    TEXT = "text"       # Texto livre
    NUMBER = "number"   # Número


# =============================================================================
# MODELOS CONVERSACIONAIS
# =============================================================================

@dataclass
class CampoInfo:
    """Informação sobre um campo extraído ou pendente"""
    nome: str
    valor: Any = None
    fonte: FonteCampo = FonteCampo.PADRAO
    confianca: float = 0.0
    confirmado: bool = False
    obrigatorio: bool = True

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "valor": self.valor,
            "fonte": self.fonte.value if self.fonte else None,
            "confianca": self.confianca,
            "confirmado": self.confirmado,
            "obrigatorio": self.obrigatorio
        }


@dataclass
class PerguntaCampo:
    """Definição de pergunta para um campo"""
    campo: str
    pergunta: str
    tipo: TipoCampo
    opcoes: Optional[List[str]] = None
    valor_atual: Any = None

    def to_dict(self) -> dict:
        return {
            "campo": self.campo,
            "pergunta": self.pergunta,
            "tipo": self.tipo.value,
            "opcoes": self.opcoes,
            "valor_atual": self.valor_atual
        }


@dataclass
class EstadoConversacao:
    """Estado completo de uma sessão conversacional"""
    session_id: str
    fase: FaseConversacao = FaseConversacao.COLETA
    campos: Dict[str, CampoInfo] = field(default_factory=dict)
    campos_pendentes: List[str] = field(default_factory=list)
    historico_mensagens: List[str] = field(default_factory=list)
    texto_original: str = ""
    nome_obra: Optional[str] = None
    criado_em: datetime = field(default_factory=datetime.now)
    atualizado_em: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "fase": self.fase.value,
            "campos": {k: v.to_dict() for k, v in self.campos.items()},
            "campos_pendentes": self.campos_pendentes,
            "criado_em": self.criado_em.isoformat(),
            "atualizado_em": self.atualizado_em.isoformat()
        }

    def obter_resumo(self) -> dict:
        """Retorna resumo dos campos para confirmação"""
        return {
            campo: info.valor
            for campo, info in self.campos.items()
            if info.valor is not None
        }


@dataclass
class ResultadoExtracaoInteligente:
    """Resultado da extração inteligente com separação de campos"""
    campos_extraidos: Dict[str, CampoInfo] = field(default_factory=dict)
    campos_faltantes: List[str] = field(default_factory=list)
    campos_com_padrao: Dict[str, Any] = field(default_factory=dict)
    avisos: List[str] = field(default_factory=list)
    sucesso: bool = True
    erro: Optional[str] = None


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
    fonte_estrutura: str = "api"  # "api" ou "llm"


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
