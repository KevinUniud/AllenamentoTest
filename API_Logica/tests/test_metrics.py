import unittest

from testlogica.ast_logic import And, Iff, Imp, Not, Or, Var
from testlogica.metrics import (
    formula_atom_count,
    formula_binary_operator_count,
    formula_depth,
    formula_operator_count,
    formula_size,
)


class FormulaMetricTests(unittest.TestCase):
    def test_metrics_for_nested_formula(self) -> None:
        formula = Iff(Imp(Var("p"), Var("q")), Or(Not(Var("r")), And(Var("p"), Var("s"))))

        self.assertEqual(formula_depth(formula), 3)
        self.assertEqual(formula_size(formula), 10)
        self.assertEqual(formula_atom_count(formula), 5)
        self.assertEqual(formula_operator_count(formula), 5)
        self.assertEqual(formula_binary_operator_count(formula), 4)

    def test_unknown_nodes_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            formula_depth(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
