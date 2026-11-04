"""Avaliador seguro de fórmulas aritméticas dos Rule Packs.

Nunca usa `eval`. Só aceita números, variáveis, + - * / // %, parênteses e as
funções floor, ceil, min, max e abs.
"""

import ast
import math
import operator
from collections.abc import Callable, Mapping
from typing import Any

MAX_FORMULA_LENGTH = 200

Number = int | float


class ExpressionError(ValueError):
    """Fórmula inválida ou que não pôde ser avaliada."""


class UnknownNameError(ExpressionError):
    """A fórmula usa uma variável que não foi fornecida."""

    def __init__(self, name: str) -> None:
        super().__init__(f"variável desconhecida: {name!r}")
        self.name = name


_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_FUNCS: dict[str, Callable[..., Any]] = {
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "abs": abs,
}


def parse_formula(formula: str) -> ast.Expression:
    """Faz o parse e rejeita qualquer construção fora da lista permitida."""
    if len(formula) > MAX_FORMULA_LENGTH:
        raise ExpressionError(f"fórmula longa demais (máx. {MAX_FORMULA_LENGTH} caracteres)")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"fórmula inválida: {formula!r}") from exc
    _check(tree.body)
    return tree


def _check(node: ast.AST) -> None:
    match node:
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINOPS:
            _check(left)
            _check(right)
        case ast.UnaryOp(op=ast.UAdd() | ast.USub(), operand=operand):
            _check(operand)
        case ast.Constant(value=value) if isinstance(value, int | float) and not isinstance(
            value, bool
        ):
            pass
        case ast.Name():
            pass
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _FUNCS:
            for arg in args:
                _check(arg)
        case _:
            raise ExpressionError(f"construção não permitida na fórmula: {type(node).__name__}")


def formula_names(formula: str) -> set[str]:
    """Variáveis usadas na fórmula (exclui nomes de funções)."""
    tree = parse_formula(formula)
    func_nodes = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in func_nodes}


def evaluate(formula: str, variables: Mapping[str, Number]) -> Number:
    tree = parse_formula(formula)
    try:
        result: Number = _eval(tree.body, variables)
        return result
    except ExpressionError:
        raise
    except ZeroDivisionError as exc:
        raise ExpressionError("divisão por zero") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExpressionError(f"erro ao avaliar {formula!r}: {exc}") from exc


def _eval(node: ast.AST, env: Mapping[str, Number]) -> Any:
    match node:
        case ast.Constant(value=value):
            return value
        case ast.Name(id=name):
            if name not in env:
                raise UnknownNameError(name)
            return env[name]
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_eval(operand, env)
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _eval(operand, env)
        case ast.BinOp(left=left, op=op, right=right):
            return _BINOPS[type(op)](_eval(left, env), _eval(right, env))
        case ast.Call(func=ast.Name(id=name), args=args):
            return _FUNCS[name](*[_eval(a, env) for a in args])
        case _:  # pragma: no cover - parse_formula já barrou
            raise ExpressionError("construção não permitida")
