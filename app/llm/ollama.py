"""
Provider Ollama (LLM local)
"""

import time
from typing import Optional

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Provider para Ollama (modelos locais)"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ollama_url
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "ollama"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout)
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500
    ) -> LLMResponse:
        """Executa completion via Ollama API"""
        client = await self._get_client()

        # Montar prompt completo
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        inicio = time.time()

        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

        tempo_resposta = time.time() - inicio

        data = response.json()

        return LLMResponse(
            content=data.get("response", ""),
            model=self.model,
            provider=self.name,
            tokens_input=data.get("prompt_eval_count"),
            tokens_output=data.get("eval_count"),
            tempo_resposta=tempo_resposta
        )

    async def health_check(self) -> bool:
        """Verifica se o Ollama está acessível"""
        client = await self._get_client()
        try:
            response = await client.get("/api/tags")
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
