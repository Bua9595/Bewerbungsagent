from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict

from job_state import (
    STATUS_APPLIED,
    STATUS_CLOSED,
    STATUS_IGNORED,
    parse_ts,
)

TRACKER_HEADERS = [
    "job_uid",
    "status",
    "erledigt",
    "aktion",
    "title",
    "company",
    "location",
    "source",
    "link",
    "first_seen_at",
    "last_seen_at",
    "last_sent_at",
    "score",
    "match",
    "notes",
]

MANUAL_COLUMNS = {"erledigt", "aktion", "notes"}

TRUTHY = {"1", "true", "t", "yes", "y", "ja", "j", "x"}
APPLIED_ACTIONS = {"applied", "apply", "done", "sent", "bewerbung", "gesendet"}
IGNORED_ACTIONS = {"ignored", "ignore", "skip", "no", "nein"}


def get_tracker_path() -> Path:
    return Path(os.getenv("JOB_TRACKER_FILE", "generated/job_tracker.csv"))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def load_tracker(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "job_uid" not in reader.fieldnames:
            return {}
        rows: Dict[str, Dict[str, Any]] = {}
        for row in reader:
            uid = _clean(row.get("job_uid"))
            if not uid:
                continue
            rows[uid] = row
        return rows


def apply_tracker_marks(
    state: Dict[str, Dict[str, Any]],
    tracker_rows: Dict[str, Dict[str, Any]],
) -> int:
    updates = 0
    for uid, row in tracker_rows.items():
        record = state.get(uid)
        if not record:
            continue
        action = _clean(row.get("aktion")).lower()
        done = _clean(row.get("erledigt")).lower()
        desired = ""
        if action in APPLIED_ACTIONS:
            desired = STATUS_APPLIED
        elif action in IGNORED_ACTIONS:
            desired = STATUS_IGNORED
        elif done in TRUTHY:
            desired = STATUS_APPLIED
        if desired and record.get("status") != desired:
            record["status"] = desired
            updates += 1
    return updates


def _sort_key(row: Dict[str, Any]) -> float:
    last_seen = parse_ts(_clean(row.get("last_seen_at")))
    return last_seen.timestamp() if last_seen else 0.0


def build_tracker_rows(
    state: Dict[str, Dict[str, Any]],
    existing_rows: Dict[str, Dict[str, Any]] | None = None,
    include_closed: bool = False,
) -> list[Dict[str, Any]]:
    existing_rows = existing_rows or {}
    rows: list[Dict[str, Any]] = []
    for uid, record in state.items():
        status = record.get("status") or ""
        if status == STATUS_CLOSED and not include_closed:
            continue
        row = {k: "" for k in TRACKER_HEADERS}
        row.update(
            {
                "job_uid": uid,
                "status": status,
                "title": record.get("title") or "",
                "company": record.get("company") or "",
                "location": record.get("location") or "",
                "source": record.get("source") or "",
                "link": record.get("link") or record.get("canonical_url") or "",
                "first_seen_at": record.get("first_seen_at") or "",
                "last_seen_at": record.get("last_seen_at") or "",
                "last_sent_at": record.get("last_sent_at") or "",
                "score": record.get("score") or "",
                "match": record.get("match") or "",
            }
        )
        existing = existing_rows.get(uid, {})
        for col in MANUAL_COLUMNS:
            if _clean(existing.get(col)):
                row[col] = existing.get(col)
        if status in (STATUS_APPLIED, STATUS_IGNORED):
            row["erledigt"] = "x"
            if status == STATUS_APPLIED and not row["aktion"]:
                row["aktion"] = "applied"
            if status == STATUS_IGNORED and not row["aktion"]:
                row["aktion"] = "ignored"
        rows.append(row)

    rows.sort(key=_sort_key, reverse=True)
    return rows


def write_tracker(
    state: Dict[str, Dict[str, Any]],
    path: Path,
    existing_rows: Dict[str, Dict[str, Any]] | None = None,
    include_closed: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_tracker_rows(state, existing_rows, include_closed)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
