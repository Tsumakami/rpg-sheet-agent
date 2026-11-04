"""Geração estruturada com validação e laço de reparo.

Fluxo: chama o LLM com o JSON Schema -> valida com Pydantic -> aplica checagens de
regras (`check`) -> se algo falhar, devolve os problemas ao modelo e tenta de novo.
Em cada retentativa o contexto é refeito (mensagens base + última resposta + problemas),
sem acumular histórico, para caber em um contexto pequeno.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from rpg_agent.application.errors import LLMOutputError
from rpg_agent.application.rendering import PromptRenderer
from rpg_agent.ports.llm import LLMPort, Message


@dataclass(frozen=True)
class GenerationReport:
    attempts: int
    latency_s: float
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class Generated[T: BaseModel]:
    value: T
    report: GenerationReport


def extract_json(text: str) -> str:
    """Tolera cercas de código (```json) e texto em volta do objeto JSON."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned


def describe_validation_error(exc: ValidationError) -> list[str]:
    errors = exc.errors()
    if any(err["type"] == "json_invalid" for err in errors):
        return ["a resposta não é um JSON válido"]
    problems = []
    for err in errors[:5]:
        location = ".".join(str(part) for part in err["loc"]) or "(raiz)"
        problems.append(f"campo {location}: {err['msg']}")
    return problems


def _parse[T: BaseModel](
    content: str,
    output_model: type[T],
    check: Callable[[T], Sequence[str]] | None,
) -> tuple[T | None, list[str]]:
    try:
        value = output_model.model_validate_json(extract_json(content))
    except ValidationError as exc:
        return None, describe_validation_error(exc)
    problems = list(check(value)) if check is not None else []
    return value, problems


class StructuredGenerator:
    def __init__(self, llm: LLMPort, renderer: PromptRenderer, max_retries: int = 2) -> None:
        self._llm = llm
        self._renderer = renderer
        self._max_retries = max(0, max_retries)

    def generate[T: BaseModel](
        self,
        messages: Sequence[Message],
        output_model: type[T],
        *,
        schema: dict[str, Any] | None = None,
        check: Callable[[T], Sequence[str]] | None = None,
    ) -> Generated[T]:
        json_schema = schema if schema is not None else output_model.model_json_schema()
        base = list(messages)
        conversation = base
        problems_by_attempt: list[list[str]] = []
        latency = 0.0
        prompt_tokens = completion_tokens = 0

        for attempt in range(1, self._max_retries + 2):
            response = self._llm.chat_structured(conversation, json_schema)
            latency += response.latency_s
            prompt_tokens += response.prompt_tokens
            completion_tokens += response.completion_tokens

            value, problems = _parse(response.content, output_model, check)
            if value is not None and not problems:
                report = GenerationReport(attempt, latency, prompt_tokens, completion_tokens)
                return Generated(value, report)

            problems_by_attempt.append(problems)
            repair = self._renderer.render("repair.j2", problems=problems)
            conversation = [*base, Message("assistant", response.content), Message("user", repair)]

        raise LLMOutputError(problems_by_attempt)
