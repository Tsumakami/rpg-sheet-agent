import pytest

from rpg_agent.application.apply import apply_suggestion
from rpg_agent.application.step_advisor import (
    AttributesSuggestion,
    ChoiceSuggestion,
    SkillsSuggestion,
    TextSuggestion,
)
from rpg_agent.application.structured import GenerationReport
from rpg_agent.domain.editor import RuleViolationError, SheetEditor
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack

REPORT = GenerationReport(attempts=1, latency_s=0.0, prompt_tokens=0, completion_tokens=0)


def test_apply_each_kind_of_suggestion(dnd_pack: RulePack) -> None:
    editor = SheetEditor(dnd_pack)
    character = Character(system_id="dnd5e_srd")

    choice = ChoiceSuggestion("class", "class", "wizard", "", REPORT)
    result = apply_suggestion(editor, character, choice)
    assert result.character.choices == {"class": "wizard"}

    scores = {"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10}
    attrs = AttributesSuggestion("attributes", "standard_array", list(scores), scores, "", REPORT)
    result = apply_suggestion(editor, result.character, attrs)
    assert result.character.attributes == scores

    skills = SkillsSuggestion("skills", ["arcana", "history"], "", REPORT)
    result = apply_suggestion(editor, result.character, skills)
    assert result.character.skills == {"arcana": 1, "history": 1}

    text = TextSuggestion("name", "name", ["Aelar", "Lyra"], REPORT)
    result = apply_suggestion(editor, result.character, text)
    assert result.character.name == "Aelar"


def test_apply_rejects_rule_breaking_suggestion(dnd_pack: RulePack, elf_wizard: Character) -> None:
    editor = SheetEditor(dnd_pack)
    base = elf_wizard.model_copy(update={"skills": {}, "completed_steps": ["race", "class"]})
    # furtividade não está na lista de perícias do mago
    bad = SkillsSuggestion("skills", ["arcana", "stealth"], "", REPORT)
    with pytest.raises(RuleViolationError):
        apply_suggestion(editor, base, bad)
