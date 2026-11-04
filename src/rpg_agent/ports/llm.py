"""Porta do LLM: o domínio e a aplicação dependem disto, nunca do Ollama."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


class LLMError(Exception):
    """Erro base relacionado ao LLM."""


class LLMUnavailableError(LLMError):
    """Servidor/modelo indisponível, timeout ou falha de transporte."""


class LLMPort(Protocol):
    def chat_structured(
        self,
        messages: Sequence[Message],
        json_schema: dict[str, Any],
    ) -> LLMResponse:
        """Conversa com o modelo exigindo saída JSON que siga `json_schema`."""
        ...
