import pytest

from rpg_agent.domain.issues import Issue, Severity, has_errors
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack
from rpg_agent.domain.validators import validate_character


def codes(issues: list[Issue]) -> set[str]:
    return {i.code for i in issues}


def test_valid_complete_character(dnd_pack: RulePack, elf_wizard: Character) -> None:
    assert validate_character(dnd_pack, elf_wizard, require_complete=True) == []


def test_system_mismatch(dnd_pack: RulePack) -> None:
    issues = validate_character(dnd_pack, Character(system_id="vampire_v5"))
    assert codes(issues) == {"system_mismatch"}


def test_partial_character_only_checks_completed_steps(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    partial = elf_wizard.model_copy(
        update={"completed_steps": ["concept", "race", "class"], "attributes": {}}
    )
    assert validate_character(dnd_pack, partial) == []


def test_completed_attributes_step_requires_all_scores(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    c = elf_wizard.model_copy(update={"completed_steps": ["attributes"], "attributes": {}})
    issues = validate_character(dnd_pack, c)
    assert [i.code for i in issues] == ["attribute_missing"] * 6


def test_unknown_step(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(update={"completed_steps": ["voar"]})
    assert "unknown_step" in codes(validate_character(dnd_pack, c))


def test_unknown_attribute_always_checked(dnd_pack: RulePack) -> None:
    c = Character(system_id="dnd5e_srd", attributes={"luck": 10})
    assert "unknown_attribute" in codes(validate_character(dnd_pack, c))


def test_invalid_option_always_checked(dnd_pack: RulePack) -> None:
    c = Character(system_id="dnd5e_srd", choices={"race": "orc", "faction": "x"})
    assert codes(validate_character(dnd_pack, c)) == {"invalid_option", "unknown_choice"}


def test_missing_choice_when_step_completed(dnd_pack: RulePack) -> None:
    c = Character(system_id="dnd5e_srd", completed_steps=["race"])
    assert codes(validate_character(dnd_pack, c)) == {"choice_missing"}


def test_point_buy_exact_budget(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(
        update={
            "attribute_method": "point_buy",
            "attributes": {"str": 15, "dex": 15, "con": 15, "int": 8, "wis": 8, "cha": 8},
        }
    )
    assert validate_character(dnd_pack, c) == []


def test_point_buy_over_budget(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(
        update={
            "attribute_method": "point_buy",
            "attributes": {"str": 15, "dex": 15, "con": 15, "int": 10, "wis": 8, "cha": 8},
        }
    )
    assert codes(validate_character(dnd_pack, c)) == {"point_buy_over_budget"}


def test_point_buy_unspent_is_only_a_warning(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(
        update={
            "attribute_method": "point_buy",
            "attributes": dict.fromkeys(["str", "dex", "con", "int", "wis", "cha"], 8),
        }
    )
    issues = validate_character(dnd_pack, c)
    assert codes(issues) == {"point_buy_unspent"}
    assert issues[0].severity is Severity.WARNING
    assert not has_errors(issues)


def test_point_buy_rejects_score_above_15(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(
        update={
            "attribute_method": "point_buy",
            "attributes": {"str": 16, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8},
        }
    )
    assert codes(validate_character(dnd_pack, c)) == {"attribute_out_of_range"}


def test_standard_array_mismatch(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(
        update={"attributes": {"str": 15, "dex": 15, "con": 13, "int": 12, "wis": 10, "cha": 8}}
    )
    assert codes(validate_character(dnd_pack, c)) == {"standard_array_mismatch"}


def test_roll_method_accepts_3_to_18(dnd_pack: RulePack, elf_wizard: Character) -> None:
    ok = elf_wizard.model_copy(
        update={
            "attribute_method": "roll",
            "attributes": {"str": 18, "dex": 3, "con": 12, "int": 9, "wis": 14, "cha": 7},
        }
    )
    assert validate_character(dnd_pack, ok) == []


def test_method_is_required_when_pack_has_several(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    c = elf_wizard.model_copy(update={"attribute_method": None})
    assert codes(validate_character(dnd_pack, c)) == {"attribute_method_missing"}


def test_invalid_method(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(update={"attribute_method": "magic"})
    assert codes(validate_character(dnd_pack, c)) == {"invalid_attribute_method"}


@pytest.mark.parametrize(
    ("skills", "expected"),
    [
        ({"arcana": 1, "history": 1, "investigation": 1}, {"skills_over_budget"}),
        ({"arcana": 1, "insight": 1}, {"skill_already_granted"}),
        ({"arcana": 1, "perception": 1}, {"skill_already_granted"}),
        ({"arcana": 2}, {"skill_out_of_range"}),
        ({"juggling": 1}, {"unknown_skill"}),
        ({"arcana": 1}, {"skills_unspent"}),
    ],
)
def test_skills(
    dnd_pack: RulePack, elf_wizard: Character, skills: dict[str, int], expected: set[str]
) -> None:
    c = elf_wizard.model_copy(update={"skills": skills})
    assert codes(validate_character(dnd_pack, c)) == expected


def test_require_complete_flags_empty_narrative(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(update={"name": "  ", "background": ""})
    issues = validate_character(dnd_pack, c, require_complete=True)
    assert [i.path for i in issues] == ["name", "background"]
    assert codes(issues) == {"narrative_missing"}


def test_skill_outside_class_list_is_rejected(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(update={"skills": {"arcana": 1, "stealth": 1}})
    assert codes(validate_character(dnd_pack, c)) == {"skill_not_allowed"}


def test_skill_restriction_only_applies_once_a_class_is_chosen(dnd_pack: RulePack) -> None:
    c = Character(system_id="dnd5e_srd", skills={"stealth": 1})
    assert validate_character(dnd_pack, c) == []


def test_unspent_skills_block_a_completed_skills_step(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    c = elf_wizard.model_copy(update={"skills": {"arcana": 1}})
    assert has_errors(validate_character(dnd_pack, c))
