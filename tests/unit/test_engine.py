from rpg_agent.domain.engine import compute_sheet
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack


def test_computes_elf_wizard(dnd_pack: RulePack, elf_wizard: Character) -> None:
    sheet = compute_sheet(dnd_pack, elf_wizard)

    assert sheet.final_attributes["dex"] == 16  # 14 base + 2 do elfo
    assert sheet.derived["dex_mod"] == 3
    assert sheet.derived["str_mod"] == -1
    assert sheet.derived["con_mod"] == 1
    assert sheet.derived["hit_points"] == 7  # d6 + mod. CON
    assert sheet.derived["armor_class"] == 13
    assert sheet.derived["initiative"] == 3
    assert sheet.derived["speed"] == 30
    assert sheet.derived["proficiency_bonus"] == 2
    assert sheet.skill_budget == 2
    assert sheet.pending == ()


def test_human_gets_bonus_on_every_attribute(dnd_pack: RulePack) -> None:
    c = Character(
        system_id="dnd5e_srd",
        attributes={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        choices={"race": "human"},
    )
    assert set(compute_sheet(dnd_pack, c).final_attributes.values()) == {11}


def test_incomplete_character_marks_pending(dnd_pack: RulePack) -> None:
    c = Character(
        system_id="dnd5e_srd",
        attributes={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
    )
    sheet = compute_sheet(dnd_pack, c)

    assert sheet.derived["con_mod"] == 0
    assert "hit_points" in sheet.pending  # falta escolher a classe
    assert "speed" in sheet.pending  # falta escolher a raça
    assert sheet.skill_budget is None


def test_empty_character_does_not_crash(dnd_pack: RulePack) -> None:
    sheet = compute_sheet(dnd_pack, Character(system_id="dnd5e_srd"))
    assert sheet.final_attributes == {}
    assert "str_mod" in sheet.pending


def test_invalid_choice_is_ignored_by_engine(dnd_pack: RulePack, elf_wizard: Character) -> None:
    c = elf_wizard.model_copy(update={"choices": {"race": "orc", "class": "wizard"}})
    sheet = compute_sheet(dnd_pack, c)
    assert sheet.final_attributes["dex"] == 14  # sem bônus racial
    assert "speed" in sheet.pending


def test_allowed_skills_follow_the_class(dnd_pack: RulePack, elf_wizard: Character) -> None:
    sheet = compute_sheet(dnd_pack, elf_wizard)
    # lista do mago, sem as perícias que o elfo e o acólito já concedem
    assert sheet.allowed_skills == ("arcana", "history", "investigation", "medicine")


def test_all_skills_are_allowed_before_a_class_is_chosen(dnd_pack: RulePack) -> None:
    sheet = compute_sheet(dnd_pack, Character(system_id="dnd5e_srd"))
    assert sheet.allowed_skills == tuple(dnd_pack.skill_ids())


def test_granted_and_proficient_skills(dnd_pack: RulePack, elf_wizard: Character) -> None:
    sheet = compute_sheet(dnd_pack, elf_wizard)
    assert sheet.granted_skills == ("insight", "perception", "religion")
    assert sheet.proficient_skills == ("arcana", "history", "insight", "perception", "religion")


def test_saving_throws_add_proficiency_for_class_attributes(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    sheet = compute_sheet(dnd_pack, elf_wizard)
    assert sheet.grants == {"saving_throws": ("int", "wis")}
    saves = {a: sheet.derived[f"{a}_save"] for a in dnd_pack.attribute_ids()}
    assert saves == {"str": -1, "dex": 3, "con": 1, "int": 4, "wis": 3, "cha": 0}


def test_saving_throws_change_with_the_class(dnd_pack: RulePack, elf_wizard: Character) -> None:
    rogue = elf_wizard.model_copy(update={"choices": {**elf_wizard.choices, "class": "rogue"}})
    sheet = compute_sheet(dnd_pack, rogue)
    assert sheet.derived["dex_save"] == 5  # mod. +3 e proficiência +2
    assert sheet.derived["int_save"] == 4
    assert sheet.derived["wis_save"] == 1  # sem proficiência


def test_skill_modifiers(dnd_pack: RulePack, elf_wizard: Character) -> None:
    mods = compute_sheet(dnd_pack, elf_wizard).skill_modifiers
    assert mods["arcana"] == 4  # mod. INT +2, proficiente +2
    assert mods["perception"] == 3  # mod. SAB +1, proficiente (elfo) +2
    assert mods["religion"] == 4  # proficiente (antecedente)
    assert mods["stealth"] == 3  # só o mod. DES, sem proficiência
    assert mods["athletics"] == -1
    assert len(mods) == 18


def test_priority_attributes_come_from_the_class(dnd_pack: RulePack, elf_wizard: Character) -> None:
    sheet = compute_sheet(dnd_pack, elf_wizard)
    assert sheet.priority_attributes == ("int", "con", "dex", "wis", "cha", "str")
    assert compute_sheet(dnd_pack, Character(system_id="dnd5e_srd")).priority_attributes == ()


def test_sheet_without_attributes_has_no_saves_or_skill_modifiers(dnd_pack: RulePack) -> None:
    sheet = compute_sheet(dnd_pack, Character(system_id="dnd5e_srd"))
    assert sheet.skill_modifiers == {}
    assert "str_save" in sheet.pending
