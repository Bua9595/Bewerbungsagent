"""Combine rule-based score and LLM score into a stable final_score.

Weighting (configurable via env):
  RANK_RULE_WEIGHT  default 0.60  (60% rule-based)
  RANK_LLM_WEIGHT   default 0.40  (40% LLM)

score_rule is typically in range -20..60+ (from job_collector.py scoring).
score_llm  is 0..100.

Both are normalized to 0..100 before combining.

If LLM review is unavailable (fallback), the LLM score used is a neutral 50
with weight 0 so only rule score decides.
"""
from __future__ import annotations

import os
from typing import List

from pipeline.normalize import NormalizedJob


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)) or default)
    except (ValueError, TypeError):
        return default


# Typical score_rule range from job_collector scoring
_RULE_MIN = -30.0
_RULE_MAX = 80.0


def _normalize_rule_score(score_rule: int) -> float:
    """Map score_rule to 0..100."""
    clipped = max(_RULE_MIN, min(_RULE_MAX, float(score_rule)))
    return (clipped - _RULE_MIN) / (_RULE_MAX - _RULE_MIN) * 100.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_final_scores(jobs: List[NormalizedJob]) -> List[NormalizedJob]:
    """Compute score_final for each job and sort descending. Returns same list."""
    rule_weight = _float_env("RANK_RULE_WEIGHT", 0.60)
    llm_weight = _float_env("RANK_LLM_WEIGHT", 0.40)

    for job in jobs:
        rule_norm = _normalize_rule_score(job.score_rule)

        llm_review = job.llm_review or {}
        llm_raw = llm_review.get("score_llm")
        is_fallback = llm_review.get("reason_short", "").startswith(("llm_review_skipped", "llm_error"))

        if llm_raw is not None and not is_fallback:
            # Full weighted combination
            llm_score = max(0.0, min(100.0, float(llm_raw)))
            job.score_final = rule_weight * rule_norm + llm_weight * llm_score
        else:
            # LLM unavailable: use rule score only
            job.score_final = rule_norm

        # Sync the .score field (int) so email system shows final score
        job.score = round(job.score_final)

        # Also update .match label if LLM gave a seniority hint
        if llm_review.get("seniority") and llm_review["seniority"] != "unknown":
            job.match = f"{job.match}|{llm_review['seniority']}"

    # Sort descending by final score
    jobs.sort(key=lambda j: j.score_final, reverse=True)
    return jobs
