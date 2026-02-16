"""
Definicoes de tools e handlers para o BudgetAgent.
Encapsula os servicos existentes (Spring API, pgvector) como tools para o LLM.
"""

import asyncio
import json
import logging
import traceback
from typing import Dict, Any, Callable, Awaitable, List, Optional

from app.llm.base import ToolDefinition, ToolParameter, ToolResult
from app.services.spring_client import get_spring_client
from app.services.vector_search import get_vector_search_service

logger = logging.getLogger(__name__)

# Limita concorrencia para nao estourar pool de conexoes do pgvector
_semaphore = asyncio.Semaphore(5)

# Armazena os dados processados do ultimo orcamento para uso no salvamento
_ultimo_orcamento_processado: Optional[List[Dict[str, Any]]] = None


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

TOOL_BUSCAR_ORCAMENTO_REFERENCIA = ToolDefinition(
    name="buscar_orcamento_referencia",
    description=(
        "Busca um orcamento de referencia (estrutura de etapas e itens) para padrao MINIMO ou BASICO. "
        "Esta tool e OPCIONAL. Disponivel apenas para padroes MINIMO e BASICO. "
        "Para outros padroes (MEDIO, ALTO) ou se a referencia nao for encontrada, "
        "voce deve montar a estrutura de etapas e itens usando seu conhecimento de engenharia civil."
    ),
    parameters=[
        ToolParameter(
            name="padrao_construtivo",
            type="string",
            description="Padrao construtivo da obra",
            required=True,
            enum=["MINIMO", "BASICO"]
        )
    ]
)

TOOL_PROCESSAR_ITENS_ORCAMENTO = ToolDefinition(
    name="processar_itens_orcamento",
    description=(
        "Processa TODOS os itens do orcamento de uma vez: busca composicao SINAPI + preco para cada item. "
        "Use esta tool apos obter a estrutura de referencia. Passe todos os itens de todas as etapas. "
        "Internamente faz busca semantica SINAPI e consulta de precos em paralelo. "
        "Retorna cada item com codigo SINAPI, confianca e preco."
    ),
    parameters=[
        ToolParameter(
            name="itens",
            type="array",
            description=(
                "Lista de itens para processar. Cada item: "
                "{nome: str, quantidade: float, unidade: str, etapa: str}"
            ),
            required=True
        ),
        ToolParameter(
            name="uf",
            type="string",
            description="Sigla do estado (ex: 'MA', 'SP')",
            required=True
        ),
        ToolParameter(
            name="mes",
            type="integer",
            description="Mes de referencia (1-12)",
            required=True
        ),
        ToolParameter(
            name="ano",
            type="integer",
            description="Ano de referencia (ex: 2025)",
            required=True
        )
    ]
)

TOOL_SALVAR_ORCAMENTO = ToolDefinition(
    name="salvar_orcamento",
    description=(
        "Salva o orcamento finalizado no sistema. Usa automaticamente os dados das etapas e itens "
        "que foram processados pela tool processar_itens_orcamento. "
        "Voce so precisa informar nome_obra e descricao. "
        "Use somente quando o usuario confirmar que deseja salvar."
    ),
    parameters=[
        ToolParameter(
            name="nome_obra",
            type="string",
            description="Nome da obra (ex: '2 Casas Residenciais - MA')",
            required=True
        ),
        ToolParameter(
            name="descricao",
            type="string",
            description="Descricao da obra",
            required=True
        )
    ]
)


ALL_TOOLS: List[ToolDefinition] = [
    TOOL_BUSCAR_ORCAMENTO_REFERENCIA,
    TOOL_PROCESSAR_ITENS_ORCAMENTO,
    TOOL_SALVAR_ORCAMENTO,
]


# =============================================================================
# TOOL HANDLERS
# =============================================================================

async def handle_buscar_orcamento_referencia(arguments: Dict[str, Any]) -> str:
    """Handler: busca orcamento de referencia e suas etapas"""
    padrao = arguments.get("padrao_construtivo", "MINIMO")
    spring = get_spring_client()

    orcamento = await spring.buscar_orcamento_base(padrao)
    if not orcamento:
        return f"Erro: orcamento de referencia nao encontrado para padrao '{padrao}'"

    codigo = orcamento.get("codigo")
    etapas = await spring.buscar_etapas_por_orcamento(codigo)

    # Formato compacto para economizar tokens
    etapas_compact = []
    for e in etapas:
        itens_compact = [
            f"{item.nome}|{item.quantidade}{item.unidade}"
            for item in e.itens
        ]
        etapas_compact.append(f"## {e.nome}\n" + "\n".join(f"- {i}" for i in itens_compact))

    return f"Orcamento ref: {padrao} (cod:{codigo})\n\n" + "\n\n".join(etapas_compact)


async def _processar_item(
    item: Any, uf: str, mes: int, ano: int
) -> Dict[str, Any]:
    """Processa um unico item: busca SINAPI + preco. Retorna dados estruturados."""
    # Normalizar: LLMs menores podem enviar string em vez de dict
    if isinstance(item, str):
        item = {"nome": item, "quantidade": 1, "unidade": "un", "etapa": "Geral"}

    nome = item.get("nome", "")
    quantidade = item.get("quantidade", 0)
    unidade = item.get("unidade", "")
    etapa = item.get("etapa", "")

    async with _semaphore:
        vector_search = await get_vector_search_service()
        resultado = await vector_search.buscar_com_confianca(nome)

        if not resultado.melhor_match:
            return {
                "etapa": etapa, "nome": nome, "quantidade": quantidade,
                "unidade": unidade, "custo_unitario": 0, "texto": f"{etapa}|{nome}|{quantidade}{unidade}|SEM_MATCH|R$0,00"
            }

        match = resultado.melhor_match
        conf = resultado.nivel_confianca.value

        # Buscar preco
        spring = get_spring_client()
        preco = await spring.buscar_preco_composicao(match.codigo, uf, mes, ano)

        custo = preco.custo_sem_desoneracao if preco else 0
        total = custo * quantidade

        if preco:
            texto = (
                f"{etapa}|{nome}|{quantidade}{unidade}"
                f"|cod:{match.codigo}|conf:{conf}|sim:{match.similaridade:.0%}"
                f"|unit:R${custo:.2f}|total:R${total:.2f}"
            )
        else:
            texto = (
                f"{etapa}|{nome}|{quantidade}{unidade}"
                f"|cod:{match.codigo}|conf:{conf}|sim:{match.similaridade:.0%}"
                f"|SEM_PRECO"
            )

        return {
            "etapa": etapa, "nome": nome, "descricao": f"SINAPI {match.codigo} - {match.nome}",
            "quantidade": quantidade, "unidade": unidade, "custo_unitario": custo,
            "texto": texto,
        }


async def handle_processar_itens_orcamento(arguments: Dict[str, Any]) -> str:
    """Handler: processa todos os itens em batch (SINAPI + preco em paralelo)"""
    global _ultimo_orcamento_processado

    itens = arguments.get("itens", [])
    uf = arguments.get("uf", "")
    mes = arguments.get("mes", 1)
    ano = arguments.get("ano", 2025)

    if not itens:
        return "Erro: nenhum item fornecido"

    logger.info(f"[Tools] Processando {len(itens)} itens em batch para {uf} {mes}/{ano}")

    # Processar todos os itens em paralelo
    resultados = await asyncio.gather(*[
        _processar_item(item, uf, mes, ano)
        for item in itens
    ])

    # Agrupar por etapa para saida organizada (texto) e dados estruturados
    etapas_texto: Dict[str, List[str]] = {}
    etapas_dados: Dict[str, List[Dict[str, Any]]] = {}

    for item_result in resultados:
        texto = item_result["texto"]
        etapa_nome = item_result["etapa"] or "Geral"

        parts = texto.split("|", 1)
        etapas_texto.setdefault(etapa_nome, []).append(parts[1] if len(parts) > 1 else texto)

        etapas_dados.setdefault(etapa_nome, []).append({
            "nome": item_result["nome"],
            "descricao": item_result.get("descricao", ""),
            "quantidade": item_result["quantidade"],
            "unidade": item_result["unidade"],
            "custo_unitario": item_result["custo_unitario"],
        })

    # Armazenar dados estruturados para uso no salvamento
    _ultimo_orcamento_processado = [
        {"nome": etapa_nome, "descricao": f"Etapa: {etapa_nome}", "itens": itens_list}
        for etapa_nome, itens_list in etapas_dados.items()
    ]
    logger.info(f"[Tools] Dados armazenados: {len(_ultimo_orcamento_processado)} etapas para salvamento")

    # Saida compacta para o LLM
    output_lines = [f"Processados {len(itens)} itens para {uf} {mes}/{ano}:\n"]
    for etapa_nome, linhas in etapas_texto.items():
        output_lines.append(f"## {etapa_nome}")
        for l in linhas:
            output_lines.append(f"- {l}")
        output_lines.append("")

    return "\n".join(output_lines)


async def handle_salvar_orcamento(arguments: Dict[str, Any]) -> str:
    """Handler: salva orcamento completo no sistema usando dados processados"""
    global _ultimo_orcamento_processado

    nome_obra = arguments.get("nome_obra", "Obra sem nome")
    descricao = arguments.get("descricao", "")
    etapas_data = _ultimo_orcamento_processado

    logger.info(f"[Tools] salvar_orcamento: nome='{nome_obra}', etapas armazenadas={len(etapas_data) if etapas_data else 0}")

    if not etapas_data:
        return "Erro: nenhum orcamento processado. Execute processar_itens_orcamento antes de salvar."

    spring = get_spring_client()

    # Criar obra
    obra = await spring.criar_obra(nome_obra, descricao)
    if not obra:
        return "Erro: falha ao criar obra"

    codigo_obra = obra.get("codigo")
    logger.info(f"[Tools] Obra criada: {codigo_obra}")

    # Criar orcamento
    orcamento = await spring.criar_orcamento(
        nome=f"Orcamento - {nome_obra}",
        descricao=descricao,
        codigo_obra=codigo_obra
    )
    if not orcamento:
        return "Erro: falha ao criar orcamento"

    codigo_orcamento = orcamento.get("codigo")
    logger.info(f"[Tools] Orcamento criado: {codigo_orcamento}")

    etapas_criadas = 0
    itens_criados = 0
    erros = []

    for idx, etapa_data in enumerate(etapas_data):
        nome_etapa = etapa_data.get("nome", "")
        logger.info(f"[Tools] Criando etapa {idx+1}/{len(etapas_data)}: '{nome_etapa}'")

        etapa = await spring.criar_etapa_orcamento(
            codigo_orcamento=codigo_orcamento,
            nome=nome_etapa,
            descricao=etapa_data.get("descricao", "")
        )
        if not etapa:
            erros.append(f"Falha ao criar etapa '{nome_etapa}'")
            logger.error(f"[Tools] Falha ao criar etapa '{nome_etapa}'")
            continue

        etapas_criadas += 1
        codigo_etapa = etapa.get("codigo")

        itens = etapa_data.get("itens", [])
        logger.info(f"[Tools] Etapa '{nome_etapa}' (cod:{codigo_etapa}) - {len(itens)} itens")

        if itens:
            itens_api = [
                {
                    "nome": item.get("nome", ""),
                    "descricao": item.get("descricao", ""),
                    "quantidade": item.get("quantidade", 0),
                    "unidade": item.get("unidade", "un"),
                    "custoUnitario": item.get("custo_unitario", 0),
                }
                for item in itens
            ]
            logger.info(f"[Tools] Enviando {len(itens_api)} itens para etapa {codigo_etapa}: {json.dumps(itens_api[:2], ensure_ascii=False)}...")
            ok = await spring.adicionar_itens_etapa(codigo_etapa, itens_api)
            if ok:
                itens_criados += len(itens)
            else:
                erros.append(f"Falha ao adicionar itens na etapa '{nome_etapa}'")
                logger.error(f"[Tools] Falha ao adicionar itens na etapa '{nome_etapa}'")

    # Limpar dados processados apos salvamento
    _ultimo_orcamento_processado = None

    resultado = (
        f"Salvo! obra:{codigo_obra} orcamento:{codigo_orcamento} "
        f"etapas:{etapas_criadas}/{len(etapas_data)} itens:{itens_criados}"
    )
    if erros:
        resultado += f"\nErros: {'; '.join(erros)}"

    logger.info(f"[Tools] Resultado: {resultado}")
    return resultado


# Mapa nome -> handler
TOOL_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]] = {
    "buscar_orcamento_referencia": handle_buscar_orcamento_referencia,
    "processar_itens_orcamento": handle_processar_itens_orcamento,
    "salvar_orcamento": handle_salvar_orcamento,
}


async def execute_tool(
    tool_call_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> ToolResult:
    """Executa uma tool e retorna o resultado"""
    handler = TOOL_HANDLERS.get(tool_name)

    if not handler:
        return ToolResult(
            tool_call_id=tool_call_id,
            content=f"Erro: tool desconhecida '{tool_name}'",
            is_error=True
        )

    try:
        content = await handler(arguments)
        return ToolResult(
            tool_call_id=tool_call_id,
            content=content,
            is_error=False
        )
    except Exception as e:
        logger.error(f"[Tools] Erro em {tool_name}: {e}\n{traceback.format_exc()}")
        return ToolResult(
            tool_call_id=tool_call_id,
            content=f"Erro em {tool_name}: {e}",
            is_error=True
        )
