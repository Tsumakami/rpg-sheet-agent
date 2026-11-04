import random

import pytest

from rpg_agent.adapters.llm.fake import FakeLLM
from rpg_agent.application.errors import LLMOutputError, StepPreconditionError
from rpg_agent.application.step_advisor import (
    AttributesSuggestion,
    ChoiceSuggestion,
    SkillsSuggestion,
    StepAdvisor,
    TextSuggestion,
)
from rpg_agent.domain.dice import DiceRoller
from rpg_agent.domain.issues import has_errors
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack
from rpg_agent.domain.validators import validate_character

RANKING = '{"ranking": ["int", "dex", "con", "wis", "cha", "str"], "reason": "mago"}'


def advisor(fake: FakeLLM, roller: DiceRoller | None = None) -> StepAdvisor:
    return StepAdvisor(fake, roller=roller)


# ----------------------------------------------------------------- escolhas
def test_choice_suggestion(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "elf", "reason": "ágil"}'])
    result = advisor(fake).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "race")

    assert isinstance(result, ChoiceSuggestion)
    assert (result.choice_id, result.option_id, result.reason) == ("race", "elf", "ágil")
    enum = fake.schemas[0]["properties"]["choice_id"]["enum"]
    race = dnd_pack.get_choice("race")
    assert race is not None
    assert enum == [o.id for o in race.options]


def test_choice_retries_with_feedback_when_id_is_invalid(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "orc"}', '{"choice_id": "dwarf"}'])
    result = advisor(fake).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "race")

    assert isinstance(result, ChoiceSuggestion)
    assert result.option_id == "dwarf"
    assert result.report.attempts == 2
    assert "orc" in fake.calls[1][-1].content


def test_choice_fails_after_retries(dnd_pack: RulePack) -> None:
    fake = FakeLLM(["lixo", "{}", '{"choice_id": "orc"}'])
    with pytest.raises(LLMOutputError):
        advisor(fake).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "race")


def test_prompt_contains_character_state_and_user_input(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    fake = FakeLLM(['{"choice_id": "wizard"}'])
    advisor(fake).suggest(dnd_pack, elf_wizard, "class", user_input="quero um mago sombrio")
    user_prompt = fake.calls[0][1].content
    assert "mago sombrio" in user_prompt
    assert "Raça: Elfo" in user_prompt
    assert "Destreza 16" in user_prompt  # já inclui o bônus racial


# ----------------------------------------------------------------- atributos
def _validated(pack: RulePack, base: Character, result: AttributesSuggestion) -> bool:
    candidate = base.model_copy(
        update={
            "attributes": result.scores,
            "attribute_method": result.method,
            "completed_steps": ["attributes"],
        }
    )
    return not has_errors(validate_character(pack, candidate))


def test_attributes_standard_array(dnd_pack: RulePack) -> None:
    base = Character(system_id="dnd5e_srd", attribute_method="standard_array")
    result = advisor(FakeLLM([RANKING])).suggest(dnd_pack, base, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert result.scores == {"int": 15, "dex": 14, "con": 13, "wis": 12, "cha": 10, "str": 8}
    assert _validated(dnd_pack, base, result)


def test_attributes_point_buy_is_valid_per_rules(dnd_pack: RulePack) -> None:
    base = Character(system_id="dnd5e_srd", attribute_method="point_buy")
    result = advisor(FakeLLM([RANKING])).suggest(dnd_pack, base, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert _validated(dnd_pack, base, result)


def test_attributes_roll_uses_dice_not_llm(dnd_pack: RulePack) -> None:
    base = Character(system_id="dnd5e_srd", attribute_method="roll")
    roller = DiceRoller(random.Random(7))
    result = advisor(FakeLLM([RANKING]), roller=roller).suggest(dnd_pack, base, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert all(3 <= v <= 18 for v in result.scores.values())
    assert _validated(dnd_pack, base, result)


def test_attributes_ranking_must_be_a_permutation(dnd_pack: RulePack) -> None:
    bad = '{"ranking": ["int", "int", "dex", "con", "wis", "cha"]}'
    fake = FakeLLM([bad, RANKING])
    base = Character(system_id="dnd5e_srd", attribute_method="standard_array")
    result = advisor(fake).suggest(dnd_pack, base, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert result.report.attempts == 2


def test_attributes_require_method_when_pack_offers_several(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="attribute_method"):
        advisor(FakeLLM([RANKING])).suggest(
            dnd_pack, Character(system_id="dnd5e_srd"), "attributes"
        )


def test_attributes_schema_pins_ids_and_length(dnd_pack: RulePack) -> None:
    fake = FakeLLM([RANKING])
    base = Character(system_id="dnd5e_srd", attribute_method="standard_array")
    advisor(fake).suggest(dnd_pack, base, "attributes")
    ranking = fake.schemas[0]["properties"]["ranking"]
    assert ranking["minItems"] == ranking["maxItems"] == 6
    assert ranking["items"]["enum"] == ["str", "dex", "con", "int", "wis", "cha"]


# ----------------------------------------------------------------- perícias
def test_skills_suggestion(dnd_pack: RulePack, elf_wizard: Character) -> None:
    fake = FakeLLM(['{"skill_ids": ["arcana", "history"], "reason": "estudioso"}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "skills")

    assert isinstance(result, SkillsSuggestion)
    assert result.skill_ids == ["arcana", "history"]
    assert fake.schemas[0]["properties"]["skill_ids"]["minItems"] == 2


def test_skills_wrong_count_is_retried(dnd_pack: RulePack, elf_wizard: Character) -> None:
    fake = FakeLLM(['{"skill_ids": ["arcana"]}', '{"skill_ids": ["arcana", "medicine"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "skills")

    assert isinstance(result, SkillsSuggestion)
    assert result.report.attempts == 2
    assert "exatamente 2" in fake.calls[1][-1].content


def test_skills_are_limited_to_the_class_list(dnd_pack: RulePack, elf_wizard: Character) -> None:
    fake = FakeLLM(['{"skill_ids": ["arcana", "history"]}'])
    advisor(fake).suggest(dnd_pack, elf_wizard, "skills")

    enum = fake.schemas[0]["properties"]["skill_ids"]["items"]["enum"]
    # lista do mago, sem Intuição e Religião (acólito) nem Percepção (elfo)
    assert enum == ["arcana", "history", "investigation", "medicine"]
    assert "stealth" not in fake.calls[0][1].content


def test_skill_outside_class_list_is_retried(dnd_pack: RulePack, elf_wizard: Character) -> None:
    wrong = '{"skill_ids": ["arcana", "stealth"]}'
    fake = FakeLLM([wrong, '{"skill_ids": ["arcana", "medicine"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "skills")

    assert isinstance(result, SkillsSuggestion)
    assert result.report.attempts == 2
    assert "stealth" in fake.calls[1][-1].content


def test_skills_need_a_class_first(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="classe"):
        advisor(FakeLLM()).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "skills")


# ----------------------------------------------------------------- textos
def test_name_suggestions(dnd_pack: RulePack, elf_wizard: Character) -> None:
    fake = FakeLLM(['{"suggestions": ["  Aelar ", "Lyra", "Thalor"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "name")

    assert isinstance(result, TextSuggestion)
    assert result.field == "name"
    assert result.suggestions == ["Aelar", "Lyra", "Thalor"]


def test_blank_suggestions_are_retried(dnd_pack: RulePack, elf_wizard: Character) -> None:
    fake = FakeLLM(['{"suggestions": ["  "]}', '{"suggestions": ["Aelar"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "name")

    assert isinstance(result, TextSuggestion)
    assert result.report.attempts == 2


def test_too_many_suggestions_are_retried(dnd_pack: RulePack, elf_wizard: Character) -> None:
    too_many = '{"suggestions": ["Ab", "Cd", "Ef", "Gh"]}'
    fake = FakeLLM([too_many, '{"suggestions": ["Ab", "Cd"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "name")

    assert isinstance(result, TextSuggestion)
    assert result.suggestions == ["Ab", "Cd"]


def test_too_short_background_is_retried(dnd_pack: RulePack, elf_wizard: Character) -> None:
    story = "Cresceu entre pergaminhos antigos e jurou descobrir o que a biblioteca escondia. " * 2
    fake = FakeLLM(['{"suggestions": ["["]}', f'{{"suggestions": ["{story.strip()}"]}}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "background")

    assert isinstance(result, TextSuggestion)
    assert result.report.attempts == 2
    assert "pelo menos 80" in fake.calls[1][-1].content
    assert fake.schemas[0]["properties"]["suggestions"]["items"]["minLength"] == 80


# ----------------------------------------------------------------- pré-condições
def test_unknown_step(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="desconhecida"):
        advisor(FakeLLM()).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "voar")


def test_system_mismatch(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="sistema"):
        advisor(FakeLLM()).suggest(dnd_pack, Character(system_id="vampire_v5"), "race")


def test_granted_skill_is_not_offered_and_is_retried_if_chosen(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    fake = FakeLLM(['{"skill_ids": ["arcana", "insight"]}', '{"skill_ids": ["arcana", "history"]}'])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "skills")

    assert isinstance(result, SkillsSuggestion)
    assert result.report.attempts == 2
    assert "insight" not in fake.schemas[0]["properties"]["skill_ids"]["items"]["enum"]


def test_attributes_prompt_includes_class_priority(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    fake = FakeLLM([RANKING])
    advisor(fake).suggest(dnd_pack, elf_wizard, "attributes")

    prompt = fake.calls[0][1].content
    assert "Ordem recomendada" in prompt
    assert "Inteligência, Constituição, Destreza" in prompt


def test_attributes_ranking_must_keep_the_class_main_attribute_near_the_top(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    bad = '{"ranking": ["str", "cha", "wis", "dex", "con", "int"]}'
    fake = FakeLLM([bad, RANKING])
    result = advisor(fake).suggest(dnd_pack, elf_wizard, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert result.report.attempts == 2
    assert "Inteligência" in fake.calls[1][-1].content


def test_choice_options_mention_granted_skills(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "elf"}'])
    advisor(fake).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "race")
    assert "perícias concedidas: Percepção" in fake.calls[0][1].content


def test_antecedent_suggestion(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "acolyte", "reason": "religioso"}'])
    result = advisor(fake).suggest(dnd_pack, Character(system_id="dnd5e_srd"), "antecedent")

    assert isinstance(result, ChoiceSuggestion)
    assert result.option_id == "acolyte"
    assert "Intuição, Religião" in fake.calls[0][1].content


# ----------------------------------------------------------------- sugestão padrão (sem LLM)
def test_default_choice_picks_the_first_option_in_pack_order(dnd_pack: RulePack) -> None:
    race = dnd_pack.get_choice("race")
    assert race is not None
    fake = FakeLLM()  # não deve ser chamado
    result = advisor(fake).default_suggestion(dnd_pack, Character(system_id="dnd5e_srd"), "race")

    assert isinstance(result, ChoiceSuggestion)
    assert result.option_id == race.options[0].id
    assert result.report.attempts == 0
    assert fake.calls == []


def test_default_attributes_uses_the_chosen_class_priority(dnd_pack: RulePack) -> None:
    character = Character(
        system_id="dnd5e_srd", attribute_method="standard_array", choices={"class": "wizard"}
    )
    result = advisor(FakeLLM()).default_suggestion(dnd_pack, character, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert result.ranking == ["int", "con", "dex", "wis", "cha", "str"]
    assert result.scores == {"int": 15, "con": 14, "dex": 13, "wis": 12, "cha": 10, "str": 8}
    assert result.report.attempts == 0


def test_default_attributes_falls_back_to_pack_order_without_a_class(dnd_pack: RulePack) -> None:
    character = Character(system_id="dnd5e_srd", attribute_method="standard_array")
    result = advisor(FakeLLM()).default_suggestion(dnd_pack, character, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert result.ranking == dnd_pack.attribute_ids()


def test_default_attributes_uses_dice_for_the_roll_method(dnd_pack: RulePack) -> None:
    character = Character(system_id="dnd5e_srd", attribute_method="roll")
    roller = DiceRoller(random.Random(7))
    result = advisor(FakeLLM(), roller=roller).default_suggestion(dnd_pack, character, "attributes")

    assert isinstance(result, AttributesSuggestion)
    assert _validated(dnd_pack, character, result)


def test_default_attributes_is_none_without_a_chosen_method(dnd_pack: RulePack) -> None:
    character = Character(system_id="dnd5e_srd")  # pack tem 3 métodos; nenhum escolhido
    result = advisor(FakeLLM()).default_suggestion(dnd_pack, character, "attributes")
    assert result is None


def test_default_suggestion_is_none_for_skills_and_narrative_steps(
    dnd_pack: RulePack, elf_wizard: Character
) -> None:
    advisor_ = advisor(FakeLLM())
    assert advisor_.default_suggestion(dnd_pack, elf_wizard, "skills") is None
    assert advisor_.default_suggestion(dnd_pack, elf_wizard, "name") is None
    assert advisor_.default_suggestion(dnd_pack, elf_wizard, "background") is None


def test_default_suggestion_unknown_step_raises(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="desconhecida"):
        advisor(FakeLLM()).default_suggestion(dnd_pack, Character(system_id="dnd5e_srd"), "voar")


def test_default_suggestion_system_mismatch_raises(dnd_pack: RulePack) -> None:
    with pytest.raises(StepPreconditionError, match="sistema"):
        advisor(FakeLLM()).default_suggestion(dnd_pack, Character(system_id="vampire_v5"), "race")
