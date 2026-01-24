"""
Extração de informações do texto usando LLM
"""

import json
import re
from dataclasses import dataclass
from typing import Optional, List

from app.llm import LLMProvider
from app.core.prompts import criar_prompt_extracao, PROMPT_SISTEMA_EXTRACAO
from app.core.validators import (
    validar_uf,
    validar_padrao,
    validar_tipo,
    validar_data_referencia,
    validar_quantidade
)
from app.core.models import DadosExtraidos


@dataclass
class ResultadoExtracao:
    """Resultado da extração de informações"""
    sucesso: bool
    dados: Optional[DadosExtraidos] = None
    erros: List[str] = None
    avisos: List[str] = None

    def __post_init__(self):
        if self.erros is None:
            self.erros = []
        if self.avisos is None:
            self.avisos = []


def extrair_json_da_resposta(resposta_texto: str) -> Optional[dict]:
    """
    Extrai JSON da resposta do LLM, mesmo se houver texto extra

    Args:
        resposta_texto: Texto da resposta do LLM

    Returns:
        Dict parseado ou None
    """
    # Tentar extrair JSON entre chaves
    match = re.search(r'\{[^{}]*\}', resposta_texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Tentar limpar markdown
    texto_limpo = resposta_texto.strip()
    if texto_limpo.startswith('```'):
        linhas = texto_limpo.split('\n')
        # Remover primeira e última linha (```json e ```)
        linhas = [l for l in linhas if not l.strip().startswith('```')]
        texto_limpo = '\n'.join(linhas)

    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError:
        return None


async def extrair_informacoes(
    texto_usuario: str,
    llm_provider: LLMProvider
) -> ResultadoExtracao:
    """
    Extrai informações estruturadas do texto do usuário usando LLM

    Args:
        texto_usuario: Texto em linguagem natural
        llm_provider: Provider LLM a usar

    Returns:
        ResultadoExtracao com dados ou erros
    """
    resultado = ResultadoExtracao(sucesso=False)

    # 1. Chamar LLM
    prompt = criar_prompt_extracao(texto_usuario)

    try:
        resposta = await llm_provider.complete(
            prompt=prompt,
            system_prompt=PROMPT_SISTEMA_EXTRACAO,
            temperature=0.1,
            max_tokens=300
        )
    except Exception as e:
        resultado.erros.append(f"Erro ao chamar LLM: {str(e)}")
        return resultado

    # 2. Extrair JSON
    dados_extraidos = extrair_json_da_resposta(resposta.content)

    if not dados_extraidos:
        resultado.erros.append("Não foi possível extrair JSON da resposta do LLM")
        return resultado

    # 3. Validar e normalizar cada campo
    erros = []
    avisos = []

    # Quantidade
    quantidade, erro_qtd = validar_quantidade(dados_extraidos.get('quantidade', 1))
    if quantidade is None:
        erros.append(erro_qtd)
    elif erro_qtd:
        avisos.append(erro_qtd)

    # Tipo Construtivo
    tipo_raw = dados_extraidos.get('tipo_construtivo', '')
    tipo_valido, conf_tipo = validar_tipo(tipo_raw)
    if not tipo_valido:
        erros.append(
            f"Tipo construtivo '{tipo_raw}' não reconhecido. "
            "Apenas 'residencial' está disponível."
        )

    # Padrão Construtivo
    padrao_raw = dados_extraidos.get('padrao_construtivo', '')
    padrao_valido, conf_padrao = validar_padrao(padrao_raw)
    if not padrao_valido:
        erros.append(
            f"Padrão construtivo '{padrao_raw}' não reconhecido. "
            "Use 'mínimo' ou 'básico'."
        )

    # Estado/UF
    estado_raw = dados_extraidos.get('estado', '')
    uf_valida, conf_uf = validar_uf(estado_raw)
    if not uf_valida:
        erros.append(f"Estado '{estado_raw}' não reconhecido")
    elif conf_uf < 1.0:
        avisos.append(f"Estado '{estado_raw}' interpretado como '{uf_valida}' por aproximação")

    # Data de Referência
    mes_raw = dados_extraidos.get('mes_referencia')
    ano_raw = dados_extraidos.get('ano_referencia')
    mes, ano, usou_corrente = validar_data_referencia(mes_raw, ano_raw)

    if usou_corrente:
        avisos.append(f"Data de referência não especificada. Usando: {mes:02d}/{ano}")

    # Se houver erros críticos, retornar
    if erros:
        resultado.erros = erros
        resultado.avisos = avisos
        return resultado

    # 4. Montar dados validados
    resultado.sucesso = True
    resultado.avisos = avisos
    resultado.dados = DadosExtraidos(
        quantidade=quantidade,
        tipo_construtivo=tipo_valido,
        padrao_construtivo=padrao_valido,
        uf=uf_valida,
        mes_referencia=mes,
        ano_referencia=ano,
        descricao_original=texto_usuario
    )

    return resultado
