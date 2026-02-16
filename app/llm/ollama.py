"""
Provider Ollama (LLM local)
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any

import httpx

from app.config import get_settings
from app.llm.base import (
    LLMProvider,
    LLMResponse,
    ToolDefinition,
    ToolCall,
    StopReason,
    LLMResponseWithTools,
)

logger = logging.getLogger(__name__)


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
        """Executa completion via Ollama API (/api/generate)"""
        client = await self._get_client()

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

    def _convert_tools(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Converte ToolDefinition para formato Ollama (OpenAI-compatible)"""
        ollama_tools = []
        for tool in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.to_json_schema()
                }
            })
        return ollama_tools

    def _convert_messages(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Converte mensagens para formato Ollama /api/chat (OpenAI-compatible)"""
        ollama_messages = []

        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            role = msg.get("role")

            if role == "user":
                ollama_messages.append({
                    "role": "user",
                    "content": msg["content"]
                })

            elif role == "assistant":
                oai_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                }
                if msg.get("tool_calls"):
                    oai_msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        }
                        for tc in msg["tool_calls"]
                    ]
                ollama_messages.append(oai_msg)

            elif role == "tool":
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "content": msg["content"],
                }
                if msg.get("tool_call_id"):
                    tool_msg["tool_call_id"] = msg["tool_call_id"]
                ollama_messages.append(tool_msg)

        return ollama_messages

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponseWithTools:
        """Parseia resposta Ollama /api/chat para LLMResponseWithTools"""
        message = data.get("message", {})

        content = message.get("content") or None
        tool_calls = []

        for tc in message.get("tool_calls") or []:
            func = tc.get("function", {})
            arguments = func.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            tool_calls.append(ToolCall(
                id=tc.get("id", f"call_{len(tool_calls)}"),
                name=func.get("name", ""),
                arguments=arguments
            ))

        if tool_calls:
            stop_reason = StopReason.TOOL_USE
        elif data.get("done_reason") == "length":
            stop_reason = StopReason.MAX_TOKENS
        else:
            stop_reason = StopReason.END_TURN

        return LLMResponseWithTools(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            model=self.model,
            provider=self.name,
            tokens_input=data.get("prompt_eval_count"),
            tokens_output=data.get("eval_count"),
            raw_response=data
        )

    async def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[ToolDefinition],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096
    ) -> LLMResponseWithTools:
        """Executa completion com tool use via Ollama /api/chat"""
        client = await self._get_client()

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages, system_prompt),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        inicio = time.time()

        response = await client.post("/api/chat", json=payload)

        if response.status_code >= 400:
            logger.error(f"[Ollama] HTTP {response.status_code}: {response.text}")
        response.raise_for_status()

        data = response.json()
        result = self._parse_response(data)
        result.tempo_resposta = time.time() - inicio

        return result

    async def health_check(self) -> bool:
        """Verifica se o Ollama esta acessivel"""
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
