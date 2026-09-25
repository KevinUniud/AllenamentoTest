import unittest

from pydantic import ValidationError

from server.schemas import (
    AutoDepthRequest,
    FormulaByVariableCountRequest,
    GeneratorAutoDepthRequest,
    GeneratorExprRequest,
    LogicalConsequenceQuestionRequest,
    MultipleQuestionsRequest,
    TranslationQuestionRequest,
)
from testlogica.config import MAX_BATCH_SIZE


class GeneratorRequestSchemaTests(unittest.TestCase):
    def test_formula_generators_reject_more_than_five_variables(self) -> None:
        with self.assertRaises(ValidationError):
            AutoDepthRequest(variables=[f"p{index}" for index in range(6)])
        with self.assertRaises(ValidationError):
            FormulaByVariableCountRequest(variable_count=6)

    def test_equivalence_rejects_distractor_counts_above_the_operational_limit(self) -> None:
        with self.assertRaises(ValidationError):
            GeneratorAutoDepthRequest(wrong_answers_count=22)
        with self.assertRaises(ValidationError):
            GeneratorExprRequest(expr="and(p,q)", wrong_answers_count=4)

    def test_logical_consequence_enforces_operational_range_and_even_total(self) -> None:
        valid = {
            "variable_count": 4,
            "correct_options_count": 1,
            "wrong_options_count": 3,
        }
        self.assertEqual(LogicalConsequenceQuestionRequest(**valid).variable_count, 4)

        for invalid in (
            {**valid, "variable_count": 1},
            {**valid, "variable_count": 6},
            {**valid, "wrong_options_count": 2},
            {**valid, "wrong_options_count": 9},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                LogicalConsequenceQuestionRequest(**invalid)

    def test_translation_requires_the_three_distractors_the_builder_produces(self) -> None:
        base = {
            "mode": "propositional",
            "quantifier_ratio": 0,
            "names_pool": ["Anna", "Bruno", "Carla"],
            "actions_pool": ["studia", "corre", "legge"],
            "allow_spoken_mode": False,
        }
        self.assertEqual(TranslationQuestionRequest(**base).wrong_options_count, 3)
        with self.assertRaises(ValidationError):
            TranslationQuestionRequest(**base, wrong_options_count=2)

    def test_translation_rejects_pools_too_small_for_a_possible_subtype(self) -> None:
        base = {
            "mode": "auto",
            "quantifier_ratio": 0.5,
            "names_pool": ["Anna", "Bruno"],
            "people_count": 2,
            "actions_pool": ["studia", "corre"],
            "allow_spoken_mode": False,
        }
        for invalid in (
            {**base, "actions_pool": ["studia"]},
            {**base, "names_pool": ["Anna", "Anna"]},
            {
                **base,
                "mode": "quantifier",
                "people_count": None,
                "actions_pool": ["studia"],
            },
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TranslationQuestionRequest(**invalid)

        # Il pool non usato dal solo subtype scelto non deve introdurre un
        # vincolo artificiale.
        TranslationQuestionRequest(**{**base, "mode": "propositional", "actions_pool": ["studia"]})
        TranslationQuestionRequest(
            **{
                **base,
                "mode": "quantifier",
                "names_pool": ["Anna"],
            }
        )

        for invalid in (
            {
                **base,
                "mode": "propositional",
                "people_count": 1,
                "names_pool": ["Anna", "Anna"],
                "actions_pool": ["corre", "corre"],
            },
            {
                **base,
                "mode": "quantifier",
                "people_count": 2,
                "actions_pool": ["corre", "corre"],
            },
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TranslationQuestionRequest(**invalid)

    def test_batch_validates_nested_payload_without_changing_canonical_data(self) -> None:
        payload = {
            "predicate_count": 4,
            "true_options_count": 1,
            "false_options_count": 3,
            "timeout": 10,
        }
        request = MultipleQuestionsRequest(questions=[{"operation": "build_tvq", "payload": payload}])
        self.assertEqual(request.questions[0].payload, payload)

        for invalid_payload in (
            {**payload, "predicate_count": 6},
            {**payload, "true_options_count": 33},
            {**payload, "timeout": 121},
            {**payload, "unexpected": True},
        ):
            with self.subTest(invalid_payload=invalid_payload), self.assertRaises(ValidationError):
                MultipleQuestionsRequest(questions=[{"operation": "build_tvq", "payload": invalid_payload}])

    def test_batch_size_accepts_the_configured_boundary_and_rejects_one_more(self) -> None:
        item = {"operation": "unknown", "payload": {}}

        request = MultipleQuestionsRequest(questions=[item] * MAX_BATCH_SIZE)
        self.assertEqual(len(request.questions), MAX_BATCH_SIZE)

        with self.assertRaises(ValidationError):
            MultipleQuestionsRequest(questions=[item] * (MAX_BATCH_SIZE + 1))

    def test_batch_normalizes_supported_alias_before_dispatch(self) -> None:
        payload = {
            "mode": "propositional",
            "quantifier_ratio": 0,
            "names_pool": ["Anna", "Bruno", "Carla"],
            "people_count": 3,
            "actions_pool": ["studia", "corre", "legge"],
            "allow_spoken_mode": False,
            "timeout_seconds": 5,
        }
        request = MultipleQuestionsRequest(
            questions=[{"operation": "build_translation_question", "payload": payload}]
        )
        normalized = request.questions[0].payload
        self.assertEqual(normalized["timeout"], 5)
        self.assertNotIn("timeout_seconds", normalized)


if __name__ == "__main__":
    unittest.main()
