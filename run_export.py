from job_collector import collect_jobs, export_csv, format_jobs_plain

jobs = collect_jobs()
export_csv(jobs)
print(format_jobs_plain(jobs, top=20))
print(f"exported {len(jobs)} jobs")
