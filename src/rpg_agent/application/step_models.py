"""Formatos de saída que o LLM deve produzir em cada etapa, e seus JSON Schemas.

Os schemas são restringidos com os ids reais do Rule Pack (enum, minItems...), para que
o modelo pequeno só consiga escolher valores existentes.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field


class ChoiceProposal(BaseModel):
    choice_id: str
    reason: str = ""


class RankingProposal(BaseModel):
    ranking: list[str]
    reason: str = ""


class SkillsProposal(BaseModel):
    skill_ids: list[str]
    reason: str = ""


class TextProposal(BaseModel):
    suggestions: list[str] = Field(min_length=1, max_length=5)


def choice_schema(option_ids: Sequence[str]) -> dict[str, Any]:
    schema = ChoiceProposal.model_json_schema()
    schema["properties"]["choice_id"]["enum"] = list(option_ids)
    return schema


def ranking_schema(attribute_ids: Sequence[str]) -> dict[str, Any]:
    schema = RankingProposal.model_json_schema()
    schema["properties"]["ranking"].update(
        {
            "items": {"type": "string", "enum": list(attribute_ids)},
            "minItems": len(attribute_ids),
            "maxItems": len(attribute_ids),
            "uniqueItems": True,
        }
    )
    return schema


def skills_schema(skill_ids: Sequence[str], count: int) -> dict[str, Any]:
    schema = SkillsProposal.model_json_schema()
    schema["properties"]["skill_ids"].update(
        {
            "items": {"type": "string", "enum": list(skill_ids)},
            "minItems": count,
            "maxItems": count,
            "uniqueItems": True,
        }
    )
    return schema


def text_schema(max_items: int, min_chars: int) -> dict[str, Any]:
    schema = TextProposal.model_json_schema()
    schema["properties"]["suggestions"].update(
        {
            "items": {"type": "string", "minLength": min_chars},
            "maxItems": max_items,
        }
    )
    return schema
