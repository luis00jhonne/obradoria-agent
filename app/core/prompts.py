"""
Prompts centralizados para o LLM
"""

from datetime import datetime


MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}


def criar_prompt_extracao(texto_usuario: str) -> str:
    """
    Prompt otimizado para extração rápida e direta de informações do pedido

    Args:
        texto_usuario: Texto do usuário em linguagem natural

    Returns:
        Prompt formatado para o LLM
    """
    data_atual = datetime.now()
    mes_atual = MESES_PT[data_atual.month]
    ano_atual = data_atual.year

    return f"""Extraia as informações do texto e retorne APENAS um JSON válido.

Texto: "{texto_usuario}"

Campos a extrair:
- quantidade: número inteiro (padrão: 1)
- tipo_construtivo: tipo da construção (ex: "residencial")
- padrao_construtivo: padrão (ex: "minimo", "basico")
- estado: UF ou nome do estado brasileiro
- mes_referencia: número do mês 1-12 (padrão: {data_atual.month})
- ano_referencia: ano com 4 dígitos (padrão: {ano_atual})

Exemplo de resposta:
{{"quantidade": 2, "tipo_construtivo": "residencial", "padrao_construtivo": "minimo", "estado": "MA", "mes_referencia": 9, "ano_referencia": 2025}}

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
