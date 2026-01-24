"""
LLM module - Provider abstractions
"""

from typing import Dict, Optional

from app.config import get_settings
from app.llm.base import LLMProvider, LLMResponse
from app.llm.ollama import OllamaProvider
from app.llm.openai import OpenAIProvider
from app.llm.anthropic import AnthropicProvider


# Cache de providers instanciados
_providers: Dict[str, LLMProvider] = {}


def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """
    Factory para obter provider LLM

    Args:
        provider_name: Nome do provider (ollama, openai, anthropic)
                      Se None, usa o padrão configurado

    Returns:
        Instância do provider solicitado
    """
    settings = get_settings()

    if provider_name is None:
        provider_name = settings.default_llm_provider

    provider_name = provider_name.lower()

    # Retornar do cache se já existe
    if provider_name in _providers:
        return _providers[provider_name]

    # Criar nova instância
    if provider_name == "ollama":
        provider = OllamaProvider()
    elif provider_name == "openai":
        provider = OpenAIProvider()
    elif provider_name == "anthropic":
        provider = AnthropicProvider()
    else:
        raise ValueError(f"Provider desconhecido: {provider_name}")

    _providers[provider_name] = provider
    return provider


def get_available_providers() -> list[str]:
    """
    Retorna lista de providers disponíveis (com credenciais configuradas)
    """
    settings = get_settings()
    available = ["ollama"]  # Ollama sempre disponível (local)

    if settings.openai_api_key:
        available.append("openai")

    if settings.anthropic_api_key:
        available.append("anthropic")

    return available


async def close_all_providers() -> None:
    """Fecha todos os providers instanciados"""
    for provider in _providers.values():
        await provider.close()
    _providers.clear()


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "OllamaProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "get_llm_provider",
    "get_available_providers",
    "close_all_providers"
]
