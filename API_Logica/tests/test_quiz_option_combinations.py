from __future__ import annotations

import shutil
from collections.abc import Iterator
from typing import Any

import pytest

from server.schemas import MultipleQuestionsRequest
from testlogica import generator, orchestrator
from testlogica.constants import DEFAULT_VARIABLES
from testlogica.metrics import formula_atom_count
from testlogica.prolog.codec import collect_variables, from_prolog
from testlogica.prolog_bridge import PrologBridge

QUESTION_TYPES = (
    "equivalence",
    "truth-value",
    "logical-consequence",
    "translation",
    "quantifier-negation",
)
DIFFICULTIES = {
    "easy": (3, 0.25),
    "medium": (4, 0.50),
    "hard": (5, 0.75),
}
TRANSLATION_NAMES = ["Sofia", "Chiara", "Martina", "Luca", "Giulia"]
TRANSLATION_ACTIONS = ["studia", "corre", "legge", "nuota", "ascolta"]

QUIZ_OPTION_MATRIX = tuple(
    pytest.param(
        question_type,
        difficulty,
        spoken_mode,
        7_000 + type_index * 100 + difficulty_index * 10 + int(spoken_mode),
        id=f"{question_type}-{difficulty}-spoken-{str(spoken_mode).lower()}",
    )
    for type_index, question_type in enumerate(QUESTION_TYPES)
    for difficulty_index, difficulty in enumerate(DIFFICULTIES)
    for spoken_mode in (False, True)
)


@pytest.fixture(scope="module")
def real_prolog_bridge() -> Iterator[PrologBridge]:
    if shutil.which("swipl") is None:
        pytest.skip("SWI-Prolog non disponibile: matrice delle opzioni quiz non eseguibile")

    bridge = PrologBridge(persistent=True)
    bridge.ensure_available()
    generator._FORMULA_FETCH_CACHE.clear()
    try:
        yield bridge
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()


def _build_case(
    question_type: str,
    difficulty: str,
    spoken_mode: bool,
    seed: int,
    bridge: PrologBridge,
) -> dict[str, Any] | str:
    atom_count, quantifier_ratio = DIFFICULTIES[difficulty]

    if question_type == "equivalence":
        return generator.build_ex_depth(
            use_all=False,
            wrong_answers_count=3,
            allow_spoken_mode=spoken_mode,
            timeout=10,
            seed=seed,
            bridge=bridge,
        )
    if question_type == "truth-value":
        return generator.build_tvq(
            predicate_count=atom_count,
            true_options_count=1,
            false_options_count=3,
            allow_spoken_mode=spoken_mode,
            timeout=10,
            seed=seed,
            bridge=bridge,
        )
    if question_type == "logical-consequence":
        return generator.build_logical_consequence_question(
            variable_count=atom_count,
            correct_options_count=1,
            wrong_options_count=3,
            allow_spoken_mode=spoken_mode,
            timeout=10,
            seed=seed,
            bridge=bridge,
        )
    if question_type == "translation":
        return generator.build_translation_question(
            mode="auto",
            quantifier_ratio=quantifier_ratio,
            wrong_options_count=3,
            names_pool=TRANSLATION_NAMES,
            people_count=3,
            actions_pool=TRANSLATION_ACTIONS,
            allow_spoken_mode=spoken_mode,
            timeout=10,
            seed=seed,
        )
    if question_type == "quantifier-negation":
        return generator.generate_formula_by_variable_count(
            variable_count=atom_count,
            use_all=False,
            allow_spoken_mode=spoken_mode,
            timeout=10,
            seed=seed,
            bridge=bridge,
        )
    raise AssertionError(f"Tipologia quiz non coperta dal test: {question_type}")


def _assert_option_contract(
    options: list[dict[str, Any]],
    *,
    formula_key: str,
    correctness_key: str,
) -> None:
    assert len(options) == 4
    assert sum(bool(option[correctness_key]) for option in options) == 1
    formulas = [option[formula_key] for option in options]
    assert len(set(formulas)) == 4
    assert all(option["construction"]["final_formula_prolog"] == option[formula_key] for option in options)


def _assert_case_contract(
    question_type: str,
    difficulty: str,
    spoken_mode: bool,
    result: dict[str, Any] | str,
) -> None:
    atom_count = DIFFICULTIES[difficulty][0]

    if question_type == "quantifier-negation":
        assert isinstance(result, str)
        formula = from_prolog(result)
        assert set(collect_variables(formula)) == set(DEFAULT_VARIABLES[:atom_count])
        assert formula_atom_count(formula) >= atom_count
        if spoken_mode:
            assert generator._formula_is_spoken_friendly(result, max_nested_negations=0)
        return

    assert isinstance(result, dict)

    if question_type == "equivalence":
        assert result["source"] == "prolog_builder"
        assert result["spoken_mode"] is spoken_mode
        assert result["atom_count"] == 3
        assert len(result["variables"]) == 3
        assert set(collect_variables(from_prolog(result["question_prolog"]))) == set(result["variables"])
        assert len(result["wrong_answers_prolog"]) == 3
        _assert_option_contract(
            result["options"],
            formula_key="formula_prolog",
            correctness_key="is_correct",
        )
        if spoken_mode:
            exposed = [result["question_prolog"], *(
                option["formula_prolog"] for option in result["options"]
            )]
            for option in result["options"]:
                trace = option.get("transformation", {})
                exposed.extend(
                    [
                        trace.get("source_formula_prolog", result["question_prolog"]),
                        trace.get("final_formula_prolog", option["formula_prolog"]),
                    ]
                )
                for step in trace.get("steps", []):
                    exposed.extend(
                        step[field]
                        for field in (
                            "before_prolog",
                            "after_prolog",
                            "before_subformula_prolog",
                            "after_subformula_prolog",
                        )
                    )
            assert all(generator._formula_is_spoken_friendly(item) for item in exposed)
        return

    if question_type == "truth-value":
        assert result["type"] == "truth_value_options_question"
        assert result["source"] == "prolog_assignment_and_eval"
        assert result["spoken_mode"] is spoken_mode
        assert result["predicate_count"] == atom_count
        assert len(result["variables"]) == atom_count
        assert len(result["information"]) == atom_count
        _assert_option_contract(
            result["options"],
            formula_key="formula_prolog",
            correctness_key="is_true",
        )
        for option in result["options"]:
            formula = from_prolog(option["formula_prolog"])
            assert formula_atom_count(formula) == atom_count
            assert set(collect_variables(formula)) == set(result["variables"])
        if spoken_mode:
            assert all(
                generator._formula_is_spoken_friendly(option["formula_prolog"])
                for option in result["options"]
            )
        return

    if question_type == "logical-consequence":
        assert result["type"] == "logical_consequence_question"
        assert result["source"] == "prolog_implies_formula"
        assert result["spoken_mode"] is spoken_mode
        assert result["variable_count"] == atom_count
        assert len(result["variables"]) == atom_count
        question = from_prolog(result["question_prolog"])
        assert formula_atom_count(question) == atom_count
        assert set(collect_variables(question)) == set(result["variables"])
        _assert_option_contract(
            result["options"],
            formula_key="formula_prolog",
            correctness_key="is_consequence",
        )
        if spoken_mode:
            assert all(
                generator._formula_is_spoken_friendly(item)
                for item in [result["question_prolog"], *(
                    option["formula_prolog"] for option in result["options"]
                )]
            )
        return

    if question_type == "translation":
        assert result["type"] == "translation_question"
        assert result["spoken_mode"] is spoken_mode
        assert result["subtype"] in {"propositional", "quantifier"}
        assert result["metadata"]["source"] == "rule_generator"
        assert result["metadata"]["people_count"] == 3
        assert result["metadata"]["actual_people_count"] == 3
        _assert_option_contract(
            result["options"],
            formula_key="formula",
            correctness_key="is_correct",
        )
        return

    raise AssertionError(f"Tipologia quiz senza contratto verificato: {question_type}")


@pytest.mark.parametrize(
    ("question_type", "difficulty", "spoken_mode", "seed"),
    QUIZ_OPTION_MATRIX,
)
def test_every_question_type_difficulty_and_spoken_mode_combination_is_generable(
    question_type: str,
    difficulty: str,
    spoken_mode: bool,
    seed: int,
    real_prolog_bridge: PrologBridge,
) -> None:
    assert len(QUIZ_OPTION_MATRIX) == 5 * 3 * 2 == 30

    result = _build_case(
        question_type,
        difficulty,
        spoken_mode,
        seed,
        real_prolog_bridge,
    )

    _assert_case_contract(question_type, difficulty, spoken_mode, result)


def test_all_remote_quiz_operations_validate_and_run_in_the_mixed_batch(
    real_prolog_bridge: PrologBridge,
) -> None:
    payloads = [
        {
            "operation": "build_ex_depth",
            "payload": {
                "use_all": False,
                "wrong_answers_count": 3,
                "allow_spoken_mode": True,
                "timeout": 10,
            },
        },
        {
            "operation": "build_tvq",
            "payload": {
                "predicate_count": 4,
                "true_options_count": 1,
                "false_options_count": 3,
                "allow_spoken_mode": True,
                "timeout": 10,
            },
        },
        {
            "operation": "build_logical_consequence_question",
            "payload": {
                "variable_count": 4,
                "correct_options_count": 1,
                "wrong_options_count": 3,
                "allow_spoken_mode": True,
                "timeout": 10,
            },
        },
        {
            "operation": "build_translation_question",
            "payload": {
                "mode": "auto",
                "quantifier_ratio": 0.5,
                "wrong_options_count": 3,
                "names_pool": TRANSLATION_NAMES,
                "people_count": 3,
                "actions_pool": TRANSLATION_ACTIONS,
                "allow_spoken_mode": True,
                "timeout": 10,
            },
        },
    ]
    request = MultipleQuestionsRequest(questions=payloads, seed=8_200)
    validated_questions = [item.model_dump() for item in request.questions]

    assert validated_questions == payloads

    result = orchestrator.multiple_questions(
        validated_questions,
        seed=request.seed,
        bridge=real_prolog_bridge,
    )

    assert result["count"] == 4
    assert result["success_count"] == 4
    assert result["failed_count"] == 0
    assert {item["operation"] for item in result["questions"]} == {
        item["operation"] for item in payloads
    }
    assert all(item["status"] == "ok" for item in result["questions"])
    assert all(item["result"]["question_id"] for item in result["questions"])
