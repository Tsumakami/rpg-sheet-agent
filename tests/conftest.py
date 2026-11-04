from pathlib import Path

import pytest

from rpg_agent.adapters.rules.yaml_loader import YamlRulePackLoader
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack

RULE_PACKS_DIR = Path(__file__).resolve().parents[1] / "rule_packs"


@pytest.fixture(scope="session")
def dnd_pack() -> RulePack:
    return YamlRulePackLoader(RULE_PACKS_DIR).load("dnd5e_srd")


@pytest.fixture
def elf_wizard() -> Character:
    """Ficha completa e válida (matriz padrão de atributos)."""
    return Character(
        system_id="dnd5e_srd",
        name="Aelar",
        concept="Maga estudiosa que busca conhecimento proibido",
        background="Cresceu numa biblioteca élfica.",
        attributes={"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10},
        attribute_method="standard_array",
        skills={"arcana": 1, "history": 1},
        choices={"race": "elf", "class": "wizard", "antecedent": "acolyte"},
        completed_steps=[
            "concept",
            "race",
            "class",
            "antecedent",
            "attributes",
            "skills",
            "name",
            "background",
        ],
    )
