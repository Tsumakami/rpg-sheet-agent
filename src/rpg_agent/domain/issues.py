"""Problemas encontrados na validação de uma ficha."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    path: str = ""
    severity: Severity = Severity.ERROR


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(i.severity is Severity.ERROR for i in issues)
