import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.job_collector import (
    _batch_terms,
    _empty_cache_key,
    _prune_empty_search_cache,
)


class TestJobCollectorUtils(unittest.TestCase):
    def test_batch_terms_passthrough(self) -> None:
        terms = ["a", "b"]
        self.assertEqual(_batch_terms(terms, 1, "OR"), terms)

    def test_batch_terms_grouped(self) -> None:
        terms = ["alpha", "beta", "gamma", "delta"]
        batched = _batch_terms(terms, 2, "OR")
        self.assertEqual(batched, ["alpha OR beta", "gamma OR delta"])

    def test_empty_cache_key_normalized(self) -> None:
        key = _empty_cache_key("JobWinner", "IT Support", "Zuerich HB", 25)
        self.assertEqual(key, "jobwinner|it support|zuerich hb|25")

    def test_prune_empty_cache(self) -> None:
        now = 10000.0
        cache = {
            "keep": now - 30.0,
            "drop": now - 9000.0,
        }
        pruned = _prune_empty_search_cache(cache, 3600.0, now)
        self.assertIn("keep", pruned)
        self.assertNotIn("drop", pruned)


if __name__ == "__main__":
    unittest.main()
