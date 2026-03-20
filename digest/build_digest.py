"""Build the final email digest from ranked NormalizedJob list.

Converts NormalizedJob objects to dicts compatible with
bewerbungsagent.email_automation.send_job_alert(new_jobs, reminder_jobs).

The email system's _normalize_job() looks for:
  title / raw_title, company, location, link / url, source,
  match, score, date, job_uid

We also encode reason_short and score_final into the match field so it
surfaces in the email without requiring template changes.
"""
from __future__ import annotations

from typing import List, Tuple

from pipeline.normalize import NormalizedJob


def build_email_records(
    jobs: List[NormalizedJob],
) -> Tuple[List[dict], List[dict]]:
    """Convert pipeline output to (new_jobs_dicts, reminder_jobs_dicts).

    All jobs go into new_jobs (the daily run treats every surviving job as new
    for the email digest). reminder_jobs is always empty here; the existing
    state management in daily_run.py handles reminders separately.
    """
    records = [_to_email_dict(j) for j in jobs]
    return records, []


def _to_email_dict(job: NormalizedJob) -> dict:
    """Convert a NormalizedJob to the dict format email_automation expects."""

    # Encode score_final + reason_short into the match field
    # e.g. "good|mid|Windows, AD relevant – keine roten Flaggen"
    match_parts = [job.match] if job.match and job.match != "unknown" else []

    llm = job.llm_review or {}
    seniority = llm.get("seniority", "")
    if seniority and seniority != "unknown" and seniority not in match_parts:
        match_parts.append(seniority)

    reason = job.reason_short or llm.get("reason_short", "")
    if reason and reason not in ("llm_review_skipped",) and not reason.startswith("llm_error"):
        # Truncate to keep match field readable
        match_parts.append(reason[:100])

    match_str = " | ".join(match_parts) if match_parts else "–"

    return {
        "title": job.title or "Titel unbekannt",
        "raw_title": job.raw_title or job.title or "",
        "company": job.company or "Firma unbekannt",
        "location": job.location or "Ort unbekannt",
        "link": job.link or job.url or "",
        "url": job.url or job.link or "",
        "source": job.source or "",
        "match": match_str,
        "score": round(job.score_final),
        "date": job.date or job.published_at or "",
        "job_uid": "",   # filled by state management in daily_run.py
        "score_final": job.score_final,
        "score_rule": job.score_rule,
        "score_llm": (job.llm_review or {}).get("score_llm", ""),
        "reason_short": reason,
        "commute_min": job.commute_min,
        "employment_type": job.employment_type,
        "workload": job.workload,
    }
