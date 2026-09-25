import tempfile
import unittest
from pathlib import Path

from testlogica.prolog.health import readiness


class PrologHealthTests(unittest.TestCase):
    def test_missing_executable_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ready, detail = readiness("definitely-not-a-real-prolog-executable", Path(directory))
        self.assertFalse(ready)
        self.assertIn("executable", detail)


if __name__ == "__main__":
    unittest.main()
