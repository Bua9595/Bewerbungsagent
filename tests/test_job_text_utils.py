import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.job_text_utils import extract_from_multiline_title


class TestJobTextUtils(unittest.TestCase):
    def test_extract_with_arbeitsort(self) -> None:
        raw = "01. [exact] IT Support\nArbeitsort\nBuelach\nMuster AG"
        title, company, location = extract_from_multiline_title(raw)
        self.assertEqual(title, "IT Support")
        self.assertEqual(company, "Muster AG")
        self.assertEqual(location, "Buelach")

    def test_extract_fallbacks(self) -> None:
        raw = "Systemtechniker\nWinterthur\nBeispiel GmbH"
        title, company, location = extract_from_multiline_title(raw)
        self.assertEqual(title, "Systemtechniker")
        self.assertEqual(company, "Beispiel GmbH")
        self.assertEqual(location, "Winterthur")


if __name__ == "__main__":
    unittest.main()
