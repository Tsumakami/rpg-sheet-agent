import pytest

from rpg_agent.domain.allocator import AllocationError, allocate_point_buy, assign_sorted

DND_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
RANKING = ["int", "dex", "con", "wis", "cha", "str"]


def total_cost(scores: dict[str, int]) -> int:
    return sum(DND_COSTS[v] for v in scores.values())


def test_point_buy_spends_budget_without_exceeding_it() -> None:
    scores = allocate_point_buy(RANKING, 8, 15, 27, DND_COSTS)
    assert total_cost(scores) == 27
    assert all(8 <= v <= 15 for v in scores.values())


def test_point_buy_favors_higher_priorities() -> None:
    scores = allocate_point_buy(RANKING, 8, 15, 27, DND_COSTS)
    values = [scores[a] for a in RANKING]
    assert values == sorted(values, reverse=True)
    assert scores["int"] == 15


def test_point_buy_with_zero_budget_keeps_minimum() -> None:
    scores = allocate_point_buy(RANKING, 8, 15, 0, DND_COSTS)
    assert set(scores.values()) == {8}


def test_point_buy_is_deterministic() -> None:
    first = allocate_point_buy(RANKING, 8, 15, 27, DND_COSTS)
    assert allocate_point_buy(RANKING, 8, 15, 27, DND_COSTS) == first


def test_assign_sorted_gives_best_values_to_top_ranks() -> None:
    result = assign_sorted(RANKING, [8, 10, 12, 13, 14, 15])
    assert result == {"int": 15, "dex": 14, "con": 13, "wis": 12, "cha": 10, "str": 8}


def test_assign_sorted_rejects_wrong_length() -> None:
    with pytest.raises(AllocationError):
        assign_sorted(RANKING, [1, 2])
