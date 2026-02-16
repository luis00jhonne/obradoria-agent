"""
Interface base para providers LLM
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


@dataclass
class LLMResponse:
    """Resposta do LLM"""
    content: str
    model: str
    provider: str
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tempo_resposta: Optional[float] = None


# =============================================================================
# TOOL USE TYPES
# =============================================================================

@dataclass
class ToolParameter:
    """Definicao de parametro de uma tool"""
    name: str
    type: str  # "string", "number", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None


@dataclass
class ToolDefinition:
    """Definicao de uma tool disponivel para o LLM"""
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)

    def to_json_schema(self) -> Dict[str, Any]:
        """Converte parametros para JSON Schema"""
        properties = {}
        required = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema


@dataclass
class ToolCall:
    """Chamada de tool solicitada pelo LLM"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Resultado da execucao de uma tool"""
    tool_call_id: str
    content: str
    is_error: bool = False


class StopReason(str, Enum):
    """Razao de parada do LLM"""
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"


@dataclass
class LLMResponseWithTools:
    """Resposta do LLM com suporte a tool calls"""
    content: Optional[str]
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    model: str = ""
    provider: str = ""
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tempo_resposta: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None


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
            prompt: Prompt do usuario
            system_prompt: Prompt de sistema (opcional)
            temperature: Temperatura (criatividade)
            max_tokens: Maximo de tokens na resposta

        Returns:
            LLMResponse com a resposta
        """
        pass

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[ToolDefinition],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096
    ) -> LLMResponseWithTools:
        """
        Executa completion com suporte a tool use

        Args:
            messages: Historico de mensagens no formato [{role, content}]
            tools: Lista de tools disponiveis
            system_prompt: Prompt de sistema
            temperature: Temperatura
            max_tokens: Maximo de tokens

        Returns:
            LLMResponseWithTools com conteudo e/ou tool calls
        """
        pass

    async def health_check(self) -> bool:
        """Verifica se o provider esta acessivel"""
        return False

    async def close(self) -> None:
        """Fecha conexoes (opcional)"""
        pass
