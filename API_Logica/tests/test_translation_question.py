import unittest
from unittest.mock import patch

from testlogica.questions.translation import build_translation_question

NAMES = ["Anna", "Bruno", "Carla"]
ACTIONS = ["studia", "corre", "legge"]


class TranslationQuestionTests(unittest.TestCase):
    def test_seeded_propositional_question_is_repeatable(self) -> None:
        payload = {
            "mode": "propositional",
            "quantifier_ratio": 0.0,
            "names_pool": NAMES,
            "actions_pool": ACTIONS,
            "allow_spoken_mode": False,
            "seed": 17,
        }

        self.assertEqual(build_translation_question(**payload), build_translation_question(**payload))

    def test_options_are_unique_and_have_one_correct_answer(self) -> None:
        question = build_translation_question(
            mode="propositional",
            quantifier_ratio=0.0,
            names_pool=NAMES,
            actions_pool=ACTIONS,
            allow_spoken_mode=True,
            seed=9,
        )

        options = question["options"]
        self.assertEqual(len(options), 4)
        self.assertEqual(len({option["formula"] for option in options}), 4)
        self.assertEqual(sum(option["is_correct"] for option in options), 1)
        self.assertTrue(all(option["construction"]["version"] == 1 for option in options))
        self.assertTrue(
            all(
                option["construction"]["final_formula_prolog"] == option["formula"]
                for option in options
            )
        )

    def test_quantifier_mode_generates_predicate_formulas(self) -> None:
        question = build_translation_question(
            mode="quantifier",
            quantifier_ratio=1.0,
            names_pool=NAMES,
            people_count=3,
            actions_pool=ACTIONS,
            allow_spoken_mode=False,
            seed=4,
        )

        self.assertEqual(question["subtype"], "quantifier")
        self.assertTrue(all("(x)" in option["formula"] for option in question["options"]))
        self.assertTrue(
            all(option["construction"]["steps"][-1]["kind"] == "quantifier" for option in question["options"])
        )

    def test_single_predicate_has_distinct_options_for_both_quantifiers(self) -> None:
        expected_correct = {
            "per_ogni": "forall(x,A(x))",
            "esiste": "exists(x,A(x))",
        }

        for quantifier in expected_correct:
            with self.subTest(quantifier=quantifier):
                with patch(
                    "testlogica.questions.translation.random.Random.choice",
                    return_value=quantifier,
                ):
                    question = build_translation_question(
                        mode="quantifier",
                        quantifier_ratio=1.0,
                        names_pool=NAMES,
                        people_count=1,
                        actions_pool=ACTIONS,
                        allow_spoken_mode=False,
                        seed=4,
                    )

                options = question["options"]
                self.assertEqual(len(options), 4)
                self.assertEqual(len({option["formula"] for option in options}), 4)
                self.assertEqual(sum(option["is_correct"] for option in options), 1)
                self.assertTrue(
                    all(option["formula"].startswith(("forall(", "exists(")) for option in options)
                )
                self.assertEqual(
                    next(option["formula"] for option in options if option["is_correct"]),
                    expected_correct[quantifier],
                )
                formulas = {option["formula"] for option in options}
                prefix = "forall" if quantifier == "per_ogni" else "exists"
                self.assertIn(f"{prefix}(x,not(A(x)))", formulas)
                self.assertIn(f"{prefix}(x,and(A(x),not(A(x))))", formulas)
                self.assertNotIn(f"{prefix}(x,imp(A(x),not(A(x))))", formulas)

    def test_wrong_option_count_is_part_of_the_contract(self) -> None:
        with self.assertRaises(ValueError):
            build_translation_question(
                mode="propositional",
                quantifier_ratio=0.0,
                wrong_options_count=2,
                names_pool=NAMES,
                actions_pool=ACTIONS,
                allow_spoken_mode=False,
            )

    def test_metadata_distinguishes_requested_and_actual_people_count(self) -> None:
        question = build_translation_question(
            mode="propositional",
            quantifier_ratio=0,
            names_pool=[*NAMES, "Diego"],
            people_count=4,
            actions_pool=ACTIONS,
            allow_spoken_mode=False,
            seed=4,
        )

        self.assertEqual(question["metadata"]["people_count"], 4)
        self.assertEqual(
            question["metadata"]["actual_people_count"],
            len(question["metadata"]["names_used"]),
        )
        self.assertLessEqual(question["metadata"]["actual_people_count"], 3)

    def test_pool_capacity_is_validated_for_every_possible_subtype(self) -> None:
        with self.assertRaisesRegex(ValueError, "actions_pool"):
            build_translation_question(
                mode="quantifier",
                quantifier_ratio=1,
                names_pool=["Anna"],
                actions_pool=["studia"],
                allow_spoken_mode=False,
            )

        with self.assertRaisesRegex(ValueError, "nomi distinti"):
            build_translation_question(
                mode="propositional",
                quantifier_ratio=0,
                names_pool=["Anna", "Anna"],
                people_count=2,
                actions_pool=["studia"],
                allow_spoken_mode=False,
            )

        for quantifier_ratio, expected_message in ((0.5, "actions_pool"), (0.5, "nomi distinti")):
            with self.subTest(expected_message=expected_message):
                payload = {
                    "mode": "auto",
                    "quantifier_ratio": quantifier_ratio,
                    "names_pool": ["Anna", "Bruno"],
                    "people_count": 2,
                    "actions_pool": ["studia", "corre"],
                    "allow_spoken_mode": False,
                }
                if expected_message == "actions_pool":
                    payload["actions_pool"] = ["studia"]
                else:
                    payload["names_pool"] = ["Anna", "Anna"]
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_translation_question(**payload)

    def test_propositional_atoms_always_have_distinct_natural_descriptions(self) -> None:
        for names, actions in ((["Anna", "Bruno"], ["corre"]), (["Anna"], ACTIONS)):
            for seed in range(30):
                with self.subTest(names=names, actions=actions, seed=seed):
                    question = build_translation_question(
                        mode="propositional",
                        quantifier_ratio=0,
                        names_pool=names,
                        people_count=len(names),
                        actions_pool=actions,
                        allow_spoken_mode=False,
                        seed=seed,
                    )
                    descriptions = [item.split(" = ", 1)[1] for item in question["info"]]
                    self.assertEqual(len(descriptions), len(set(descriptions)))
                    if len(names) * len(actions) == 2:
                        self.assertEqual(question["metadata"]["template_used"], "implication")

    def test_web_sized_pool_uses_distinct_actions_on_the_first_attempt(self) -> None:
        for seed in range(100):
            with self.subTest(seed=seed):
                question = build_translation_question(
                    mode="propositional",
                    quantifier_ratio=0,
                    names_pool=NAMES,
                    people_count=3,
                    actions_pool=ACTIONS,
                    allow_spoken_mode=False,
                    seed=seed,
                )
                self.assertEqual(len(question["metadata"]["actions_used"]), 3)

    def test_duplicate_pool_values_do_not_create_synonymous_atoms(self) -> None:
        with self.assertRaisesRegex(ValueError, "descrizioni atomiche distinte"):
            build_translation_question(
                mode="propositional",
                quantifier_ratio=0,
                names_pool=["Anna", "Anna"],
                people_count=1,
                actions_pool=["corre", "corre"],
                allow_spoken_mode=False,
            )

        with self.assertRaisesRegex(ValueError, "azioni distinte"):
            build_translation_question(
                mode="quantifier",
                quantifier_ratio=1,
                names_pool=["Anna"],
                people_count=2,
                actions_pool=["corre", "corre"],
                allow_spoken_mode=False,
            )


if __name__ == "__main__":
    unittest.main()
