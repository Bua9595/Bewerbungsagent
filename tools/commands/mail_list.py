from __future__ import annotations

import atexit
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.common import as_dict, env_bool, env_int, is_dry_run, score_value


AGGREGATOR_SOURCES = {"careerjet", "jobrapido", "jooble"}


def close_aggregator_records(state, terminal_statuses, status_closed) -> int:
    closed = 0
    for record in state.values():
        source = (record.get("source") or "").strip().lower()
        if source in AGGREGATOR_SOURCES and record.get("status") not in terminal_statuses:
            record["status"] = status_closed
            closed += 1
    return closed


def _run_lock_path() -> Path:
    return Path(os.getenv("RUN_LOCK_FILE", "generated/mail_list.lock"))


def _run_lock_ttl_min() -> int:
    return env_int("RUN_LOCK_TTL_MIN", 120)


def _read_lock_payload(lock_path: Path) -> dict:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _lock_is_stale(lock_path: Path, ttl_min: int) -> bool:
    if ttl_min <= 0:
        return True
    payload = _read_lock_payload(lock_path)
    started_raw = payload.get("started_at")
    if not started_raw:
        return True
    try:
        from bewerbungsagent.job_state import parse_ts

        started = parse_ts(started_raw)
    except Exception:
        started = None
    if not started:
        return True
    return (datetime.now(timezone.utc) - started) > timedelta(minutes=ttl_min)


def _release_run_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _acquire_run_lock(lock_path: Path, ttl_min: int, logger=None) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        if not _lock_is_stale(lock_path, ttl_min):
            msg = f"Run-Lock aktiv, Abbruch: {lock_path}"
            print(msg)
            if logger:
                logger.warning(msg)
            return False
        _release_run_lock(lock_path)
        if logger:
            logger.info(f"Stale Run-Lock entfernt: {lock_path}")
    try:
        from bewerbungsagent.job_state import now_iso

        payload = {
            "pid": os.getpid(),
            "started_at": now_iso(),
            "ttl_min": ttl_min,
        }
        with lock_path.open("x", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except FileExistsError:
        msg = f"Run-Lock aktiv, Abbruch: {lock_path}"
        print(msg)
        if logger:
            logger.warning(msg)
        return False
    except Exception as exc:
        msg = f"Run-Lock konnte nicht erstellt werden: {exc}"
        print(msg)
        if logger:
            logger.warning(msg)
        return False
    atexit.register(_release_run_lock, lock_path)
    if logger:
        logger.info(f"Run-Lock gesetzt: {lock_path}")
    return True


@dataclass
class MailSettings:
    min_score: int
    reminder_days: int
    close_missing_runs: int
    close_not_seen_days: int
    daily_reminders: bool


def _mail_settings() -> MailSettings:
    return MailSettings(
        min_score=env_int("MIN_SCORE_MAIL", 2),
        reminder_days=env_int("REMINDER_DAYS", 2),
        close_missing_runs=env_int("CLOSE_MISSING_RUNS", 3),
        close_not_seen_days=env_int("CLOSE_NOT_SEEN_DAYS", 7),
        daily_reminders=env_bool("REMINDER_DAILY", False),
    )


def _payload_from_rows(rows: Iterable[Any], min_score: int) -> list[dict]:
    rows_list = list(rows)
    filtered = [r for r in rows_list if (getattr(r, "score", 0) or 0) >= min_score]
    if not filtered:
        filtered = rows_list[:10]
    return [as_dict(r) for r in filtered]


def _merge_payload(
    payload: list[dict],
    state: dict,
    stamp: str,
    now_dt: datetime,
    close_missing_runs: int,
    close_not_seen_days: int,
):
    from bewerbungsagent.job_state import (
        STATUS_APPLIED,
        STATUS_CLOSED,
        STATUS_IGNORED,
        STATUS_NEW,
        STATUS_NOTIFIED,
        build_job_uid,
        canonicalize_url,
        parse_ts,
    )

    seen_this_run = set()
    newly_added = 0

    for row in payload:
        job_uid, canonical_url = build_job_uid(row)
        seen_this_run.add(job_uid)

        link = (
            row.get("link")
            or row.get("url")
            or row.get("apply_url")
            or row.get("applyLink")
            or ""
        )

        record = state.get(job_uid)
        if not record:
            record = {
                "job_uid": job_uid,
                "source": row.get("source") or "",
                "canonical_url": canonical_url or canonicalize_url(link) or link,
                "link": link,
                "title": row.get("title") or "",
                "company": row.get("company") or "",
                "location": row.get("location") or "",
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "last_sent_at": None,
                "status": STATUS_NEW,
                "score": row.get("score", ""),
                "match": row.get("match", ""),
                "date": row.get("date", ""),
                "commute_min": row.get("commute_min"),
                "missing_runs": 0,
            }
            state[job_uid] = record
            newly_added += 1
            continue

        record["source"] = row.get("source") or record.get("source", "")
        record["canonical_url"] = (
            canonical_url
            or record.get("canonical_url", "")
            or canonicalize_url(link)
            or link
        )
        record["link"] = link or record.get("link", "")
        record["title"] = row.get("title") or record.get("title", "")
        record["company"] = row.get("company") or record.get("company", "")
        record["location"] = row.get("location") or record.get("location", "")
        if row.get("score") not in (None, ""):
            record["score"] = row.get("score")
        if row.get("match"):
            record["match"] = row.get("match")
        if row.get("date"):
            record["date"] = row.get("date")
        if row.get("commute_min") is not None:
            record["commute_min"] = row.get("commute_min")
        record["last_seen_at"] = stamp
        record["missing_runs"] = 0

        status = record.get("status") or STATUS_NEW
        if status == STATUS_CLOSED:
            status = STATUS_NOTIFIED if record.get("last_sent_at") else STATUS_NEW
        if status not in (STATUS_APPLIED, STATUS_IGNORED):
            record["status"] = status

    marked_closed_count = 0
    for uid, record in state.items():
        if uid in seen_this_run:
            continue
        if record.get("status") in (STATUS_APPLIED, STATUS_IGNORED, STATUS_CLOSED):
            continue
        record["missing_runs"] = int(record.get("missing_runs", 0)) + 1
        last_seen = parse_ts(record.get("last_seen_at"))
        days_missing = (now_dt - last_seen).days if last_seen else 0
        if (
            close_missing_runs > 0
            and record["missing_runs"] >= close_missing_runs
        ) or (
            close_not_seen_days > 0
            and days_missing >= close_not_seen_days
        ):
            record["status"] = STATUS_CLOSED
            marked_closed_count += 1

    return seen_this_run, newly_added, marked_closed_count


def _classify_jobs(state, seen_this_run, now_dt, reminder_days, daily_reminders):
    from bewerbungsagent.job_state import (
        OPEN_STATUSES,
        TERMINAL_STATUSES,
        STATUS_NEW,
        should_send_reminder,
    )

    new_jobs = []
    reminder_jobs = []
    open_jobs = []
    new_uids = set()

    for uid in seen_this_run:
        record = state.get(uid)
        if not record or record.get("status") in TERMINAL_STATUSES:
            continue
        if record.get("status") == STATUS_NEW:
            new_jobs.append(record)
            new_uids.add(uid)

    for uid in seen_this_run:
        record = state.get(uid)
        if not record or record.get("status") in TERMINAL_STATUSES:
            continue
        if (
            record.get("status") in OPEN_STATUSES
            and should_send_reminder(
                record.get("last_sent_at"),
                now_dt,
                reminder_days,
                daily_reminders,
            )
        ):
            if uid not in new_uids:
                reminder_jobs.append(record)

    for uid in seen_this_run:
        record = state.get(uid)
        if not record or record.get("status") in TERMINAL_STATUSES:
            continue
        if record.get("status") in OPEN_STATUSES:
            open_jobs.append(record)

    new_jobs.sort(key=lambda r: score_value(r.get("score")), reverse=True)
    reminder_jobs.sort(key=lambda r: score_value(r.get("score")), reverse=True)
    open_jobs.sort(key=lambda r: score_value(r.get("score")), reverse=True)
    return new_jobs, reminder_jobs, open_jobs


def _maybe_send_mail(args, send_jobs, send_reminders, stamp):
    from bewerbungsagent.job_state import STATUS_NOTIFIED
    from bewerbungsagent.email_automation import email_automation

    mailed_new_count = 0
    mailed_reminder_count = 0
    mail_sent = False
    send_open = bool(args and getattr(args, "send_open", False))

    if not send_jobs and not send_reminders:
        if send_open:
            print("Keine offenen Jobs zum Senden.")
        else:
            print("Keine neuen oder offenen Jobs zum Senden.")
        return mailed_new_count, mailed_reminder_count, mail_sent

    if is_dry_run(args):
        mailed_new_count = len(send_jobs)
        mailed_reminder_count = len(send_reminders)
        if send_open:
            print(
                f"[DRY RUN] Mail waere gesendet worden ({mailed_new_count} offene Jobs)."
            )
        else:
            print(
                f"[DRY RUN] Mail waere gesendet worden ({mailed_new_count} neu, {mailed_reminder_count} Reminder)."
            )
        return mailed_new_count, mailed_reminder_count, mail_sent

    ok = email_automation.send_job_alert(send_jobs, send_reminders)
    if not ok:
        print("Mail/WhatsApp uebersprungen (disabled oder Fehler).")
        return mailed_new_count, mailed_reminder_count, mail_sent

    mail_sent = True
    mailed_new_count = len(send_jobs)
    mailed_reminder_count = len(send_reminders)
    for record in send_jobs + send_reminders:
        record["status"] = STATUS_NOTIFIED
        record["last_sent_at"] = stamp

    if send_open:
        print(f"E-Mail gesendet ({mailed_new_count} offene Jobs)")
    else:
        print(f"E-Mail gesendet ({mailed_new_count} neu, {mailed_reminder_count} Reminder)")
    return mailed_new_count, mailed_reminder_count, mail_sent


def _collect_stats(state, scraped_total, unique_total, newly_added, active_seen, mailed_new, mailed_reminder, marked_closed, applied_count, ignored_count, dry_run, mail_sent):
    return {
        "scraped_total": scraped_total,
        "unique_total": unique_total,
        "state_total": len(state),
        "newly_added": newly_added,
        "active_seen_this_run": active_seen,
        "mailed_new_count": mailed_new,
        "mailed_reminder_count": mailed_reminder,
        "marked_closed_count": marked_closed,
        "applied_count": applied_count,
        "ignored_count": ignored_count,
        "dry_run": dry_run,
        "mail_sent": mail_sent,
    }


def _print_stats(stats: dict) -> None:
    print("Mail-Statistik:")
    for key in [
        "scraped_total",
        "unique_total",
        "state_total",
        "newly_added",
        "active_seen_this_run",
        "mailed_new_count",
        "mailed_reminder_count",
        "marked_closed_count",
        "applied_count",
        "ignored_count",
    ]:
        print(f"{key}: {stats[key]}")


def send_job_alerts(args=None) -> None:
    try:
        from bewerbungsagent.job_collector import collect_jobs, export_json
        from bewerbungsagent.job_state import (
            TERMINAL_STATUSES,
            STATUS_APPLIED,
            STATUS_CLOSED,
            STATUS_IGNORED,
            load_state,
            now_iso,
            parse_ts,
            save_state,
        )
        from bewerbungsagent.job_tracker import (
            apply_tracker_marks,
            get_tracker_path,
            load_tracker,
            write_tracker,
        )
        from bewerbungsagent.logger import job_logger
    except Exception as exc:
        print(f"Mail-Liste Fehler: {exc}")
        return

    lock_path = _run_lock_path()
    lock_ttl_min = _run_lock_ttl_min()
    if not _acquire_run_lock(lock_path, lock_ttl_min, job_logger):
        return

    settings = _mail_settings()
    stamp = now_iso()
    now_dt = parse_ts(stamp) or datetime.now(timezone.utc)

    state_path = Path("generated/job_state.json")
    seen_path = Path("generated/seen_jobs.json")
    migrated_from_seen = (not state_path.exists()) and seen_path.exists()

    state = load_state(now=stamp)

    tracker_path = get_tracker_path()
    tracker_rows = load_tracker(tracker_path)
    tracker_updates = apply_tracker_marks(state, tracker_rows)
    closed_aggregators = close_aggregator_records(
        state, TERMINAL_STATUSES, STATUS_CLOSED
    )
    if closed_aggregators:
        job_logger.info(f"Aggregator-Eintraege geschlossen: {closed_aggregators}")

    rows = collect_jobs()
    scraped_total = len(rows)
    if not rows:
        applied_count = sum(
            1 for record in state.values() if record.get("status") == STATUS_APPLIED
        )
        ignored_count = sum(
            1 for record in state.values() if record.get("status") == STATUS_IGNORED
        )
        stats = _collect_stats(
            state=state,
            scraped_total=scraped_total,
            unique_total=0,
            newly_added=0,
            active_seen=0,
            mailed_new=0,
            mailed_reminder=0,
            marked_closed=0,
            applied_count=applied_count,
            ignored_count=ignored_count,
            dry_run=is_dry_run(args),
            mail_sent=False,
        )
        _print_stats(stats)
        job_logger.info(
            "Mail-Statistik " + ", ".join(f"{k}={v}" for k, v in stats.items())
        )
        if migrated_from_seen or tracker_updates:
            save_state(state)
        if migrated_from_seen:
            print("Hinweis: seen_jobs.json wurde in job_state.json migriert.")
        write_tracker(state, tracker_path, tracker_rows)
        job_logger.info(f"Run-Lock freigegeben: {lock_path}")
        _release_run_lock(lock_path)
        return

    export_json(rows)

    payload = _payload_from_rows(rows, settings.min_score)
    unique_total = len(payload)

    seen_this_run, newly_added, marked_closed_count = _merge_payload(
        payload,
        state,
        stamp,
        now_dt,
        settings.close_missing_runs,
        settings.close_not_seen_days,
    )

    new_jobs, reminder_jobs, open_jobs = _classify_jobs(
        state,
        seen_this_run,
        now_dt,
        settings.reminder_days,
        settings.daily_reminders,
    )

    active_seen = sum(
        1
        for uid in seen_this_run
        if uid in state and state[uid].get("status") not in TERMINAL_STATUSES
    )
    applied_count = sum(
        1 for record in state.values() if record.get("status") == STATUS_APPLIED
    )
    ignored_count = sum(
        1 for record in state.values() if record.get("status") == STATUS_IGNORED
    )

    send_open = bool(args and getattr(args, "send_open", False))
    send_jobs = open_jobs if send_open else new_jobs
    send_reminders = [] if send_open else reminder_jobs

    mailed_new_count, mailed_reminder_count, mail_sent = _maybe_send_mail(
        args, send_jobs, send_reminders, stamp
    )

    save_state(state)

    stats = _collect_stats(
        state=state,
        scraped_total=scraped_total,
        unique_total=unique_total,
        newly_added=newly_added,
        active_seen=active_seen,
        mailed_new=mailed_new_count,
        mailed_reminder=mailed_reminder_count,
        marked_closed=marked_closed_count,
        applied_count=applied_count,
        ignored_count=ignored_count,
        dry_run=is_dry_run(args),
        mail_sent=mail_sent,
    )

    _print_stats(stats)
    job_logger.info(
        "Mail-Statistik " + ", ".join(f"{k}={v}" for k, v in stats.items())
    )
    if migrated_from_seen:
        print("Hinweis: seen_jobs.json wurde in job_state.json migriert.")
    write_tracker(state, tracker_path, tracker_rows)
    job_logger.info(f"Run-Lock freigegeben: {lock_path}")
    _release_run_lock(lock_path)
