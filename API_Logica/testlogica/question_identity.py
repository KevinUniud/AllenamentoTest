"""Stable identity keys used to deduplicate generated batch questions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_truth_value_options(options: list[Any]) -> list[dict[str, Any]]:
    """Return the semantic option content without presentation order."""
    normalized = [
        {
            "formula_prolog": option.get("formula_prolog"),
            "is_true": option.get("is_true"),
        }
        if isinstance(option, dict)
        else {"formula_prolog": option, "is_true": None}
        for option in options
    ]
    return sorted(
        normalized,
        key=lambda option: json.dumps(option, sort_keys=True, ensure_ascii=False),
    )


def _canonical_logical_consequence_options(options: list[Any]) -> list[dict[str, Any]]:
    """Return formulas with their semantic labels, independent of UI order."""
    normalized = [
        {
            "formula_prolog": option.get("formula_prolog"),
            "is_consequence": option.get("is_consequence"),
        }
        if isinstance(option, dict)
        else {"formula_prolog": option, "is_consequence": None}
        for option in options
    ]
    return sorted(
        normalized,
        key=lambda option: json.dumps(option, sort_keys=True, ensure_ascii=False),
    )


def question_identity_key(operation: str, result: Any) -> str:
    if not isinstance(result, dict):
        return f"{operation}|{json.dumps(result, sort_keys=True, ensure_ascii=False)}"

    if (
        operation == "build_ex_depth"
        and isinstance(result.get("original_formula"), dict)
        and isinstance(result.get("modified_formula"), dict)
    ):
        identity = {
            "original_formula": result["original_formula"].get("formula_prolog"),
            "modified_formula": result["modified_formula"].get("formula_prolog"),
            "rewrite_steps": result.get("rewrite_steps"),
            "variables": result.get("variables"),
            "atom_count": result.get("atom_count"),
        }
    elif operation == "build_logical_consequence_question" and isinstance(result.get("options"), list):
        identity = {
            "type": result.get("type"),
            "question_prolog": result.get("question_prolog"),
            "variable_count": result.get("variable_count"),
            "correct_options_count": result.get("correct_options_count"),
            "wrong_options_count": result.get("wrong_options_count"),
            "variables": result.get("variables"),
            "options": _canonical_logical_consequence_options(result.get("options", [])),
            "source": result.get("source"),
        }
    elif "question_text" in result:
        identity = {"question_text": result.get("question_text"), "subtype": result.get("subtype")}
    elif "question_prolog" in result:
        identity = {"question_prolog": result.get("question_prolog")}
    elif operation == "build_tvq" and isinstance(result.get("information"), list):
        truth_value_options = result.get("options")
        identity = {
            "information": result.get("information"),
            "predicate_count": result.get("predicate_count"),
            "options": _canonical_truth_value_options(
                truth_value_options if isinstance(truth_value_options, list) else []
            ),
        }
    else:
        identity = result

    return f"{operation}|{json.dumps(identity, sort_keys=True, ensure_ascii=False)}"


def question_id(operation: str, result: Any) -> str:
    """Restituisce un identificatore stabile e non reversibile per una domanda."""
    identity = question_identity_key(operation, result).encode("utf-8")
    return "question-" + hashlib.sha256(identity).hexdigest()[:24]
