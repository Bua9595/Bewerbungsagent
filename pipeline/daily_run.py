"""Daily pipeline entry point.

Orchestrates: collect → normalize → hard_filter → llm_review →
              dedupe → final_rank → state_merge → email_digest

Usage
-----
  python -m pipeline.daily_run                 # normal run
  python -m pipeline.daily_run --dry-run       # no email sent, no state written
  python -m pipeline.daily_run --source jobs.ch,jobscout24

Cron (daily at 08:30, project root must be working directory):
  30 8 * * * cd /path/to/BewerbungsagentClaude && python -m pipeline.daily_run >> logs/daily.log 2>&1

Windows Task Scheduler:
  Program : python
  Arguments: -m pipeline.daily_run
  Start in : C:\\path\\to\\BewerbungsagentClaude
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is importable
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# load .env before any config import
from dotenv import load_dotenv  # noqa: E402
load_dotenv()


# ---------------------------------------------------------------------------
# Logger setup (mirrors bewerbungsagent/logger.py but independent)
# ---------------------------------------------------------------------------

def _build_logger() -> logging.Logger:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", "job_finder.log")
    to_console = os.getenv("LOG_TO_CONSOLE", "true").lower() not in ("false", "0")

    logger = logging.getLogger("daily_pipeline")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, log_level, logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass

    if to_console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


log = _build_logger()


# ---------------------------------------------------------------------------
# Run-lock helpers (reused logic from tools/commands/mail_list.py)
# ---------------------------------------------------------------------------

def _lock_path() -> Path:
    return Path(os.getenv("DAILY_LOCK_FILE", "generated/daily_run.lock"))


def _lock_ttl() -> int:
    try:
        return int(os.getenv("RUN_LOCK_TTL_MIN", "120") or 120)
    except (ValueError, TypeError):
        return 120


def _acquire_lock(path: Path, ttl_min: int) -> bool:
    from bewerbungsagent.job_state import now_iso, parse_ts

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            started = parse_ts(payload.get("started_at"))
            if started and (datetime.now(timezone.utc) - started) < timedelta(minutes=ttl_min):
                log.warning(f"Run-Lock aktiv, Abbruch: {path}")
                return False
        except Exception:
            pass
        path.unlink(missing_ok=True)

    try:
        payload = {"pid": os.getpid(), "started_at": now_iso(), "ttl_min": ttl_min}
        with path.open("x", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except FileExistsError:
        log.warning(f"Run-Lock aktiv (race), Abbruch: {path}")
        return False

    atexit.register(lambda: path.unlink(missing_ok=True))
    log.info(f"Run-Lock gesetzt: {path}")
    return True


def _release_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    log.info(f"Run-Lock freigegeben: {path}")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def _step_collect(sources: list[str] | None) -> list:
    from bewerbungsagent.job_collector import collect_jobs, Job

    # collect_jobs() handles per-source errors internally (try/except per adapter).
    # A KeyboardInterrupt or SystemExit will still propagate – that is intentional.
    jobs = collect_jobs(sources=sources or None)

    # Validate return type so any future regression is immediately visible.
    if not isinstance(jobs, list):
        log.error(
            f"[1/7] collect: unexpected return type {type(jobs).__name__!r} "
            f"from collect_jobs() – expected list. Treating as empty."
        )
        return []

    job_count = len(jobs)
    log.info(f"[1/7] collect: {job_count} jobs after internal collect_jobs() filtering")

    if job_count == 0:
        log.warning(
            "       collect returned 0 jobs. Common causes:\n"
            "       • DETAILS_BLOCKLIST_SCAN=true + overly broad REQUIREMENTS_BLOCKLIST\n"
            "         (e.g. 'jahre berufserfahrung' appears in every CH job posting)\n"
            "       • HARD_ALLOWED_LOCATIONS too restrictive\n"
            "       • INCLUDE_KEYWORDS not matching scraped titles\n"
            "       → Set FILTER_STATS=true in .env and re-run to see exact drop reasons."
        )

    return jobs


def _step_normalize(raw_jobs: list) -> list:
    from pipeline.normalize import normalize_jobs
    normalized = normalize_jobs(raw_jobs)
    log.info(f"[2/7] normalize: {len(normalized)} jobs normalized")
    return normalized


def _step_hard_filter(jobs: list) -> tuple[list, list]:
    from pipeline.hard_filter import hard_filter
    kept, rejected = hard_filter(jobs)
    log.info(f"[3/7] hard_filter: {len(kept)} kept, {len(rejected)} rejected")
    if rejected:
        # Log reject summary (grouped by reason category)
        reason_counts: dict[str, int] = {}
        for j in rejected:
            category = j.reject_reason.split(":")[0] if j.reject_reason else "unknown"
            reason_counts[category] = reason_counts.get(category, 0) + 1
        log.info(f"       reject reasons: {reason_counts}")
    return kept, rejected


def _step_llm_review(jobs: list) -> list:
    from ranking.llm_review import llm_review_jobs
    reviewed = llm_review_jobs(jobs, logger=log)
    # Count how many were rejected by LLM
    llm_rejected = [j for j in reviewed if j.rejected]
    surviving = [j for j in reviewed if not j.rejected]
    log.info(
        f"[4/7] llm_review: {len(surviving)} surviving, "
        f"{len(llm_rejected)} rejected by LLM"
    )
    return surviving


def _step_dedupe(jobs: list) -> list:
    from pipeline.dedupe import dedupe_jobs
    unique, removed = dedupe_jobs(jobs)
    log.info(f"[5/7] dedupe: {len(unique)} unique, {removed} duplicates removed")
    return unique


def _step_final_rank(jobs: list) -> list:
    from ranking.final_rank import compute_final_scores
    ranked = compute_final_scores(jobs)
    log.info(f"[6/7] final_rank: {len(ranked)} jobs ranked")
    if ranked:
        top = ranked[0]
        log.info(
            f"       top job: '{top.title}' @ {top.company} "
            f"(score_final={top.score_final:.1f})"
        )
    return ranked


def _step_email(
    ranked_jobs: list,
    dry_run: bool,
    stamp: str,
) -> bool:
    """Merge with state, classify new/reminders, send email."""
    from bewerbungsagent.email_automation import email_automation
    from bewerbungsagent.job_state import (
        OPEN_STATUSES,
        STATUS_APPLIED,
        STATUS_CLOSED,
        STATUS_IGNORED,
        STATUS_NEW,
        STATUS_NOTIFIED,
        TERMINAL_STATUSES,
        build_job_uid,
        canonicalize_url,
        load_state,
        now_iso,
        parse_ts,
        save_state,
        should_send_reminder,
    )
    from bewerbungsagent.job_tracker import (
        apply_tracker_marks,
        get_tracker_path,
        load_tracker,
        write_tracker,
    )
    from digest.build_digest import build_email_records

    now_dt = parse_ts(stamp) or datetime.now(timezone.utc)
    reminder_days = int(os.getenv("REMINDER_DAYS", "2") or 2)
    close_missing_runs = int(os.getenv("CLOSE_MISSING_RUNS", "3") or 3)
    close_not_seen_days = int(os.getenv("CLOSE_NOT_SEEN_DAYS", "7") or 7)
    daily_reminders = os.getenv("REMINDER_DAILY", "false").lower() not in ("false", "0")

    # Build email-compatible dicts from pipeline output
    new_records, _ = build_email_records(ranked_jobs)

    # Load state
    state = load_state(now=stamp)

    # Apply manual tracker changes
    tracker_path = get_tracker_path()
    tracker_rows = load_tracker(tracker_path)
    apply_tracker_marks(state, tracker_rows)

    # Merge pipeline records into state (dedup by job_uid)
    seen_this_run: set[str] = set()
    newly_added = 0

    for record in new_records:
        job_uid, canonical_url = build_job_uid(record)
        seen_this_run.add(job_uid)

        link = record.get("link") or record.get("url") or ""

        existing = state.get(job_uid)
        if not existing:
            state[job_uid] = {
                "job_uid": job_uid,
                "source": record.get("source", ""),
                "canonical_url": canonical_url or canonicalize_url(link) or link,
                "link": link,
                "title": record.get("title", ""),
                "company": record.get("company", ""),
                "location": record.get("location", ""),
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "last_sent_at": None,
                "status": STATUS_NEW,
                "score": record.get("score", ""),
                "match": record.get("match", ""),
                "date": record.get("date", ""),
                "commute_min": record.get("commute_min"),
                "missing_runs": 0,
                # Pipeline extras
                "score_final": record.get("score_final", 0.0),
                "score_rule": record.get("score_rule", 0),
                "score_llm": record.get("score_llm", ""),
                "reason_short": record.get("reason_short", ""),
            }
            newly_added += 1
            continue

        # Update existing record
        existing["last_seen_at"] = stamp
        existing["missing_runs"] = 0
        for f in ("title", "company", "location", "source", "match", "date", "commute_min"):
            if record.get(f):
                existing[f] = record[f]
        if record.get("score") not in (None, ""):
            existing["score"] = record["score"]
        if record.get("score_final"):
            existing["score_final"] = record["score_final"]
        if record.get("reason_short"):
            existing["reason_short"] = record["reason_short"]

        status = existing.get("status") or STATUS_NEW
        if status == STATUS_CLOSED:
            status = STATUS_NOTIFIED if existing.get("last_sent_at") else STATUS_NEW
        if status not in (STATUS_APPLIED, STATUS_IGNORED):
            existing["status"] = status

    # Increment missing_runs for not-seen jobs
    marked_closed = 0
    for uid, rec in state.items():
        if uid in seen_this_run:
            continue
        if rec.get("status") in (STATUS_APPLIED, STATUS_IGNORED, STATUS_CLOSED):
            continue
        rec["missing_runs"] = int(rec.get("missing_runs", 0)) + 1
        last_seen = parse_ts(rec.get("last_seen_at"))
        days_missing = (now_dt - last_seen).days if last_seen else 0
        if (close_missing_runs > 0 and rec["missing_runs"] >= close_missing_runs) or (
            close_not_seen_days > 0 and days_missing >= close_not_seen_days
        ):
            rec["status"] = STATUS_CLOSED
            marked_closed += 1

    # Classify new vs reminders
    new_jobs_recs = []
    reminder_recs = []
    new_uids: set[str] = set()

    for uid in seen_this_run:
        rec = state.get(uid)
        if not rec or rec.get("status") in TERMINAL_STATUSES:
            continue
        if rec.get("status") == STATUS_NEW:
            new_jobs_recs.append(rec)
            new_uids.add(uid)

    for uid in seen_this_run:
        rec = state.get(uid)
        if not rec or rec.get("status") in TERMINAL_STATUSES:
            continue
        if rec.get("status") in OPEN_STATUSES and uid not in new_uids:
            if should_send_reminder(rec.get("last_sent_at"), now_dt, reminder_days, daily_reminders):
                reminder_recs.append(rec)

    # Sort by score_final desc, fallback to score
    def _sort_key(r):
        return float(r.get("score_final") or 0) or float(r.get("score") or 0)

    new_jobs_recs.sort(key=_sort_key, reverse=True)
    reminder_recs.sort(key=_sort_key, reverse=True)

    log.info(
        f"[7/7] email_digest: {len(new_jobs_recs)} new, "
        f"{len(reminder_recs)} reminders, "
        f"{newly_added} newly_added, "
        f"{marked_closed} marked_closed"
    )

    # Send or dry-run
    mail_sent = False
    if not new_jobs_recs and not reminder_recs:
        log.info("       no jobs to send")
        send_empty = os.getenv("SEND_EMPTY_DIGEST", "false").lower() not in ("false", "0")
        if send_empty:
            email_automation.send_job_alert([], [])
    elif dry_run:
        log.info(
            f"[DRY RUN] Would send email: "
            f"{len(new_jobs_recs)} new, {len(reminder_recs)} reminders"
        )
        mail_sent = True  # counts as "would have sent"
    else:
        ok = email_automation.send_job_alert(new_jobs_recs, reminder_recs)
        if ok:
            mail_sent = True
            for rec in new_jobs_recs + reminder_recs:
                rec["status"] = STATUS_NOTIFIED
                rec["last_sent_at"] = stamp
            log.info(f"       email sent successfully")
        else:
            log.warning("       email_automation returned False (disabled or error)")

    if not dry_run:
        save_state(state)
        write_tracker(state, tracker_path, tracker_rows)

    return mail_sent


# ---------------------------------------------------------------------------
# Pipeline stats summary
# ---------------------------------------------------------------------------

def _log_pipeline_summary(
    scraped: int,
    normalized: int,
    after_hard_filter: int,
    after_llm: int,
    after_dedupe: int,
    final_digest: int,
    rejected_hard: int,
    dry_run: bool,
) -> None:
    log.info("=" * 60)
    log.info("PIPELINE SUMMARY")
    log.info(f"  scraped          : {scraped}")
    log.info(f"  after normalize  : {normalized}")
    log.info(f"  after hard_filter: {after_hard_filter}  (rejected: {rejected_hard})")
    log.info(f"  after llm_review : {after_llm}")
    log.info(f"  after dedupe     : {after_dedupe}")
    log.info(f"  final digest     : {final_digest}")
    if dry_run:
        log.info("  mode             : DRY RUN (no email sent, no state saved)")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, sources: list[str] | None = None) -> None:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    log.info(f"Daily pipeline started at {stamp}")

    lock = _lock_path()
    if not _acquire_lock(lock, _lock_ttl()):
        return

    try:
        # 1. Collect
        raw_jobs = _step_collect(sources)
        scraped_count = len(raw_jobs)

        if not raw_jobs:
            log.info("No jobs scraped – pipeline exits early.")
            _log_pipeline_summary(0, 0, 0, 0, 0, 0, 0, dry_run)
            return

        # 2. Normalize
        normalized = _step_normalize(raw_jobs)

        # 3. Hard filter
        kept, rejected_hard = _step_hard_filter(normalized)
        after_hard_count = len(kept)

        # 3b. Detail-page hard-phrase filter (runs on candidates only, fetches detail URLs)
        from pipeline.detail_filter import detail_filter  # noqa: PLC0415
        kept, detail_rejected, detail_stats = detail_filter(kept)
        after_detail_count = len(kept)

        # 4. LLM review (also rejects obvious mismatches)
        after_llm = _step_llm_review(kept)

        # 5. Dedupe
        deduped = _step_dedupe(after_llm)

        # 6. Final rank
        ranked = _step_final_rank(deduped)

        # 7. Email digest + state management
        _step_email(ranked, dry_run=dry_run, stamp=stamp)

        _log_pipeline_summary(
            scraped=scraped_count,
            normalized=len(normalized),
            after_hard_filter=after_hard_count,
            after_llm=len(after_llm),
            after_dedupe=len(deduped),
            final_digest=len(ranked),
            rejected_hard=len(rejected_hard),
            dry_run=dry_run,
        )

        # Write summary for web UI status endpoint
        try:
            summary_path = _PROJECT_ROOT / "generated" / "pipeline_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps({
                    "scraped":                 scraped_count,
                    "after_hard_filter":       after_hard_count,
                    "after_detail_filter":     after_detail_count,
                    "detail_skipped_domain":   detail_stats["skipped_domain"],
                    "detail_fetch_failed":     detail_stats["fetch_failed"],
                    "detail_cap_reached":      detail_stats["cap_reached"],
                    "detail_phrase_hits":      detail_stats["rejected_phrase_hits"],
                    "after_llm":               len(after_llm),
                    "digested":                len(ranked),
                    "finished_at":             datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _summary_exc:
            log.debug("pipeline_summary.json write failed: %s", _summary_exc)

    except Exception as exc:
        log.exception(f"Pipeline failed with unexpected error: {exc}")
        # Try to send error notification
        try:
            from bewerbungsagent.email_automation import email_automation
            import traceback as tb
            email_automation.send_error_notification(
                "DailyPipelineError",
                str(exc),
                tb.format_exc(),
            )
        except Exception:
            pass
        raise
    finally:
        _release_lock(lock)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily job pipeline")
    parser.add_argument("--dry-run", action="store_true", help="No email, no state write")
    parser.add_argument(
        "--source",
        default="",
        help="Comma-separated source filter, e.g. jobs.ch,jobscout24",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sources = [s.strip() for s in args.source.split(",") if s.strip()] or None
    run(dry_run=args.dry_run, sources=sources)
