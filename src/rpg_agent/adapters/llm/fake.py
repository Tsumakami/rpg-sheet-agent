"""LLM falso para testes: respostas roteirizadas, sem rede e sem GPU."""

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from rpg_agent.ports.llm import LLMResponse, Message


class FakeLLM:
    """Devolve as respostas do roteiro na ordem (ou levanta, se o item for uma exceção).

    Alternativamente, passe `handler(messages, schema) -> str` para respostas dinâmicas.
    Todas as chamadas ficam registradas em `calls` e `schemas`.
    """

    def __init__(
        self,
        script: Iterable[str | Exception] = (),
        handler: Callable[[Sequence[Message], dict[str, Any]], str] | None = None,
    ) -> None:
        self._script: deque[str | Exception] = deque(script)
        self._handler = handler
        self.calls: list[list[Message]] = []
        self.schemas: list[dict[str, Any]] = []

    def chat_structured(
        self,
        messages: Sequence[Message],
        json_schema: dict[str, Any],
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.schemas.append(json_schema)

        if self._handler is not None:
            content = self._handler(messages, json_schema)
        elif self._script:
            item = self._script.popleft()
            if isinstance(item, Exception):
                raise item
            content = item
        else:
            raise AssertionError("FakeLLM: o roteiro de respostas acabou")

        prompt_chars = sum(len(m.content) for m in messages)
        return LLMResponse(content, prompt_chars // 4, len(content) // 4, 0.0)
