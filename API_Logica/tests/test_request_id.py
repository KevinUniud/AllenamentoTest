import re
import unittest

from server.request_id import normalize_request_id


class RequestIdTests(unittest.TestCase):
    def test_safe_caller_identifier_is_preserved(self) -> None:
        self.assertEqual(normalize_request_id("client-request_42.1"), "client-request_42.1")

    def test_unsafe_identifier_is_replaced(self) -> None:
        generated = normalize_request_id("invalid request id\nheader")

        self.assertRegex(generated, re.compile(r"^[0-9a-f]{32}$"))

    def test_overlong_identifier_is_replaced(self) -> None:
        generated = normalize_request_id("a" * 129)

        self.assertNotEqual(generated, "a" * 129)


if __name__ == "__main__":
    unittest.main()
