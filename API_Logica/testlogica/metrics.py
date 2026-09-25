"""Pure structural metrics for propositional-formula AST nodes."""

from __future__ import annotations

from .ast_logic import And, Formula, Iff, Imp, Not, Or, Var


def formula_depth(expr: Formula) -> int:
    if isinstance(expr, Var):
        return 0
    if isinstance(expr, Not):
        return 1 + formula_depth(expr.expr)  # type: ignore[arg-type]
    if isinstance(expr, (And, Or, Imp, Iff)):
        return 1 + max(formula_depth(expr.left), formula_depth(expr.right))  # type: ignore[arg-type]
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_size(expr: Formula) -> int:
    if isinstance(expr, Var):
        return 1
    if isinstance(expr, Not):
        return 1 + formula_size(expr.expr)  # type: ignore[arg-type]
    if isinstance(expr, (And, Or, Imp, Iff)):
        return 1 + formula_size(expr.left) + formula_size(expr.right)  # type: ignore[arg-type]
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_atom_count(expr: Formula) -> int:
    if isinstance(expr, Var):
        return 1
    if isinstance(expr, Not):
        return formula_atom_count(expr.expr)  # type: ignore[arg-type]
    if isinstance(expr, (And, Or, Imp, Iff)):
        return formula_atom_count(expr.left) + formula_atom_count(expr.right)  # type: ignore[arg-type]
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_operator_count(expr: Formula) -> int:
    if isinstance(expr, Var):
        return 0
    if isinstance(expr, Not):
        return 1 + formula_operator_count(expr.expr)  # type: ignore[arg-type]
    if isinstance(expr, (And, Or, Imp, Iff)):
        return 1 + formula_operator_count(expr.left) + formula_operator_count(expr.right)  # type: ignore[arg-type]
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_binary_operator_count(expr: Formula) -> int:
    if isinstance(expr, Var):
        return 0
    if isinstance(expr, Not):
        return formula_binary_operator_count(expr.expr)  # type: ignore[arg-type]
    if isinstance(expr, (And, Or, Imp, Iff)):
        return 1 + formula_binary_operator_count(expr.left) + formula_binary_operator_count(expr.right)  # type: ignore[arg-type]
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")
