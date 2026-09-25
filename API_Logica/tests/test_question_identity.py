import unittest

from testlogica.question_identity import question_id, question_identity_key


class QuestionIdentityTests(unittest.TestCase):
    def test_dictionary_order_does_not_change_identity(self) -> None:
        left = {"question_text": "Domanda", "subtype": "translation", "ignored": 1}
        right = {"ignored": 2, "subtype": "translation", "question_text": "Domanda"}

        self.assertEqual(
            question_identity_key("build_translation_question", left),
            question_identity_key("build_translation_question", right),
        )

    def test_logical_consequence_options_are_part_of_identity(self) -> None:
        base = {
            "type": "logical_consequence_question",
            "question_prolog": "and(p,q)",
            "options": [
                {"formula_prolog": "p", "is_consequence": True},
                {"formula_prolog": "q", "is_consequence": False},
            ],
        }
        changed = {
            **base,
            "options": [
                {"formula_prolog": "p", "is_consequence": True},
                {"formula_prolog": "r", "is_consequence": False},
            ],
        }

        self.assertNotEqual(
            question_identity_key("build_logical_consequence_question", base),
            question_identity_key("build_logical_consequence_question", changed),
        )

    def test_logical_consequence_question_and_labels_are_part_of_identity(self) -> None:
        base = {
            "type": "logical_consequence_question",
            "question_prolog": "and(p,q)",
            "options": [
                {"formula_prolog": "p", "is_consequence": True},
                {"formula_prolog": "q", "is_consequence": False},
            ],
        }
        changed_question = {**base, "question_prolog": "or(p,q)"}
        changed_label = {
            **base,
            "options": [
                {"formula_prolog": "p", "is_consequence": False},
                {"formula_prolog": "q", "is_consequence": False},
            ],
        }

        self.assertNotEqual(
            question_identity_key("build_logical_consequence_question", base),
            question_identity_key("build_logical_consequence_question", changed_question),
        )
        self.assertNotEqual(
            question_identity_key("build_logical_consequence_question", base),
            question_identity_key("build_logical_consequence_question", changed_label),
        )

    def test_logical_consequence_option_order_does_not_change_identity(self) -> None:
        options = [
            {"formula_prolog": "p", "is_consequence": True},
            {"formula_prolog": "q", "is_consequence": False},
            {"formula_prolog": "r", "is_consequence": False},
        ]
        base = {
            "type": "logical_consequence_question",
            "question_prolog": "and(p,q)",
            "options": options,
        }
        reordered = {**base, "options": list(reversed(options))}

        self.assertEqual(
            question_identity_key("build_logical_consequence_question", base),
            question_identity_key("build_logical_consequence_question", reordered),
        )

    def test_truth_value_options_are_part_of_identity(self) -> None:
        base = {
            "information": ["p-true", "q-false", "r-true", "s-false"],
            "predicate_count": 4,
            "options": [
                {"formula_prolog": "and(p,and(q,and(r,s)))", "is_true": False},
                {"formula_prolog": "or(p,or(q,or(r,s)))", "is_true": True},
            ],
        }
        changed = {
            **base,
            "options": [
                {"formula_prolog": "imp(p,imp(q,imp(r,s)))", "is_true": False},
                {"formula_prolog": "or(p,or(q,or(r,s)))", "is_true": True},
            ],
        }

        self.assertNotEqual(
            question_identity_key("build_tvq", base),
            question_identity_key("build_tvq", changed),
        )

    def test_truth_value_option_order_does_not_change_identity(self) -> None:
        options = [
            {"formula_prolog": "and(p,and(q,and(r,s)))", "is_true": False},
            {"formula_prolog": "or(p,or(q,or(r,s)))", "is_true": True},
            {"formula_prolog": "iff(p,iff(q,iff(r,s)))", "is_true": False},
        ]
        base = {
            "information": ["p-true", "q-false", "r-true", "s-false"],
            "predicate_count": 4,
            "options": options,
        }
        reordered = {**base, "options": list(reversed(options))}

        self.assertEqual(
            question_identity_key("build_tvq", base),
            question_identity_key("build_tvq", reordered),
        )

    def test_truth_value_correctness_is_part_of_identity(self) -> None:
        base = {
            "information": ["p-true", "q-false", "r-true", "s-false"],
            "predicate_count": 4,
            "options": [{"formula_prolog": "or(p,or(q,or(r,s)))", "is_true": True}],
        }
        changed = {
            **base,
            "options": [{"formula_prolog": "or(p,or(q,or(r,s)))", "is_true": False}],
        }

        self.assertNotEqual(
            question_identity_key("build_tvq", base),
            question_identity_key("build_tvq", changed),
        )

    def test_public_question_id_is_stable_and_does_not_embed_content(self) -> None:
        result = {"question_text": "Domanda riservata", "subtype": "translation"}
        left = question_id("build_translation_question", result)
        right = question_id("build_translation_question", dict(result))
        self.assertEqual(left, right)
        self.assertRegex(left, r"^question-[0-9a-f]{24}$")
        self.assertNotIn("riservata", left)


if __name__ == "__main__":
    unittest.main()
