"""Build versioned, deterministic construction traces for logical formulas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from .ast_logic import And, Formula, Iff, Imp, Not, Or, Var
from .metrics import formula_depth
from .prolog.codec import to_prolog

TRACE_VERSION = 1
AST_STRATEGY = "ast_postorder"
TERM_STRATEGY = "term_postorder"

_BINARY_OPERATORS: dict[type[Any], str] = {
    And: "and",
    Or: "or",
    Imp: "imp",
    Iff: "iff",
}
_TERM_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TERM_BINARY_OPERATORS = {"and", "or", "imp", "iff"}
_TERM_QUANTIFIERS = {"forall", "exists"}


def _step(
    *,
    steps: list[dict[str, Any]],
    node_id: str,
    kind: str,
    operator: str | None,
    operands: list[str],
    result_prolog: str,
    depth: int,
    details: dict[str, str] | None = None,
) -> str:
    item: dict[str, Any] = {
        "index": len(steps) + 1,
        "node_id": node_id,
        "kind": kind,
        "operator": operator,
        "operands": operands,
        "result_prolog": result_prolog,
        "depth": depth,
    }
    if details:
        item["details"] = details
    steps.append(item)
    return node_id


def build_construction_trace(expr: Formula) -> dict[str, Any]:
    """Return a bottom-up construction trace for a propositional AST."""

    steps: list[dict[str, Any]] = []

    def visit(node: Formula, node_id: str) -> str:
        if isinstance(node, Var):
            return _step(
                steps=steps,
                node_id=node_id,
                kind="atom",
                operator=None,
                operands=[],
                result_prolog=to_prolog(node),
                depth=0,
                details={"name": node.name},
            )

        if isinstance(node, Not):
            child_id = f"{node_id}.operand"
            visit(cast(Formula, node.expr), child_id)
            return _step(
                steps=steps,
                node_id=node_id,
                kind="unary",
                operator="not",
                operands=[child_id],
                result_prolog=to_prolog(node),
                depth=formula_depth(node),
            )

        if isinstance(node, (And, Or, Imp, Iff)):
            left_id = f"{node_id}.left"
            right_id = f"{node_id}.right"
            visit(cast(Formula, node.left), left_id)
            visit(cast(Formula, node.right), right_id)
            return _step(
                steps=steps,
                node_id=node_id,
                kind="binary",
                operator=_BINARY_OPERATORS[type(node)],
                operands=[left_id, right_id],
                result_prolog=to_prolog(node),
                depth=formula_depth(node),
            )

        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    visit(expr, "root")
    return {
        "version": TRACE_VERSION,
        "strategy": AST_STRATEGY,
        "final_formula_prolog": to_prolog(expr),
        "steps": steps,
    }


@dataclass(frozen=True)
class _Term:
    name: str
    arguments: tuple[_Term, ...] = ()


class _TermParser:
    def __init__(self, text: str):
        self.text = text.strip()
        self.index = 0

    def parse(self) -> _Term:
        term = self._parse_term()
        self._skip_spaces()
        if self.index != len(self.text):
            raise ValueError(f"Testo non consumato in posizione {self.index}")
        return term

    def _skip_spaces(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def _parse_identifier(self) -> str:
        self._skip_spaces()
        start = self.index
        while self.index < len(self.text):
            char = self.text[self.index]
            if not (char.isalnum() or char == "_"):
                break
            self.index += 1
        identifier = self.text[start : self.index]
        if not _TERM_IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"Identificatore non valido in posizione {start}")
        return identifier

    def _consume(self, token: str) -> None:
        self._skip_spaces()
        if not self.text.startswith(token, self.index):
            raise ValueError(f"Atteso {token!r} in posizione {self.index}")
        self.index += len(token)

    def _parse_term(self) -> _Term:
        name = self._parse_identifier()
        self._skip_spaces()
        if self.index >= len(self.text) or self.text[self.index] != "(":
            return _Term(name)

        self._consume("(")
        arguments = [self._parse_term()]
        self._skip_spaces()
        while self.index < len(self.text) and self.text[self.index] == ",":
            self._consume(",")
            arguments.append(self._parse_term())
            self._skip_spaces()
        self._consume(")")
        return _Term(name, tuple(arguments))


def _render_term(term: _Term) -> str:
    if not term.arguments:
        return term.name
    return f"{term.name}({','.join(_render_term(argument) for argument in term.arguments)})"


def _term_depth(term: _Term) -> int:
    if not term.arguments or term.name not in _TERM_BINARY_OPERATORS | _TERM_QUANTIFIERS | {"not"}:
        return 0
    if term.name in _TERM_QUANTIFIERS:
        return 1 + _term_depth(term.arguments[1])
    return 1 + max(_term_depth(argument) for argument in term.arguments)


def build_term_construction_trace(formula: str) -> dict[str, Any]:
    """Build a trace for translation terms, including predicates and quantifiers.

    This parser is deliberately independent from the executable Prolog codec. It
    accepts only the compact term grammar emitted by the translation generator.
    """

    if not isinstance(formula, str) or not formula.strip():
        raise ValueError("La formula deve essere una stringa non vuota")
    if len(formula) > 10_000:
        raise ValueError("La formula supera il limite di 10000 caratteri")

    root = _TermParser(formula).parse()
    steps: list[dict[str, Any]] = []

    def visit(term: _Term, node_id: str) -> str:
        rendered = _render_term(term)
        if not term.arguments:
            return _step(
                steps=steps,
                node_id=node_id,
                kind="atom",
                operator=None,
                operands=[],
                result_prolog=rendered,
                depth=0,
                details={"name": term.name},
            )

        if term.name == "not":
            if len(term.arguments) != 1:
                raise ValueError("not richiede esattamente un argomento")
            child_id = f"{node_id}.operand"
            visit(term.arguments[0], child_id)
            return _step(
                steps=steps,
                node_id=node_id,
                kind="unary",
                operator="not",
                operands=[child_id],
                result_prolog=rendered,
                depth=_term_depth(term),
            )

        if term.name in _TERM_BINARY_OPERATORS:
            if len(term.arguments) != 2:
                raise ValueError(f"{term.name} richiede esattamente due argomenti")
            left_id = f"{node_id}.left"
            right_id = f"{node_id}.right"
            visit(term.arguments[0], left_id)
            visit(term.arguments[1], right_id)
            return _step(
                steps=steps,
                node_id=node_id,
                kind="binary",
                operator=term.name,
                operands=[left_id, right_id],
                result_prolog=rendered,
                depth=_term_depth(term),
            )

        if term.name in _TERM_QUANTIFIERS:
            if len(term.arguments) != 2 or term.arguments[0].arguments:
                raise ValueError(f"{term.name} richiede una variabile e un corpo")
            body_id = f"{node_id}.body"
            visit(term.arguments[1], body_id)
            return _step(
                steps=steps,
                node_id=node_id,
                kind="quantifier",
                operator=term.name,
                operands=[body_id],
                result_prolog=rendered,
                depth=_term_depth(term),
                details={"bound_variable": term.arguments[0].name},
            )

        arguments = ",".join(_render_term(argument) for argument in term.arguments)
        return _step(
            steps=steps,
            node_id=node_id,
            kind="predicate",
            operator=term.name,
            operands=[],
            result_prolog=rendered,
            depth=0,
            details={"name": term.name, "arguments": arguments},
        )

    visit(root, "root")
    return {
        "version": TRACE_VERSION,
        "strategy": TERM_STRATEGY,
        "final_formula_prolog": _render_term(root),
        "steps": steps,
    }


__all__ = [
    "AST_STRATEGY",
    "TERM_STRATEGY",
    "TRACE_VERSION",
    "build_construction_trace",
    "build_term_construction_trace",
]
