import os
import unittest
from unittest.mock import patch

from testlogica.config import _cors_origins_environment, _integer_environment, _log_level_environment


class ConfigurationTests(unittest.TestCase):
    def test_integer_environment_is_bounded(self) -> None:
        with patch.dict(os.environ, {"TEST_INTEGER": "12"}):
            self.assertEqual(_integer_environment("TEST_INTEGER", 5, minimum=1, maximum=20), 12)

        with patch.dict(os.environ, {"TEST_INTEGER": "not-a-number"}):
            with self.assertRaises(RuntimeError):
                _integer_environment("TEST_INTEGER", 5, minimum=1, maximum=20)

        with patch.dict(os.environ, {"TEST_INTEGER": "21"}):
            with self.assertRaises(RuntimeError):
                _integer_environment("TEST_INTEGER", 5, minimum=1, maximum=20)

    def test_log_level_rejects_unknown_values(self) -> None:
        with patch.dict(os.environ, {"TEST_LOG_LEVEL": "debug"}):
            self.assertEqual(_log_level_environment("TEST_LOG_LEVEL"), "DEBUG")

        with patch.dict(os.environ, {"TEST_LOG_LEVEL": "verbose"}):
            with self.assertRaises(RuntimeError):
                _log_level_environment("TEST_LOG_LEVEL")

    def test_cors_origins_are_normalized_and_deduplicated(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_CORS": "https://example.test/, http://localhost:12345,https://example.test"},
        ):
            self.assertEqual(
                _cors_origins_environment("TEST_CORS", ""),
                ("https://example.test", "http://localhost:12345"),
            )

    def test_cors_origins_reject_wildcards_and_paths(self) -> None:
        for value in ("*", "https://example.test/private", "file://example.test"):
            with self.subTest(value=value), patch.dict(os.environ, {"TEST_CORS": value}):
                with self.assertRaises(RuntimeError):
                    _cors_origins_environment("TEST_CORS", "")


if __name__ == "__main__":
    unittest.main()
