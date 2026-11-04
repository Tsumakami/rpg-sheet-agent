"""Testes com o modelo REAL do Ollama. Rodam só com `make test-llm` (marker `llm`)."""

import pytest

from rpg_agent.adapters.llm.ollama import OllamaAdapter
from rpg_agent.application.errors import LLMOutputError
from rpg_agent.application.step_advisor import ChoiceSuggestion, StepAdvisor
from rpg_agent.config import get_settings
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack
from rpg_agent.ports.llm import LLMUnavailableError, Message

pytestmark = pytest.mark.llm

CONCEPTS = [
    "um mago sombrio obcecado por conhecimento proibido",
    "uma guerreira honrada que protege a aldeia",
    "um ladino charmoso que vive de pequenos golpes",
    "uma clériga gentil que cuida dos feridos",
    "um anão rabugento ferreiro de armas lendárias",
    "uma halfling curiosa que adora explorar ruínas",
    "um humano ambicioso que quer virar rei",
    "uma elfa silenciosa que caça monstros à noite",
    "um estudioso desastrado que acidentalmente salva o dia",
    "um mercenário cansado procurando redenção",
]


@pytest.fixture(scope="module")
def adapter() -> OllamaAdapter:
    adapter = OllamaAdapter(get_settings())
    try:
        ping = [Message("user", "Responda com um JSON vazio.")]
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        adapter.chat_structured(ping, schema)
    except LLMUnavailableError as exc:
        pytest.skip(f"Ollama indisponível: {exc}")
    return adapter


def test_first_try_validity_rate(adapter: OllamaAdapter, dnd_pack: RulePack) -> None:
    """Meta da Fase 2: >= 95% de saídas válidas SEM usar retentativas."""
    advisor = StepAdvisor(adapter, max_retries=0)
    successes = total = 0
    for concept in CONCEPTS:
        for step_id in ("race", "class"):
            total += 1
            character = Character(system_id="dnd5e_srd", concept=concept)
            try:
                result = advisor.suggest(dnd_pack, character, step_id, user_input=concept)
            except LLMOutputError:
                continue
            assert isinstance(result, ChoiceSuggestion)
            successes += 1

    rate = successes / total
    print(f"\nTaxa de validade na 1ª tentativa: {successes}/{total} = {rate:.0%}")
    assert rate >= 0.95
