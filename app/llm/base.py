"""
Interface base para providers LLM
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """Resposta do LLM"""
    content: str
    model: str
    provider: str
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tempo_resposta: Optional[float] = None


class LLMProvider(ABC):
    """Interface abstrata para providers de LLM"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome do provider"""
        pass

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500
    ) -> LLMResponse:
        """
        Executa completion no LLM

        Args:
            prompt: Prompt do usuário
            system_prompt: Prompt de sistema (opcional)
            temperature: Temperatura (criatividade)
            max_tokens: Máximo de tokens na resposta

        Returns:
            LLMResponse com a resposta
        """
        pass

    async def health_check(self) -> bool:
        """Verifica se o provider está acessível"""
        return False

    async def close(self) -> None:
        """Fecha conexões (opcional)"""
        pass
