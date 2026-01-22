from __future__ import annotations

import re
from typing import Tuple

_COMPANY_HINT_RE = re.compile(
    r"\b(ag|gmbh|sa|s\.a\.|kg|sarl|s\u00e0rl|sarl\.?|ltd|inc|llc)\b",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(
    r"(arbeitsort|pensum|vertragsart|einfach bewerben|neu)",
    re.IGNORECASE,
)
_RELDATE_INLINE_RE = re.compile(
    r"\b(heute|gestern|vorgestern|letzte woche|letzten monat|vor \d+ (stunden?|tagen|wochen|monaten?))\b",
    re.IGNORECASE,
)
_CITY_HINT_RE = re.compile(
    r"\b("
    r"z\u00fcrich|zurich|zuerich|"
    r"b\u00fclach|buelach|"
    r"kloten|winterthur|baden|zug|aarau|basel|bern|luzern|thun|"
    r"gen\u00e8ve|geneve|"
    r"schweiz"
    r")\b",
    re.IGNORECASE,
)


def _normalize_line(line: str) -> str:
    # Remove leading "01. [exact]" style prefixes.
    line = re.sub(r"^\s*\d+\.\s*\[[^\]]+\]\s*", "", line)
    return line.strip().strip('"').strip()


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    if _LABEL_RE.search(line):
        return True
    if re.match(r"^ref[:\s]", line, re.IGNORECASE):
        return True
    if _RELDATE_INLINE_RE.search(line):
        return True
    return False


def extract_from_multiline_title(raw_title: str) -> Tuple[str, str, str]:
    """
    Parse multi-line titles into (job_title, company, location).
    """
    raw_lines = [_normalize_line(x) for x in (raw_title or "").splitlines()]
    raw_lines = [x for x in raw_lines if x]

    location = ""
    for i, line in enumerate(raw_lines):
        if line.lower().startswith("arbeitsort"):
            if i + 1 < len(raw_lines):
                location = _normalize_line(raw_lines[i + 1])
            break

    clean = [line for line in raw_lines if not _is_noise_line(line)]

    job_title = clean[0] if clean else ""
    company = ""

    for line in reversed(clean):
        if _COMPANY_HINT_RE.search(line):
            company = line
            break

    if not company and len(clean) >= 2:
        company = clean[-1]
        if company == job_title:
            company = ""

    if not location:
        for line in clean[1:]:
            if _CITY_HINT_RE.search(line):
                location = line
                break

    if location == company:
        location = ""

    return job_title, company, location
