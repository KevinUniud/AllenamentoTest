from __future__ import annotations

import random
import unittest

from testlogica.ast_logic import And, Imp, Not, Var
from testlogica.formula_construction import build_construction_trace, build_term_construction_trace
from testlogica.generator import _formula_entry


class FormulaConstructionTests(unittest.TestCase):
    def test_ast_trace_is_postorder_and_complete(self) -> None:
        formula = Imp(And(Var("p"), Var("q")), Not(Var("r")))

        trace = build_construction_trace(formula)
        steps = trace["steps"]

        self.assertEqual(trace["version"], 1)
        self.assertEqual(trace["strategy"], "ast_postorder")
        self.assertEqual(trace["final_formula_prolog"], "imp(and(p,q),not(r))")
        self.assertEqual(
            [step["result_prolog"] for step in steps],
            ["p", "q", "and(p,q)", "r", "not(r)", "imp(and(p,q),not(r))"],
        )
        self.assertEqual([step["index"] for step in steps], list(range(1, 7)))
        self.assertEqual(steps[-1]["node_id"], "root")

    def test_repeated_atoms_keep_distinct_occurrences(self) -> None:
        trace = build_construction_trace(And(Var("p"), Var("p")))
        atom_steps = [step for step in trace["steps"] if step["kind"] == "atom"]

        self.assertEqual([step["result_prolog"] for step in atom_steps], ["p", "p"])
        self.assertEqual({step["node_id"] for step in atom_steps}, {"root.left", "root.right"})

    def test_every_operand_points_to_an_earlier_step(self) -> None:
        trace = build_construction_trace(Imp(Not(Var("p")), And(Var("q"), Var("r"))))
        positions = {step["node_id"]: step["index"] for step in trace["steps"]}

        for step in trace["steps"]:
            self.assertTrue(all(positions[operand] < step["index"] for operand in step["operands"]))

    def test_translation_trace_supports_predicates_and_quantifiers(self) -> None:
        trace = build_term_construction_trace("forall(x,imp(A(x),not(B(x))))")
        steps = trace["steps"]

        self.assertEqual(trace["strategy"], "term_postorder")
        self.assertEqual(trace["final_formula_prolog"], "forall(x,imp(A(x),not(B(x))))")
        self.assertEqual([step["kind"] for step in steps], ["predicate", "predicate", "unary", "binary", "quantifier"])
        self.assertEqual(steps[-1]["details"]["bound_variable"], "x")

    def test_invalid_term_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_term_construction_trace("forall(x,and(A(x),B(x))")

    def test_formula_entry_trace_matches_the_materialized_display(self) -> None:
        entry = _formula_entry(And(Var("p"), Var("q")), rng=random.Random(3))

        self.assertEqual(entry["construction"]["final_formula_prolog"], entry["formula_prolog"])
        self.assertEqual(entry["construction"]["steps"][-1]["result_prolog"], entry["formula_prolog"])


if __name__ == "__main__":
    unittest.main()
