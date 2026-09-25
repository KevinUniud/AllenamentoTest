from __future__ import annotations

import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from testlogica import generator
from testlogica.metrics import formula_atom_count, formula_binary_operator_count
from testlogica.prolog.codec import from_prolog
from testlogica.prolog_bridge import PrologBridge
from testlogica.questions import truth_value


def _truth_value_formulas(variables: list[str]) -> list[str]:
    tail = variables[-1]
    for variable in reversed(variables[1:-1]):
        tail = f"and({variable},{tail})"
    return [f"{head}({variables[0]},{tail})" for head in ("and", "or", "imp", "iff")]


class DeterministicTruthValueBridge:
    def __init__(self) -> None:
        self.assignment_variables: list[str] = []

    def assignment(self, variables: list[str], timeout: int = 10) -> list[list[tuple[str, bool]]]:
        self.assignment_variables = list(variables)
        return [[(variable, True) for variable in variables]]

    def formula_of_depth(self, depth: int, variables: list[str], timeout: int = 10) -> list[str]:
        return _truth_value_formulas(list(variables))

    def eval(self, formula: str, valuation: Any, timeout: int = 10) -> bool:
        return formula.startswith("and(")


class CacheProbeBridge(PrologBridge):
    def __init__(self) -> None:
        self.fetch_count = 0

    def some_depth_head(
        self,
        depth: int,
        variables: list[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        self.fetch_count += 1
        formulas = dict(zip(("and", "or", "imp", "iff"), _truth_value_formulas(list(variables)), strict=True))
        if head == "not":
            return [f"not({_truth_value_formulas(list(variables))[0]})"]
        return [formulas[head]]

    def some_depth_hbal(
        self,
        depth: int,
        variables: list[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        self.fetch_count += 1
        return []

    def some_depth_allvars(
        self,
        depth: int,
        variables: list[str],
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        self.fetch_count += 1
        return []


def test_partition_selection_never_bypasses_the_repetition_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_policy(*_args: Any, **_kwargs: Any) -> list[str]:
        raise RuntimeError("policy non soddisfatta")

    monkeypatch.setattr(truth_value, "_select_formulas_with_repetition_policy", reject_policy)

    selected = truth_value._sample_partitioned_options(
        rng=random.Random(7),
        left_candidates=["and(p,q)"],
        right_candidates=["or(p,q)"],
        left_count=1,
        right_count=1,
    )

    assert selected is None

@pytest.mark.parametrize("predicate_count", [4, 5])
def test_tvq_generates_requested_atom_count(predicate_count: int) -> None:
    bridge = DeterministicTruthValueBridge()

    result = generator.build_tvq(
        predicate_count=predicate_count,
        true_options_count=1,
        false_options_count=3,
        seed=17,
        bridge=bridge,  # type: ignore[arg-type]
    )

    expected_variables = list(generator.DEFAULT_VARIABLES[:predicate_count])
    assert result["predicate_count"] == predicate_count
    assert result["variables"] == expected_variables
    assert bridge.assignment_variables == expected_variables
    assert len(result["options"]) == 4
    assert sum(bool(option["is_true"]) for option in result["options"]) == 1
    for option in result["options"]:
        formula = from_prolog(option["formula_prolog"])
        assert not generator._has_excessive_negation_chain(formula)
        assert formula_atom_count(formula) == predicate_count
        assert formula_binary_operator_count(formula) == predicate_count - 1


@pytest.mark.parametrize(("predicate_count", "expected_limit"), [(4, 3), (5, 4)])
def test_tvq_propagates_binary_operator_limit(
    monkeypatch: pytest.MonkeyPatch,
    predicate_count: int,
    expected_limit: int,
) -> None:
    observed_limits: list[int] = []

    def collect_candidates(**kwargs: Any) -> list[str]:
        observed_limits.append(kwargs["max_binary_operators"])
        return _truth_value_formulas(list(kwargs["variables"]))

    monkeypatch.setattr(generator, "_collect_candidate_formulas", collect_candidates)

    generator.build_tvq(
        predicate_count=predicate_count,
        true_options_count=1,
        false_options_count=3,
        seed=23,
        bridge=DeterministicTruthValueBridge(),  # type: ignore[arg-type]
    )

    assert observed_limits == [expected_limit]


def test_formula_cache_does_not_reuse_empty_pool_across_operator_limits() -> None:
    bridge = CacheProbeBridge()
    variables = ["p", "q", "r", "s"]
    generator._FORMULA_FETCH_CACHE.clear()

    try:
        rejected = generator._get_formulas(
            bridge=bridge,
            depth=3,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
            max_binary_operators=2,
        )
        fetches_after_rejected = bridge.fetch_count

        accepted = generator._get_formulas(
            bridge=bridge,
            depth=3,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
            max_binary_operators=3,
        )
        fetches_after_accepted = bridge.fetch_count

        assert rejected == []
        assert accepted
        assert fetches_after_accepted > fetches_after_rejected
        assert all(formula_binary_operator_count(from_prolog(formula)) == 3 for formula in accepted)

        fetches_before_second_rejected = bridge.fetch_count
        assert (
            generator._get_formulas(
                bridge=bridge,
                depth=3,
                variables=variables,
                use_all=False,
                timeout=3,
                rng=random.Random(2),
                max_binary_operators=2,
            )
            == []
        )
        assert bridge.fetch_count == fetches_before_second_rejected
    finally:
        generator._FORMULA_FETCH_CACHE.clear()


def test_tvq_works_from_a_cold_generator_import() -> None:
    api_root = Path(__file__).parents[1]
    script = """
from testlogica.generator import build_tvq

class Bridge:
    def assignment(self, variables, timeout=10):
        return [[(variable, True) for variable in variables]]

    def formula_of_depth(self, depth, variables, timeout=10):
        tail = variables[-1]
        for variable in reversed(variables[1:-1]):
            tail = f"and({variable},{tail})"
        return [f"{head}({variables[0]},{tail})" for head in ("and", "or", "imp", "iff")]

    def eval(self, formula, valuation, timeout=10):
        return formula.startswith("and(")

result = build_tvq(4, 1, 3, seed=31, bridge=Bridge())
assert result["predicate_count"] == 4
assert len(result["options"]) == 4
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
@pytest.mark.parametrize("predicate_count", [4, 5])
def test_tvq_real_prolog_supports_medium_and_hard_atom_counts(predicate_count: int) -> None:
    result = generator.build_tvq(
        predicate_count=predicate_count,
        true_options_count=1,
        false_options_count=3,
        seed=41,
        bridge=PrologBridge(persistent=False),
    )

    assert result["predicate_count"] == predicate_count
    assert len(result["variables"]) == predicate_count
    assert len(result["options"]) == 4
    for option in result["options"]:
        formula = from_prolog(option["formula_prolog"])
        assert formula_atom_count(formula) == predicate_count
        assert formula_binary_operator_count(formula) == predicate_count - 1


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_tvq_standard_case_is_generable_with_one_second_budget() -> None:
    bridge = PrologBridge(persistent=True)
    generator._FORMULA_FETCH_CACHE.clear()
    try:
        for seed in range(5):
            result = generator.build_tvq(
                predicate_count=4,
                true_options_count=1,
                false_options_count=3,
                timeout=1,
                seed=seed,
                bridge=bridge,
            )
            assert len(result["options"]) == 4
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()
