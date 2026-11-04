import pytest
from pydantic import BaseModel

from rpg_agent.adapters.llm.fake import FakeLLM
from rpg_agent.application.errors import LLMOutputError
from rpg_agent.application.rendering import PromptRenderer
from rpg_agent.application.structured import StructuredGenerator, extract_json
from rpg_agent.ports.llm import Message


class Dummy(BaseModel):
    value: int


MESSAGES = [Message("system", "sys"), Message("user", "pergunta")]


def make(fake: FakeLLM, retries: int = 2) -> StructuredGenerator:
    return StructuredGenerator(fake, PromptRenderer(), max_retries=retries)


def test_valid_on_first_attempt() -> None:
    fake = FakeLLM(['{"value": 3}'])
    result = make(fake).generate(MESSAGES, Dummy)
    assert result.value.value == 3
    assert result.report.attempts == 1
    assert len(fake.calls) == 1


def test_uses_model_schema_by_default_and_custom_schema_when_given() -> None:
    fake = FakeLLM(['{"value": 1}', '{"value": 1}'])
    gen = make(fake)
    gen.generate(MESSAGES, Dummy)
    gen.generate(MESSAGES, Dummy, schema={"custom": True})
    assert fake.schemas[0]["properties"]["value"]["type"] == "integer"
    assert fake.schemas[1] == {"custom": True}


def test_retries_after_invalid_json_and_sends_repair_message() -> None:
    fake = FakeLLM(["isto não é json", '{"value": 7}'])
    result = make(fake).generate(MESSAGES, Dummy)
    assert result.value.value == 7
    assert result.report.attempts == 2
    repair_call = fake.calls[1]
    assert repair_call[-2] == Message("assistant", "isto não é json")
    assert "JSON válido" in repair_call[-1].content


def test_retries_when_schema_validation_fails() -> None:
    fake = FakeLLM(['{"value": "abc"}', '{"value": 2}'])
    result = make(fake).generate(MESSAGES, Dummy)
    assert result.report.attempts == 2
    assert "value" in fake.calls[1][-1].content


def test_retries_when_rule_check_fails() -> None:
    fake = FakeLLM(['{"value": 1}', '{"value": 10}'])

    def check(d: Dummy) -> list[str]:
        return [] if d.value >= 5 else ["o valor deve ser pelo menos 5"]

    result = make(fake).generate(MESSAGES, Dummy, check=check)
    assert result.value.value == 10
    assert "pelo menos 5" in fake.calls[1][-1].content


def test_context_does_not_grow_between_retries() -> None:
    fake = FakeLLM(["x", "y", '{"value": 1}'])
    make(fake).generate(MESSAGES, Dummy)
    assert [len(c) for c in fake.calls] == [2, 4, 4]


def test_raises_after_exhausting_retries() -> None:
    fake = FakeLLM(["lixo", "{}", '{"value": "x"}'])
    with pytest.raises(LLMOutputError) as info:
        make(fake, retries=2).generate(MESSAGES, Dummy)
    assert len(info.value.problems_by_attempt) == 3
    assert len(fake.calls) == 3


def test_zero_retries_means_single_attempt() -> None:
    fake = FakeLLM(["lixo"])
    with pytest.raises(LLMOutputError):
        make(fake, retries=0).generate(MESSAGES, Dummy)
    assert len(fake.calls) == 1


def test_accepts_code_fenced_json() -> None:
    fake = FakeLLM(['```json\n{"value": 5}\n```'])
    assert make(fake).generate(MESSAGES, Dummy).value.value == 5


def test_extract_json_ignores_text_around_object() -> None:
    assert extract_json('Claro! {"value": 1} Pronto.') == '{"value": 1}'
