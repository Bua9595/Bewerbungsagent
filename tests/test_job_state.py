import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.job_state import build_job_uid


class TestJobState(unittest.TestCase):
    def test_build_job_uid_stable(self) -> None:
        job = {
            "source": "jobs.ch",
            "link": "https://jobs.ch/de/job/12345/",
            "title": "IT Support",
            "company": "Muster AG",
            "location": "Buelach",
        }
        uid1, canonical1 = build_job_uid(job)
        uid2, canonical2 = build_job_uid(job)
        self.assertEqual(uid1, uid2)
        self.assertEqual(canonical1, canonical2)

    def test_build_job_uid_fallback_differs(self) -> None:
        job_a = {"source": "other", "title": "IT Support", "company": "A", "location": "B"}
        job_b = {"source": "other", "title": "IT Support", "company": "C", "location": "B"}
        uid_a, _ = build_job_uid(job_a)
        uid_b, _ = build_job_uid(job_b)
        self.assertNotEqual(uid_a, uid_b)


if __name__ == "__main__":
    unittest.main()
