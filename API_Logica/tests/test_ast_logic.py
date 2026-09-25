import unittest
from dataclasses import FrozenInstanceError

from testlogica.ast_logic import And, Iff, Imp, Not, Or, Var


class FormulaAstTests(unittest.TestCase):
    def test_nodes_render_as_prolog_terms(self) -> None:
        formula = Iff(Imp(Var("p"), Var("q")), Or(Not(Var("r")), And(Var("p"), Var("s"))))

        self.assertEqual(
            repr(formula),
            "iff(imp(p, q), or(not(r), and(p, s)))",
        )

    def test_nodes_are_immutable_values(self) -> None:
        self.assertEqual(And(Var("p"), Var("q")), And(Var("p"), Var("q")))
        with self.assertRaises(FrozenInstanceError):
            Var("p").name = "q"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
