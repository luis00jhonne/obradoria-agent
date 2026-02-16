"""
Provider Anthropic (Claude)
"""

import asyncio
import json
import logging
import time
from typing import Optional, List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # segundos

from app.config import get_settings
from app.llm.base import (
    LLMProvider,
    LLMResponse,
    ToolDefinition,
    ToolCall,
    ToolResult,
    StopReason,
    LLMResponseWithTools,
)


class AnthropicProvider(LLMProvider):
    """Provider para Anthropic API (Claude)"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.timeout = settings.anthropic_timeout
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY nao configurada")

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

    async def _post_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /v1/messages com retry e backoff exponencial para 429/529"""
        client = await self._get_client()

        for attempt in range(MAX_RETRIES + 1):
            response = await client.post("/v1/messages", json=payload)

            if response.status_code == 429 or response.status_code == 529:
                if attempt < MAX_RETRIES:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"[Anthropic] {response.status_code} - retry {attempt + 1}/{MAX_RETRIES} em {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

            if response.status_code >= 400:
                body = response.text
                logger.error(f"[Anthropic] HTTP {response.status_code}: {body}")

            response.raise_for_status()
            return response.json()

        response.raise_for_status()
        return {}

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 500
    ) -> LLMResponse:
        """Executa completion via Anthropic API"""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        if system_prompt:
            payload["system"] = system_prompt

        if temperature != 0.1:
            payload["temperature"] = temperature

        inicio = time.time()
        data = await self._post_with_retry(payload)
        tempo_resposta = time.time() - inicio

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

    def _convert_tools(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Converte ToolDefinition para formato Anthropic"""
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.to_json_schema()
            })
        return anthropic_tools

    def _convert_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Converte mensagens do formato generico para formato Anthropic.

        Formato generico:
        - {role: "user", content: "texto"}
        - {role: "assistant", content: "texto"}
        - {role: "assistant", content: "texto", tool_calls: [...]}
        - {role: "tool", tool_call_id: "id", content: "resultado"}

        Formato Anthropic:
        - {role: "user", content: "texto"} ou content blocks
        - {role: "assistant", content: [...blocks...]}
        - tool_results vao como content blocks dentro de mensagem "user"
        """
        anthropic_messages = []
        i = 0

        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")

            if role == "user":
                # Se a ultima mensagem ja e user, fundir conteudo
                if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                    prev = anthropic_messages[-1]
                    prev_content = prev["content"]
                    new_text = msg["content"]
                    # Converter para lista de blocks se necessario
                    if isinstance(prev_content, str):
                        prev["content"] = [
                            {"type": "text", "text": prev_content},
                            {"type": "text", "text": new_text},
                        ]
                    elif isinstance(prev_content, list):
                        prev["content"].append({"type": "text", "text": new_text})
                else:
                    anthropic_messages.append({
                        "role": "user",
                        "content": msg["content"]
                    })
                i += 1

            elif role == "assistant":
                content_blocks = []

                # Texto do assistente
                if msg.get("content"):
                    content_blocks.append({
                        "type": "text",
                        "text": msg["content"]
                    })

                # Tool calls do assistente
                for tc in msg.get("tool_calls", []):
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"]
                    })

                anthropic_messages.append({
                    "role": "assistant",
                    "content": content_blocks if content_blocks else msg.get("content", "")
                })
                i += 1

                # Coletar tool_results consecutivos -> mensagem user com content blocks
                tool_result_blocks = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tool_msg["tool_call_id"],
                        "content": tool_msg["content"],
                        **({"is_error": True} if tool_msg.get("is_error") else {})
                    })
                    i += 1

                if tool_result_blocks:
                    anthropic_messages.append({
                        "role": "user",
                        "content": tool_result_blocks
                    })

            else:
                i += 1

        return anthropic_messages

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponseWithTools:
        """Parseia resposta Anthropic para LLMResponseWithTools"""
        content_text = ""
        tool_calls = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {})
                ))

        stop = data.get("stop_reason", "end_turn")
        if stop == "tool_use":
            stop_reason = StopReason.TOOL_USE
        elif stop == "max_tokens":
            stop_reason = StopReason.MAX_TOKENS
        else:
            stop_reason = StopReason.END_TURN

        return LLMResponseWithTools(
            content=content_text or None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            model=self.model,
            provider=self.name,
            tokens_input=data.get("usage", {}).get("input_tokens"),
            tokens_output=data.get("usage", {}).get("output_tokens"),
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
        """Executa completion com tool use via Anthropic API"""
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": self._convert_messages(messages),
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        if system_prompt:
            payload["system"] = system_prompt

        if temperature != 0.1:
            payload["temperature"] = temperature

        inicio = time.time()
        data = await self._post_with_retry(payload)
        result = self._parse_response(data)
        result.tempo_resposta = time.time() - inicio

        return result

    async def health_check(self) -> bool:
        """Verifica se a API Anthropic esta acessivel (chave configurada)"""
        return bool(self.api_key)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
