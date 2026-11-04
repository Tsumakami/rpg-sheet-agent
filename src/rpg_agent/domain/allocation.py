"""Verificação dos métodos de distribuição de atributos."""

from collections.abc import Mapping, Sequence

from rpg_agent.domain.issues import Issue, Severity
from rpg_agent.domain.rule_system import AllocationRule


def check_allocation(
    rule: AllocationRule,
    scores: Mapping[str, int],
    attribute_ids: Sequence[str],
) -> list[Issue]:
    issues: list[Issue] = []

    missing = [a for a in attribute_ids if a not in scores]
    for attr in missing:
        issues.append(
            Issue("attribute_missing", f"Atributo {attr!r} não definido.", f"attributes.{attr}")
        )
    if missing:
        return issues

    for attr in attribute_ids:
        value = scores[attr]
        too_low = rule.min_score is not None and value < rule.min_score
        too_high = rule.max_score is not None and value > rule.max_score
        if too_low or too_high:
            issues.append(
                Issue(
                    "attribute_out_of_range",
                    f"{attr}={value} fora do intervalo {rule.min_score}-{rule.max_score} "
                    f"({rule.method}).",
                    f"attributes.{attr}",
                )
            )
    if issues:
        return issues

    if rule.method == "point_buy":
        cost = sum(rule.costs[scores[a]] for a in attribute_ids)
        budget = rule.budget or 0
        if cost > budget:
            issues.append(
                Issue(
                    "point_buy_over_budget",
                    f"Custo {cost} excede o orçamento de {budget} pontos.",
                    "attributes",
                )
            )
        elif cost < budget:
            issues.append(
                Issue(
                    "point_buy_unspent",
                    f"Sobraram {budget - cost} pontos.",
                    "attributes",
                    Severity.WARNING,
                )
            )
    elif rule.method == "standard_array" and sorted(scores[a] for a in attribute_ids) != sorted(
        rule.array
    ):
        issues.append(
            Issue(
                "standard_array_mismatch",
                f"Os valores devem ser exatamente {sorted(rule.array, reverse=True)}.",
                "attributes",
            )
        )
    return issues
