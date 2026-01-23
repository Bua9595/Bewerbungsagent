from __future__ import annotations

from typing import Any


def sync_tracker(_args=None) -> None:
    from bewerbungsagent.job_state import (
        load_state,
        save_state,
        STATUS_CLOSED,
        TERMINAL_STATUSES,
    )
    from bewerbungsagent.job_tracker import (
        apply_tracker_marks,
        get_tracker_path,
        load_tracker,
        write_tracker,
    )
    from tools.commands.mail_list import close_aggregator_records

    state = load_state()
    if not state:
        print("Kein job_state.json vorhanden.")
        return

    tracker_path = get_tracker_path()
    tracker_rows = load_tracker(tracker_path)
    if not tracker_rows:
        print("Kein job_tracker vorhanden.")
        return

    updates = apply_tracker_marks(state, tracker_rows)
    closed_aggregators = close_aggregator_records(
        state, TERMINAL_STATUSES, STATUS_CLOSED
    )
    if updates or closed_aggregators:
        save_state(state)
    write_tracker(state, tracker_path, tracker_rows)
    print(f"Tracker Sync: {updates} Aktualisierungen.")


def run_tracker_ui(args) -> None:
    from bewerbungsagent.tracker_ui import run_tracker_ui as _run

    _run(
        host=getattr(args, "host", "127.0.0.1"),
        port=getattr(args, "port", 8765),
        open_browser=bool(getattr(args, "open", False)),
    )


def resolve_job_uid(state: dict, job_uid: str, url: str) -> str | None:
    from bewerbungsagent.job_state import canonicalize_url

    if job_uid:
        matches = [uid for uid in state.keys() if uid.startswith(job_uid)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print("Mehrere Treffer fuer job_uid, bitte laenger angeben.")
            return None
        print("Keine Treffer fuer job_uid.")
        return None

    if url:
        target = url.strip()
        target_canon = canonicalize_url(target)
        matches = []
        for uid, record in state.items():
            link = record.get("link") or ""
            canon = record.get("canonical_url") or ""
            if target and target == link:
                matches.append(uid)
                continue
            if target_canon:
                if canon and canonicalize_url(canon) == target_canon:
                    matches.append(uid)
                    continue
                if link and canonicalize_url(link) == target_canon:
                    matches.append(uid)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print("Mehrere Treffer fuer URL, bitte job_uid nutzen.")
            return None
        print("Keine Treffer fuer URL.")
        return None

    print("Bitte job_uid oder --url angeben.")
    return None


def mark_job_status(args: Any, status: str) -> None:
    from bewerbungsagent.job_state import load_state, save_state
    from bewerbungsagent.job_tracker import (
        get_tracker_path,
        load_tracker,
        write_tracker,
    )

    state = load_state()
    if not state:
        print("Kein job_state.json vorhanden.")
        return

    job_uid = resolve_job_uid(
        state, getattr(args, "job_uid", ""), getattr(args, "url", "")
    )
    if not job_uid:
        return

    record = state.get(job_uid)
    if not record:
        print("Job nicht gefunden.")
        return

    prev = record.get("status") or ""
    record["status"] = status
    save_state(state)

    try:
        tracker_rows = load_tracker(get_tracker_path())
        write_tracker(state, get_tracker_path(), tracker_rows)
    except Exception:
        pass

    title = record.get("title") or "Titel unbekannt"
    company = record.get("company") or "Firma unbekannt"
    print(f"{job_uid}: {prev} -> {status} ({title} - {company})")


def mark_applied(args) -> None:
    from bewerbungsagent.job_state import STATUS_APPLIED

    mark_job_status(args, STATUS_APPLIED)


def mark_ignored(args) -> None:
    from bewerbungsagent.job_state import STATUS_IGNORED

    mark_job_status(args, STATUS_IGNORED)
