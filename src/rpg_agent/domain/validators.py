"""Validação de uma ficha contra um Rule Pack.

Fichas parciais são suportadas: só as etapas listadas em `completed_steps` são
verificadas a fundo. Com `require_complete=True`, todas as etapas são exigidas.
"""

from rpg_agent.domain.allocation import check_allocation
from rpg_agent.domain.engine import compute_sheet
from rpg_agent.domain.issues import Issue
from rpg_agent.domain.models.character import Character
from rpg_agent.domain.rule_system import RulePack


def validate_character(
    pack: RulePack,
    character: Character,
    *,
    require_complete: bool = False,
) -> list[Issue]:
    if character.system_id != pack.id:
        return [
            Issue(
                "system_mismatch",
                f"Ficha do sistema {character.system_id!r}, mas o pack é {pack.id!r}.",
                "system_id",
            )
        ]

    issues: list[Issue] = []
    known = {s.id for s in pack.steps}
    for step_id in character.completed_steps:
        if step_id not in known:
            issues.append(
                Issue("unknown_step", f"Etapa desconhecida: {step_id!r}.", "completed_steps")
            )

    checked = known if require_complete else {s for s in character.completed_steps if s in known}

    issues += _check_attributes(pack, character, checked)
    issues += _check_choices(pack, character, checked)
    issues += _check_skills(pack, character, checked)
    if require_complete:
        issues += _check_narrative(pack, character)
    return issues


def _check_attributes(pack: RulePack, character: Character, checked: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    ids = set(pack.attribute_ids())
    for key in character.attributes:
        if key not in ids:
            issues.append(
                Issue("unknown_attribute", f"Atributo desconhecido: {key!r}.", f"attributes.{key}")
            )

    if not any(s.kind == "attributes" and s.id in checked for s in pack.steps):
        return issues

    method = character.attribute_method
    if method is None:
        if len(pack.attribute_rules) != 1:
            methods = [r.method for r in pack.attribute_rules]
            issues.append(
                Issue(
                    "attribute_method_missing",
                    f"Informe o método de atributos: {methods}.",
                    "attribute_method",
                )
            )
            return issues
        rule = pack.attribute_rules[0]
    else:
        found = pack.get_attribute_rule(method)
        if found is None:
            issues.append(
                Issue(
                    "invalid_attribute_method",
                    f"Método não permitido: {method!r}.",
                    "attribute_method",
                )
            )
            return issues
        rule = found

    issues += check_allocation(rule, character.attributes, pack.attribute_ids())
    return issues


def _check_choices(pack: RulePack, character: Character, checked: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    for choice_id, option_id in character.choices.items():
        choice = pack.get_choice(choice_id)
        if choice is None:
            issues.append(
                Issue(
                    "unknown_choice",
                    f"Escolha desconhecida: {choice_id!r}.",
                    f"choices.{choice_id}",
                )
            )
        elif pack.get_option(choice_id, option_id) is None:
            valid = [o.id for o in choice.options]
            issues.append(
                Issue(
                    "invalid_option",
                    f"Opção {option_id!r} inválida para {choice_id!r}. Válidas: {valid}.",
                    f"choices.{choice_id}",
                )
            )

    for step in pack.steps:
        if step.kind != "choice" or step.id not in checked or step.target is None:
            continue
        choice = pack.get_choice(step.target)
        if choice is not None and choice.required and step.target not in character.choices:
            issues.append(
                Issue(
                    "choice_missing",
                    f"Escolha obrigatória não feita: {step.target!r}.",
                    f"choices.{step.target}",
                )
            )
    return issues


def _check_skills(pack: RulePack, character: Character, checked: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    ids = set(pack.skill_ids())
    sheet = compute_sheet(pack, character)
    for skill_id, value in character.skills.items():
        if skill_id not in ids:
            issues.append(
                Issue("unknown_skill", f"Perícia desconhecida: {skill_id!r}.", f"skills.{skill_id}")
            )
        elif not pack.skill_min <= value <= pack.skill_max:
            issues.append(
                Issue(
                    "skill_out_of_range",
                    f"{skill_id}={value} fora do intervalo {pack.skill_min}-{pack.skill_max}.",
                    f"skills.{skill_id}",
                )
            )
        elif value > 0 and skill_id in sheet.granted_skills:
            issues.append(
                Issue(
                    "skill_already_granted",
                    f"A perícia {skill_id!r} já é concedida por outra escolha. Escolha outra.",
                    f"skills.{skill_id}",
                )
            )
        elif value > 0 and skill_id not in sheet.allowed_skills:
            issues.append(
                Issue(
                    "skill_not_allowed",
                    f"A perícia {skill_id!r} não está disponível para as escolhas feitas.",
                    f"skills.{skill_id}",
                )
            )

    if not any(s.kind == "skills" and s.id in checked for s in pack.steps) or issues:
        return issues

    budget = sheet.skill_budget
    if budget is not None:
        total = sum(v for v in character.skills.values() if v > 0)
        if total > budget:
            issues.append(
                Issue("skills_over_budget", f"{total} perícias, mas o limite é {budget}.", "skills")
            )
        elif total < budget:
            issues.append(
                Issue("skills_unspent", f"Faltam {budget - total} perícias a escolher.", "skills")
            )
    return issues


def _check_narrative(pack: RulePack, character: Character) -> list[Issue]:
    values = {
        "name": character.name,
        "concept": character.concept,
        "background": character.background,
    }
    return [
        Issue("narrative_missing", f"Campo obrigatório vazio: {step.fills}.", step.fills)
        for step in pack.steps
        if step.kind == "narrative" and step.fills is not None and not values[step.fills].strip()
    ]
