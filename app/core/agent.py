"""
BudgetAgent - Orquestrador baseado em LLM com Tool Use.
Pipeline de criação de orçamentos controlado por um agent loop onde o LLM decide quais tools chamar.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator

from app.llm import get_llm_provider
from app.llm.base import (
    LLMProvider,
    ToolDefinition,
    StopReason,
    LLMResponseWithTools,
)
from app.core.models import EventoStream
from app.core.tools import ALL_TOOLS, execute_tool

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 30

# Mapa tool_name -> (evento_inicio, evento_fim, mensagem)
TOOL_EVENT_MAP = {
    "buscar_orcamento_referencia": ("load_base", "load_base_done", "Buscando estrutura de referência..."),
    "processar_itens_orcamento": ("search", "search_done", "Processando itens (SINAPI + preços)..."),
    "salvar_orcamento": ("persist", "persist_done", "Salvando orçamento..."),
}

SYSTEM_PROMPT = """Voce e o ObradorIA, um engenheiro civil especialista em orcamentos de construcao civil usando a base de composicoes SINAPI.

## Seu papel
Voce ajuda usuarios a gerar orcamentos de construcao residencial. Voce conversa naturalmente, coleta as informacoes necessarias e usa as tools disponiveis para montar o orcamento completo.

## Informacoes necessarias para um orcamento
- **Tipo construtivo**: casa, apartamento, sobrado, kitnet (apenas residencial)
- **Padrao construtivo**: MINIMO, BASICO, MEDIO, ALTO
- **UF**: estado brasileiro (sigla, ex: MA, SP)
- **Quantidade**: numero de unidades
- **Periodo de referencia**: mes e ano para precos SINAPI

## Fluxo de trabalho
1. **Coletar informacoes**: Extraia do texto do usuario ou pergunte o que faltar. Seja direto e objetivo.
2. **Montar estrutura de etapas e itens**: Use seu conhecimento de engenharia civil para definir as etapas e itens do orcamento. Opcionalmente, use `buscar_orcamento_referencia` se o padrao for MINIMO ou BASICO para obter uma estrutura base. Para outros padroes ou se a referencia nao existir, monte a estrutura voce mesmo com etapas tipicas de construcao residencial (Servicos Preliminares, Fundacao, Estrutura, Alvenaria, Cobertura, Instalacoes Eletricas, Instalacoes Hidraulicas, Revestimento, Pintura, Loucas e Metais, etc).
3. **Processar itens**: Use `processar_itens_orcamento` passando TODOS os itens de todas as etapas de uma unica vez, junto com UF, mes e ano. Cada item deve ter: nome, quantidade, unidade e etapa. Esta tool faz busca SINAPI e precos em paralelo internamente. NAO chame esta tool item por item.
4. **Apresentar resultado**: Monte e apresente o orcamento completo com valores formatados em Reais (R$).
5. **Oferecer salvamento**: Apos apresentar o orcamento, SEMPRE pergunte: "Deseja salvar este orcamento? Se sim, informe um nome para a obra (ex: 'Residencial Popular MA')."
6. **Salvar**: Quando o usuario confirmar, use `salvar_orcamento` com o nome fornecido. Os dados das etapas e itens sao salvos automaticamente a partir do processamento anterior. Se ele nao informar um nome, sugira um baseado nos dados (tipo, quantidade, UF).

## Regras importantes
- Estamos trabalhando apenas com o Custo Direto da obra, não consideramos BDI nem encargos sociais.
- Somente orcamentos RESIDENCIAIS sao suportados (casa, apartamento, sobrado, kitnet). Se pedirem outro tipo, informe educadamente.
- Formate valores monetarios: R$ 1.234,56
- Indique o nivel de confianca das composicoes SINAPI encontradas (ALTA, MEDIA, BAIXA).
- Se um item nao tiver composicao SINAPI confiavel, indique isso claramente.
- Ajuste quantidades proporcionalmente ao numero de unidades solicitado.
- Ao apresentar o orcamento, organize por etapas com subtotais e total geral.
- Seja conciso nas respostas, mas completo nos orcamentos.
- Se o usuario nao informar mes/ano, use o periodo mais recente disponivel.
- Se o usuario nao informar quantidade, assuma 1 unidade.
- IMPORTANTE: Sempre chame as tools diretamente. Nunca apenas descreva o que pretende fazer sem chamar a tool.
"""


class BudgetAgent:
    """Agent que usa LLM com tool use para gerar orcamentos."""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider: LLMProvider = get_llm_provider(provider_name)
        self.tools: List[ToolDefinition] = ALL_TOOLS

    async def process_stream(
        self,
        mensagem_usuario: str,
        historico: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[EventoStream, None]:
        """
        Processa mensagem do usuario com agent loop, emitindo eventos SSE.
        """
        messages = list(historico) if historico else []
        messages.append({"role": "user", "content": mensagem_usuario})

        tools_called: set[str] = set()  # Quais tools ja foram chamadas

        for iteration in range(MAX_ITERATIONS):
            logger.info(f"[Agent] Iteracao {iteration + 1}/{MAX_ITERATIONS}")

            try:
                response: LLMResponseWithTools = await self.provider.complete_with_tools(
                    messages=messages,
                    tools=self.tools,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=4096,
                )
            except Exception as e:
                logger.error(f"[Agent] Erro no LLM: {e}")
                yield EventoStream(
                    etapa="error",
                    mensagem=f"Erro ao chamar LLM: {e}"
                )
                return

            # Se ha tool_calls, SEMPRE executar (independente de stop_reason)
            # Anthropic exige tool_result apos cada tool_use no historico
            if response.tool_calls:
                # Montar mensagem do assistente COM tool_calls
                assistant_msg: Dict[str, Any] = {"role": "assistant"}
                if response.content:
                    assistant_msg["content"] = response.content
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ]
                messages.append(assistant_msg)
                # Emitir texto do assistente ANTES das tools
                if response.content:
                    yield EventoStream(
                        etapa="message",
                        mensagem=response.content,
                    )

                for tc in response.tool_calls:
                    event_info = TOOL_EVENT_MAP.get(tc.name)

                    # Evento de inicio
                    if event_info:
                        etapa_inicio, _, msg = event_info
                        yield EventoStream(
                            etapa=etapa_inicio,
                            mensagem=msg,
                            dados={"tool": tc.name}
                        )

                    # Executar tool
                    result = await execute_tool(tc.id, tc.name, tc.arguments)
                    tools_called.add(tc.name)

                    # Evento de conclusao
                    if event_info:
                        _, etapa_fim, _ = event_info
                        yield EventoStream(
                            etapa=etapa_fim,
                            mensagem=f"Concluido: {tc.name}",
                            dados={
                                "tool": tc.name,
                                "is_error": result.is_error,
                            }
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "content": result.content,
                        "is_error": result.is_error,
                    })

                # Continuar loop para LLM processar os resultados das tools
                continue

            # Sem tool_calls -> montar mensagem do assistente sem tools
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            assistant_msg["content"] = response.content or ""
            messages.append(assistant_msg)

            # Resposta final do LLM
            yield EventoStream(
                etapa="complete",
                mensagem=response.content or "",
                dados={"provider": self.provider.name, "iteration": iteration + 1}
            )
            return

        # Limite de iteracoes atingido
        yield EventoStream(
            etapa="error",
            mensagem="Limite de iteracoes do agent atingido. Tente simplificar o pedido."
        )
