"""
Gerenciador de sessões conversacionais
"""

import uuid
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from app.core.models import (
    EstadoConversacao,
    CampoInfo,
    FonteCampo,
    FaseConversacao,
    PerguntaCampo,
    TipoCampo
)
from app.config import UF_MAPPING


# =============================================================================
# DEFINIÇÕES DE CAMPOS
# =============================================================================

# Campos obrigatórios que SEMPRE devem ser perguntados se não informados
CAMPOS_OBRIGATORIOS = ["uf", "tipo_construtivo", "padrao_construtivo"]

# Campos com valores padrão (confirmar antes de usar)
CAMPOS_COM_PADRAO = {
    "quantidade": 1,
    "mes_referencia": lambda: datetime.now().month,
    "ano_referencia": lambda: datetime.now().year
}

# Configuração das perguntas para cada campo
PERGUNTAS_CAMPOS: Dict[str, PerguntaCampo] = {
    "uf": PerguntaCampo(
        campo="uf",
        pergunta="Em qual estado será construída a obra?",
        tipo=TipoCampo.SELECT,
        opcoes=sorted(set(UF_MAPPING.values()))
    ),
    "tipo_construtivo": PerguntaCampo(
        campo="tipo_construtivo",
        pergunta="Qual tipo de construção residencial?",
        tipo=TipoCampo.SELECT,
        opcoes=["Casa", "Apartamento", "Sobrado", "Kitnet"]
    ),
    "padrao_construtivo": PerguntaCampo(
        campo="padrao_construtivo",
        pergunta="Qual o padrão construtivo?",
        tipo=TipoCampo.SELECT,
        opcoes=["MINIMO", "BASICO", "ALTO"]
    ),
    "quantidade": PerguntaCampo(
        campo="quantidade",
        pergunta="Quantas unidades serão construídas?",
        tipo=TipoCampo.NUMBER
    ),
    "mes_referencia": PerguntaCampo(
        campo="mes_referencia",
        pergunta="Qual o mês de referência para os preços?",
        tipo=TipoCampo.SELECT,
        opcoes=[str(i) for i in range(1, 13)]
    ),
    "ano_referencia": PerguntaCampo(
        campo="ano_referencia",
        pergunta="Qual o ano de referência para os preços?",
        tipo=TipoCampo.SELECT,
        opcoes=[str(y) for y in range(2024, 2027)]
    )
}


class ConversationManager:
    """
    Gerenciador de sessões conversacionais.

    Armazena sessões em memória com TTL para limpeza automática.
    Thread-safe para uso em ambiente assíncrono.
    """

    SESSION_TTL = 3600  # 1 hora em segundos

    def __init__(self):
        self._sessions: Dict[str, EstadoConversacao] = {}
        self._lock = threading.Lock()

    def criar_sessao(self, texto_original: str = "", nome_obra: Optional[str] = None) -> str:
        """
        Cria nova sessão conversacional.

        Args:
            texto_original: Texto inicial do usuário
            nome_obra: Nome da obra (opcional)

        Returns:
            ID da sessão criada
        """
        session_id = str(uuid.uuid4())

        sessao = EstadoConversacao(
            session_id=session_id,
            fase=FaseConversacao.COLETA,
            texto_original=texto_original,
            nome_obra=nome_obra,
            criado_em=datetime.now(),
            atualizado_em=datetime.now()
        )

        # Inicializar campos com padrões
        for campo, valor_ou_fn in CAMPOS_COM_PADRAO.items():
            valor = valor_ou_fn() if callable(valor_ou_fn) else valor_ou_fn
            sessao.campos[campo] = CampoInfo(
                nome=campo,
                valor=valor,
                fonte=FonteCampo.PADRAO,
                confianca=1.0,
                confirmado=False,
                obrigatorio=False
            )

        # Marcar campos obrigatórios como pendentes
        sessao.campos_pendentes = list(CAMPOS_OBRIGATORIOS)

        with self._lock:
            self._sessions[session_id] = sessao

        return session_id

    def obter_sessao(self, session_id: str) -> Optional[EstadoConversacao]:
        """
        Recupera sessão existente.

        Args:
            session_id: ID da sessão

        Returns:
            EstadoConversacao ou None se não encontrada/expirada
        """
        with self._lock:
            sessao = self._sessions.get(session_id)

            if sessao is None:
                return None

            # Verificar expiração
            tempo_decorrido = (datetime.now() - sessao.atualizado_em).total_seconds()
            if tempo_decorrido > self.SESSION_TTL:
                del self._sessions[session_id]
                return None

            return sessao

    def atualizar_campo(
        self,
        session_id: str,
        campo: str,
        valor: Any,
        fonte: FonteCampo = FonteCampo.USUARIO,
        confianca: float = 1.0
    ) -> bool:
        """
        Atualiza valor de um campo na sessão.

        Args:
            session_id: ID da sessão
            campo: Nome do campo
            valor: Novo valor
            fonte: Fonte do valor
            confianca: Nível de confiança (0-1)

        Returns:
            True se atualizado com sucesso
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        with self._lock:
            sessao.campos[campo] = CampoInfo(
                nome=campo,
                valor=valor,
                fonte=fonte,
                confianca=confianca,
                confirmado=fonte == FonteCampo.CONFIRMADO,
                obrigatorio=campo in CAMPOS_OBRIGATORIOS
            )

            # Remover da lista de pendentes se estava lá
            if campo in sessao.campos_pendentes:
                sessao.campos_pendentes.remove(campo)

            sessao.atualizado_em = datetime.now()

        return True

    def marcar_confirmado(self, session_id: str, campo: str) -> bool:
        """
        Marca um campo como confirmado pelo usuário.

        Args:
            session_id: ID da sessão
            campo: Nome do campo

        Returns:
            True se marcado com sucesso
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        with self._lock:
            if campo in sessao.campos:
                sessao.campos[campo].confirmado = True
                sessao.campos[campo].fonte = FonteCampo.CONFIRMADO
                sessao.atualizado_em = datetime.now()
                return True

        return False

    def confirmar_todos_defaults(self, session_id: str) -> bool:
        """
        Confirma todos os campos com valor padrão.

        Args:
            session_id: ID da sessão

        Returns:
            True se confirmado com sucesso
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        with self._lock:
            for campo, info in sessao.campos.items():
                if info.fonte == FonteCampo.PADRAO and not info.confirmado:
                    info.confirmado = True
                    info.fonte = FonteCampo.CONFIRMADO
            sessao.atualizado_em = datetime.now()

        return True

    def obter_campos_pendentes(self, session_id: str) -> List[str]:
        """
        Retorna lista de campos obrigatórios ainda não preenchidos.

        Args:
            session_id: ID da sessão

        Returns:
            Lista de nomes de campos pendentes
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return []

        return sessao.campos_pendentes.copy()

    def obter_campos_com_padrao_nao_confirmados(self, session_id: str) -> Dict[str, Any]:
        """
        Retorna campos que usam valor padrão mas não foram confirmados.

        Args:
            session_id: ID da sessão

        Returns:
            Dict com campo -> {valor, pode_alterar}
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return {}

        resultado = {}
        for campo, info in sessao.campos.items():
            if info.fonte == FonteCampo.PADRAO and not info.confirmado:
                resultado[campo] = {
                    "valor": info.valor,
                    "pode_alterar": True
                }

        return resultado

    def todos_campos_prontos(self, session_id: str) -> bool:
        """
        Verifica se todos os campos necessários estão preenchidos e confirmados.

        Args:
            session_id: ID da sessão

        Returns:
            True se todos prontos
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        # Verificar campos obrigatórios
        for campo in CAMPOS_OBRIGATORIOS:
            if campo not in sessao.campos or sessao.campos[campo].valor is None:
                return False

        # Verificar se não há pendentes
        if sessao.campos_pendentes:
            return False

        # Verificar se todos defaults foram confirmados
        for campo, info in sessao.campos.items():
            if info.fonte == FonteCampo.PADRAO and not info.confirmado:
                return False

        return True

    def obter_resumo(self, session_id: str) -> Dict[str, Any]:
        """
        Retorna resumo completo dos campos para confirmação.

        Args:
            session_id: ID da sessão

        Returns:
            Dict com resumo dos campos
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return {}

        return sessao.obter_resumo()

    def atualizar_fase(self, session_id: str, fase: FaseConversacao) -> bool:
        """
        Atualiza a fase da conversa.

        Args:
            session_id: ID da sessão
            fase: Nova fase

        Returns:
            True se atualizado com sucesso
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        with self._lock:
            sessao.fase = fase
            sessao.atualizado_em = datetime.now()

        return True

    def adicionar_mensagem(self, session_id: str, mensagem: str) -> bool:
        """
        Adiciona mensagem ao histórico da sessão.

        Args:
            session_id: ID da sessão
            mensagem: Mensagem a adicionar

        Returns:
            True se adicionado com sucesso
        """
        sessao = self.obter_sessao(session_id)
        if sessao is None:
            return False

        with self._lock:
            sessao.historico_mensagens.append(mensagem)
            sessao.atualizado_em = datetime.now()

        return True

    def limpar_expiradas(self) -> int:
        """
        Remove sessões expiradas.

        Returns:
            Número de sessões removidas
        """
        agora = datetime.now()
        expiradas = []

        with self._lock:
            for session_id, sessao in self._sessions.items():
                tempo_decorrido = (agora - sessao.atualizado_em).total_seconds()
                if tempo_decorrido > self.SESSION_TTL:
                    expiradas.append(session_id)

            for session_id in expiradas:
                del self._sessions[session_id]

        return len(expiradas)

    def obter_pergunta_para_campo(self, campo: str) -> Optional[PerguntaCampo]:
        """
        Retorna a pergunta configurada para um campo.

        Args:
            campo: Nome do campo

        Returns:
            PerguntaCampo ou None
        """
        return PERGUNTAS_CAMPOS.get(campo)


# Instância singleton
_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Retorna instância singleton do ConversationManager"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager
