import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.job_collector import collect_jobs, export_csv, format_jobs_plain

jobs = collect_jobs()
export_csv(jobs)
print(format_jobs_plain(jobs, top=20))
print(f"exported {len(jobs)} jobs")
