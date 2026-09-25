from __future__ import annotations

import random
import shutil
from unittest.mock import patch

import pytest

from testlogica import generator, orchestrator
from testlogica.metrics import formula_atom_count, formula_binary_operator_count
from testlogica.prolog.codec import collect_variables, from_prolog
from testlogica.prolog.exceptions import PrologExecutionError
from testlogica.prolog_bridge import PrologBridge
from testlogica.validation import GenerationDeadlineExceeded


def _balanced_formula(variables: list[str]) -> str:
    if len(variables) == 1:
        return variables[0]
    split = len(variables) // 2
    return f"and({_balanced_formula(variables[:split])},{_balanced_formula(variables[split:])})"


class ExactVariablesBridge:
    def formula_of_depth(self, depth: int, variables: list[str], timeout: int = 10) -> list[str]:
        return [_balanced_formula(list(variables))]


class SpokenTrackingBridge(ExactVariablesBridge):
    def __init__(self) -> None:
        self.to_nnf_calls = 0
        self.expand_implications_calls = 0

    def to_nnf(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        self.to_nnf_calls += 1
        return [formula]

    def expand_implications(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        self.expand_implications_calls += 1
        return [formula]


class NegationChainBridge:
    def formula_of_depth(self, depth: int, variables: list[str], timeout: int = 10) -> list[str]:
        del depth, variables, timeout
        return [
            "and(p,q)",
            "not(not(and(p,q)))",
            "not(not(not(and(p,q))))",
            "and(not(not(not(p))),q)",
        ]


class NegationChainSpokenBridge(NegationChainBridge):
    def to_nnf(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        return [formula]

    def expand_implications(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        return [formula]


def _cache_pool() -> list[str]:
    operators = ("and", "or", "imp", "iff")
    return [
        f"{outer}({first},{inner}({second},{third}))"
        for first, second, third in (
            ("p", "q", "r"),
            ("p", "r", "q"),
            ("q", "p", "r"),
            ("q", "r", "p"),
            ("r", "p", "q"),
            ("r", "q", "p"),
        )
        for outer in operators
        for inner in operators
    ]


def _head_biased_cache_pool() -> list[str]:
    operators = ("and", "or", "imp", "iff")
    return [
        f"and({first},{inner}({second},{third}))"
        for first, second, third in (
            ("p", "q", "r"),
            ("p", "r", "q"),
            ("q", "p", "r"),
            ("q", "r", "p"),
            ("r", "p", "q"),
            ("r", "q", "p"),
        )
        for inner in operators
    ]


class SwitchableCacheBridge(PrologBridge):
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.fetch_count = 0

    def _result(self) -> list[str]:
        self.fetch_count += 1
        if self.mode == "empty":
            return []
        if self.mode == "partial":
            return _cache_pool()[:1]
        if self.mode == "biased":
            return _head_biased_cache_pool()
        return _cache_pool()

    def some_depth_head(self, *args, **kwargs) -> list[str]:
        return self._result()

    def some_depth_hbal(self, *args, **kwargs) -> list[str]:
        return self._result()

    def some_depth_allvars(self, *args, **kwargs) -> list[str]:
        return self._result()


class TimeoutBridge:
    def formula_of_depth(self, *args, **kwargs) -> list[str]:
        raise PrologExecutionError("Timeout durante l'esecuzione della query Prolog")


class AllFormulasBridge:
    def __init__(self) -> None:
        self.fetch_count = 0

    def all_depth_allvars(self, *args, **kwargs) -> list[str]:
        self.fetch_count += 1
        return ["and(p,q)"]


@pytest.mark.parametrize("variable_count", [4, 5])
def test_generate_formula_admits_the_minimum_operator_count_for_all_variables(variable_count: int) -> None:
    formula = generator.generate_formula_by_variable_count(
        variable_count,
        seed=17,
        bridge=ExactVariablesBridge(),  # type: ignore[arg-type]
    )
    expression = from_prolog(formula)

    assert sorted(collect_variables(expression)) == sorted(generator.DEFAULT_VARIABLES[:variable_count])
    assert formula_atom_count(expression) == variable_count
    assert formula_binary_operator_count(expression) == variable_count - 1


def test_explicit_three_variable_generation_keeps_the_short_formula_limit() -> None:
    variables = list(generator.DEFAULT_VARIABLES[:3])
    formulas = generator._get_formulas(
        bridge=ExactVariablesBridge(),  # type: ignore[arg-type]
        depth=2,
        variables=variables,
        use_all=False,
        timeout=10,
        rng=random.Random(17),
        max_binary_operators=generator.MAX_BINARY_OPERATORS,
    )

    assert formulas == [_balanced_formula(variables)]


def test_formula_pool_rejects_excessive_negation_chains() -> None:
    formulas = generator._get_formulas(
        bridge=NegationChainBridge(),  # type: ignore[arg-type]
        depth=3,
        variables=["p", "q"],
        use_all=False,
        timeout=10,
        rng=random.Random(17),
    )

    assert set(formulas) == {"and(p,q)", "not(not(and(p,q)))"}
    assert all(not generator._has_excessive_negation_chain(formula) for formula in formulas)


def test_spoken_formula_pool_uses_a_stricter_branch_budget_only_in_spoken_mode() -> None:
    common = {
        "bridge": NegationChainBridge(),  # type: ignore[arg-type]
        "depth": 3,
        "variables": ["p", "q"],
        "use_all": False,
        "timeout": 10,
    }
    symbolic = generator._get_formulas(rng=random.Random(17), **common)
    spoken = generator._get_formulas(
        rng=random.Random(17),
        spoken_negation_limit=generator.MAX_SPOKEN_NESTED_NEGATIONS,
        **common,
    )

    assert "not(not(and(p,q)))" in symbolic
    assert spoken == ["and(p,q)"]


def test_spoken_formula_endpoint_uses_negation_free_candidates() -> None:
    # Il client aggiunge un ¬ esterno nei quiz di negazione dei quantificatori.
    # La formula di base parlata deve quindi arrivare senza negazioni interne.
    formula = generator.generate_formula(
        depth=3,
        variables=["p", "q"],
        seed=17,
        bridge=NegationChainSpokenBridge(),  # type: ignore[arg-type]
        allow_spoken_mode=True,
    )

    assert formula == "and(p,q)"
    assert generator._formula_is_spoken_friendly(formula, max_nested_negations=0)


def test_spoken_candidate_collector_prefilters_the_fetched_pool() -> None:
    with (
        patch("testlogica.orchestrator.generator._get_formulas", return_value=[]) as fetch,
        patch("testlogica.orchestrator._transform_answer_candidates", return_value=[]),
    ):
        orchestrator._collect_candidate_formulas(
            bridge=object(),  # type: ignore[arg-type]
            variables=["p", "q"],
            required_options=4,
            rng=random.Random(17),
            timeout_provider=lambda _requested: 3,
            operator_cycles=None,
            spoken_only=True,
        )

    assert fetch.call_count > 0
    assert all(
        call.kwargs["spoken_negation_limit"] == generator.MAX_SPOKEN_NESTED_NEGATIONS
        for call in fetch.call_args_list
    )


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("not(not(and(p,q)))", False),
        ("not(not(not(and(p,q))))", True),
        ("and(not(p),not(not(q)))", False),
        ("and(p,not(not(not(q))))", True),
    ],
)
def test_excessive_negation_detection_checks_every_subformula(formula: str, expected: bool) -> None:
    assert generator._has_excessive_negation_chain(formula) is expected


def test_spoken_formula_filter_rejects_excessive_negation_chains() -> None:
    # La doppia negazione resta valida nel simbolico, ma non viene selezionata
    # per la resa parlata perché produrrebbe la stessa locuzione due volte.
    assert not generator._has_excessive_negation_chain("not(not(and(p,q)))")
    assert not generator._formula_is_spoken_friendly("not(not(and(p,q)))")
    assert not generator._formula_is_spoken_friendly("not(not(not(and(p,q))))")
    assert generator._formula_is_spoken_friendly("and(not(p),not(q))")


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("not(not(or(not(r),or(not(p),q))))", True),
        ("and(p,not(not(or(not(q),r))))", True),
        ("not(or(not(p),not(q)))", True),
        ("and(not(p),and(not(q),not(r)))", False),
    ],
)
def test_spoken_negation_detection_follows_nested_formula_branches(
    formula: str,
    expected: bool,
) -> None:
    # I primi tre casi non superano la vecchia catena adiacente: erano quindi
    # il buco della precedente verifica, ma il renderer pronunciava le
    # negazioni annidate sullo stesso ramo come una ripetizione consecutiva.
    assert generator._has_excessive_spoken_negation_nesting(formula) is expected
    if expected:
        assert not generator._formula_is_spoken_friendly(formula)


def test_spoken_json_pipeline_reuses_the_supplied_bridge_without_fallback() -> None:
    bridge = SpokenTrackingBridge()

    result = generator.generate_formula_by_variable_count_json(
        variable_count=2,
        seed=7,
        bridge=bridge,  # type: ignore[arg-type]
        allow_spoken_mode=True,
    )

    assert result["spoken_fallback_used"] is False
    assert bridge.to_nnf_calls == 1
    assert bridge.expand_implications_calls == 1


def test_spoken_json_wrappers_forward_the_mode_to_formula_selection() -> None:
    bridge = SpokenTrackingBridge()
    with patch(
        "testlogica.generator.generate_formula",
        return_value="and(p,q)",
    ) as generate:
        generator.generate_formula_json(
            depth=2,
            variables=["p", "q"],
            seed=7,
            bridge=bridge,  # type: ignore[arg-type]
            allow_spoken_mode=True,
        )
    assert generate.call_args.kwargs["allow_spoken_mode"] is True

    with patch(
        "testlogica.generator.generate_formula_by_variable_count",
        return_value="and(p,q)",
    ) as generate_by_count:
        generator.generate_formula_by_variable_count_json(
            variable_count=2,
            seed=7,
            bridge=bridge,  # type: ignore[arg-type]
            allow_spoken_mode=True,
        )
    assert generate_by_count.call_args.kwargs["allow_spoken_mode"] is True


@pytest.mark.parametrize("initial_mode", ["empty", "partial"])
def test_empty_or_partial_formula_pool_does_not_poison_cache(initial_mode: str) -> None:
    bridge = SwitchableCacheBridge(initial_mode)
    variables = ["p", "q", "r"]
    cache_key = (
        bridge.__class__.__name__,
        2,
        tuple(variables),
        False,
        generator.MAX_BINARY_OPERATORS,
    )
    generator._FORMULA_FETCH_CACHE.clear()

    try:
        first = generator._get_formulas(
            bridge=bridge,
            depth=2,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
        )
        first_fetch_count = bridge.fetch_count

        assert len(first) <= 1
        assert cache_key not in generator._FORMULA_FETCH_CACHE

        bridge.mode = "complete"
        second = generator._get_formulas(
            bridge=bridge,
            depth=2,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
        )

        assert len(second) > len(first)
        assert bridge.fetch_count > first_fetch_count
        assert cache_key in generator._FORMULA_FETCH_CACHE
        assert len(generator._FORMULA_FETCH_CACHE[cache_key]) >= generator._MIN_CACHEABLE_FORMULA_POOL
    finally:
        generator._FORMULA_FETCH_CACHE.clear()


def test_single_head_formula_pool_does_not_poison_cache() -> None:
    bridge = SwitchableCacheBridge("biased")
    variables = ["p", "q", "r"]
    cache_key = (
        bridge.__class__.__name__,
        2,
        tuple(variables),
        False,
        generator.MAX_BINARY_OPERATORS,
    )
    generator._FORMULA_FETCH_CACHE.clear()

    try:
        first = generator._get_formulas(
            bridge=bridge,
            depth=2,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
        )
        first_fetch_count = bridge.fetch_count

        assert first
        assert {_formula.split("(", 1)[0] for _formula in first} == {"and"}
        assert cache_key not in generator._FORMULA_FETCH_CACHE

        bridge.mode = "complete"
        second = generator._get_formulas(
            bridge=bridge,
            depth=2,
            variables=variables,
            use_all=False,
            timeout=3,
            rng=random.Random(1),
        )

        assert bridge.fetch_count > first_fetch_count
        assert len({_formula.split("(", 1)[0] for _formula in second}) >= 3
        assert cache_key in generator._FORMULA_FETCH_CACHE
    finally:
        generator._FORMULA_FETCH_CACHE.clear()


def test_bridge_timeout_is_not_masked_as_an_empty_formula_pool() -> None:
    with pytest.raises(PrologExecutionError, match="Timeout"):
        generator.generate_formula(
            depth=1,
            variables=["p"],
            timeout=10,
            bridge=TimeoutBridge(),  # type: ignore[arg-type]
        )


def test_result_completed_after_formula_deadline_is_rejected() -> None:
    with (
        patch("testlogica.generator.time.monotonic", side_effect=[10.0, 10.0, 10.0, 11.01]),
        pytest.raises(GenerationDeadlineExceeded, match="Tempo complessivo"),
    ):
        generator.generate_formula(
            depth=1,
            variables=["p"],
            timeout=1,
            bridge=ExactVariablesBridge(),  # type: ignore[arg-type]
        )


def test_use_all_rejects_unsafe_formula_space_before_calling_bridge() -> None:
    bridge = AllFormulasBridge()

    with pytest.raises(ValueError, match="use_all=false"):
        generator.generate_formula(
            depth=3,
            variables=["p", "q", "r", "s", "t"],
            use_all=True,
            timeout=10,
            bridge=bridge,  # type: ignore[arg-type]
        )

    assert bridge.fetch_count == 0


def test_use_all_keeps_safe_shallow_enumeration_available() -> None:
    bridge = AllFormulasBridge()

    formula = generator.generate_formula(
        depth=1,
        variables=["p", "q"],
        use_all=True,
        timeout=10,
        seed=1,
        bridge=bridge,  # type: ignore[arg-type]
    )

    assert formula == "and(p,q)"
    assert bridge.fetch_count == 1


def test_more_than_five_variables_are_rejected_before_bridge_use() -> None:
    bridge = AllFormulasBridge()
    variables = [f"p{index}" for index in range(6)]

    with pytest.raises(ValueError, match="al massimo 5"):
        generator.generate_formula(
            depth=3,
            variables=variables,
            timeout=10,
            bridge=bridge,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="non può superare 5"):
        generator.generate_formula_by_variable_count(
            variable_count=6,
            timeout=10,
            bridge=bridge,  # type: ignore[arg-type]
        )

    assert bridge.fetch_count == 0


def test_impossible_binary_operator_budget_skips_prolog_search() -> None:
    bridge = AllFormulasBridge()

    formulas = generator._get_formulas(
        bridge=bridge,  # type: ignore[arg-type]
        depth=3,
        variables=["p", "q", "r", "s"],
        use_all=False,
        timeout=10,
        rng=random.Random(1),
        max_binary_operators=2,
    )

    assert formulas == []
    assert bridge.fetch_count == 0


def test_equivalence_rejects_unreliable_distractor_counts_before_bridge_use() -> None:
    bridge = AllFormulasBridge()

    with pytest.raises(ValueError, match="non può superare 21"):
        generator.build_ex_depth(
            wrong_answers_count=22,
            bridge=bridge,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="non può superare 3"):
        generator.build_exercise(
            "and(p,q)",
            wrong_answers_count=4,
            bridge=bridge,  # type: ignore[arg-type]
        )

    assert bridge.fetch_count == 0


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        ("p", "almeno 2 atomi"),
        ("and(p,p)", "due atomi uguali"),
        ("and(p,and(q,and(r,s)))", "più di 2 operatori binari"),
        ("not(not(not(and(p,q))))", "più di due negazioni consecutive"),
    ],
)
def test_explicit_equivalence_rejects_formulas_outside_the_supported_profile(
    formula: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        generator.build_exercise(formula, wrong_answers_count=3, bridge=AllFormulasBridge())  # type: ignore[arg-type]


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_generated_equivalence_keeps_the_extended_distractor_capacity() -> None:
    bridge = PrologBridge(persistent=True)
    try:
        result = generator.build_ex_depth(
            wrong_answers_count=21,
            seed=0,
            timeout=10,
            bridge=bridge,
        )
    finally:
        bridge.close()

    assert len(result["wrong_answers_prolog"]) == 21


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog non disponibile")
def test_generated_equivalence_payloads_never_expose_excessive_negation_chains() -> None:
    bridge = PrologBridge(persistent=True)
    generator._FORMULA_FETCH_CACHE.clear()
    try:
        for allow_spoken_mode in (False, True):
            for seed in range(10):
                result = generator.build_ex_depth(
                    seed=seed,
                    timeout=10,
                    bridge=bridge,
                    allow_spoken_mode=allow_spoken_mode,
                )
                exposed = [
                    result["question_prolog"],
                    result["correct_answer_prolog"],
                    *result["wrong_answers_prolog"],
                ]
                for option in result["options"]:
                    transformation = option.get("transformation", {})
                    exposed.extend(
                        [
                            transformation.get("source_formula_prolog", result["question_prolog"]),
                            transformation.get("final_formula_prolog", option["formula_prolog"]),
                        ]
                    )
                    for step in transformation.get("steps", []):
                        exposed.extend(
                            [
                                step["before_prolog"],
                                step["after_prolog"],
                                step["before_subformula_prolog"],
                                step["after_subformula_prolog"],
                            ]
                        )

                assert all(
                    not generator._has_excessive_negation_chain(formula)
                    for formula in exposed
                ), f"spoken={allow_spoken_mode}, seed={seed}: {exposed}"
                if allow_spoken_mode:
                    assert all(
                        generator._formula_is_spoken_friendly(formula)
                        for formula in exposed
                    ), f"spoken={allow_spoken_mode}, seed={seed}: {exposed}"
    finally:
        generator._FORMULA_FETCH_CACHE.clear()
        bridge.close()


def test_generated_equivalence_propagates_a_candidate_deadline_immediately() -> None:
    deadline = GenerationDeadlineExceeded("Tempo complessivo di generazione esaurito")
    with (
        patch(
            "testlogica.questions.equivalence._get_formulas",
            return_value=["and(p,and(q,r))", "or(p,and(q,r))"],
        ),
        patch(
            "testlogica.questions.equivalence._build_exercise",
            side_effect=deadline,
        ) as build,
        pytest.raises(GenerationDeadlineExceeded, match="Tempo complessivo"),
    ):
        generator.build_ex_depth(
            seed=7,
            timeout=10,
            bridge=AllFormulasBridge(),  # type: ignore[arg-type]
        )

    assert build.call_count == 1
