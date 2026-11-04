"""Distribui os valores de atributos a partir de um ranking de prioridades.

O LLM só decide a ORDEM de importância dos atributos; as contas ficam aqui,
de forma determinística e testável.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpg_agent.domain.rule_system import AllocationRule


class AllocationError(ValueError):
    """Não foi possível distribuir os atributos com o método pedido."""


def allocate_point_buy(
    ranking: Sequence[str],
    min_score: int,
    max_score: int,
    budget: int,
    costs: Mapping[int, int],
) -> dict[str, int]:
    """Gasta o orçamento priorizando os primeiros do ranking, com retornos decrescentes."""
    count = len(ranking)
    scores = dict.fromkeys(ranking, min_score)
    remaining = budget - costs[min_score] * count
    weights = {attr: count - i for i, attr in enumerate(ranking)}

    while True:
        best: str | None = None
        best_priority = -1.0
        for attr in ranking:
            value = scores[attr]
            if value >= max_score:
                continue
            step_cost = costs[value + 1] - costs[value]
            if step_cost > remaining:
                continue
            priority = weights[attr] / (1 + value - min_score)
            if priority > best_priority:  # empate: vence quem vem antes no ranking
                best, best_priority = attr, priority
        if best is None:
            return scores
        remaining -= costs[scores[best] + 1] - costs[scores[best]]
        scores[best] += 1


def assign_sorted(ranking: Sequence[str], values: Sequence[int]) -> dict[str, int]:
    """Atribui os maiores valores aos atributos mais prioritários."""
    if len(ranking) != len(values):
        raise AllocationError("quantidade de valores diferente da de atributos")
    return dict(zip(ranking, sorted(values, reverse=True), strict=True))


def allocate_by_ranking(
    rule: "AllocationRule",
    ranking: Sequence[str],
    rolled: Sequence[int] | None = None,
) -> dict[str, int]:
    if rule.method == "standard_array":
        return assign_sorted(ranking, rule.array)
    if rule.method == "roll":
        if rolled is None:
            raise AllocationError("o método 'roll' precisa dos valores rolados")
        return assign_sorted(ranking, rolled)
    if rule.method == "point_buy":
        if rule.min_score is None or rule.max_score is None or rule.budget is None:
            raise AllocationError("point_buy mal configurado no pack")
        return allocate_point_buy(ranking, rule.min_score, rule.max_score, rule.budget, rule.costs)
    raise AllocationError(f"o método {rule.method!r} não suporta sugestão automática")
