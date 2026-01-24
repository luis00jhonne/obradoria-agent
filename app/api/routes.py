"""
Rotas da API FastAPI
"""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.llm import get_available_providers, get_llm_provider
from app.core.orchestrator import BudgetOrchestrator
from app.api.schemas import (
    BudgetRequest,
    BudgetResponse,
    HealthResponse,
    ProvidersResponse,
    ErrorResponse,
    DadosExtraidosResponse,
    EtapaResponse,
    ItemResponse,
    EstatisticasResponse
)


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Verifica saúde da aplicação"""
    settings = get_settings()

    # Verificar providers disponíveis
    providers = get_available_providers()

    # TODO: Verificar conexão com banco e API Spring
    # Por enquanto retorna status fixo
    return HealthResponse(
        status="ok",
        llm_providers=providers,
        database="não verificado",
        spring_api="não verificado"
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
async def generate_budget_stream(request: BudgetRequest):
    """
    Gera orçamento com streaming SSE

    Retorna Server-Sent Events com progresso em tempo real.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            orchestrator = BudgetOrchestrator(provider_name=request.provider)

            async for evento in orchestrator.process_stream(
                texto_usuario=request.mensagem,
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


@router.post("/budget", response_model=BudgetResponse)
async def generate_budget(request: BudgetRequest):
    """
    Gera orçamento (sem streaming)

    Retorna resultado completo após processamento.
    """
    try:
        orchestrator = BudgetOrchestrator(provider_name=request.provider)

        resultado_final = None

        async for evento in orchestrator.process_stream(
            texto_usuario=request.mensagem,
            nome_obra=request.nome_obra
        ):
            # Capturar último evento (complete ou error)
            if evento.etapa == "complete":
                resultado_final = evento.dados
            elif evento.etapa == "error":
                raise HTTPException(
                    status_code=400,
                    detail=evento.mensagem
                )

        if not resultado_final:
            raise HTTPException(
                status_code=500,
                detail="Processamento não retornou resultado"
            )

        # Converter para response model
        dados_extraidos = None
        if resultado_final.get("dados_extraidos"):
            dados_extraidos = DadosExtraidosResponse(
                **resultado_final["dados_extraidos"]
            )

        etapas = []
        for etapa_data in resultado_final.get("etapas", []):
            itens = [
                ItemResponse(**item)
                for item in etapa_data.get("itens", [])
            ]
            etapas.append(EtapaResponse(
                nome=etapa_data["nome"],
                itens=itens,
                valor_total=etapa_data["valor_total"]
            ))

        estatisticas = None
        if resultado_final.get("estatisticas"):
            estatisticas = EstatisticasResponse(
                **resultado_final["estatisticas"]
            )

        return BudgetResponse(
            sucesso=resultado_final["sucesso"],
            dados_extraidos=dados_extraidos,
            etapas=etapas,
            valor_total=resultado_final["valor_total"],
            estatisticas=estatisticas,
            avisos=resultado_final.get("avisos", []),
            codigo_orcamento_criado=resultado_final.get("codigo_orcamento_criado"),
            codigo_obra_criada=resultado_final.get("codigo_obra_criada"),
            tempo_processamento=resultado_final.get("tempo_processamento", 0),
            provider_usado=orchestrator.provider_name
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
