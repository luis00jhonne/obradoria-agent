"""
Provider OpenAI (GPT-4)
"""

import json
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


class OpenAIProvider(LLMProvider):
    """Provider para OpenAI API"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.timeout = settings.openai_timeout
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY nao configurada")

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

    def _convert_tools(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Converte ToolDefinition para formato OpenAI"""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.to_json_schema()
                }
            })
        return openai_tools

    def _convert_messages(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Converte mensagens do formato generico para formato OpenAI.

        Formato OpenAI:
        - {role: "system", content: "..."}
        - {role: "user", content: "..."}
        - {role: "assistant", content: "...", tool_calls: [...]}
        - {role: "tool", tool_call_id: "id", content: "resultado"}
        """
        openai_messages = []

        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            role = msg.get("role")

            if role == "user":
                openai_messages.append({
                    "role": "user",
                    "content": msg["content"]
                })

            elif role == "assistant":
                oai_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("content") or None,
                }
                if msg.get("tool_calls"):
                    oai_msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"])
                            }
                        }
                        for tc in msg["tool_calls"]
                    ]
                openai_messages.append(oai_msg)

            elif role == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": msg["content"]
                })

        return openai_messages

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponseWithTools:
        """Parseia resposta OpenAI para LLMResponseWithTools"""
        choice = data["choices"][0]
        message = choice["message"]

        content = message.get("content")
        tool_calls = []

        for tc in message.get("tool_calls") or []:
            arguments = tc["function"].get("arguments", "{}")
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=arguments
            ))

        finish = choice.get("finish_reason", "stop")
        if finish == "tool_calls":
            stop_reason = StopReason.TOOL_USE
        elif finish == "length":
            stop_reason = StopReason.MAX_TOKENS
        else:
            stop_reason = StopReason.TOOL_USE if tool_calls else StopReason.END_TURN

        return LLMResponseWithTools(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            model=self.model,
            provider=self.name,
            tokens_input=data.get("usage", {}).get("prompt_tokens"),
            tokens_output=data.get("usage", {}).get("completion_tokens"),
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
        """Executa completion com tool use via OpenAI API"""
        client = await self._get_client()

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages, system_prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        inicio = time.time()

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()

        data = response.json()
        result = self._parse_response(data)
        result.tempo_resposta = time.time() - inicio

        return result

    async def health_check(self) -> bool:
        """Verifica se a API OpenAI esta acessivel"""
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
