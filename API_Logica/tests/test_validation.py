import random
import unittest
from unittest.mock import patch

from testlogica.validation import (
    GenerationDeadlineExceeded,
    default_vars,
    make_timeout_provider,
    normalize_vars,
    resolve_depth,
    select_random_var_set,
)


class ValidationTests(unittest.TestCase):
    def test_default_variables_expand_deterministically(self) -> None:
        self.assertEqual(default_vars(7), ["p", "q", "r", "s", "t", "p1", "p2"])

    def test_normalization_preserves_order_and_removes_duplicates(self) -> None:
        self.assertEqual(normalize_vars(["q", "p", "q"]), ["q", "p"])

    def test_depth_is_resolved_and_validated(self) -> None:
        self.assertEqual(resolve_depth(None, ["p", "q", "r"]), (2, ["p", "q", "r"]))
        with self.assertRaises(ValueError):
            resolve_depth(0, ["p", "q"])

    def test_seeded_variable_set_selection_is_repeatable(self) -> None:
        self.assertEqual(select_random_var_set(rng=random.Random(7)), select_random_var_set(rng=random.Random(7)))

    def test_timeout_provider_rejects_calls_after_the_global_deadline(self) -> None:
        with patch("testlogica.validation.time.monotonic", side_effect=[10.0, 11.01]):
            remaining_timeout = make_timeout_provider(1)
            with self.assertRaisesRegex(GenerationDeadlineExceeded, "Tempo complessivo"):
                remaining_timeout(None)


if __name__ == "__main__":
    unittest.main()
