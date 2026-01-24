"""
Prompts centralizados para o LLM
"""

from datetime import datetime


def criar_prompt_extracao(texto_usuario: str) -> str:
    """
    Prompt otimizado para extração rápida e direta de informações do pedido

    Args:
        texto_usuario: Texto do usuário em linguagem natural

    Returns:
        Prompt formatado para o LLM
    """
    data_atual = datetime.now()
    mes_atual = data_atual.strftime("%B")
    ano_atual = data_atual.year

    return f"""Extraia as informações e retorne APENAS o JSON. Não explique, não comente.

Texto: "{texto_usuario}"

Extrair:
- quantidade (inteiro, padrão=1)
- tipo_construtivo (ex: residencial)
- padrao_construtivo (ex: minimo, basico)
- estado (sigla UF ou nome)
- mes_referencia (nome ou número do mês, padrão={mes_atual})
- ano_referencia (ano com 4 dígitos, padrão={ano_atual})

JSON:"""


def criar_prompt_extracao_sistema() -> str:
    """
    Prompt de sistema para extração de informações

    Returns:
        Prompt de sistema formatado
    """
    return """Você é um assistente especializado em extrair informações de pedidos de orçamentos de construção civil.
Sua tarefa é identificar:
- Quantidade de unidades a construir
- Tipo de construção (residencial, comercial, industrial)
- Padrão construtivo (mínimo/popular, básico/intermediário, alto)
- Estado/UF do Brasil onde será construído
- Mês e ano de referência para os preços

Sempre retorne um JSON válido com as informações extraídas.
Se alguma informação não estiver clara, use valores padrão sensatos.
"""


PROMPT_SISTEMA_EXTRACAO = criar_prompt_extracao_sistema()
