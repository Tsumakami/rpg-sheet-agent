import pytest

from rpg_agent.domain.editor import RuleViolationError, SheetEditor
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack

STANDARD = {"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10}


@pytest.fixture
def editor(dnd_pack: RulePack) -> SheetEditor:
    return SheetEditor(dnd_pack)


def new_character() -> Character:
    return Character(system_id="dnd5e_srd")


def codes(error: pytest.ExceptionInfo[RuleViolationError]) -> set[str]:
    return {i.code for i in error.value.issues}


# ----------------------------------------------------------------- escolhas
def test_set_choice_completes_step_and_leaves_original_untouched(editor: SheetEditor) -> None:
    base = new_character()
    result = editor.set_choice(base, "race", "elf")

    assert result.character.choices == {"race": "elf"}
    assert result.character.completed_steps == ["race"]
    assert result.reopened_steps == ()
    assert base.choices == {}
    assert base.completed_steps == []


def test_set_choice_rejects_invalid_option(editor: SheetEditor) -> None:
    with pytest.raises(RuleViolationError) as info:
        editor.set_choice(new_character(), "race", "orc")
    assert codes(info) == {"invalid_option"}


def test_set_choice_rejects_unknown_choice(editor: SheetEditor) -> None:
    with pytest.raises(RuleViolationError) as info:
        editor.set_choice(new_character(), "faction", "x")
    assert codes(info) == {"unknown_step"}


# ----------------------------------------------------------------- atributos
def test_set_attributes_accepts_valid_distribution(editor: SheetEditor) -> None:
    result = editor.set_attributes(new_character(), "standard_array", STANDARD)
    assert result.character.attributes == STANDARD
    assert result.character.attribute_method == "standard_array"
    assert "attributes" in result.character.completed_steps


def test_set_attributes_rejects_over_budget_point_buy(editor: SheetEditor) -> None:
    over = {"str": 15, "dex": 15, "con": 15, "int": 10, "wis": 8, "cha": 8}
    base = new_character()
    with pytest.raises(RuleViolationError) as info:
        editor.set_attributes(base, "point_buy", over)
    assert codes(info) == {"point_buy_over_budget"}
    assert base.attributes == {}


def test_set_attributes_rejects_unknown_method(editor: SheetEditor) -> None:
    with pytest.raises(RuleViolationError) as info:
        editor.set_attributes(new_character(), "magic", STANDARD)
    assert codes(info) == {"invalid_attribute_method"}


# ----------------------------------------------------------------- perícias
@pytest.fixture
def wizard_without_skills(elf_wizard: Character) -> Character:
    return elf_wizard.model_copy(
        update={"skills": {}, "completed_steps": ["concept", "race", "class", "attributes"]}
    )


def test_set_skills_accepts_class_skills(
    editor: SheetEditor, wizard_without_skills: Character
) -> None:
    result = editor.set_skills(wizard_without_skills, {"arcana": 1, "history": 1})
    assert result.character.skills == {"arcana": 1, "history": 1}
    assert "skills" in result.character.completed_steps


def test_set_skills_rejects_skill_outside_class_list(
    editor: SheetEditor, wizard_without_skills: Character
) -> None:
    with pytest.raises(RuleViolationError) as info:
        editor.set_skills(wizard_without_skills, {"arcana": 1, "sleight_of_hand": 1})
    assert codes(info) == {"skill_not_allowed"}


@pytest.mark.parametrize(
    ("skills", "expected"),
    [
        ({"arcana": 1}, {"skills_unspent"}),
        ({"arcana": 1, "history": 1, "investigation": 1}, {"skills_over_budget"}),
        ({"arcana": 1, "religion": 1}, {"skill_already_granted"}),
    ],
)
def test_set_skills_requires_exact_count(
    editor: SheetEditor,
    wizard_without_skills: Character,
    skills: dict[str, int],
    expected: set[str],
) -> None:
    with pytest.raises(RuleViolationError) as info:
        editor.set_skills(wizard_without_skills, skills)
    assert codes(info) == expected


# ----------------------------------------------------------------- cascata
def test_changing_class_reopens_skills_that_became_invalid(
    editor: SheetEditor, elf_wizard: Character
) -> None:
    result = editor.set_choice(elf_wizard, "class", "rogue")  # arcana não é de ladino

    assert result.reopened_steps == ("skills",)
    assert result.character.skills == {}
    assert "skills" not in result.character.completed_steps
    assert result.character.choices["class"] == "rogue"
    assert "attributes" in result.character.completed_steps
    assert elf_wizard.choices["class"] == "wizard"  # original intacto


def test_changing_class_reopens_skills_when_budget_changes(
    editor: SheetEditor, elf_wizard: Character
) -> None:
    choices = {**elf_wizard.choices, "class": "fighter"}
    skills = {"acrobatics": 1, "athletics": 1}  # valem para guerreiro e para ladino
    base = elf_wizard.model_copy(update={"choices": choices, "skills": skills})
    result = editor.set_choice(base, "class", "rogue")  # ladino escolhe 4, não 2
    assert result.reopened_steps == ("skills",)


def test_changing_class_keeps_skills_that_are_still_valid(
    editor: SheetEditor, elf_wizard: Character
) -> None:
    base = elf_wizard.model_copy(update={"skills": {"history": 1, "medicine": 1}})
    result = editor.set_choice(base, "class", "cleric")  # ambas valem para clérigo
    assert result.reopened_steps == ()
    assert result.character.skills == {"history": 1, "medicine": 1}


# ----------------------------------------------------------------- textos
def test_set_text_strips_and_completes_step(editor: SheetEditor) -> None:
    result = editor.set_text(new_character(), "name", "  Aelar  ")
    assert result.character.name == "Aelar"
    assert "name" in result.character.completed_steps


def test_set_text_rejects_blank_and_unknown_field(editor: SheetEditor) -> None:
    with pytest.raises(RuleViolationError) as blank:
        editor.set_text(new_character(), "name", "   ")
    assert codes(blank) == {"narrative_empty"}
    with pytest.raises(RuleViolationError) as unknown:
        editor.set_text(new_character(), "hp", "99")
    assert codes(unknown) == {"unknown_field"}


# ----------------------------------------------------------------- finalização
def test_finalize_accepts_complete_character(editor: SheetEditor, elf_wizard: Character) -> None:
    assert editor.finalize(elf_wizard) is elf_wizard


def test_finalize_rejects_incomplete_character(editor: SheetEditor) -> None:
    with pytest.raises(RuleViolationError):
        editor.finalize(new_character())


def test_building_a_sheet_step_by_step_always_ends_valid(editor: SheetEditor) -> None:
    c = new_character()
    c = editor.set_text(c, "concept", "Maga estudiosa").character
    c = editor.set_choice(c, "race", "elf").character
    c = editor.set_choice(c, "class", "wizard").character
    c = editor.set_choice(c, "antecedent", "acolyte").character
    c = editor.set_attributes(c, "standard_array", STANDARD).character
    c = editor.set_skills(c, {"arcana": 1, "investigation": 1}).character
    c = editor.set_text(c, "name", "Aelar").character
    c = editor.set_text(c, "background", "Cresceu numa biblioteca.").character

    assert editor.finalize(c) is c
