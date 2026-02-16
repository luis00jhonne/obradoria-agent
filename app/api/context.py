"""
Context vars para dados do request (token JWT, modelo LLM).
Permite acesso em qualquer camada sem passar por parâmetros.
"""

from contextvars import ContextVar

# Token JWT do usuário (repassado nas chamadas à API Spring)
request_token: ContextVar[str] = ContextVar("request_token", default="")

# Modelo LLM usado na sessão (salvo junto ao orçamento)
request_model: ContextVar[str] = ContextVar("request_model", default="")
