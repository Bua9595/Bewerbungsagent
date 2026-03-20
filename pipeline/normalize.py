"""Normalize raw Job objects to a unified NormalizedJob schema.

Every downstream pipeline step works exclusively with NormalizedJob so that
scraper-specific quirks are isolated here.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

from bewerbungsagent.job_collector import Job


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class NormalizedJob:
    # --- Identity ---
    source: str = ""
    source_job_id: str = ""
    url: str = ""           # canonical URL (also used as "link" by email system)
    link: str = ""          # alias kept for email-system compatibility

    # --- Core display fields ---
    title: str = ""
    raw_title: str = ""
    company: str = ""
    location: str = ""

    # --- Extended schema fields (best-effort, may be empty) ---
    workload: str = ""
    published_at: str = ""
    description_raw: str = ""
    language_hint: str = ""     # "de" | "en" | "fr" | "it" | ""
    employment_type: str = ""   # "Vollzeit" | "Teilzeit" | "Freelance" | ""
    salary_hint: str = ""

    # --- Scoring from collector (rule-based) ---
    score_rule: int = 0
    score: int = 0              # kept in sync with score_final at end of pipeline
    match: str = "unknown"      # exact | good | weak | unknown
    date: str = ""
    commute_min: Optional[int] = None

    # --- LLM enrichment (filled by ranking/llm_review.py) ---
    llm_review: Optional[dict] = None

    # --- Final output ---
    score_final: float = 0.0
    reason_short: str = ""      # filled from llm_review

    # --- Rejection tracking ---
    rejected: bool = False
    reject_reason: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKLOAD_RE = re.compile(
    r"(\d{2,3})\s*[-–]\s*(\d{2,3})\s*%"
    r"|(\d{2,3})\s*%",
    re.IGNORECASE,
)

_EMPLOYMENT_KEYWORDS = {
    "Vollzeit": ["vollzeit", "full-time", "fulltime", "100%", "pensum 100"],
    "Teilzeit": ["teilzeit", "part-time", "parttime", "50%", "60%", "70%", "80%"],
    "Freelance": ["freelance", "freelance", "selbständig", "selbstaendig", "contract"],
}

_LANG_KEYWORDS = {
    "de": ["deutsch", "german", "deutschkenntnisse", "deutschsprachig"],
    "en": ["english", "englisch", "englishspeaking"],
    "fr": ["francais", "français", "french", "französisch", "franzosisch"],
    "it": ["italiano", "italian", "italienisch"],
}

_SOURCE_ID_PATTERNS: list[tuple[str, str]] = [
    # (source_prefix, regex_group_name)
    (r"jobs\.ch", r"/(\d{6,})"),
    (r"jobup\.ch", r"/(\d{6,})"),
    (r"jobscout24", r"[?&]id=([^&]+)"),
    (r"monster\.", r"/(\d{6,})"),
    (r"indeed\.", r"[?&]jk=([a-zA-Z0-9]+)"),
    (r"itjobs\.ch", r"/(\d{4,})"),
    (r"ictjobs\.ch", r"/(\d{4,})"),
    (r"jobwinner", r"/(\d{4,})"),
    (r"swissdevjobs", r"/(\d{4,})"),
]


def _extract_source_job_id(url: str) -> str:
    if not url:
        return ""
    for pattern, id_pattern in _SOURCE_ID_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            m = re.search(id_pattern, url)
            if m:
                return m.group(1)
    # Fallback: last path segment that looks like an ID
    try:
        path = urlparse(url).path.rstrip("/")
        last = path.split("/")[-1] if path else ""
        if re.match(r"^[\w-]{4,}$", last):
            return last
    except Exception:
        pass
    return ""


def _detect_language(title: str, raw_title: str) -> str:
    combined = (title + " " + raw_title).lower()
    for lang, kws in _LANG_KEYWORDS.items():
        for kw in kws:
            if kw in combined:
                return lang
    # Default to German for Swiss job market
    return "de"


def _detect_employment_type(title: str, raw_title: str) -> str:
    combined = (title + " " + raw_title).lower()
    for emp_type, kws in _EMPLOYMENT_KEYWORDS.items():
        for kw in kws:
            if kw in combined.lower():
                return emp_type
    return ""


def _detect_workload(title: str, raw_title: str) -> str:
    combined = title + " " + raw_title
    m = _WORKLOAD_RE.search(combined)
    if m:
        return m.group(0).strip()
    return ""


def _clean_text(value: str) -> str:
    """Strip, collapse whitespace, remove control chars."""
    if not value:
        return ""
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _normalize_date(date_str: str) -> str:
    """Attempt to unify date to YYYY-MM-DD; return as-is if unparseable."""
    if not date_str:
        return ""
    cleaned = date_str.strip()
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned[:10]
    # DD.MM.YYYY
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", cleaned)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # DD/MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return cleaned


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def normalize_jobs(jobs: List[Job]) -> List[NormalizedJob]:
    """Convert raw Job objects to NormalizedJob list. Never raises."""
    result: List[NormalizedJob] = []
    for job in jobs:
        try:
            result.append(_normalize_single(job))
        except Exception as exc:
            # Log but do not abort the entire run
            try:
                from bewerbungsagent.logger import job_logger
                job_logger.warning(f"normalize: error for job {getattr(job, 'link', '?')}: {exc}")
            except Exception:
                pass
    return result


def _normalize_single(job: Job) -> NormalizedJob:
    raw_title = _clean_text(getattr(job, "raw_title", "") or "")
    title = _clean_text(getattr(job, "title", "") or raw_title)
    company = _clean_text(getattr(job, "company", "") or "")
    location = _clean_text(getattr(job, "location", "") or "")
    link = _clean_text(getattr(job, "link", "") or "")
    source = _clean_text(getattr(job, "source", "") or "")
    score_rule = int(getattr(job, "score", 0) or 0)
    match = _clean_text(getattr(job, "match", "") or "unknown")
    date = _normalize_date(getattr(job, "date", "") or "")
    commute_min = getattr(job, "commute_min", None)

    workload = _detect_workload(title, raw_title)
    employment_type = _detect_employment_type(title, raw_title)
    language_hint = _detect_language(title, raw_title)

    source_job_id = _extract_source_job_id(link)

    return NormalizedJob(
        source=source,
        source_job_id=source_job_id,
        url=link,
        link=link,
        title=title,
        raw_title=raw_title,
        company=company,
        location=location,
        workload=workload,
        published_at=date,
        description_raw="",    # not carried in Job dataclass
        language_hint=language_hint,
        employment_type=employment_type,
        salary_hint="",
        score_rule=score_rule,
        score=score_rule,
        match=match,
        date=date,
        commute_min=commute_min,
    )
