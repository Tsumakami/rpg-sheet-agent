"""Rolagem de dados determinística (RNG injetável para testes)."""

import random
import re
from dataclasses import dataclass
from typing import Protocol

_PATTERN = re.compile(
    r"^\s*(?P<count>\d*)d(?P<sides>\d+)"
    r"(?:(?P<keep>k[hl])(?P<keepn>\d+))?"
    r"\s*(?P<mod>[+-]\s*\d+)?\s*$",
    re.IGNORECASE,
)
_MAX_DICE = 100
_MAX_SIDES = 1000


class DiceError(ValueError):
    """Expressão de dados inválida."""


class _Rng(Protocol):
    def randint(self, a: int, b: int) -> int: ...


@dataclass(frozen=True)
class RollResult:
    expression: str
    rolls: tuple[int, ...]
    kept: tuple[int, ...]
    modifier: int
    total: int


class DiceRoller:
    """Suporta `NdM`, `NdMkhK` / `NdMklK` (manter maiores/menores) e `+/-X`."""

    def __init__(self, rng: _Rng | None = None) -> None:
        self._rng: _Rng = rng if rng is not None else random.Random()

    def roll(self, expression: str) -> RollResult:
        match = _PATTERN.match(expression)
        if match is None:
            raise DiceError(f"expressão de dados inválida: {expression!r}")

        count = int(match["count"] or 1)
        sides = int(match["sides"])
        if not 1 <= count <= _MAX_DICE:
            raise DiceError(f"quantidade de dados deve estar entre 1 e {_MAX_DICE}")
        if not 2 <= sides <= _MAX_SIDES:
            raise DiceError(f"lados do dado devem estar entre 2 e {_MAX_SIDES}")

        rolls = tuple(self._rng.randint(1, sides) for _ in range(count))

        kept = rolls
        keep_mode = (match["keep"] or "").lower()
        if keep_mode:
            keep_n = int(match["keepn"])
            if not 1 <= keep_n <= count:
                raise DiceError("quantidade a manter deve estar entre 1 e o total de dados")
            ordered = sorted(rolls, reverse=keep_mode == "kh")
            kept = tuple(ordered[:keep_n])

        modifier = int(match["mod"].replace(" ", "")) if match["mod"] else 0
        return RollResult(expression.strip(), rolls, kept, modifier, sum(kept) + modifier)

    def roll_scores(self, count: int = 6, expression: str = "4d6kh3") -> list[int]:
        """Rola `count` valores (padrão: 6 atributos de D&D, 4d6 descartando o menor)."""
        return [self.roll(expression).total for _ in range(count)]
