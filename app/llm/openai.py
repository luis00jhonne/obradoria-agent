"""
Provider OpenAI (GPT-4)
"""

import time
from typing import Optional

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """Provider para OpenAI API"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.timeout = settings.openai_timeout
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY não configurada")

    @property
    def name(self) -> str:
        return "openai"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.openai.com/v1",
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500
    ) -> LLMResponse:
        """Executa completion via OpenAI API"""
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        inicio = time.time()

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()

        tempo_resposta = time.time() - inicio

        data = response.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=self.model,
            provider=self.name,
            tokens_input=data.get("usage", {}).get("prompt_tokens"),
            tokens_output=data.get("usage", {}).get("completion_tokens"),
            tempo_resposta=tempo_resposta
        )

    async def health_check(self) -> bool:
        """Verifica se a API OpenAI está acessível"""
        client = await self._get_client()
        try:
            response = await client.get("/models")
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
