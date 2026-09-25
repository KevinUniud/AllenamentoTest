"""Conversion between formula AST values and validated Prolog terms."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from ..ast_logic import And, Iff, Imp, Not, Or, Var

_IDENTIFIER = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_VALUATION = re.compile(r"^[a-z][A-Za-z0-9_]*-(?:true|false)$")


def to_prolog(expr):
    if isinstance(expr, Var):
        if not _IDENTIFIER.fullmatch(expr.name):
            raise ValueError(f"Identificatore Prolog non valido: {expr.name!r}")
        return expr.name
    if isinstance(expr, Not):
        return f"not({to_prolog(expr.expr)})"
    if isinstance(expr, And):
        return f"and({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Or):
        return f"or({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Imp):
        return f"imp({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Iff):
        return f"iff({to_prolog(expr.left)},{to_prolog(expr.right)})"
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


class PrologTermParser:
    def __init__(self, text: str):
        self.text = text.strip()
        self.i = 0

    def parse(self):
        expr = self._parse_expr()
        self._skip_ws()
        if self.i != len(self.text):
            raise ValueError(f"Input Prolog non consumato completamente: {self.text!r}")
        return expr

    def _skip_ws(self) -> None:
        while self.i < len(self.text) and self.text[self.i].isspace():
            self.i += 1

    def _peek(self):
        self._skip_ws()
        return None if self.i >= len(self.text) else self.text[self.i]

    def _consume(self, token: str) -> None:
        self._skip_ws()
        if not self.text.startswith(token, self.i):
            found = self.text[self.i : self.i + 20]
            raise ValueError(f"Atteso {token!r} in posizione {self.i}, trovato: {found!r}")
        self.i += len(token)

    def _parse_ident(self) -> str:
        self._skip_ws()
        start = self.i
        while self.i < len(self.text) and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
            self.i += 1
        if start == self.i:
            raise ValueError(f"Identificatore atteso in posizione {self.i}")
        ident = self.text[start : self.i]
        if not _IDENTIFIER.fullmatch(ident):
            raise ValueError(f"Identificatore Prolog non valido: {ident!r}")
        return ident

    def _parse_expr(self):
        ident = self._parse_ident()
        self._skip_ws()
        if self._peek() != "(":
            return Var(ident)
        self._consume("(")
        if ident == "not":
            child = self._parse_expr()
            self._consume(")")
            return Not(child)
        left = self._parse_expr()
        self._consume(",")
        right = self._parse_expr()
        self._consume(")")
        constructors = {"and": And, "or": Or, "imp": Imp, "iff": Iff}
        constructor = constructors.get(ident)
        if constructor is None:
            raise ValueError(f"Funtore Prolog non supportato: {ident!r}")
        return constructor(left, right)


def from_prolog(term: str):
    if not isinstance(term, str) or not term.strip():
        raise ValueError("La formula Prolog deve essere una stringa non vuota")
    if len(term) > 10_000:
        raise ValueError("La formula Prolog supera il limite di 10000 caratteri")
    return PrologTermParser(term).parse()


def collect_variables(expr):
    if isinstance(expr, Var):
        return {expr.name}
    if isinstance(expr, Not):
        return collect_variables(expr.expr)
    if isinstance(expr, (And, Or, Imp, Iff)):
        return collect_variables(expr.left) | collect_variables(expr.right)
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


@lru_cache(maxsize=4096)
def _cached_var_list(vars_sorted: tuple[str, ...]) -> str:
    for value in vars_sorted:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError(f"Variabile Prolog non valida: {value!r}")
    return "[" + ",".join(vars_sorted) + "]"


def prolog_var_list(expr_or_vars):
    values = expr_or_vars if isinstance(expr_or_vars, (set, list, tuple)) else collect_variables(expr_or_vars)
    return _cached_var_list(tuple(sorted(values)))


def _resolve_vars_for_expr(expr, vars_list: Iterable[str] | None = None) -> list[str]:
    if vars_list is not None:
        prolog_var_list(tuple(vars_list))
        return list(vars_list)
    parsed = from_prolog(expr) if isinstance(expr, str) else expr
    return sorted(collect_variables(parsed))


def _resolve_vars_for_binary(left, right, vars_list: Iterable[str] | None = None) -> list[str]:
    if vars_list is not None:
        prolog_var_list(tuple(vars_list))
        return list(vars_list)
    left_expr = from_prolog(left) if isinstance(left, str) else left
    right_expr = from_prolog(right) if isinstance(right, str) else right
    return sorted(collect_variables(left_expr) | collect_variables(right_expr))


def valuation_to_prolog(valuation: Sequence[tuple[str, bool] | str]) -> str:
    parts: list[str] = []
    for item in valuation:
        if isinstance(item, str):
            if not _VALUATION.fullmatch(item):
                raise ValueError(f"Valutazione Prolog non valida: {item!r}")
            parts.append(item)
            continue
        name, value = item
        if not _IDENTIFIER.fullmatch(name) or not isinstance(value, bool):
            raise ValueError(f"Valutazione non valida per {name!r}")
        parts.append(f"{name}-{'true' if value else 'false'}")
    return "[" + ",".join(parts) + "]"


def prolog_term_list(terms: Sequence[str]) -> str:
    return "[" + ",".join(terms) + "]"


def formula_to_dict(expr):
    if isinstance(expr, Var):
        return {"type": "var", "name": expr.name}
    if isinstance(expr, Not):
        return {"type": "not", "expr": formula_to_dict(expr.expr)}
    if isinstance(expr, (And, Or, Imp, Iff)):
        return {
            "type": type(expr).__name__.lower(),
            "left": formula_to_dict(expr.left),
            "right": formula_to_dict(expr.right),
        }
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")
