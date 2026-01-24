"""
Provider Anthropic (Claude)
"""

import time
from typing import Optional

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    """Provider para Anthropic API (Claude)"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.timeout = settings.anthropic_timeout
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY não configurada")

    @property
    def name(self) -> str:
        return "anthropic"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.anthropic.com",
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01"
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
        """Executa completion via Anthropic API"""
        client = await self._get_client()

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        if system_prompt:
            payload["system"] = system_prompt

        # Anthropic não usa temperature da mesma forma
        # mas podemos passar se necessário
        if temperature != 0.1:
            payload["temperature"] = temperature

        inicio = time.time()

        response = await client.post("/v1/messages", json=payload)
        response.raise_for_status()

        tempo_resposta = time.time() - inicio

        data = response.json()

        # Extrair conteúdo da resposta
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        return LLMResponse(
            content=content,
            model=self.model,
            provider=self.name,
            tokens_input=data.get("usage", {}).get("input_tokens"),
            tokens_output=data.get("usage", {}).get("output_tokens"),
            tempo_resposta=tempo_resposta
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
