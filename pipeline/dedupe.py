"""Deduplication of NormalizedJob list before final email digest.

Strategy (priority order):
  1. source + source_job_id  (exact match)
  2. canonical URL           (exact match after normalization)
  3. title + company similarity (fuzzy: normalized tokens)

The highest-scored job in each duplicate cluster is kept.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple

from pipeline.normalize import NormalizedJob


# ---------------------------------------------------------------------------
# Text normalization for similarity checks
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, remove diacritics, keep only a-z0-9 words."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _canonicalize_url(url: str) -> str:
    """Remove query/fragment, lowercase scheme+host, strip trailing slash."""
    if not url:
        return ""
    # Strip fragment
    url = url.split("#")[0]
    # Remove common tracking params
    for param in ("utm_source", "utm_medium", "utm_campaign", "ref", "from"):
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    url = re.sub(r"[?&]+$", "", url)
    # Lowercase scheme + host
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        url = urlunparse((
            p.scheme.lower(),
            p.netloc.lower(),
            p.path.rstrip("/"),
            p.params,
            p.query,
            "",
        ))
    except Exception:
        pass
    return url.strip()


def _title_company_key(job: NormalizedJob) -> str:
    """Short fingerprint from normalized title + company tokens."""
    title_tokens = set(_norm(job.title).split())
    company_tokens = set(_norm(job.company).split())
    # Remove very common short words
    noise = {"ag", "gmbh", "sa", "ltd", "group", "und", "and", "der", "die", "das"}
    title_tokens -= noise
    company_tokens -= noise
    # Keep up to 4 title tokens + 2 company tokens for fingerprint
    t_key = " ".join(sorted(title_tokens)[:4])
    c_key = " ".join(sorted(company_tokens)[:2])
    return f"{t_key}|{c_key}"


# ---------------------------------------------------------------------------
# Cluster building
# ---------------------------------------------------------------------------

def _cluster_jobs(jobs: List[NormalizedJob]) -> list[list[NormalizedJob]]:
    """Group jobs into clusters of duplicates. Return list of clusters."""
    clusters: list[list[NormalizedJob]] = []
    # Map each job to its cluster index
    assigned: dict[int, int] = {}  # job index -> cluster index

    # Build lookup tables
    id_to_cluster: dict[str, int] = {}    # source_id_key -> cluster index
    url_to_cluster: dict[str, int] = {}   # canonical_url -> cluster index
    tc_to_cluster: dict[str, int] = {}    # title+company key -> cluster index

    for i, job in enumerate(jobs):
        if i in assigned:
            continue

        # Keys for this job
        source_id_key = (
            f"{job.source}::{job.source_job_id}"
            if job.source and job.source_job_id
            else ""
        )
        url_key = _canonicalize_url(job.url)
        tc_key = _title_company_key(job)

        # Look for an existing cluster to merge into
        cluster_idx: int | None = None
        for key, lookup in [
            (source_id_key, id_to_cluster),
            (url_key, url_to_cluster),
            (tc_key if tc_key and "|" in tc_key else "", tc_to_cluster),
        ]:
            if key and key in lookup:
                cluster_idx = lookup[key]
                break

        if cluster_idx is None:
            # New cluster
            cluster_idx = len(clusters)
            clusters.append([])

        clusters[cluster_idx].append(job)
        assigned[i] = cluster_idx

        # Register keys
        if source_id_key:
            id_to_cluster.setdefault(source_id_key, cluster_idx)
        if url_key:
            url_to_cluster.setdefault(url_key, cluster_idx)
        if tc_key and "|" in tc_key:
            tc_to_cluster.setdefault(tc_key, cluster_idx)

    return clusters


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dedupe_jobs(jobs: List[NormalizedJob]) -> Tuple[List[NormalizedJob], int]:
    """Remove duplicates; return (unique_jobs, removed_count).

    Within each cluster, keeps the job with the highest score_final
    (or score_rule as fallback before final ranking runs).
    """
    clusters = _cluster_jobs(jobs)
    unique: List[NormalizedJob] = []
    removed = 0

    for cluster in clusters:
        if not cluster:
            continue
        # Pick best job in cluster
        best = max(
            cluster,
            key=lambda j: (j.score_final if j.score_final else float(j.score_rule)),
        )
        unique.append(best)
        removed += len(cluster) - 1

    return unique, removed
