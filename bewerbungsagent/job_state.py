from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse, urlunparse

STATE_PATH = Path("generated/job_state.json")
SEEN_PATH = Path("generated/seen_jobs.json")

STATUS_NEW = "new"
STATUS_NOTIFIED = "notified"
STATUS_APPLIED = "applied"
STATUS_IGNORED = "ignored"
STATUS_CLOSED = "closed"

OPEN_STATUSES = {STATUS_NEW, STATUS_NOTIFIED}
TERMINAL_STATUSES = {STATUS_APPLIED, STATUS_IGNORED, STATUS_CLOSED}


def now_iso() -> str:
    # UTC-Timestamp in ISO-Format (Z-Suffix).
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_ts(value: str | None) -> datetime | None:
    # ISO-Timestamp sicher parsen.
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_text(value: str) -> str:
    # Text normalisieren (lowercase, diakritische entfernen, nur a-z0-9).
    text = (value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_url(url: str) -> str:
    # URL auf kanonische Form kuerzen (Schema/Host lower, Pfad ohne Slash).
    if not url:
        return ""
    raw = url.strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw
    path = parsed.path or ""
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", "")
    )


def _job_to_dict(job: Any) -> Dict[str, Any]:
    # Jobobjekt robust in Dict umwandeln.
    if isinstance(job, dict):
        return dict(job)
    if hasattr(job, "__dict__"):
        return dict(job.__dict__)
    return {}


def build_job_uid(job: Any) -> Tuple[str, str]:
    # Stabile UID aus URL/ID/Fallback-Daten erzeugen.
    data = _job_to_dict(job)
    source = (
        data.get("source")
        or data.get("portal")
        or data.get("origin")
        or data.get("site")
        or ""
    ).strip()
    if not source:
        source = "unknown"

    link = (
        data.get("link")
        or data.get("url")
        or data.get("apply_url")
        or data.get("applyLink")
        or ""
    ).strip()
    canonical_url = canonicalize_url(link)

    # Prioritaet: kanonische URL -> externe ID -> Fallback-Text.
    base = ""
    if canonical_url:
        base = f"url|{source}|{canonical_url}"
    else:
        external_id = (
            data.get("external_id")
            or data.get("job_id")
            or data.get("id")
            or ""
        ).strip()
        if external_id:
            base = f"id|{source}|{external_id}"
        else:
            title = _normalize_text(
                data.get("title")
                or data.get("job_title")
                or data.get("position")
                or ""
            )
            company = _normalize_text(
                data.get("company") or data.get("employer") or ""
            )
            location = _normalize_text(
                data.get("location") or data.get("city") or ""
            )
            link_norm = _normalize_text(link)
            base = f"fallback|{source}|{title}|{company}|{location}|{link_norm}"

    job_uid = sha256(base.encode("utf-8")).hexdigest()[:16]
    return job_uid, canonical_url


def _empty_state_record(now: str) -> Dict[str, Any]:
    # Basisstruktur fuer einen State-Eintrag.
    return {
        "job_uid": "",
        "source": "",
        "canonical_url": "",
        "link": "",
        "title": "",
        "company": "",
        "location": "",
        "first_seen_at": now,
        "last_seen_at": now,
        "last_sent_at": None,
        "status": STATUS_NOTIFIED,
        "score": "",
        "match": "",
        "commute_min": None,
        "missing_runs": 0,
    }


def _migrate_seen_jobs(seen_path: Path, now: str) -> Dict[str, Dict[str, Any]]:
    # Altes seen_jobs.json in neues State-Format migrieren.
    state: Dict[str, Dict[str, Any]] = {}
    try:
        raw = json.loads(seen_path.read_text(encoding="utf-8"))
    except Exception:
        return state

    if isinstance(raw, dict):
        raw = list(raw.keys())
    if not isinstance(raw, list):
        return state

    # Eintraege in neue Struktur uebertragen.
    for entry in raw:
        if isinstance(entry, dict):
            job_uid, canonical_url = build_job_uid(entry)
            record = _empty_state_record(now)
            record.update(
                {
                    "job_uid": job_uid,
                    "source": (
                        entry.get("source")
                        or entry.get("portal")
                        or entry.get("origin")
                        or ""
                    ),
                    "canonical_url": canonical_url,
                    "link": entry.get("link") or entry.get("url") or "",
                    "title": entry.get("title") or "",
                    "company": entry.get("company") or "",
                    "location": entry.get("location") or "",
                    "last_sent_at": now,
                    "status": STATUS_NOTIFIED,
                }
            )
        else:
            # Legacy-Format: nur ein Key pro Eintrag.
            key = str(entry)
            job_uid = sha256(f"legacy|{key}".encode("utf-8")).hexdigest()[:16]
            record = _empty_state_record(now)
            record.update(
                {
                    "job_uid": job_uid,
                    "source": "legacy",
                    "last_sent_at": now,
                    "status": STATUS_NOTIFIED,
                    "legacy_key": key,
                }
            )
        state[job_uid] = record

    return state


def load_state(
    path: Path = STATE_PATH,
    seen_path: Path = SEEN_PATH,
    now: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    # State laden; falls nicht vorhanden, optional aus seen_jobs migrieren.
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            # Legacy-Liste in Dict nach job_uid konvertieren.
            converted = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                job_uid = item.get("job_uid")
                if not job_uid:
                    continue
                converted[job_uid] = item
            return converted
        return {}

    if seen_path.exists():
        stamp = now or now_iso()
        return _migrate_seen_jobs(seen_path, stamp)

    return {}


def save_state(state: Dict[str, Dict[str, Any]], path: Path = STATE_PATH) -> None:
    # State als JSON im Zielpfad speichern.
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(payload, encoding="utf-8")


def should_send_reminder(
    last_sent_at: str | None,
    now_dt: datetime,
    reminder_days: int,
    daily_reminders: bool,
) -> bool:
    # Entscheiden, ob ein Reminder faellig ist.
    if daily_reminders:
        return True
    if not last_sent_at:
        return True
    if reminder_days <= 0:
        return True
    last_dt = parse_ts(last_sent_at)
    if not last_dt:
        return True
    delta = now_dt - last_dt
    return delta.days >= reminder_days
