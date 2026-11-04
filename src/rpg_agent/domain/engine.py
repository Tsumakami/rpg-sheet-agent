"""Motor de regras: calcula valores finais e derivados a partir do Rule Pack."""

from collections.abc import Sequence
from dataclasses import dataclass

from rpg_agent.domain.expressions import Number, UnknownNameError, evaluate
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import OptionDef, RulePack, is_number

Chosen = list[tuple[str, OptionDef]]


@dataclass(frozen=True)
class ComputedSheet:
    final_attributes: dict[str, int]  # base + bônus de escolhas (raça etc.)
    derived: dict[str, Number]
    pending: tuple[str, ...]  # derivados que ainda não dá para calcular (ficha incompleta)
    skill_budget: int | None  # quantas perícias o jogador ainda escolhe
    allowed_skills: tuple[str, ...]  # perícias que o jogador pode ESCOLHER agora
    granted_skills: tuple[str, ...]  # perícias concedidas por raça, antecedente etc.
    proficient_skills: tuple[str, ...]  # concedidas + escolhidas
    skill_modifiers: dict[str, Number]  # bônus final de cada perícia calculável
    grants: dict[str, tuple[str, ...]]  # listas concedidas por grupo (ex.: salvaguardas)
    priority_attributes: tuple[str, ...]  # ordem recomendada de atributos (vazio = sem dica)


def _normalize(value: Number) -> Number:
    return int(value) if float(value).is_integer() else value


def _chosen_options(pack: RulePack, character: Character) -> Chosen:
    chosen: Chosen = []
    for choice_id, option_id in character.choices.items():
        option = pack.get_option(choice_id, option_id)
        if option is not None:  # opções inválidas são problema do validador, não do motor
            chosen.append((choice_id, option))
    return chosen


def _granted_skills(pack: RulePack, chosen: Chosen) -> tuple[str, ...]:
    granted = {skill for _, option in chosen for skill in option.granted_skills}
    return tuple(s for s in pack.skill_ids() if s in granted)


def _allowed_skills(pack: RulePack, chosen: Chosen, granted: Sequence[str]) -> tuple[str, ...]:
    allowed: set[str] | None = None
    for _, option in chosen:
        if option.allowed_skills is not None:
            restriction = set(option.allowed_skills)
            allowed = restriction if allowed is None else allowed & restriction
    return tuple(
        s for s in pack.skill_ids() if (allowed is None or s in allowed) and s not in granted
    )


def _grants(chosen: Chosen) -> dict[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {}
    for _, option in chosen:
        for group, ids in option.grants.items():
            bucket = merged.setdefault(group, [])
            bucket.extend(i for i in ids if i not in bucket)
    return {group: tuple(ids) for group, ids in merged.items()}


def _priority(chosen: Chosen) -> tuple[str, ...]:
    for _, option in chosen:
        if option.priority_attributes:
            return tuple(option.priority_attributes)
    return ()


def _attribute_context(
    env: dict[str, Number], attr: str, value: int, done: Sequence[str]
) -> dict[str, Number]:
    """Variáveis da fórmula de um atributo: `value` e derivados já calculados, sem prefixo."""
    context: dict[str, Number] = {**env, "value": value}
    for derived_id in done:
        key = f"{attr}_{derived_id}"
        if key in env:
            context[derived_id] = env[key]
    return context


def compute_sheet(pack: RulePack, character: Character) -> ComputedSheet:
    chosen = _chosen_options(pack, character)
    bonuses: dict[str, int] = {}
    env: dict[str, Number] = {}

    for choice_id, option in chosen:
        for attr, bonus in option.attribute_bonuses.items():
            bonuses[attr] = bonuses.get(attr, 0) + bonus
        for key, value in option.data.items():
            if is_number(value):
                env[f"{choice_id}_{key}"] = value

    final = {
        a: character.attributes[a] + bonuses.get(a, 0)
        for a in pack.attribute_ids()
        if a in character.attributes
    }
    env.update(final)

    grants = _grants(chosen)
    derived: dict[str, Number] = {}
    pending: list[str] = []
    per_attribute_done: list[str] = []

    for d in pack.derived:
        if d.per_attribute:
            flagged = set(grants.get(d.flag_from, ())) if d.flag_from else set()
            for attr in pack.attribute_ids():
                name = f"{attr}_{d.id}"
                if attr not in final:
                    pending.append(name)
                    continue
                context = _attribute_context(env, attr, final[attr], per_attribute_done)
                if d.flag_from is not None:
                    context["granted"] = 1 if attr in flagged else 0
                try:
                    result = _normalize(evaluate(d.formula, context))
                except UnknownNameError:
                    pending.append(name)
                    continue
                env[name] = derived[name] = result
            per_attribute_done.append(d.id)
        else:
            try:
                result = _normalize(evaluate(d.formula, env))
            except UnknownNameError:
                pending.append(d.id)
                continue
            env[d.id] = derived[d.id] = result

    budget: int | None = None
    if pack.skill_budget is not None:
        try:
            budget = int(evaluate(pack.skill_budget, env))
        except UnknownNameError:
            budget = None

    granted = _granted_skills(pack, chosen)
    known_skills = set(pack.skill_ids())
    chosen_skills = {s for s, v in character.skills.items() if v > 0 and s in known_skills}
    proficient = {*granted, *chosen_skills}

    skill_modifiers: dict[str, Number] = {}
    if pack.skill_modifier is not None:
        for skill in pack.skills:
            if skill.attribute is None or skill.attribute not in final:
                continue
            attr = skill.attribute
            context = _attribute_context(env, attr, final[attr], per_attribute_done)
            context["proficient"] = 1 if skill.id in proficient else 0
            try:
                skill_modifiers[skill.id] = _normalize(evaluate(pack.skill_modifier, context))
            except UnknownNameError:
                continue

    return ComputedSheet(
        final_attributes=final,
        derived=derived,
        pending=tuple(pending),
        skill_budget=budget,
        allowed_skills=_allowed_skills(pack, chosen, granted),
        granted_skills=granted,
        proficient_skills=tuple(s for s in pack.skill_ids() if s in proficient),
        skill_modifiers=skill_modifiers,
        grants=grants,
        priority_attributes=_priority(chosen),
    )
