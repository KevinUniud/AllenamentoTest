"""Versioned traces that explain how one formula was reached from another."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Any, Literal

from .ast_logic import And, Formula, Iff, Imp, Not, Or, Var
from .prolog.codec import from_prolog, to_prolog

TRANSFORMATION_VERSION = 1
TransformationStrategy = Literal["equivalence_rewrite", "distractor_mutation"]


def _normalize_formula(formula: str) -> str:
    return to_prolog(from_prolog(formula))


def _operator(node: Formula) -> str:
    if isinstance(node, Var):
        return "atom"
    if isinstance(node, Not):
        return "not"
    if isinstance(node, And):
        return "and"
    if isinstance(node, Or):
        return "or"
    if isinstance(node, Imp):
        return "imp"
    if isinstance(node, Iff):
        return "iff"
    raise TypeError(f"Tipo formula non supportato: {type(node)!r}")


def _changed_subformula(before: Formula, after: Formula, location: str = "root") -> tuple[str, Formula, Formula]:
    """Locate a single local change, falling back to the current subtree."""
    if type(before) is not type(after):
        return location, before, after

    if isinstance(before, Var) and isinstance(after, Var):
        return location, before, after

    if isinstance(before, Not) and isinstance(after, Not):
        if before.expr != after.expr:
            return _changed_subformula(before.expr, after.expr, f"{location}.operand")  # type: ignore[arg-type]
        return location, before, after

    if isinstance(before, (And, Or, Imp, Iff)) and isinstance(after, (And, Or, Imp, Iff)):
        left_changed = before.left != after.left
        right_changed = before.right != after.right
        if left_changed and not right_changed:
            return _changed_subformula(before.left, after.left, f"{location}.left")  # type: ignore[arg-type]
        if right_changed and not left_changed:
            return _changed_subformula(before.right, after.right, f"{location}.right")  # type: ignore[arg-type]

    return location, before, after


def _is_constant(node: Any, name: str) -> bool:
    return isinstance(node, Var) and node.name == name


def _is_complement(left: Any, right: Any) -> bool:
    return (isinstance(left, Not) and left.expr == right) or (isinstance(right, Not) and right.expr == left)


def _equivalence_rule(before: Formula, after: Formula) -> str | None:
    if isinstance(before, Not) and isinstance(before.expr, Not) and before.expr.expr == after:
        return "double_negation"
    if isinstance(after, Not) and isinstance(after.expr, Not) and after.expr.expr == before:
        return "double_negation"
    if isinstance(before, Imp) and after == Or(Not(before.left), before.right):
        return "implication_elimination"
    if isinstance(before, Iff) and after == And(Imp(before.left, before.right), Imp(before.right, before.left)):
        return "biconditional_elimination"
    if (
        isinstance(before, Iff)
        and isinstance(after, Iff)
        and after == Iff(Not(before.left), Not(before.right))
    ) or (
        isinstance(before, Iff)
        and isinstance(after, Iff)
        and before == Iff(Not(after.left), Not(after.right))
    ):
        return "biconditional_negation"
    if (
        isinstance(before, Not)
        and isinstance(before.expr, And)
        and after == Or(Not(before.expr.left), Not(before.expr.right))
    ):
        return "de_morgan_and"
    if (
        isinstance(after, Not)
        and isinstance(after.expr, Or)
        and before == And(Not(after.expr.left), Not(after.expr.right))
    ):
        return "de_morgan_and"
    if (
        isinstance(before, And)
        and after == Not(Or(Not(before.left), Not(before.right)))
    ):
        return "de_morgan_and"
    if (
        isinstance(before, Not)
        and isinstance(before.expr, Or)
        and after == And(Not(before.expr.left), Not(before.expr.right))
    ):
        return "de_morgan_or"
    if (
        isinstance(after, Not)
        and isinstance(after.expr, And)
        and before == Or(Not(after.expr.left), Not(after.expr.right))
    ):
        return "de_morgan_or"
    if (
        isinstance(before, Or)
        and after == Not(And(Not(before.left), Not(before.right)))
    ):
        return "de_morgan_or"

    if (
        isinstance(before, And)
        and isinstance(after, And)
        and before.left == after.right
        and before.right == after.left
    ):
        return "commutativity_and"
    if (
        isinstance(before, Or)
        and isinstance(after, Or)
        and before.left == after.right
        and before.right == after.left
    ):
        return "commutativity_or"
    if (
        isinstance(before, Iff)
        and isinstance(after, Iff)
        and before.left == after.right
        and before.right == after.left
    ):
        return "commutativity_iff"

    if isinstance(before, And) and isinstance(after, And):
        if isinstance(before.right, And) and after == And(And(before.left, before.right.left), before.right.right):
            return "associativity_and"
        if isinstance(before.left, And) and after == And(before.left.left, And(before.left.right, before.right)):
            return "associativity_and"
    if isinstance(before, Or) and isinstance(after, Or):
        if isinstance(before.right, Or) and after == Or(Or(before.left, before.right.left), before.right.right):
            return "associativity_or"
        if isinstance(before.left, Or) and after == Or(before.left.left, Or(before.left.right, before.right)):
            return "associativity_or"

    if isinstance(before, And) and isinstance(before.right, Or):
        distributed_and_right = Or(And(before.left, before.right.left), And(before.left, before.right.right))
        if after == distributed_and_right:
            return "distribution_and_over_or"
    if isinstance(before, And) and isinstance(before.left, Or):
        distributed_and_left = Or(And(before.left.left, before.right), And(before.left.right, before.right))
        if after == distributed_and_left:
            return "distribution_and_over_or"
    if isinstance(before, Or) and isinstance(before.right, And):
        distributed_or_right = And(Or(before.left, before.right.left), Or(before.left, before.right.right))
        if after == distributed_or_right:
            return "distribution_or_over_and"
    if isinstance(before, Or) and isinstance(before.left, And):
        distributed_or_left = And(Or(before.left.left, before.right), Or(before.left.right, before.right))
        if after == distributed_or_left:
            return "distribution_or_over_and"

    if isinstance(before, And) and before.left == before.right == after:
        return "idempotence_and"
    if isinstance(before, Or) and before.left == before.right == after:
        return "idempotence_or"
    if isinstance(before, And) and after in (before.left, before.right):
        other = before.right if after == before.left else before.left
        if isinstance(other, Or) and after in (other.left, other.right):
            return "absorption_and"
    if isinstance(before, Or) and after in (before.left, before.right):
        other = before.right if after == before.left else before.left
        if isinstance(other, And) and after in (other.left, other.right):
            return "absorption_or"

    if isinstance(before, And):
        if (_is_constant(before.left, "true") and after == before.right) or (
            _is_constant(before.right, "true") and after == before.left
        ):
            return "identity_and"
        if (_is_constant(before.left, "false") or _is_constant(before.right, "false")) and _is_constant(
            after, "false"
        ):
            return "domination_and"
        if _is_complement(before.left, before.right) and _is_constant(after, "false"):
            return "complement_and"
    if isinstance(before, Or):
        if (_is_constant(before.left, "false") and after == before.right) or (
            _is_constant(before.right, "false") and after == before.left
        ):
            return "identity_or"
        if (_is_constant(before.left, "true") or _is_constant(before.right, "true")) and _is_constant(
            after, "true"
        ):
            return "domination_or"
        if _is_complement(before.left, before.right) and _is_constant(after, "true"):
            return "complement_or"
    if isinstance(before, Not) and (
        (_is_constant(before.expr, "true") and _is_constant(after, "false"))
        or (_is_constant(before.expr, "false") and _is_constant(after, "true"))
    ):
        return "constant_negation"
    if isinstance(before, Imp) and (
        (_is_constant(before.left, "true") and after == before.right)
        or (_is_constant(before.left, "false") and _is_constant(after, "true"))
        or (_is_constant(before.right, "true") and _is_constant(after, "true"))
        or (_is_constant(before.right, "false") and after == Not(before.left))
    ):
        return "constant_implication"
    if isinstance(before, Iff) and (
        (_is_constant(before.left, "true") and after == before.right)
        or (_is_constant(before.right, "true") and after == before.left)
        or (_is_constant(before.left, "false") and after == Not(before.right))
        or (_is_constant(before.right, "false") and after == Not(before.left))
    ):
        return "constant_biconditional"
    return None


def _mutation_rule(before: Formula, after: Formula) -> str:
    if isinstance(before, Var) and isinstance(after, Not) and after.expr == before:
        return "negate_atom"
    if (
        isinstance(before, Var)
        and isinstance(after, (And, Or, Imp))
        and after.left == before
        and after.right == before
    ):
        return f"wrap_atom_with_{_operator(after)}"
    before_operator = _operator(before)
    after_operator = _operator(after)
    if before_operator != after_operator:
        return f"replace_operator_{before_operator}_with_{after_operator}"
    return "distractor_mutation"


def build_transformation_trace(
    source_formula_prolog: str,
    formula_path: Sequence[str],
    *,
    strategy: TransformationStrategy,
    preserves_meaning: bool,
) -> dict[str, Any]:
    """Build and validate a continuous, endpoint-preserving transformation trace."""
    source = _normalize_formula(source_formula_prolog)
    path = [_normalize_formula(formula) for formula in formula_path]
    if not path or path[0] != source:
        path.insert(0, source)

    compact_path: list[str] = []
    for formula in path:
        if not compact_path or compact_path[-1] != formula:
            compact_path.append(formula)
    if len(compact_path) < 2:
        raise ValueError("Una trasformazione richiede almeno due formule distinte")

    kind = "rewrite" if strategy == "equivalence_rewrite" else "mutation"
    steps: list[dict[str, Any]] = []
    for index, (before_prolog, after_prolog) in enumerate(pairwise(compact_path), start=1):
        before = from_prolog(before_prolog)
        after = from_prolog(after_prolog)
        location, local_before, local_after = _changed_subformula(before, after)
        rule = (
            _equivalence_rule(local_before, local_after)
            if strategy == "equivalence_rewrite"
            else _mutation_rule(local_before, local_after)
        )
        if rule is None:
            raise ValueError(
                "Passaggio equivalente privo di una legge logica riconosciuta: "
                f"{to_prolog(local_before)} -> {to_prolog(local_after)}"
            )
        steps.append(
            {
                "index": index,
                "kind": kind,
                "rule": rule,
                "before_prolog": before_prolog,
                "after_prolog": after_prolog,
                "before_subformula_prolog": to_prolog(local_before),
                "after_subformula_prolog": to_prolog(local_after),
                "location": location,
            }
        )

    trace: dict[str, Any] = {
        "version": TRANSFORMATION_VERSION,
        "strategy": strategy,
        "source_formula_prolog": source,
        "final_formula_prolog": compact_path[-1],
        "preserves_meaning": preserves_meaning,
        "steps": steps,
    }
    validate_transformation_trace(trace)
    return trace


def validate_transformation_trace(trace: dict[str, Any]) -> None:
    """Reject discontinuous traces or traces whose declared endpoints do not match."""
    if trace.get("version") != TRANSFORMATION_VERSION:
        raise ValueError("Versione transformation non supportata")
    strategy = trace.get("strategy")
    if strategy not in {"equivalence_rewrite", "distractor_mutation"}:
        raise ValueError("Strategia transformation non supportata")
    if trace.get("preserves_meaning") is not (strategy == "equivalence_rewrite"):
        raise ValueError("preserves_meaning non coerente con la strategia")
    steps = trace.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("La transformation deve contenere almeno un passaggio")

    source = trace.get("source_formula_prolog")
    final = trace.get("final_formula_prolog")
    if not isinstance(source, str) or not isinstance(final, str):
        raise ValueError("Estremi transformation mancanti")
    try:
        _normalize_formula(source)
        _normalize_formula(final)
    except (TypeError, ValueError) as exc:
        raise ValueError("Estremi transformation non validi") from exc

    expected_kind = "rewrite" if strategy == "equivalence_rewrite" else "mutation"
    previous = source
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or step.get("index") != index:
            raise ValueError("Indici transformation non consecutivi")
        if step.get("before_prolog") != previous:
            raise ValueError("Transformation non continua")
        if step.get("kind") != expected_kind or not step.get("rule") or not step.get("location"):
            raise ValueError("Passaggio transformation incompleto")
        before_prolog = step.get("before_prolog")
        after_prolog = step.get("after_prolog")
        before_subformula_prolog = step.get("before_subformula_prolog")
        after_subformula_prolog = step.get("after_subformula_prolog")
        if (
            not isinstance(before_prolog, str)
            or not before_prolog
            or not isinstance(after_prolog, str)
            or not after_prolog
            or not isinstance(before_subformula_prolog, str)
            or not before_subformula_prolog
            or not isinstance(after_subformula_prolog, str)
            or not after_subformula_prolog
        ):
            raise ValueError("Sottoformule transformation mancanti")

        try:
            before = from_prolog(before_prolog)
            after = from_prolog(after_prolog)
            location, local_before, local_after = _changed_subformula(before, after)
            normalized_local_before = _normalize_formula(before_subformula_prolog)
            normalized_local_after = _normalize_formula(after_subformula_prolog)
        except (TypeError, ValueError) as exc:
            raise ValueError("Formula transformation non valida") from exc

        if before == after:
            raise ValueError("Un passaggio transformation deve modificare la formula")
        if step.get("location") != location:
            raise ValueError("Posizione della sottoformula transformation non coerente")
        if normalized_local_before != to_prolog(local_before) or normalized_local_after != to_prolog(local_after):
            raise ValueError("Sottoformule transformation non coerenti con il passaggio")

        expected_rule = (
            _equivalence_rule(local_before, local_after)
            if strategy == "equivalence_rewrite"
            else _mutation_rule(local_before, local_after)
        )
        if expected_rule is None:
            raise ValueError("Passaggio equivalente privo di una legge logica riconosciuta")
        if step.get("rule") != expected_rule:
            raise ValueError("Regola transformation non coerente con le sottoformule")

        previous = after_prolog
    if previous != final:
        raise ValueError("Formula finale transformation non coerente")


__all__ = [
    "TRANSFORMATION_VERSION",
    "build_transformation_trace",
    "validate_transformation_trace",
]
