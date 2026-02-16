"""
Rotas da API FastAPI
"""

import json
import uuid
from typing import AsyncGenerator, Dict, List, Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.llm import get_available_providers, get_llm_provider
from app.core.orchestrator import ConversationalOrchestrator
from app.core.agent import BudgetAgent
from app.services.spring_client import get_spring_client
from app.services.vector_search import check_database_connection
from app.api.schemas import (
    ConversationRequest,
    AgentRequest,
    HealthResponse,
    ComponentHealthResponse,
    ProvidersResponse
)


# Sessoes em memoria para o agent (session_id -> historico de mensagens)
_agent_sessions: Dict[str, List[Dict[str, Any]]] = {}


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Verifica saúde da aplicação e conectividade dos componentes"""
    settings = get_settings()
    providers = get_available_providers()
    components = {}

    # Verificar banco de dados (pgvector)
    try:
        db_ok = await check_database_connection()
        components["database"] = ComponentHealthResponse(
            status="ok" if db_ok else "indisponível",
            detalhes=f"{settings.db_host}:{settings.db_port}/{settings.db_name}" if db_ok else "Falha na conexão"
        )
    except Exception as e:
        components["database"] = ComponentHealthResponse(
            status="indisponível",
            detalhes=str(e)
        )

    # Verificar API Spring
    try:
        spring_client = get_spring_client()
        spring_ok = await spring_client.health_check()
        components["spring_api"] = ComponentHealthResponse(
            status="ok" if spring_ok else "indisponível",
            detalhes=settings.spring_api_url if spring_ok else "Falha na conexão"
        )
    except Exception as e:
        components["spring_api"] = ComponentHealthResponse(
            status="indisponível",
            detalhes=str(e)
        )

    # Verificar LLM provider padrão
    try:
        llm = get_llm_provider()
        llm_ok = await llm.health_check()
        components["llm"] = ComponentHealthResponse(
            status="ok" if llm_ok else "indisponível",
            detalhes=f"{llm.name}" if llm_ok else f"{llm.name} - Falha na conexão"
        )
    except Exception as e:
        components["llm"] = ComponentHealthResponse(
            status="indisponível",
            detalhes=str(e)
        )

    # Status geral
    all_ok = all(c.status == "ok" for c in components.values())
    status = "ok" if all_ok else "degradado"

    return HealthResponse(
        status=status,
        components=components,
        llm_providers=providers
    )


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers():
    """Lista providers LLM disponíveis"""
    settings = get_settings()
    providers = get_available_providers()

    return ProvidersResponse(
        providers=providers,
        default=settings.default_llm_provider
    )


@router.post("/budget/stream")
async def generate_budget_stream(request: ConversationRequest):
    """
    Gera orçamento com streaming SSE e fluxo conversacional inteligente.

    Este endpoint implementa um fluxo que:
    1. Extrai informações do texto inicial
    2. Pergunta dados faltantes um a um
    3. Confirma valores padrão antes de usar
    4. Mostra resumo para confirmação final
    5. Processa o orçamento após confirmação

    ## Uso:

    ### Iniciar conversa (nova sessão):
    ```json
    {"mensagem": "quero construir uma casa"}
    ```

    ### Responder pergunta:
    ```json
    {
        "session_id": "abc123",
        "resposta": {"campo": "uf", "valor": "SP"}
    }
    ```

    ### Confirmar defaults/resumo:
    ```json
    {
        "session_id": "abc123",
        "acao": "confirmar"
    }
    ```

    ### Solicitar correção:
    ```json
    {
        "session_id": "abc123",
        "acao": "corrigir"
    }
    ```

    ## Eventos SSE retornados:

    - `session_created`: Nova sessão criada
    - `session_resumed`: Sessão existente retomada
    - `session_expired`: Sessão expirou
    - `extraction_start`: Iniciando extração
    - `extraction_partial`: Dados extraídos até o momento
    - `question`: Pergunta ao usuário (aguarda resposta)
    - `field_updated`: Campo atualizado com sucesso
    - `confirm_defaults`: Solicita confirmação de valores padrão
    - `confirm_summary`: Solicita confirmação do resumo final
    - `user_confirmed`: Usuário confirmou, processando
    - `correction_needed`: Usuário quer corrigir
    - Eventos de processamento (load_base, search, pricing, etc.)
    - `complete`: Orçamento finalizado
    - `error`: Erro no processamento
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            orchestrator = ConversationalOrchestrator(
                provider_name=request.provider
            )

            # Preparar resposta de campo se houver
            resposta_campo = None
            if request.resposta:
                resposta_campo = {
                    "campo": request.resposta.campo,
                    "valor": request.resposta.valor
                }

            async for evento in orchestrator.process_stream(
                texto_usuario=request.mensagem,
                session_id=request.session_id,
                resposta_campo=resposta_campo,
                confirmacao=request.acao,
                nome_obra=request.nome_obra
            ):
                # Formato SSE
                data = json.dumps(evento.to_dict(), ensure_ascii=False)
                yield f"event: {evento.etapa}\ndata: {data}\n\n"

        except Exception as e:
            error_data = json.dumps({
                "etapa": "error",
                "mensagem": str(e)
            }, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/agent/stream")
async def agent_stream(request: AgentRequest):
    """
    Gera orçamento usando agent-based architecture com tool use.

    O LLM decide quais tools chamar e em que ordem, conversando
    naturalmente com o usuário. Suporta multi-turno via session_id.

    ## Uso:

    ### Nova conversa:
    ```json
    {"mensagem": "quero construir 2 casas padrao minimo no Maranhao jan/2025"}
    ```

    ### Continuar conversa:
    ```json
    {
        "mensagem": "use padrao basico em vez de minimo",
        "session_id": "uuid-da-sessao"
    }
    ```

    ## Eventos SSE retornados:

    - `load_base` / `load_base_done`: Buscando estrutura de referencia
    - `search` / `search_done`: Buscando composicoes SINAPI
    - `pricing` / `pricing_done`: Buscando precos
    - `persist` / `persist_done`: Salvando orcamento
    - `synthesize`: Texto parcial do agente
    - `complete`: Resposta final do agente
    - `error`: Erro no processamento
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Gerenciar sessao
            session_id = request.session_id
            if session_id and session_id in _agent_sessions:
                historico = _agent_sessions[session_id]
            else:
                session_id = session_id or str(uuid.uuid4())
                historico = []
                _agent_sessions[session_id] = historico

            # Emitir session_id
            session_data = json.dumps({
                "etapa": "session_created",
                "mensagem": "Sessao iniciada",
                "dados": {"session_id": session_id}
            }, ensure_ascii=False)
            yield f"event: session_created\ndata: {session_data}\n\n"

            agent = BudgetAgent(provider_name=request.provider)

            async for evento in agent.process_stream(
                mensagem_usuario=request.mensagem,
                historico=historico,
            ):
                data = json.dumps(evento.to_dict(), ensure_ascii=False)
                yield f"event: {evento.etapa}\ndata: {data}\n\n"

                # Atualizar historico da sessao com as mensagens acumuladas
                # O agent acumula mensagens internamente; salvamos o estado final
                if evento.etapa == "complete" and evento.dados:
                    # Salvar mensagem do usuario e resposta no historico
                    historico.append({"role": "user", "content": request.mensagem})
                    historico.append({"role": "assistant", "content": evento.mensagem})

        except Exception as e:
            error_data = json.dumps({
                "etapa": "error",
                "mensagem": str(e)
            }, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

