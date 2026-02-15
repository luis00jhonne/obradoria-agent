"""
Funções de validação e normalização de dados
"""

import unicodedata
from datetime import datetime
from typing import Optional, Tuple

from app.config import UF_MAPPING, PADRAO_MAPPING, TIPO_MAPPING, MESES_MAPPING


def normalizar_texto(texto: str) -> str:
    """Remove acentos e converte para maiúsculas"""
    nfd = unicodedata.normalize('NFD', texto)
    return ''.join([c for c in nfd if unicodedata.category(c) != 'Mn']).upper()


def validar_uf(estado_input: str) -> Tuple[Optional[str], float]:
    """
    Valida e normaliza UF usando aproximação

    Returns:
        Tuple[uf_valida, confianca]
    """
    if not estado_input:
        return None, 0.0

    estado_norm = normalizar_texto(estado_input.strip())

    # Busca exata
    if estado_norm in UF_MAPPING:
        return UF_MAPPING[estado_norm], 1.0

    # Busca por substring (aproximação)
    for nome, uf in UF_MAPPING.items():
        if estado_norm in nome or nome in estado_norm:
            return uf, 0.8

    return None, 0.0


def validar_padrao(padrao_input: str) -> Tuple[Optional[str], float]:
    """
    Valida e normaliza padrão construtivo

    Returns:
        Tuple[padrao_valido, confianca]
    """
    if not padrao_input:
        return None, 0.0

    padrao_norm = normalizar_texto(padrao_input.strip())

    for padrao_oficial, sinonimos in PADRAO_MAPPING.items():
        for sinonimo in sinonimos:
            if normalizar_texto(sinonimo) == padrao_norm:
                return padrao_oficial, 1.0
            # Busca parcial
            if padrao_norm in normalizar_texto(sinonimo) or normalizar_texto(sinonimo) in padrao_norm:
                return padrao_oficial, 0.8

    return None, 0.0


def validar_tipo(tipo_input: str) -> Tuple[Optional[str], float]:
    """
    Valida e normaliza tipo construtivo (subtipos residenciais)

    Returns:
        Tuple[tipo_valido, confianca]
        - tipo_valido: RESIDENCIAL_CASA, RESIDENCIAL_APARTAMENTO, RESIDENCIAL_SOBRADO, RESIDENCIAL_KITNET
        - confianca: 0.0 a 1.0
    """
    if not tipo_input:
        return None, 0.0

    tipo_norm = normalizar_texto(tipo_input.strip())

    # Mapeamento direto de nomes amigáveis para tipos internos
    mapeamento_direto = {
        'CASA': 'RESIDENCIAL_CASA',
        'APARTAMENTO': 'RESIDENCIAL_APARTAMENTO',
        'SOBRADO': 'RESIDENCIAL_SOBRADO',
        'KITNET': 'RESIDENCIAL_KITNET',
        'KITINETE': 'RESIDENCIAL_KITNET',
        'STUDIO': 'RESIDENCIAL_KITNET',
    }

    # Verificar mapeamento direto primeiro
    if tipo_norm in mapeamento_direto:
        return mapeamento_direto[tipo_norm], 1.0

    # Buscar no TIPO_MAPPING completo
    for tipo_oficial, sinonimos in TIPO_MAPPING.items():
        for sinonimo in sinonimos:
            sinonimo_norm = normalizar_texto(sinonimo)
            if tipo_norm == sinonimo_norm or tipo_norm in sinonimo_norm or sinonimo_norm in tipo_norm:
                return tipo_oficial, 1.0

    return None, 0.0


def obter_tipos_disponiveis() -> list:
    """
    Retorna lista de tipos residenciais disponíveis para exibição ao usuário.

    Returns:
        Lista com nomes amigáveis dos tipos disponíveis
    """
    from app.config import TIPOS_RESIDENCIAIS_DISPONIVEIS
    return TIPOS_RESIDENCIAIS_DISPONIVEIS


def validar_mes(mes_input) -> Optional[int]:
    """
    Valida e converte mês para número

    Args:
        mes_input: Nome do mês ou número (str ou int)

    Returns:
        Número do mês (1-12) ou None se inválido
    """
    if mes_input is None:
        return None

    # Se já é número
    if isinstance(mes_input, int):
        if 1 <= mes_input <= 12:
            return mes_input
        return None

    # Tentar converter string para número
    mes_str = str(mes_input).strip()
    try:
        mes = int(mes_str)
        if 1 <= mes <= 12:
            return mes
        return None
    except ValueError:
        pass

    # Tentar como nome do mês
    mes_norm = normalizar_texto(mes_str)
    if mes_norm in MESES_MAPPING:
        return MESES_MAPPING[mes_norm]

    return None


def validar_ano(ano_input) -> Optional[int]:
    """
    Valida ano de referência

    Args:
        ano_input: Ano (str ou int)

    Returns:
        Ano válido ou None
    """
    if ano_input is None:
        return None

    try:
        ano = int(ano_input)

        # Se ano com 2 dígitos, assumir 20XX
        if ano < 100:
            ano = 2000 + ano

        # Validar ano razoável (2020-2030)
        if 2020 <= ano <= 2030:
            return ano

        return None
    except (ValueError, TypeError):
        return None


def validar_data_referencia(
    mes_input=None,
    ano_input=None
) -> Tuple[int, int, bool]:
    """
    Valida e normaliza data de referência

    Returns:
        Tuple[mes, ano, usou_data_corrente]
    """
    data_atual = datetime.now()
    usou_corrente = False

    # Processar mês
    mes = validar_mes(mes_input)
    if mes is None:
        mes = data_atual.month
        usou_corrente = True

    # Processar ano
    ano = validar_ano(ano_input)
    if ano is None:
        ano = data_atual.year
        usou_corrente = True

    return mes, ano, usou_corrente


def validar_quantidade(quantidade_input) -> Tuple[Optional[int], str]:
    """
    Valida quantidade de unidades

    Returns:
        Tuple[quantidade_valida, mensagem_erro]
    """
    if quantidade_input is None:
        return 1, ""  # Valor padrão

    try:
        qtd = int(quantidade_input)
        if qtd <= 0:
            return None, "Quantidade deve ser maior que zero"
        return qtd, ""
    except (ValueError, TypeError):
        return None, "Quantidade inválida"
