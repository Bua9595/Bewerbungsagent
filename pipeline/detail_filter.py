"""Detail-page fetch filter — runs AFTER hard_filter, BEFORE LLM review.

Fetches the job detail page for surviving candidates and rejects jobs that
contain hard-reject phrases in the actual page text.

Only fetches pages for jobs NOT on aggregator skip-domains.
Capped at DETAIL_FILTER_MAX_FETCHES per run.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from pipeline.normalize import NormalizedJob

logger = logging.getLogger("bwa.detail_filter")

# ---------------------------------------------------------------------------
# Hard-reject phrases — mandatory formulations only.
# Soft formulations ("von Vorteil", "wünschenswert", "erste Erfahrung") are
# intentionally absent to avoid over-blocking entry-level jobs.
# ---------------------------------------------------------------------------
_HARD_REJECT_PHRASES: list[str] = [
    # Führerschein / Fahrzeugpflicht (as hard requirement, not "von Vorteil")
    "führerausweis erforderlich",
    "führerschein erforderlich",
    "führerschein voraussetzung",
    "führerschein zwingend",
    "führerschein wird vorausgesetzt",
    "eigener pkw",
    "eigenes fahrzeug",
    "eigenes auto",
    "driving license required",
    "driving licence required",
    "driver license required",
    "own car required",
    "aussendienst mit fahrzeugpflicht",
    # Mehrjährige Berufserfahrung (Pflichtformulierungen — NOT "von Vorteil")
    "mehrjährige berufserfahrung",
    "mehrjährige einschlägige berufserfahrung",
    "mehrjährige relevante berufserfahrung",
    "fundierte berufserfahrung",
    "langjährige berufserfahrung",
    "langjährige einschlägige",
    "mindestens 3 jahre berufserfahrung",
    "mindestens 5 jahre berufserfahrung",
    "mindestens 3 jahre erfahrung",
    "mindestens 5 jahre erfahrung",
    "min. 3 jahre berufserfahrung",
    "min. 5 jahre berufserfahrung",
    "3+ jahre berufserfahrung",
    "5+ jahre berufserfahrung",
    "3 jahre berufserfahrung",
    "5 jahre berufserfahrung",
    "extensive experience required",
    "several years of experience required",
    # Studium / Hochschulabschluss (als Pflicht — NOT "oder gleichwertige Erfahrung")
    "abgeschlossenes studium",
    "abgeschlossenes hochschulstudium",
    "hochschulabschluss erforderlich",
    "hochschulabschluss wird vorausgesetzt",
    "hochschulabschluss zwingend",
    "bachelor erforderlich",
    "master erforderlich",
    "master of science",
    "master of engineering",
    "university degree required",
    "degree required",
    "fh-abschluss erforderlich",
    "uni-abschluss erforderlich",
    "universitätsabschluss",
]

MAX_FETCHES: int = int(os.getenv("DETAIL_FILTER_MAX_FETCHES", "50"))
FETCH_TIMEOUT: float = float(os.getenv("DETAIL_FILTER_TIMEOUT_S", "8"))

_SKIP_DOMAINS: frozenset[str] = frozenset(
    x.strip().lower()
    for x in os.getenv(
        "DETAILS_BLOCKLIST_SKIP_DOMAINS",
        "jobrapido.com,jooble.org,jora.com,careerjet.ch,jobwinner.ch,monster.ch",
    ).split(",")
    if x.strip()
)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BewerbungsagentClaude/1.0)"}


def _should_skip(url: str) -> str | None:
    """Return skip-reason string, or None if the URL should be fetched."""
    if not url:
        return "no_url"
    host = urlparse(url).hostname or ""
    if any(dom in host for dom in _SKIP_DOMAINS):
        return f"skipped_domain:{host}"
    return None


def _fetch_text(url: str) -> str:
    """Fetch page and return lowercased plain text, or empty string on failure."""
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text(" ", strip=True).lower()
    except Exception as exc:
        logger.debug("detail_filter: fetch error %s — %s", url, exc)
        return ""


def _phrase_hit(text: str) -> str | None:
    """Return the first matching hard-reject phrase, or None."""
    for phrase in _HARD_REJECT_PHRASES:
        if phrase in text:
            return phrase
    return None


def detail_filter(
    jobs: list[NormalizedJob],
) -> tuple[list[NormalizedJob], list[NormalizedJob], dict]:
    """Fetch detail pages for candidates and reject hard-phrase matches.

    Returns (kept, rejected, stats).
    stats keys: fetched, skipped_domain, fetch_failed, cap_reached, rejected_phrase_hits
    """
    kept: list[NormalizedJob] = []
    rejected: list[NormalizedJob] = []
    stats: dict[str, int] = {
        "fetched": 0,
        "skipped_domain": 0,
        "fetch_failed": 0,
        "cap_reached": 0,
        "rejected_phrase_hits": 0,
    }

    for job in jobs:
        url = job.url or job.link
        skip_reason = _should_skip(url)

        if skip_reason:
            if "skipped_domain" in skip_reason:
                stats["skipped_domain"] += 1
            logger.debug("detail_filter: %s — %s", skip_reason, job.title)
            kept.append(job)
            continue

        if stats["fetched"] >= MAX_FETCHES:
            stats["cap_reached"] += 1
            logger.debug("detail_filter: cap_reached — unverified keep: %s", job.title)
            kept.append(job)
            continue

        page_text = _fetch_text(url)
        stats["fetched"] += 1

        if not page_text:
            stats["fetch_failed"] += 1
            logger.debug("detail_filter: fetch_failed — keep: %s", job.title)
            kept.append(job)
            continue

        hit = _phrase_hit(page_text)
        if hit:
            stats["rejected_phrase_hits"] += 1
            job.rejected = True
            job.reject_reason = f"detail_phrase:{hit}"
            rejected.append(job)
            logger.info("detail_filter: REJECT %r — phrase_hit:%r", job.title, hit)
        else:
            kept.append(job)

    logger.info(
        "detail_filter: kept=%d rejected=%d | fetched=%d skipped_domain=%d "
        "fetch_failed=%d cap_reached=%d phrase_hits=%d",
        len(kept), len(rejected),
        stats["fetched"], stats["skipped_domain"],
        stats["fetch_failed"], stats["cap_reached"],
        stats["rejected_phrase_hits"],
    )
    return kept, rejected, stats
