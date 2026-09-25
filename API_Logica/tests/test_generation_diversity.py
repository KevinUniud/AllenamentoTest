from __future__ import annotations

import random
import shutil
import time
from collections.abc import Sequence

import pytest

from testlogica import generator
from testlogica.orchestrator import _pick_wrongs
from testlogica.prolog_bridge import PrologBridge

DEFAULT_STRESS_SEED = 20260906 + 400_000


def test_cached_formula_pool_reapplies_seed_dependent_diversification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = PrologBridge(persistent=True)
    variables = ["p", "q", "r"]
    cache_key = ("PrologBridge", 2, tuple(variables), False, generator.MAX_BINARY_OPERATORS)
    generator._FORMULA_FETCH_CACHE.clear()
    generator._FORMULA_FETCH_CACHE[cache_key] = (
        "and(p,and(q,r))",
        "or(p,or(q,r))",
        "imp(p,imp(q,r))",
        "iff(p,iff(q,r))",
    )
    calls: list[str] = []

    def permute(formulas: Sequence[str], _variables: Sequence[str], _rng: random.Random) -> list[str]:
        calls.append("permute")
        return list(formulas)

    def scatter(formulas: Sequence[str], _rng: random.Random) -> list[str]:
        calls.append("scatter")
        return list(formulas)

    monkeypatch.setattr(generator, "_permute_vars", permute)
    monkeypatch.setattr(generator, "_scatter_vars", scatter)
    try:
        formulas = generator._get_formulas(
            bridge=bridge,
            depth=2,
            variables=variables,
            use_all=False,
            timeout=10,
            rng=random.Random(17),
        )
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()

    assert formulas
    assert calls == ["permute", "scatter"]


def test_variable_permutation_is_independent_for_each_candidate() -> None:
    class ScriptedShuffle:
        def __init__(self) -> None:
            self.index = 0

        def shuffle(self, values: list[str]) -> None:
            permutations = (["q", "r", "p"], ["r", "p", "q"])
            values[:] = permutations[self.index]
            self.index += 1

    formulas = generator._permute_vars(
        ["and(p,and(q,r))", "or(p,or(q,r))"],
        ["p", "q", "r"],
        ScriptedShuffle(),  # type: ignore[arg-type]
    )

    assert formulas == ["and(q,and(r,p))", "or(r,or(p,q))"]


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_seeded_generation_is_identical_with_cold_and_warm_cache() -> None:
    bridge = PrologBridge(persistent=True)
    generator._FORMULA_FETCH_CACHE.clear()
    try:
        # Tre variabili percorrono anche permutazione, scattering e selezione
        # casuale: il test intercetta quindi consumo di RNG nel solo fetch.
        cold = generator.generate_formula_by_variable_count(3, seed=123, bridge=bridge)
        warm = generator.generate_formula_by_variable_count(3, seed=123, bridge=bridge)
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()

    assert cold == warm


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_one_second_budget_keeps_five_variable_generation_bounded() -> None:
    bridge = PrologBridge(persistent=True)
    generator._FORMULA_FETCH_CACHE.clear()
    started = time.monotonic()
    try:
        formula = generator.generate_formula_by_variable_count(
            5,
            timeout=1,
            seed=41,
            bridge=bridge,
        )
    finally:
        elapsed = time.monotonic() - started
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()

    assert formula
    assert elapsed < 1.25


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_quantifier_base_formulas_are_semantically_diverse_over_default_seeds() -> None:
    bridge = PrologBridge(persistent=True)
    generator._FORMULA_FETCH_CACHE.clear()
    pairs: set[tuple[str, int]] = set()
    formulas: set[str] = set()
    try:
        for offset in range(100):
            seed = DEFAULT_STRESS_SEED + offset
            formula = generator.generate_formula_by_variable_count(4, seed=seed, bridge=bridge)
            quantifier = random.Random(seed).choice(("∀", "∃"))
            signature = generator._formula_truth_signature(formula, ("p", "q", "r", "s"))
            formulas.add(formula)
            pairs.add((quantifier, signature))
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()

    assert len(formulas) >= 95
    assert len(pairs) >= 95


class DiverseDistractorBridge:
    def some_step_neq(self, _formula: str, limit: int, timeout: int = 10) -> list[str]:
        del limit, timeout
        return [
            "or(p,q)",
            "imp(p,q)",
            "iff(p,q)",
            "and(not(p),q)",
            "and(p,not(q))",
        ]

    def one_step_neq(self, _formula: str, timeout: int = 10) -> list[str]:
        del timeout
        return []

    def some_neq(self, _formula: str, max_steps: int, limit: int, timeout: int = 10) -> list[str]:
        del max_steps, limit, timeout
        return []

    def non_equivalent_distraction(self, _formula: str, max_steps: int, timeout: int = 10) -> list[str]:
        del max_steps, timeout
        return []


def test_distractor_seed_changes_the_selected_set_not_only_its_order() -> None:
    bridge = DiverseDistractorBridge()
    selected_sets: set[frozenset[str]] = set()

    for seed in range(5):
        selected = _pick_wrongs(
            question_prolog="and(p,q)",
            correct_prolog="and(q,p)",
            variables=["p", "q"],
            target_atom_count=2,
            wrong_answers_count=3,
            operator_cycles=0,
            from_correct_answer=False,
            bridge=bridge,  # type: ignore[arg-type]
            filter_wrong_batch=lambda candidates: list(candidates),
            seed=seed,
        )
        assert isinstance(selected, list)
        assert len(selected) == len(set(selected)) == 3
        selected_sets.add(frozenset(selected))

    assert len(selected_sets) > 1
