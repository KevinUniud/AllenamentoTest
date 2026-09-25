import unittest

from testlogica.ast_logic import And, Iff, Imp, Not, Or, Var
from testlogica.prolog_bridge import PrologBridge, collect_variables, from_prolog, to_prolog, valuation_to_prolog


class PrologCodecTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        formulas = [
            Var("p"),
            Not(Var("p")),
            And(Var("p"), Or(Var("q"), Var("r"))),
            Iff(Imp(Var("p"), Var("q")), Not(Var("r"))),
        ]

        for formula in formulas:
            with self.subTest(formula=formula):
                self.assertEqual(from_prolog(to_prolog(formula)), formula)

    def test_variables_are_unique(self) -> None:
        formula = And(Var("z"), Or(Var("a"), Var("z")))
        self.assertEqual(collect_variables(formula), {"a", "z"})

    def test_valuation_encoding_rejects_invalid_values(self) -> None:
        self.assertEqual(valuation_to_prolog([("p", True), ("q", False)]), "[p-true,q-false]")
        with self.assertRaises(ValueError):
            valuation_to_prolog([("p", 1)])  # type: ignore[list-item]

    def test_rejects_untrusted_prolog_fragments(self) -> None:
        with self.assertRaises(ValueError):
            from_prolog("p),halt,(")
        with self.assertRaises(ValueError):
            valuation_to_prolog(["p-true),halt,("])

    def test_bridge_validates_formula_strings_before_starting_prolog(self) -> None:
        bridge = PrologBridge(swipl_path="missing-swipl", persistent=False)

        with self.assertRaises(ValueError):
            bridge.eval("p),halt,(", [("p", True)])


if __name__ == "__main__":
    unittest.main()
