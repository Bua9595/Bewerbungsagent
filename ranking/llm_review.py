"""LLM review step using the Anthropic Claude API.

For each job, Claude returns a fixed JSON object with:
  - is_relevant        (bool)
  - score_llm          (0-100)
  - corrected_title    (str)
  - corrected_company  (str)
  - corrected_location (str)
  - seniority          ("unknown" | "junior" | "mid" | "senior")
  - must_have_flags    (list[str])
  - red_flags          (list[str])
  - reason_short       (str, max 200 chars)

No free text outside JSON. Parsing errors are caught and logged;
the job gets a neutral fallback review so the pipeline continues.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List

from pipeline.normalize import NormalizedJob


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 400
_TEMPERATURE = 0.0         # deterministic
_REQUEST_DELAY_S = 0.3     # seconds between API calls
_DEFAULT_MAX_JOBS = 60     # maximum jobs sent to LLM per run

_FALLBACK_REVIEW: dict = {
    "is_relevant": True,
    "score_llm": 50,
    "corrected_title": "",
    "corrected_company": "",
    "corrected_location": "",
    "seniority": "unknown",
    "must_have_flags": [],
    "red_flags": [],
    "reason_short": "llm_review_skipped",
}

_SYSTEM_PROMPT = """You are a job-relevance classifier for an IT support specialist in Switzerland.
Return ONLY a valid JSON object — no text before or after it.
The candidate profile: entry-level to mid-level IT support (1st/2nd Level, Service Desk, Helpdesk,
Systemtechniker, ICT Supporter). Target region: Zürich and surroundings. No senior/lead roles.
Language: primarily German-speaking Switzerland."""

_USER_PROMPT_TEMPLATE = """Evaluate this job posting and return ONLY the JSON object below.

Job data:
- Title: {title}
- Company: {company}
- Location: {location}
- Source: {source}
- Raw title: {raw_title}

Return this exact JSON structure (no extra text):
{{
  "is_relevant": true,
  "score_llm": 0,
  "corrected_title": "",
  "corrected_company": "",
  "corrected_location": "",
  "seniority": "unknown",
  "must_have_flags": [],
  "red_flags": [],
  "reason_short": ""
}}

Rules:
- score_llm: 0-100 (100 = perfect fit for entry/mid IT support in Zürich region)
- seniority: "junior" | "mid" | "senior" | "unknown"
- is_relevant: false if senior/lead role, clearly wrong field, or outside target region
- reason_short: max 200 characters, German or English
- red_flags: list strings like ["senior_required", "driving_license", "french_required"]
- must_have_flags: list strings like ["windows", "ad", "m365"]
- corrected_*: fill only if the scraped value looks clearly wrong, else leave empty"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client():
    """Lazy-load Anthropic client. Returns None if not available."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def _parse_llm_response(text: str) -> dict:
    """Extract and parse JSON from LLM response. Returns fallback on failure."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... } block
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("No JSON object found in response")
    data = json.loads(m.group(0))

    # Validate and coerce types
    review: dict = {}
    review["is_relevant"] = bool(data.get("is_relevant", True))
    review["score_llm"] = max(0, min(100, int(data.get("score_llm", 50))))
    review["corrected_title"] = str(data.get("corrected_title") or "")[:120]
    review["corrected_company"] = str(data.get("corrected_company") or "")[:120]
    review["corrected_location"] = str(data.get("corrected_location") or "")[:120]
    review["seniority"] = str(data.get("seniority") or "unknown")
    review["must_have_flags"] = [str(f) for f in (data.get("must_have_flags") or [])]
    review["red_flags"] = [str(f) for f in (data.get("red_flags") or [])]
    review["reason_short"] = str(data.get("reason_short") or "")[:200]
    return review


def _review_single(client, job: NormalizedJob, logger=None) -> dict:
    """Call Claude for one job. Returns parsed review dict."""
    prompt = _USER_PROMPT_TEMPLATE.format(
        title=job.title or "",
        company=job.company or "",
        location=job.location or "",
        source=job.source or "",
        raw_title=job.raw_title or "",
    )
    try:
        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text if message.content else ""
        return _parse_llm_response(response_text)
    except Exception as exc:
        if logger:
            logger.warning(f"llm_review: API call failed for '{job.title}': {exc}")
        return dict(_FALLBACK_REVIEW, reason_short=f"llm_error:{type(exc).__name__}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_review_jobs(jobs: List[NormalizedJob], logger=None) -> List[NormalizedJob]:
    """Run LLM review on all jobs. Mutates .llm_review field in-place.

    - Skips if ANTHROPIC_API_KEY not set (uses fallback review).
    - Caps at LLM_REVIEW_MAX_JOBS (env, default 60).
    - Non-relevant jobs (is_relevant=False, score_llm<30) get marked rejected.
    - Returns the same list (mutated).
    """
    if not jobs:
        return jobs

    enabled = os.getenv("LLM_REVIEW_ENABLED", "true").strip().lower() not in ("false", "0", "no")
    max_jobs = int(os.getenv("LLM_REVIEW_MAX_JOBS", str(_DEFAULT_MAX_JOBS)) or _DEFAULT_MAX_JOBS)
    rejection_threshold = int(os.getenv("LLM_REVIEW_REJECT_THRESHOLD", "25"))

    client = _get_client() if enabled else None

    if not client:
        if logger:
            reason = "LLM_REVIEW_ENABLED=false" if not enabled else "ANTHROPIC_API_KEY not set or anthropic not installed"
            logger.info(f"llm_review: skipped ({reason}), using fallback scores")
        for job in jobs:
            job.llm_review = dict(_FALLBACK_REVIEW)
        return jobs

    # Only review up to max_jobs (best rule-scored first)
    jobs_to_review = sorted(jobs, key=lambda j: j.score_rule, reverse=True)[:max_jobs]
    skipped = [j for j in jobs if j not in set(jobs_to_review)]

    if logger and skipped:
        logger.info(f"llm_review: capped at {max_jobs} jobs, {len(skipped)} get fallback review")

    for job in skipped:
        job.llm_review = dict(_FALLBACK_REVIEW)

    reviewed = 0
    rejected_by_llm = 0

    for job in jobs_to_review:
        review = _review_single(client, job, logger=logger)
        job.llm_review = review
        reviewed += 1

        # Apply LLM rejection: only if clearly not relevant and very low score
        if not review["is_relevant"] and review["score_llm"] < rejection_threshold:
            if not job.rejected:  # don't override existing hard-filter rejection
                job.rejected = True
                flags = review.get("red_flags", [])
                reason_detail = ",".join(flags[:3]) if flags else review.get("reason_short", "")[:60]
                job.reject_reason = f"llm_reject:{reason_detail}"
                rejected_by_llm += 1

        # Apply corrected fields if LLM found obvious scraper errors
        if review.get("corrected_title"):
            job.title = review["corrected_title"]
        if review.get("corrected_company"):
            job.company = review["corrected_company"]
        if review.get("corrected_location"):
            job.location = review["corrected_location"]

        if review.get("reason_short"):
            job.reason_short = review["reason_short"]

        if reviewed < len(jobs_to_review):
            time.sleep(_REQUEST_DELAY_S)

    if logger:
        logger.info(
            f"llm_review: reviewed={reviewed}, fallback={len(skipped)}, "
            f"rejected_by_llm={rejected_by_llm}"
        )

    return jobs
