"""Rule-based hard filter – runs before LLM review.

Every rejected job gets a clear reject_reason string.
This step is fully deterministic and transparent.
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

from pipeline.normalize import NormalizedJob


# ---------------------------------------------------------------------------
# Seniority / level patterns (title only – fast signal)
# ---------------------------------------------------------------------------

_SENIORITY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bsenior\b",
        r"\bsr\.?\s",
        r"\blead\b",
        r"\bprincipal\b",
        r"\bhead\s+of\b",
        r"\bdirector\b",
        r"\bchief\b",
        r"\bvp\b",
        r"\bvice\s+president\b",
        r"\bleiter(in)?\b",
        r"\bleitung\b",
        r"\bteam\s*lead(er)?\b",
        r"\barchitect\b",
        r"\barchitekt\b",
        r"\bc[ist]o\b",             # CTO, CIO, CSO
    ]
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env_list(key: str) -> list[str]:
    """Load a comma-separated env variable as a lowercase list."""
    raw = os.getenv(key, "")
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def _title_matches_pattern(title: str, patterns: list[re.Pattern]) -> str | None:
    """Return the matching pattern string or None."""
    for pat in patterns:
        m = pat.search(title)
        if m:
            return m.group(0)
    return None


def _text_contains_keyword(text: str, keywords: list[str]) -> str | None:
    """Return the first matched keyword or None (case-insensitive substring)."""
    text_lower = text.lower()
    for kw in keywords:
        if kw and kw in text_lower:
            return kw
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hard_filter(jobs: List[NormalizedJob]) -> Tuple[List[NormalizedJob], List[NormalizedJob]]:
    """Split jobs into (kept, rejected).

    Each rejected job has .rejected=True and a non-empty .reject_reason.
    """
    # Load config from environment (same source as bewerbungsagent/config.py)
    blacklist_keywords = _load_env_list("BLACKLIST_KEYWORDS")
    negative_keywords = _load_env_list("NEGATIVE_KEYWORDS")
    language_blocklist = _load_env_list("LANGUAGE_BLOCKLIST")
    requirements_blocklist = _load_env_list("REQUIREMENTS_BLOCKLIST")
    blacklist_companies = _load_env_list("BLACKLIST_COMPANIES")
    include_keywords = _load_env_list("INCLUDE_KEYWORDS")

    # Merge all "negative content" keyword lists
    all_block_kws = list(dict.fromkeys(blacklist_keywords + negative_keywords))

    kept: List[NormalizedJob] = []
    rejected: List[NormalizedJob] = []

    for job in jobs:
        reason = _evaluate_single(
            job,
            all_block_kws=all_block_kws,
            language_blocklist=language_blocklist,
            requirements_blocklist=requirements_blocklist,
            blacklist_companies=blacklist_companies,
            include_keywords=include_keywords,
        )
        if reason:
            job.rejected = True
            job.reject_reason = reason
            rejected.append(job)
        else:
            kept.append(job)

    return kept, rejected


def _evaluate_single(
    job: NormalizedJob,
    all_block_kws: list[str],
    language_blocklist: list[str],
    requirements_blocklist: list[str],
    blacklist_companies: list[str],
    include_keywords: list[str],
) -> str:
    """Return reject reason string, or empty string if job should be kept."""

    title = job.title or ""
    raw_title = job.raw_title or ""
    company = job.company or ""
    location = job.location or ""
    description = job.description_raw or ""

    combined_text = f"{title} {raw_title} {description}".strip()

    # 1. Seniority in title (most reliable signal)
    hit = _title_matches_pattern(title, _SENIORITY_PATTERNS)
    if hit:
        return f"seniority:{hit.strip().lower()}"

    # 2. Company blacklist
    company_hit = _text_contains_keyword(company, blacklist_companies)
    if company_hit:
        return f"blacklist_company:{company_hit}"

    # 3. Blacklist / negative keywords in title + raw_title
    kw_hit = _text_contains_keyword(f"{title} {raw_title}", all_block_kws)
    if kw_hit:
        return f"blacklist_keyword:{kw_hit}"

    # 4. Language blocklist (in combined text)
    lang_hit = _text_contains_keyword(combined_text, language_blocklist)
    if lang_hit:
        return f"language_requirement:{lang_hit}"

    # 5. Requirements blocklist (driving license, years of experience, etc.)
    req_hit = _text_contains_keyword(combined_text, requirements_blocklist)
    if req_hit:
        return f"requirements_blocklist:{req_hit}"

    # 6. INCLUDE_KEYWORDS check: if configured, job must match at least one
    if include_keywords:
        check_text = f"{title} {raw_title}".lower()
        has_include_match = any(kw in check_text for kw in include_keywords if kw)
        if not has_include_match:
            return "include_keyword:no_match"

    # 7. Location sanity: if location contains obvious foreign country indicators
    # (only block if clearly outside DACH region – conservative)
    foreign_countries = [
        "united states", "usa", "uk only", "london", "paris", "amsterdam",
        "berlin only", "münchen only",  # only when "only" is explicit
    ]
    location_lower = location.lower()
    for fc in foreign_countries:
        if fc in location_lower:
            return f"location:foreign:{fc}"

    return ""  # keep
