from __future__ import annotations

import itertools
import shutil
from collections.abc import Mapping
from typing import Any

import pytest

from testlogica.ast_logic import And, Iff, Imp, Not, Or, Var
from testlogica.generator import _commutative_signature
from testlogica.prolog.codec import collect_variables, from_prolog
from testlogica.prolog_bridge import PrologBridge
from testlogica.question_identity import question_id
from testlogica.questions.logical_consequence import build_logical_consequence_question

VARIABLES = ("p", "q", "r", "s")


def _evaluate(expression: Any, valuation: Mapping[str, bool]) -> bool:
    if isinstance(expression, Var):
        return valuation[expression.name]
    if isinstance(expression, Not):
        return not _evaluate(expression.expr, valuation)
    if isinstance(expression, And):
        return _evaluate(expression.left, valuation) and _evaluate(expression.right, valuation)
    if isinstance(expression, Or):
        return _evaluate(expression.left, valuation) or _evaluate(expression.right, valuation)
    if isinstance(expression, Imp):
        return not _evaluate(expression.left, valuation) or _evaluate(expression.right, valuation)
    if isinstance(expression, Iff):
        return _evaluate(expression.left, valuation) == _evaluate(expression.right, valuation)
    raise TypeError(f"Espressione non supportata: {type(expression)!r}")


def _is_logical_consequence(
    question: str,
    option: str,
    variables: tuple[str, ...] = VARIABLES,
) -> bool:
    question_ast = from_prolog(question)
    option_ast = from_prolog(option)
    valuations = (
        dict(zip(variables, values, strict=True))
        for values in itertools.product((False, True), repeat=len(variables))
    )
    return all(
        not _evaluate(question_ast, valuation) or _evaluate(option_ast, valuation)
        for valuation in valuations
    )


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_one_hundred_medium_logical_consequence_questions_are_valid_and_diverse() -> None:
    bridge = PrologBridge(persistent=True)
    results: list[dict[str, Any]] = []
    try:
        for seed in range(100):
            results.append(
                build_logical_consequence_question(
                    variable_count=4,
                    correct_options_count=1,
                    wrong_options_count=3,
                    allow_spoken_mode=False,
                    timeout=10,
                    seed=seed,
                    bridge=bridge,
                )
            )
    finally:
        bridge.close()

    identities: set[str] = set()
    complete_contents: set[tuple[str, tuple[tuple[str, bool], ...]]] = set()
    question_formulas: set[str] = set()

    for result in results:
        question = result["question_prolog"]
        options = result["options"]
        option_formulas = [option["formula_prolog"] for option in options]
        option_labels = [option["is_consequence"] for option in options]

        assert set(collect_variables(from_prolog(question))) == set(VARIABLES)
        assert len(options) == 4
        assert option_labels.count(True) == 1
        assert option_labels.count(False) == 3
        assert option_labels == [_is_logical_consequence(question, option) for option in option_formulas]
        assert len({_commutative_signature(option) for option in option_formulas}) == 4
        assert sorted(len(collect_variables(from_prolog(option))) for option in option_formulas) == [2, 2, 3, 3]

        canonical_question = _commutative_signature(question)
        canonical_options = tuple(
            sorted(
                (_commutative_signature(option["formula_prolog"]), option["is_consequence"])
                for option in options
            )
        )
        identities.add(question_id("build_logical_consequence_question", result))
        complete_contents.add((canonical_question, canonical_options))
        question_formulas.add(canonical_question)

    # La domanda più le quattro opzioni costituiscono il contenuto didattico completo.
    assert len(identities) >= 95
    assert len(complete_contents) >= 95
    assert len(question_formulas) >= 40


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_two_variable_questions_support_every_eight_option_split() -> None:
    variables = ("p", "q")
    bridge = PrologBridge(persistent=True)
    try:
        for correct_count in range(1, 8):
            wrong_count = 8 - correct_count
            result = build_logical_consequence_question(
                variable_count=2,
                correct_options_count=correct_count,
                wrong_options_count=wrong_count,
                allow_spoken_mode=False,
                timeout=10,
                seed=0,
                bridge=bridge,
            )

            question = result["question_prolog"]
            options = result["options"]
            formulas = [option["formula_prolog"] for option in options]
            labels = [option["is_consequence"] for option in options]

            assert set(collect_variables(from_prolog(question))) == set(variables)
            assert len(options) == 8
            assert labels.count(True) == correct_count
            assert labels.count(False) == wrong_count
            assert labels == [
                _is_logical_consequence(question, formula, variables)
                for formula in formulas
            ]
            assert len({_commutative_signature(formula) for formula in formulas}) == 8
    finally:
        bridge.close()
