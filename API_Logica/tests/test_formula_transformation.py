from __future__ import annotations

import shutil
import unittest
from unittest.mock import patch

from server.schemas import FormulaTransformationTrace
from testlogica import generator
from testlogica.formula_transformation import build_transformation_trace, validate_transformation_trace
from testlogica.orchestrator import _pick_modified, _pick_wrongs
from testlogica.prolog_bridge import PrologBridge
from testlogica.validation import GenerationDeadlineExceeded


class FormulaTransformationTests(unittest.TestCase):
    def test_equivalence_trace_is_continuous_and_names_nested_rules(self) -> None:
        trace = build_transformation_trace(
            "not(not(imp(p,q)))",
            ["not(not(imp(p,q)))", "imp(p,q)", "or(not(p),q)"],
            strategy="equivalence_rewrite",
            preserves_meaning=True,
        )

        self.assertEqual(trace["source_formula_prolog"], "not(not(imp(p,q)))")
        self.assertEqual(trace["final_formula_prolog"], "or(not(p),q)")
        self.assertEqual([step["rule"] for step in trace["steps"]], ["double_negation", "implication_elimination"])
        self.assertEqual(trace["steps"][1]["before_prolog"], trace["steps"][0]["after_prolog"])
        self.assertEqual(trace["steps"][0]["before_subformula_prolog"], "not(not(imp(p,q)))")
        self.assertEqual(trace["steps"][0]["after_subformula_prolog"], "imp(p,q)")
        self.assertNotIn("equivalent_rewrite", {step["rule"] for step in trace["steps"]})

    def test_nested_rewrite_reports_the_changed_location(self) -> None:
        trace = build_transformation_trace(
            "not(imp(p,q))",
            ["not(imp(p,q))", "not(or(not(p),q))"],
            strategy="equivalence_rewrite",
            preserves_meaning=True,
        )

        self.assertEqual(trace["steps"][0]["rule"], "implication_elimination")
        self.assertEqual(trace["steps"][0]["location"], "root.operand")
        self.assertEqual(trace["steps"][0]["before_subformula_prolog"], "imp(p,q)")
        self.assertEqual(trace["steps"][0]["after_subformula_prolog"], "or(not(p),q)")

    def test_double_negation_can_be_introduced_as_well_as_eliminated(self) -> None:
        trace = build_transformation_trace(
            "and(p,q)",
            [
                "and(p,q)",
                "not(not(and(p,q)))",
                "not(not(not(not(and(p,q)))))",
            ],
            strategy="equivalence_rewrite",
            preserves_meaning=True,
        )

        self.assertEqual(
            [step["rule"] for step in trace["steps"]],
            ["double_negation", "double_negation"],
        )

    def test_biconditional_joint_negation_is_named(self) -> None:
        trace = build_transformation_trace(
            "iff(p,q)",
            ["iff(p,q)", "iff(not(p),not(q))"],
            strategy="equivalence_rewrite",
            preserves_meaning=True,
        )

        self.assertEqual(trace["steps"][0]["rule"], "biconditional_negation")

    def test_distractor_trace_names_operator_replacement(self) -> None:
        trace = build_transformation_trace(
            "and(p,q)",
            ["and(p,q)", "or(p,q)"],
            strategy="distractor_mutation",
            preserves_meaning=False,
        )

        self.assertEqual(trace["steps"][0]["rule"], "replace_operator_and_with_or")
        FormulaTransformationTrace.model_validate(trace)

    def test_discontinuous_trace_is_rejected(self) -> None:
        trace = build_transformation_trace(
            "and(p,q)",
            ["and(p,q)", "or(p,q)"],
            strategy="distractor_mutation",
            preserves_meaning=False,
        )
        trace["steps"][0]["before_prolog"] = "imp(p,q)"

        with self.assertRaisesRegex(ValueError, "continua"):
            validate_transformation_trace(trace)

    def test_incoherent_local_subformula_is_rejected(self) -> None:
        trace = build_transformation_trace(
            "not(imp(p,q))",
            ["not(imp(p,q))", "not(or(not(p),q))"],
            strategy="equivalence_rewrite",
            preserves_meaning=True,
        )
        trace["steps"][0]["after_subformula_prolog"] = "and(not(p),q)"

        with self.assertRaisesRegex(ValueError, "Sottoformule.*non coerenti"):
            validate_transformation_trace(trace)

    def test_equivalence_without_a_recognized_law_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "legge logica riconosciuta"):
            build_transformation_trace(
                "imp(p,q)",
                ["imp(p,q)", "imp(not(q),not(p))"],
                strategy="equivalence_rewrite",
                preserves_meaning=True,
            )


class _TraceBridge:
    def rewrite_paths(self, _formula: str, timeout: int = 10) -> list[list[str]]:
        del timeout
        return [["not(not(imp(p,q)))", "imp(p,q)", "or(not(p),q)"]]

    def rewrite_formula(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        if formula == "imp(p,q)":
            return ["or(not(p),q)"]
        return []

    def some_step_neq(self, _formula: str, limit: int, timeout: int = 10) -> list[str]:
        del limit, timeout
        return ["and(p,q)", "or(p,q)", "imp(p,q)"]

    def one_step_neq(self, _formula: str, timeout: int = 10) -> list[str]:
        del timeout
        return []

    def some_neq(self, _formula: str, max_steps: int, limit: int, timeout: int = 10) -> list[str]:
        del max_steps, limit, timeout
        return []

    def non_equivalent_distraction(self, _formula: str, max_steps: int, timeout: int = 10) -> list[str]:
        del max_steps, timeout
        return []


class _UnknownThenKnownTraceBridge(_TraceBridge):
    def rewrite_paths(self, _formula: str, timeout: int = 10) -> list[list[str]]:
        del timeout
        return [
            ["imp(p,q)", "imp(not(q),not(p))"],
            ["imp(p,q)", "or(not(p),q)", "or(q,not(p))"],
        ]


class _ExcessiveThenReadableBridge(_TraceBridge):
    def rewrite_paths(self, _formula: str, timeout: int = 10) -> list[list[str]]:
        del timeout
        return [
            ["imp(not(not(p)),q)", "or(not(not(not(p))),q)"],
            ["imp(not(not(p)),q)", "imp(p,q)", "or(not(p),q)"],
        ]


class _FallbackExpansionBridge(_TraceBridge):
    def rewrite_paths(self, _formula: str, timeout: int = 10) -> list[list[str]]:
        del timeout
        return [["imp(p,q)"]]

    def rewrite_formula(self, formula: str, timeout: int = 10) -> list[str]:
        del timeout
        if formula == "imp(p,q)":
            return ["or(not(p),q)"]
        if formula == "or(not(p),q)":
            return ["or(q,not(p))"]
        return []


class _NoRewriteBridge(_TraceBridge):
    def rewrite_paths(self, formula: str, timeout: int = 10) -> list[list[str]]:
        del timeout
        return [[formula]]

    def rewrite_formula(self, _formula: str, timeout: int = 10) -> list[str]:
        del timeout
        return []


class _ManyShortPathsBridge(_TraceBridge):
    def __init__(self) -> None:
        self.rewrite_timeouts: list[int] = []

    def rewrite_paths(self, _formula: str, timeout: int = 10) -> list[list[str]]:
        self.rewrite_timeouts.append(timeout)
        return [
            ["and(p,q)", "or(p,q)"],
            ["and(p,q)", "imp(p,q)"],
            ["and(p,q)", "iff(p,q)"],
            ["and(p,q)", "and(not(p),q)"],
        ]

    def rewrite_formula(self, _formula: str, timeout: int = 10) -> list[str]:
        self.rewrite_timeouts.append(timeout)
        return []


class _PrimaryPathOnlyPrologBridge(PrologBridge):
    def __init__(self) -> None:
        super().__init__(persistent=True)
        self.emergency_rewrite_calls = 0

    def rewrite_formula(self, expr: str, timeout: int = 10) -> list[str]:
        self.emergency_rewrite_calls += 1
        return super().rewrite_formula(expr, timeout=timeout)


class _LateTraceBridge(_TraceBridge):
    def __init__(self, clock: list[float]) -> None:
        self.clock = clock

    def rewrite_paths(self, formula: str, timeout: int = 10) -> list[list[str]]:
        paths = super().rewrite_paths(formula, timeout=timeout)
        self.clock[0] = 2.0
        return paths


class OrchestratorTransformationTests(unittest.TestCase):
    def test_modified_selection_rejects_a_result_completed_after_deadline(self) -> None:
        clock = [0.0]
        with patch("testlogica.orchestrator.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(GenerationDeadlineExceeded, "Tempo esaurito"):
                _pick_modified(
                    question_prolog="not(not(imp(p,q)))",
                    variables=["p", "q"],
                    bridge=_LateTraceBridge(clock),  # type: ignore[arg-type]
                    filter_equiv_batch=lambda candidates: list(candidates),
                    target_atom_count=2,
                    seed=3,
                    timeout=1,
                    return_transformation=True,
                )

    def test_modified_selection_stops_bridge_calls_after_global_timeout(self) -> None:
        bridge = _ManyShortPathsBridge()
        provider_calls = 0

        def timeout_provider(cap: int) -> int:
            nonlocal provider_calls
            provider_calls += 1
            if provider_calls > 2:
                raise RuntimeError("deadline globale esaurita")
            return cap

        with self.assertRaisesRegex(RuntimeError, "deadline globale"):
            _pick_modified(
                question_prolog="and(p,q)",
                variables=["p", "q"],
                bridge=bridge,  # type: ignore[arg-type]
                filter_equiv_batch=lambda candidates: list(candidates),
                target_atom_count=2,
                seed=3,
                timeout=10,
                timeout_provider=timeout_provider,
                return_transformation=True,
            )

        self.assertGreaterEqual(provider_calls, 3)
        self.assertEqual(len(bridge.rewrite_timeouts), 1)
        self.assertTrue(all(timeout <= 3 for timeout in bridge.rewrite_timeouts))

    def test_modified_selection_returns_the_actual_rewrite_path(self) -> None:
        bridge = _TraceBridge()
        result = _pick_modified(
            question_prolog="not(not(imp(p,q)))",
            variables=["p", "q"],
            bridge=bridge,  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=3,
            return_transformation=True,
        )
        formula, rewrite_steps, trace = result

        self.assertEqual(formula, "or(not(p),q)")
        self.assertEqual(rewrite_steps, 2)
        self.assertEqual(trace["final_formula_prolog"], formula)
        self.assertEqual(trace["steps"][0]["after_prolog"], trace["steps"][1]["before_prolog"])

    def test_modified_selection_uses_a_readable_named_fallback_for_short_formulas(self) -> None:
        formula, rewrite_steps, trace = _pick_modified(
            question_prolog="and(p,q)",
            variables=["p", "q"],
            bridge=_NoRewriteBridge(),  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=3,
            return_transformation=True,
        )

        self.assertEqual(formula, "not(or(not(q),not(p)))")
        self.assertEqual(rewrite_steps, 2)
        self.assertEqual(
            [step["rule"] for step in trace["steps"]],
            ["commutativity_and", "de_morgan_and"],
        )

    def test_modified_selection_uses_commutativity_for_biconditional_fallback(self) -> None:
        formula, rewrite_steps, trace = _pick_modified(
            question_prolog="iff(p,q)",
            variables=["p", "q"],
            bridge=_NoRewriteBridge(),  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=3,
            return_transformation=True,
        )

        self.assertEqual(formula, "iff(q,p)")
        self.assertEqual(rewrite_steps, 1)
        self.assertEqual([step["rule"] for step in trace["steps"]], ["commutativity_iff"])

    def test_modified_selection_simplifies_double_negation_in_and_or_children(self) -> None:
        cases = [
            ("and(not(not(p)),q)", "and(p,q)", "root.left"),
            ("and(p,not(not(q)))", "and(p,q)", "root.right"),
            ("or(not(not(p)),q)", "or(p,q)", "root.left"),
            ("or(p,not(not(q)))", "or(p,q)", "root.right"),
        ]

        for question, expected, location in cases:
            with self.subTest(question=question):
                formula, rewrite_steps, trace = _pick_modified(
                    question_prolog=question,
                    variables=["p", "q"],
                    bridge=_NoRewriteBridge(),  # type: ignore[arg-type]
                    filter_equiv_batch=lambda candidates: list(candidates),
                    target_atom_count=2,
                    seed=3,
                    return_transformation=True,
                )

                self.assertEqual(formula, expected)
                self.assertEqual(rewrite_steps, 1)
                self.assertEqual([step["rule"] for step in trace["steps"]], ["double_negation"])
                self.assertEqual(trace["steps"][0]["location"], location)
                self.assertTrue(
                    all(
                        not generator._has_excessive_negation_chain(step[field])
                        for step in trace["steps"]
                        for field in ("before_prolog", "after_prolog")
                    )
                )

    def test_modified_selection_simplifies_double_negated_antecedent_before_fallback(self) -> None:
        formula, rewrite_steps, trace = _pick_modified(
            question_prolog="imp(not(not(p)),q)",
            variables=["p", "q"],
            bridge=_NoRewriteBridge(),  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=3,
            return_transformation=True,
        )

        self.assertEqual(formula, "or(not(p),q)")
        self.assertEqual(rewrite_steps, 2)
        self.assertEqual(
            [step["rule"] for step in trace["steps"]],
            ["double_negation", "implication_elimination"],
        )
        self.assertTrue(
            all(
                not generator._has_excessive_negation_chain(step[field])
                for step in trace["steps"]
                for field in ("before_prolog", "after_prolog")
            )
        )

    def test_modified_selection_skips_an_equivalent_path_without_named_laws(self) -> None:
        bridge = _UnknownThenKnownTraceBridge()
        result = _pick_modified(
            question_prolog="imp(p,q)",
            variables=["p", "q"],
            bridge=bridge,  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=5,
            return_transformation=True,
        )
        formula, rewrite_steps, trace = result

        self.assertEqual(formula, "or(q,not(p))")
        self.assertEqual(rewrite_steps, 2)
        self.assertEqual(
            [step["rule"] for step in trace["steps"]],
            ["implication_elimination", "commutativity_or"],
        )
        self.assertTrue(all(step["before_subformula_prolog"] for step in trace["steps"]))
        self.assertTrue(all(step["after_subformula_prolog"] for step in trace["steps"]))

    def test_modified_selection_skips_excessive_negations_in_formula_and_trace(self) -> None:
        formula, rewrite_steps, trace = _pick_modified(
            question_prolog="imp(not(not(p)),q)",
            variables=["p", "q"],
            bridge=_ExcessiveThenReadableBridge(),  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=5,
            return_transformation=True,
        )

        self.assertEqual(formula, "or(not(p),q)")
        self.assertEqual(rewrite_steps, 2)
        exposed_formulas = [formula]
        for step in trace["steps"]:
            exposed_formulas.extend(
                [
                    step["before_prolog"],
                    step["after_prolog"],
                    step["before_subformula_prolog"],
                    step["after_subformula_prolog"],
                ]
            )
        self.assertTrue(
            all(
                not generator._has_excessive_negation_chain(item)
                for item in exposed_formulas
            )
        )

    def test_modified_selection_accepts_a_named_emergency_rewrite_without_fabricated_steps(self) -> None:
        result = _pick_modified(
            question_prolog="imp(p,q)",
            variables=["p", "q"],
            bridge=_FallbackExpansionBridge(),  # type: ignore[arg-type]
            filter_equiv_batch=lambda candidates: list(candidates),
            target_atom_count=2,
            seed=42,
            return_transformation=True,
        )
        formula, rewrite_steps, trace = result

        self.assertEqual(formula, "or(not(p),q)")
        self.assertEqual(rewrite_steps, 1)
        self.assertEqual(
            [step["rule"] for step in trace["steps"]],
            ["implication_elimination"],
        )

    def test_wrong_selection_keeps_real_one_step_provenance(self) -> None:
        bridge = _TraceBridge()

        result = _pick_wrongs(
            question_prolog="iff(p,q)",
            correct_prolog="iff(q,p)",
            variables=["p", "q"],
            target_atom_count=2,
            wrong_answers_count=3,
            operator_cycles=0,
            from_correct_answer=False,
            bridge=bridge,  # type: ignore[arg-type]
            filter_wrong_batch=lambda candidates: list(candidates),
            seed=5,
            return_transformations=True,
        )
        formulas, traces = result

        self.assertEqual(len(formulas), 3)
        for formula in formulas:
            trace = traces[formula]
            self.assertEqual(trace["source_formula_prolog"], "iff(p,q)")
            self.assertEqual(trace["final_formula_prolog"], formula)
            self.assertEqual(len(trace["steps"]), 1)


@unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog non disponibile")
class PrologTransformationBridgeTests(unittest.TestCase):
    def test_persistent_bridge_loads_rpc_and_application_sources(self) -> None:
        bridge = PrologBridge(persistent=True)
        try:
            self.assertTrue(bridge.ask_bool("true", timeout=5))
            self.assertEqual(bridge.rewrite_formula("imp(p,q)", timeout=5), ["or(not(p),q)"])
        finally:
            bridge.close()

    def test_distractor_trace_is_json_serializable(self) -> None:
        bridge = PrologBridge(persistent=False)
        items = bridge.distract_trace("and(p,q)", max_steps=1, timeout=5)

        self.assertTrue(items)
        self.assertTrue(all(isinstance(item["trace"], list) for item in items))
        self.assertTrue(all(isinstance(step, str) for item in items for step in item["trace"]))

    def test_rewrite_paths_preserve_their_boundaries(self) -> None:
        bridge = PrologBridge(persistent=False)
        paths = bridge.rewrite_paths("and(true,not(not(p)))", timeout=5)

        self.assertTrue(paths)
        self.assertEqual(paths[0][0], "and(true,not(not(p)))")
        self.assertEqual(paths[0][-1], "p")

    def test_biconditional_uses_a_substantive_primary_path(self) -> None:
        bridge = PrologBridge(persistent=True)
        try:
            formula, rewrite_steps, trace = _pick_modified(
                question_prolog="iff(p,q)",
                variables=["p", "q"],
                bridge=bridge,
                filter_equiv_batch=lambda candidates: bridge.filter_equivalent(
                    "iff(p,q)",
                    candidates,
                    vars_list=["p", "q"],
                    timeout=5,
                ),
                target_atom_count=2,
                seed=3,
                timeout=5,
                return_transformation=True,
            )
        finally:
            bridge.close()

        self.assertNotEqual(formula, "iff(q,p)")
        self.assertGreaterEqual(rewrite_steps, 2)
        self.assertIn("biconditional_negation", [step["rule"] for step in trace["steps"]])

    def test_generated_equivalences_use_only_primary_prolog_paths(self) -> None:
        bridge = _PrimaryPathOnlyPrologBridge()
        generator._FORMULA_FETCH_CACHE.clear()
        try:
            with self.assertNoLogs("testlogica.orchestrator", level="WARNING"):
                for spoken_mode in (False, True):
                    for seed in range(25):
                        result = generator.build_ex_depth(
                            timeout=10,
                            seed=seed,
                            wrong_answers_count=3,
                            bridge=bridge,
                            allow_spoken_mode=spoken_mode,
                        )
                        self.assertTrue(result["modified_formula"]["transformation"]["steps"])
            self.assertEqual(bridge.emergency_rewrite_calls, 0)
        finally:
            generator._FORMULA_FETCH_CACHE.clear()
            bridge.close()


if __name__ == "__main__":
    unittest.main()
