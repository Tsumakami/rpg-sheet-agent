import pytest

from rpg_agent.adapters.llm.fake import FakeLLM
from rpg_agent.application.errors import ChoiceNotFoundError, StepPreconditionError
from rpg_agent.application.session import (
    CharacterCreationSession,
    FallbackSuggestion,
    match_option,
)
from rpg_agent.application.step_advisor import ChoiceSuggestion
from rpg_agent.application.structured import GenerationReport
from rpg_agent.domain.editor import RuleViolationError
from rpg_agent.domain.rule_system import ChoiceDef, OptionDef, RulePack

REPORT = GenerationReport(attempts=1, latency_s=0.0, prompt_tokens=0, completion_tokens=0)
STANDARD = {"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10}


def session(dnd_pack: RulePack, fake: FakeLLM | None = None) -> CharacterCreationSession:
    return CharacterCreationSession(dnd_pack, fake or FakeLLM())


def step_ids(dnd_pack: RulePack) -> list[str]:
    return [s.id for s in dnd_pack.steps]


# ----------------------------------------------------------------- casamento de texto
def _choice(*options: tuple[str, str]) -> ChoiceDef:
    return ChoiceDef(id="race", name="Raça", options=[OptionDef(id=i, name=n) for i, n in options])


def test_match_option_by_exact_id_or_name() -> None:
    choice = _choice(("elf", "Elfo"), ("dwarf", "Anão"))
    assert match_option(choice, "elf") == "elf"
    assert match_option(choice, "Elfo") == "elf"


def test_match_option_is_case_and_accent_insensitive() -> None:
    choice = _choice(("elf", "Elfo"), ("dwarf", "Anão"))
    assert match_option(choice, "ANAO") == "dwarf"
    assert match_option(choice, "anão") == "dwarf"


def test_match_option_by_unique_substring() -> None:
    choice = _choice(("elf", "Elfo"), ("dwarf", "Anão"))
    assert match_option(choice, "an") == "dwarf"


def test_match_option_raises_when_not_found() -> None:
    choice = _choice(("elf", "Elfo"), ("dwarf", "Anão"))
    with pytest.raises(ChoiceNotFoundError):
        match_option(choice, "orc")


def test_match_option_raises_when_ambiguous() -> None:
    choice = _choice(("elf_north", "Elfo do Norte"), ("elf_south", "Elfo do Sul"))
    # "elfo" não bate EXATO com nenhum dos dois nomes, só é substring dos dois
    with pytest.raises(ChoiceNotFoundError):
        match_option(choice, "elfo")


def test_match_option_exact_name_wins_over_a_substring_of_another_option() -> None:
    choice = _choice(("elf", "Elfo"), ("elf2", "Elfo do Mar"))
    # "Elfo" bate EXATO com a primeira opção, mesmo sendo também substring da segunda
    assert match_option(choice, "elfo") == "elf"


def test_match_option_rejects_blank_text() -> None:
    choice = _choice(("elf", "Elfo"))
    with pytest.raises(ChoiceNotFoundError):
        match_option(choice, "   ")


# ----------------------------------------------------------------- fluxo completo
def test_full_session_builds_a_valid_character(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    assert s.current_step is not None and s.current_step.id == "concept"
    s.set_text("uma maga estudiosa que busca conhecimento proibido")

    assert s.current_step is not None and s.current_step.id == "race"
    s.choose("Elfo")
    assert s.character.choices["race"] == "elf"

    s.choose("Mago")
    assert s.character.choices["class"] == "wizard"

    s.choose("Acólito")
    assert s.character.choices["antecedent"] == "acolyte"

    s.set_attributes("standard_array", STANDARD)
    s.set_skills(["arcana", "history"])
    s.set_text("Aelar")
    s.set_text("Cresceu entre pergaminhos antigos numa biblioteca élfica.")

    assert s.is_finished
    character = s.finalize()
    assert character.name == "Aelar"
    assert s.missing_steps() == []


def test_accepting_llm_suggestions_also_advances(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "elf", "reason": "ágil"}'])
    s = session(dnd_pack, fake)
    s.set_text("uma maga")  # concept

    suggestion = s.suggest()
    assert isinstance(suggestion, ChoiceSuggestion)
    result = s.accept(suggestion)

    assert result.character.choices["race"] == "elf"
    assert s.current_step is not None and s.current_step.id == "class"


def test_accept_invalid_suggestion_raises_and_does_not_advance(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")
    bad = ChoiceSuggestion("race", "race", "orc", "", REPORT)

    with pytest.raises(RuleViolationError):
        s.accept(bad)
    assert s.current_step is not None and s.current_step.id == "race"
    assert s.character.choices == {}


# ----------------------------------------------------------------- pular etapas
def test_skip_moves_on_without_calling_the_llm(dnd_pack: RulePack) -> None:
    fake = FakeLLM()  # roteiro vazio: qualquer chamada ao LLM levantaria erro
    s = session(dnd_pack, fake)
    s.skip()
    assert s.current_step is not None and s.current_step.id == "race"
    assert fake.calls == []


def test_skip_works_on_required_steps_but_blocks_finalize(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    for _ in step_ids(dnd_pack):
        s.skip()
    assert s.is_finished

    with pytest.raises(RuleViolationError):
        s.finalize()

    missing = {step.id for step in s.missing_steps()}
    # "skills" só aparece como pendente depois que uma classe é escolhida, já que o limite
    # de perícias (skill_budget) depende dela; até lá, o motor não tem como saber o limite.
    assert missing == set(step_ids(dnd_pack)) - {"skills"}


def test_skills_only_shows_as_missing_once_a_class_is_chosen(dnd_pack: RulePack) -> None:
    """O limite de perícias depende da classe; sem classe, o motor não sabe se falta algo."""
    s = session(dnd_pack)
    for _ in step_ids(dnd_pack):
        s.skip()
    assert "skills" not in {step.id for step in s.missing_steps()}

    s2 = session(dnd_pack)
    s2.skip()  # concept
    s2.skip()  # race
    s2.choose("Mago")  # class
    for _ in range(len(step_ids(dnd_pack)) - 3):
        s2.skip()
    assert "skills" in {step.id for step in s2.missing_steps()}


def test_missing_steps_narrows_down_as_the_player_fills_things_in(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")  # concept
    s.choose("Elfo")  # race
    for _ in range(len(step_ids(dnd_pack)) - 2):
        s.skip()

    missing = {step.id for step in s.missing_steps()}
    assert "concept" not in missing
    assert "race" not in missing
    assert "class" in missing
    assert "attributes" in missing


def test_cannot_act_after_all_steps_are_done(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    for _ in step_ids(dnd_pack):
        s.skip()
    with pytest.raises(StepPreconditionError):
        s.skip()
    with pytest.raises(StepPreconditionError):
        s.suggest()


# ----------------------------------------------------------------- desfazer / refazer
def test_undo_reverts_the_last_action(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")
    assert s.current_step is not None and s.current_step.id == "race"

    s.undo()
    assert s.current_step is not None and s.current_step.id == "concept"
    assert s.character.concept == ""


def test_redo_reapplies_the_undone_action(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")
    s.undo()
    s.redo()
    assert s.character.concept == "uma maga"
    assert s.current_step is not None and s.current_step.id == "race"


def test_new_action_clears_the_redo_stack(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")
    s.undo()
    s.set_text("um guerreiro")  # ação nova no lugar da desfeita

    assert not s.can_redo
    with pytest.raises(StepPreconditionError):
        s.redo()
    assert s.character.concept == "um guerreiro"


def test_undo_also_reverts_a_skip(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.skip()
    assert s.current_step is not None and s.current_step.id == "race"
    s.undo()
    assert s.current_step is not None and s.current_step.id == "concept"


def test_cannot_undo_at_the_start_or_redo_without_an_undo(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    assert not s.can_undo
    with pytest.raises(StepPreconditionError):
        s.undo()
    with pytest.raises(StepPreconditionError):
        s.redo()


# ----------------------------------------------------------------- precondições por tipo de etapa
def test_choose_fails_on_a_non_choice_step(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    with pytest.raises(StepPreconditionError):
        s.choose("qualquer coisa")  # etapa atual é "concept" (narrative)


def test_set_text_fails_on_a_non_narrative_step(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    s.set_text("uma maga")
    with pytest.raises(StepPreconditionError):
        s.set_text("Elfo")  # etapa atual é "race" (choice)


def test_set_attributes_fails_outside_the_attributes_step(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    with pytest.raises(StepPreconditionError):
        s.set_attributes("standard_array", STANDARD)


def test_set_skills_fails_outside_the_skills_step(dnd_pack: RulePack) -> None:
    s = session(dnd_pack)
    with pytest.raises(StepPreconditionError):
        s.set_skills(["arcana"])


# ----------------------------------------------------------------- fallback quando o LLM falha
def test_suggest_or_fallback_passes_through_on_success(dnd_pack: RulePack) -> None:
    fake = FakeLLM(['{"choice_id": "elf"}'])
    s = session(dnd_pack, fake)
    s.set_text("uma maga")  # concept

    result = s.suggest_or_fallback()
    assert isinstance(result, ChoiceSuggestion)
    assert len(fake.calls) == 1


def test_fallback_on_a_choice_step_has_a_working_default(dnd_pack: RulePack) -> None:
    race = dnd_pack.get_choice("race")
    assert race is not None
    fake = FakeLLM(["lixo", "lixo", "lixo"])
    s = session(dnd_pack, fake)
    s.set_text("uma maga")

    result = s.suggest_or_fallback()
    assert isinstance(result, FallbackSuggestion)
    assert result.step_id == "race"
    assert result.attempts == 3
    assert result.problems != ()
    assert result.default is not None
    assert result.default.option_id == race.options[0].id
    assert s.current_step is not None and s.current_step.id == "race"  # não avançou sozinho

    s.accept(result.default)
    assert s.character.choices["race"] == race.options[0].id
    assert s.current_step is not None and s.current_step.id == "class"


def test_fallback_without_a_default_falls_back_to_manual_choice(dnd_pack: RulePack) -> None:
    fake = FakeLLM(["lixo", "lixo", "lixo"])
    s = session(dnd_pack, fake)

    result = s.suggest_or_fallback()  # etapa "concept": sem padrão possível
    assert isinstance(result, FallbackSuggestion)
    assert result.default is None

    s.set_text("uma maga estudiosa")
    assert s.character.concept == "uma maga estudiosa"
    assert s.current_step is not None and s.current_step.id == "race"


def test_fallback_on_skills_has_no_default_but_manual_completes_it(dnd_pack: RulePack) -> None:
    fake = FakeLLM(["lixo", "lixo", "lixo"])
    s = session(dnd_pack, fake)
    s.set_text("uma maga")
    s.choose("Elfo")
    s.choose("Mago")
    s.choose("Acólito")
    s.set_attributes("standard_array", STANDARD)

    result = s.suggest_or_fallback()
    assert isinstance(result, FallbackSuggestion)
    assert result.step_id == "skills"
    assert result.default is None

    s.set_skills(["arcana", "history"])
    assert s.current_step is not None and s.current_step.id == "name"
