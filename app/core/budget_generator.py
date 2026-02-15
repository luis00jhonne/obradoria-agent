"""
Gerador de estrutura de orçamento usando LLM com Chain-of-Thought
"""

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from app.llm import LLMProvider
from app.core.models import DadosExtraidos


@dataclass
class ItemGerado:
    """Item gerado pelo LLM"""
    nome: str
    descricao: str
    unidade: str
    quantidade: float


@dataclass
class EtapaGerada:
    """Etapa gerada pelo LLM"""
    nome: str
    descricao: str
    itens: List[ItemGerado]


@dataclass
class EstruturaOrcamento:
    """Estrutura completa do orçamento gerada pelo LLM"""
    etapas: List[EtapaGerada]
    raciocinio: str  # Chain-of-thought reasoning
    sucesso: bool
    erro: Optional[str] = None


# =============================================================================
# PROMPTS COM CHAIN-OF-THOUGHT
# =============================================================================

SYSTEM_PROMPT_GERACAO = """Você é um engenheiro civil brasileiro especialista em orçamentos de obras residenciais.
Você tem profundo conhecimento do SINAPI (Sistema Nacional de Pesquisa de Custos e Índices da Construção Civil).
Sua tarefa é gerar estruturas de orçamento realistas e completas para construções residenciais.

Você trabalha com os seguintes tipos de construção residencial:
- Casa: Residência unifamiliar térrea
- Apartamento: Unidade em edifício multifamiliar
- Sobrado: Residência unifamiliar de dois pavimentos
- Kitnet/Studio: Unidade compacta com ambientes integrados"""


def criar_prompt_geracao_cot(dados: DadosExtraidos) -> str:
    """
    Cria prompt com Chain-of-Thought para geração de estrutura de orçamento.

    O prompt guia o LLM a raciocinar passo a passo antes de gerar o JSON.
    """

    # Determinar área estimada baseado no tipo e padrão
    # Áreas por subtipo residencial
    areas_por_tipo = {
        "RESIDENCIAL_CASA": {"MINIMO": "50-70m²", "BASICO": "80-120m²", "ALTO": "120-150m²"},
        "RESIDENCIAL_APARTAMENTO": {"MINIMO": "40-50m²", "BASICO": "60-80m²", "ALTO": "80-100m²"},
        "RESIDENCIAL_SOBRADO": {"MINIMO": "80-100m²", "BASICO": "120-160m²", "ALTO": "160-200m²"},
        "RESIDENCIAL_KITNET": {"MINIMO": "20-25m²", "BASICO": "25-35m²", "ALTO": "35-40m²"},
    }

    # Fallback para áreas genéricas se tipo não reconhecido
    areas_padrao = {"MINIMO": "40-50m²", "BASICO": "60-80m²", "ALTO": "100-150m²"}

    tipo = dados.tipo_construtivo.upper() if dados.tipo_construtivo else "RESIDENCIAL_CASA"
    areas_tipo = areas_por_tipo.get(tipo, areas_padrao)
    area_estimada = areas_tipo.get(dados.padrao_construtivo, "50-70m²")

    # Descrição amigável do tipo
    descricao_tipo = {
        "RESIDENCIAL_CASA": "casa térrea",
        "RESIDENCIAL_APARTAMENTO": "apartamento",
        "RESIDENCIAL_SOBRADO": "sobrado (dois pavimentos)",
        "RESIDENCIAL_KITNET": "kitnet/studio",
    }.get(tipo, "residência")

    return f"""Tarefa: Gerar estrutura de orçamento para construção.

## Dados do Projeto
- Tipo: {descricao_tipo}
- Padrão: {dados.padrao_construtivo}
- Quantidade: {dados.quantidade} unidade(s)
- Localização: {dados.uf}
- Área estimada por unidade: {area_estimada}

## Instruções - Pense passo a passo:

### Passo 1: Identificar as etapas necessárias
Para uma construção de {descricao_tipo} de padrão {dados.padrao_construtivo.lower()}, liste as etapas típicas de obra.
Considere: serviços preliminares, infraestrutura, superestrutura, alvenaria, instalações, acabamentos.

### Passo 2: Para cada etapa, definir os itens de serviço
Pense nos serviços específicos que compõem cada etapa.
Use nomenclatura compatível com SINAPI.
Considere o padrão {dados.padrao_construtivo} para nível de acabamento.

### Passo 3: Definir unidades de medida
Use unidades padrão: M2 (área), M3 (volume), M (linear), UN (unidade), KG (peso), H (hora).

### Passo 4: Estimar quantidades
Baseado na área de {area_estimada}, estime quantidades realistas para CADA UNIDADE.
Lembre-se: o sistema multiplicará pela quantidade ({dados.quantidade}) depois.

### Passo 5: Gerar JSON final

Após raciocinar, retorne sua resposta no seguinte formato:

<raciocinio>
[Seu raciocínio passo a passo aqui]
</raciocinio>

<json>
{{
  "etapas": [
    {{
      "nome": "Nome da Etapa",
      "descricao": "Descrição breve",
      "itens": [
        {{
          "nome": "Nome do item",
          "descricao": "Descrição detalhada compatível com SINAPI",
          "unidade": "M2",
          "quantidade": 50.0
        }}
      ]
    }}
  ]
}}
</json>

Gere uma estrutura completa e realista. Inclua pelo menos 5 etapas com 3-5 itens cada."""


def criar_prompt_geracao_simples(dados: DadosExtraidos) -> str:
    """
    Prompt alternativo mais simples (fallback).
    """
    return f"""Gere uma estrutura de orçamento para:
- {dados.quantidade}x {dados.tipo_construtivo} padrão {dados.padrao_construtivo} em {dados.uf}

Retorne JSON com etapas e itens típicos de construção civil.
Use nomenclatura compatível com SINAPI.

Formato:
{{
  "etapas": [
    {{
      "nome": "...",
      "descricao": "...",
      "itens": [
        {{"nome": "...", "descricao": "...", "unidade": "M2", "quantidade": 0.0}}
      ]
    }}
  ]
}}"""


# =============================================================================
# PARSING DA RESPOSTA
# =============================================================================

def extrair_raciocinio(resposta: str) -> str:
    """Extrai o bloco de raciocínio da resposta."""
    match = re.search(r'<raciocinio>(.*?)</raciocinio>', resposta, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extrair_json_estrutura(resposta: str) -> Optional[dict]:
    """
    Extrai o JSON da resposta do LLM.
    Tenta múltiplas estratégias de parsing.
    """
    # Estratégia 1: Buscar entre tags <json>
    match = re.search(r'<json>(.*?)</json>', resposta, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Estratégia 2: Buscar bloco de código markdown
    match = re.search(r'```(?:json)?\s*(.*?)```', resposta, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Estratégia 3: Buscar objeto JSON diretamente
    match = re.search(r'\{[\s\S]*"etapas"[\s\S]*\}', resposta)
    if match:
        try:
            # Tentar encontrar o JSON completo balanceando chaves
            texto = match.group(0)
            nivel = 0
            inicio = 0
            for i, char in enumerate(texto):
                if char == '{':
                    if nivel == 0:
                        inicio = i
                    nivel += 1
                elif char == '}':
                    nivel -= 1
                    if nivel == 0:
                        try:
                            return json.loads(texto[inicio:i+1])
                        except json.JSONDecodeError:
                            continue
        except:
            pass

    return None


def validar_estrutura(dados: dict) -> tuple[bool, str]:
    """
    Valida se a estrutura JSON está correta.

    Returns:
        Tuple[é_válido, mensagem_erro]
    """
    if not isinstance(dados, dict):
        return False, "Resposta não é um objeto JSON"

    if "etapas" not in dados:
        return False, "Campo 'etapas' não encontrado"

    if not isinstance(dados["etapas"], list):
        return False, "Campo 'etapas' deve ser uma lista"

    if len(dados["etapas"]) == 0:
        return False, "Lista de etapas está vazia"

    for i, etapa in enumerate(dados["etapas"]):
        if "nome" not in etapa:
            return False, f"Etapa {i+1} sem campo 'nome'"

        if "itens" not in etapa or not isinstance(etapa["itens"], list):
            return False, f"Etapa '{etapa.get('nome', i+1)}' sem itens válidos"

        for j, item in enumerate(etapa["itens"]):
            campos_obrigatorios = ["nome", "unidade", "quantidade"]
            for campo in campos_obrigatorios:
                if campo not in item:
                    return False, f"Item {j+1} da etapa '{etapa['nome']}' sem campo '{campo}'"

    return True, ""


def converter_para_estrutura(dados: dict) -> EstruturaOrcamento:
    """
    Converte o dicionário validado para objetos tipados.
    """
    etapas = []

    for etapa_data in dados["etapas"]:
        itens = []
        for item_data in etapa_data.get("itens", []):
            itens.append(ItemGerado(
                nome=item_data.get("nome", ""),
                descricao=item_data.get("descricao", item_data.get("nome", "")),
                unidade=item_data.get("unidade", "UN"),
                quantidade=float(item_data.get("quantidade", 0) or 0)
            ))

        etapas.append(EtapaGerada(
            nome=etapa_data.get("nome", ""),
            descricao=etapa_data.get("descricao", ""),
            itens=itens
        ))

    return EstruturaOrcamento(
        etapas=etapas,
        raciocinio="",
        sucesso=True
    )


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

async def gerar_estrutura_orcamento(
    dados: DadosExtraidos,
    llm_provider: LLMProvider,
    usar_cot: bool = True
) -> EstruturaOrcamento:
    """
    Gera estrutura de orçamento usando LLM com Chain-of-Thought.

    Args:
        dados: Dados extraídos do pedido do usuário
        llm_provider: Provider LLM a usar
        usar_cot: Se True, usa prompt com Chain-of-Thought

    Returns:
        EstruturaOrcamento com etapas e itens gerados
    """
    # Escolher prompt
    if usar_cot:
        prompt = criar_prompt_geracao_cot(dados)
    else:
        prompt = criar_prompt_geracao_simples(dados)

    # Chamar LLM
    try:
        resposta = await llm_provider.complete(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT_GERACAO,
            temperature=0.3,  # Um pouco de criatividade, mas consistente
            max_tokens=2000   # Estrutura pode ser longa
        )
    except Exception as e:
        erro_msg = str(e) if str(e) else type(e).__name__
        return EstruturaOrcamento(
            etapas=[],
            raciocinio="",
            sucesso=False,
            erro=f"Erro ao chamar LLM: {erro_msg}"
        )

    # Extrair raciocínio (para debug/log)
    raciocinio = extrair_raciocinio(resposta.content)

    # Extrair JSON
    dados_json = extrair_json_estrutura(resposta.content)

    if not dados_json:
        # Tentar novamente com prompt simples
        if usar_cot:
            return await gerar_estrutura_orcamento(
                dados, llm_provider, usar_cot=False
            )
        return EstruturaOrcamento(
            etapas=[],
            raciocinio=raciocinio,
            sucesso=False,
            erro="Não foi possível extrair JSON da resposta do LLM"
        )

    # Validar estrutura
    valido, erro = validar_estrutura(dados_json)
    if not valido:
        return EstruturaOrcamento(
            etapas=[],
            raciocinio=raciocinio,
            sucesso=False,
            erro=f"Estrutura inválida: {erro}"
        )

    # Converter para objetos tipados
    estrutura = converter_para_estrutura(dados_json)
    estrutura.raciocinio = raciocinio

    return estrutura
