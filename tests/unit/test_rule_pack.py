import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rpg_agent.adapters.rules.yaml_loader import YamlRulePackLoader
from rpg_agent.domain.rule_system import RulePack
from tests.conftest import RULE_PACKS_DIR


@pytest.fixture
def raw() -> dict[str, Any]:
    loader = YamlRulePackLoader(Path(RULE_PACKS_DIR))
    return copy.deepcopy(loader.load_raw("dnd5e_srd"))


def test_dnd_pack_is_valid(dnd_pack: RulePack) -> None:
    assert dnd_pack.id == "dnd5e_srd"
    assert dnd_pack.attribute_ids() == ["str", "dex", "con", "int", "wis", "cha"]
    assert len(dnd_pack.skills) == 18
    assert dnd_pack.get_option("class", "wizard") is not None
    assert dnd_pack.get_option("class", "nope") is None
    assert dnd_pack.get_attribute_rule("point_buy") is not None


def test_unknown_field_is_rejected(raw: dict[str, Any]) -> None:
    raw["atributes"] = []
    with pytest.raises(ValidationError):
        RulePack.model_validate(raw)


def test_formula_with_unknown_variable(raw: dict[str, Any]) -> None:
    raw["derived"].append({"id": "bad", "name": "Ruim", "formula": "foo + 1"})
    with pytest.raises(ValidationError, match="variáveis desconhecidas"):
        RulePack.model_validate(raw)


def test_malicious_formula_is_rejected(raw: dict[str, Any]) -> None:
    raw["derived"].append({"id": "bad", "name": "Ruim", "formula": "__import__('os').system('x')"})
    with pytest.raises(ValidationError):
        RulePack.model_validate(raw)


def test_duplicate_attribute(raw: dict[str, Any]) -> None:
    raw["attributes"].append({"id": "str", "name": "Outra Força"})
    with pytest.raises(ValidationError, match="duplicado"):
        RulePack.model_validate(raw)


def test_step_with_unknown_choice(raw: dict[str, Any]) -> None:
    raw["steps"].append({"id": "x", "title": "X", "kind": "choice", "target": "nope"})
    with pytest.raises(ValidationError, match="escolha inexistente"):
        RulePack.model_validate(raw)


def test_point_buy_requires_costs_for_whole_range(raw: dict[str, Any]) -> None:
    del raw["attribute_rules"][0]["costs"][10]
    with pytest.raises(ValidationError, match="faltam custos"):
        RulePack.model_validate(raw)


def test_bonus_for_unknown_attribute(raw: dict[str, Any]) -> None:
    raw["choices"][0]["options"][0]["attribute_bonuses"] = {"luck": 1}
    with pytest.raises(ValidationError, match="atributo inexistente"):
        RulePack.model_validate(raw)


def test_options_must_share_numeric_fields(raw: dict[str, Any]) -> None:
    raw["choices"][1]["options"][0]["data"] = {"hit_die": 10}  # falta skill_choices
    with pytest.raises(ValidationError, match="faltam campos numéricos"):
        RulePack.model_validate(raw)


def test_allowed_skills_must_exist(raw: dict[str, Any]) -> None:
    raw["choices"][1]["options"][0]["allowed_skills"] = ["juggling"]
    with pytest.raises(ValidationError, match="perícias inexistentes"):
        RulePack.model_validate(raw)


def test_granted_skills_must_exist(raw: dict[str, Any]) -> None:
    raw["choices"][0]["options"][0]["granted_skills"] = ["juggling"]
    with pytest.raises(ValidationError, match="perícias inexistentes"):
        RulePack.model_validate(raw)


def test_priority_attributes_must_exist(raw: dict[str, Any]) -> None:
    raw["choices"][1]["options"][0]["priority_attributes"] = ["luck"]
    with pytest.raises(ValidationError, match="priority_attributes"):
        RulePack.model_validate(raw)


def test_flag_from_must_be_granted_by_some_option(raw: dict[str, Any]) -> None:
    save = next(d for d in raw["derived"] if d["id"] == "save")
    save["flag_from"] = "nothing"
    with pytest.raises(ValidationError, match="nenhuma opção concede"):
        RulePack.model_validate(raw)


def test_flag_group_must_grant_existing_attributes(raw: dict[str, Any]) -> None:
    raw["choices"][1]["options"][0]["grants"] = {"saving_throws": ["luck"]}
    with pytest.raises(ValidationError, match="atributos inexistentes"):
        RulePack.model_validate(raw)


def test_flag_from_requires_per_attribute(raw: dict[str, Any]) -> None:
    raw["derived"].append({"id": "x", "name": "X", "formula": "1", "flag_from": "saving_throws"})
    with pytest.raises(ValidationError, match="flag_from exige per_attribute"):
        RulePack.model_validate(raw)


def test_skill_modifier_unknown_variable(raw: dict[str, Any]) -> None:
    raw["skill_modifier"] = "foo + 1"
    with pytest.raises(ValidationError, match="skill_modifier usa variáveis desconhecidas"):
        RulePack.model_validate(raw)


def test_dnd_pack_has_the_srd_antecedent(dnd_pack: RulePack) -> None:
    option = dnd_pack.get_option("antecedent", "acolyte")
    assert option is not None
    assert option.granted_skills == ["insight", "religion"]
