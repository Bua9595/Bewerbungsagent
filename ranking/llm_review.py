"""LLM review step using the Anthropic Claude API – single batch call.

All jobs are sent in ONE API call. Claude returns a JSON array with one
object per job (same index order). This is fast, cheap, and avoids N×RTT.

Each array element:
  - is_relevant        (bool)
  - score_llm          (0-100)
  - seniority          ("unknown" | "junior" | "mid" | "senior")
  - red_flags          (list[str])
  - reason_short       (str, max 200 chars)

No free text outside JSON. Parsing errors are caught and logged;
affected jobs get a neutral fallback so the pipeline continues.
"""
from __future__ import annotations

import json
import os
import re
from typing import List

from pipeline.normalize import NormalizedJob


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 2048          # enough for ~30 jobs as a JSON array
_TEMPERATURE = 0.0          # deterministic
_DEFAULT_MAX_JOBS = 30      # cap per run

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

_SYSTEM_PROMPT = (
    "You are a job-relevance classifier for an IT support specialist in Switzerland. "
    "Return ONLY a valid JSON array — no text before or after it. "
    "The candidate profile: entry-level to mid-level IT support (1st/2nd Level, Service Desk, "
    "Helpdesk, Systemtechniker, ICT Supporter). Target region: Zürich and surroundings. "
    "No senior/lead roles. Language: primarily German-speaking Switzerland."
)

_USER_PROMPT_HEADER = """\
Evaluate the following job postings and return ONLY a JSON array — one object per job,
in the SAME ORDER as the input. Each object must have exactly these fields:

{
  "is_relevant": true,
  "score_llm": 0,
  "seniority": "unknown",
  "red_flags": [],
  "reason_short": ""
}

Rules:
- score_llm: 0-100 (100 = perfect fit for entry/mid IT support in Zürich region)
- seniority: "junior" | "mid" | "senior" | "unknown"
- is_relevant: false if senior/lead role, clearly wrong field, or outside target region
- reason_short: max 200 characters, German or English
- red_flags: e.g. ["senior_required", "driving_license", "french_required"]

Jobs:
"""


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


def _build_batch_prompt(jobs: List[NormalizedJob]) -> str:
    lines = [_USER_PROMPT_HEADER]
    for i, job in enumerate(jobs, 1):
        lines.append(
            f"{i}. Title: {job.title or ''} | Company: {job.company or ''} "
            f"| Location: {job.location or ''} | Source: {job.source or ''}"
        )
    return "\n".join(lines)


def _parse_batch_response(text: str, expected: int, logger=None) -> List[dict]:
    """Extract JSON array from response. Returns list of review dicts (length == expected)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        raise ValueError("No JSON array found in response")
    raw = json.loads(m.group(0))
    if not isinstance(raw, list):
        raise ValueError(f"Expected JSON array, got {type(raw).__name__}")

    results: List[dict] = []
    for item in raw[:expected]:
        review: dict = {}
        review["is_relevant"] = bool(item.get("is_relevant", True))
        review["score_llm"] = max(0, min(100, int(item.get("score_llm", 50))))
        review["corrected_title"] = ""
        review["corrected_company"] = ""
        review["corrected_location"] = ""
        review["seniority"] = str(item.get("seniority") or "unknown")
        review["must_have_flags"] = [str(f) for f in (item.get("must_have_flags") or [])]
        review["red_flags"] = [str(f) for f in (item.get("red_flags") or [])]
        review["reason_short"] = str(item.get("reason_short") or "")[:200]
        results.append(review)

    # Pad with fallback if response was shorter than expected
    while len(results) < expected:
        results.append(dict(_FALLBACK_REVIEW, reason_short="llm_batch_short"))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_review_jobs(jobs: List[NormalizedJob], logger=None) -> List[NormalizedJob]:
    """Run LLM review on all jobs in a single batch API call.

    - Skips if ANTHROPIC_API_KEY not set (uses fallback review).
    - Caps at LLM_REVIEW_MAX_JOBS (env, default 30).
    - Non-relevant jobs (is_relevant=False, score_llm<threshold) get marked rejected.
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

    # Only review top-N by rule score
    jobs_to_review = sorted(jobs, key=lambda j: j.score_rule, reverse=True)[:max_jobs]
    review_ids = {id(j) for j in jobs_to_review}
    skipped = [j for j in jobs if id(j) not in review_ids]

    for job in skipped:
        job.llm_review = dict(_FALLBACK_REVIEW)

    if logger and skipped:
        logger.info(f"llm_review: capped at {max_jobs} jobs, {len(skipped)} get fallback")

    # Single batch call
    reviews: List[dict] = []
    try:
        prompt = _build_batch_prompt(jobs_to_review)
        message = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text if message.content else ""
        reviews = _parse_batch_response(response_text, len(jobs_to_review), logger=logger)
        if logger:
            logger.info(f"llm_review: batch call returned {len(reviews)} reviews for {len(jobs_to_review)} jobs")
    except Exception as exc:
        exc_str = str(exc)
        if "credit balance" in exc_str or "insufficient_quota" in exc_str or "402" in exc_str:
            if logger:
                logger.info("llm_review: no API credits — skipping LLM review, using fallback scores")
        else:
            if logger:
                logger.warning(f"llm_review: batch API call failed: {exc}. Using fallback for all.")
        reviews = [dict(_FALLBACK_REVIEW, reason_short="llm_skipped") for _ in jobs_to_review]

    # Apply reviews
    rejected_by_llm = 0
    for job, review in zip(jobs_to_review, reviews):
        job.llm_review = review

        if not review["is_relevant"] and review["score_llm"] < rejection_threshold:
            if not job.rejected:
                job.rejected = True
                flags = review.get("red_flags", [])
                reason_detail = ",".join(flags[:3]) if flags else review.get("reason_short", "")[:60]
                job.reject_reason = f"llm_reject:{reason_detail}"
                rejected_by_llm += 1

        if review.get("reason_short"):
            job.reason_short = review["reason_short"]

    if logger:
        logger.info(
            f"llm_review: reviewed={len(jobs_to_review)}, fallback={len(skipped)}, "
            f"rejected_by_llm={rejected_by_llm}"
        )

    return jobs
