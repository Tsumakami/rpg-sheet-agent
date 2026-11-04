"""Adapter do Ollama para a LLMPort."""

import time
from collections.abc import Sequence
from typing import Any

import ollama

from rpg_agent.config import Settings
from rpg_agent.ports.llm import LLMResponse, LLMUnavailableError, Message

_MAX_NEW_TOKENS = 1024


class OllamaAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = ollama.Client(host=settings.ollama_host, timeout=settings.timeout_s)

    def chat_structured(
        self,
        messages: Sequence[Message],
        json_schema: dict[str, Any],
    ) -> LLMResponse:
        start = time.perf_counter()
        try:
            response = self._client.chat(
                model=self._settings.model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                format=json_schema,
                options={
                    "num_ctx": self._settings.num_ctx,
                    "temperature": self._settings.temperature,
                    "num_predict": _MAX_NEW_TOKENS,
                },
            )
        except Exception as exc:  # fronteira de infraestrutura: traduz qualquer falha de transporte
            raise LLMUnavailableError(
                f"Falha ao falar com o Ollama ({self._settings.model}): {exc}"
            ) from exc

        return LLMResponse(
            content=str(response["message"]["content"]),
            prompt_tokens=int(getattr(response, "prompt_eval_count", None) or 0),
            completion_tokens=int(getattr(response, "eval_count", None) or 0),
            latency_s=time.perf_counter() - start,
        )

    def generate_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
    ) -> str:
        """Atalho de uma só rodada (usado pelo comando `doctor`)."""
        messages = [Message("system", system), Message("user", user)]
        return self.chat_structured(messages, json_schema).content
