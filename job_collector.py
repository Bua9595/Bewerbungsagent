from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Tuple
import os
import csv
import re
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from config import config
from job_query_builder import build_search_urls


@dataclass
class Job:
    title: str
    company: str
    location: str
    link: str
    source: str
    score: int = 0
    match: str = "unknown"  # exact | good | weak | unknown
    date: str = ""


def _mk_driver(headless: bool = True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,1200")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _text(v):
    return (v or "").strip()


def _score_title(title: str) -> Tuple[int, str]:
    """Heuristische Bewertung basierend auf Keywords/Negatives."""
    t = title.lower()
    positives = set(getattr(config, "SEARCH_KEYWORDS", []) + getattr(config, "TITLE_VARIANTS_DE", []) + getattr(config, "TITLE_VARIANTS_EN", []))
    positives = {p.lower() for p in positives}
    negatives = {n.lower() for n in getattr(config, "NEGATIVE_KEYWORDS", [])}

    p_hits = sum(1 for p in positives if p in t)
    n_hits = sum(1 for n in negatives if n in t)
    score = p_hits * 10 - n_hits * 20

    if p_hits >= 2 and n_hits == 0:
        label = "exact"
    elif p_hits >= 1 and n_hits == 0:
        label = "good"
    else:
        label = "weak"

    return score, label


# ----- ENV/Scoring Hilfen -----
TRUTHY = {"1", "true", "t", "y", "yes", "ja", "j"}
EXPORT_CSV = str(os.getenv("EXPORT_CSV", "true")).lower() in TRUTHY
EXPORT_CSV_PATH = os.getenv("EXPORT_CSV_PATH", "generated/jobs_latest.csv")
MIN_SCORE_MAIL = int(os.getenv("MIN_SCORE_MAIL", "2") or 2)
LOCATION_BOOST_KM = int(os.getenv("LOCATION_BOOST_KM", "15") or 15)
BLACKLIST = {x.strip().lower() for x in (os.getenv("BLACKLIST_COMPANIES", "") or "").split(",") if x.strip()}
KEYWORD_BLACKLIST = {x.strip().lower() for x in (os.getenv("BLACKLIST_KEYWORDS", "") or "").split(",") if x.strip()}


def _location_boost(job_location: str, search_locations: List[str]) -> int:
    # Pragmatismus: String-Match statt Geocoding (KM-Wert dient nur als ENV-Schwellensymbol)
    jl = (job_location or "").lower()
    return 1 if any(loc.lower() in jl for loc in search_locations or []) else 0


def _norm_key(title: str, company: str, link: str) -> str:
    t = re.sub(r"\W+", "", (title or "").lower())
    c = re.sub(r"\W+", "", (company or "").lower())
    l = re.sub(r"[?#].*$", "", (link or "").lower())
    return f"{t}|{c}|{l}"


def _collect_indeed(driver, url: str, limit: int = 25) -> List[Job]:
    jobs: List[Job] = []
    driver.get(url)
    time.sleep(2.0)

    cards = driver.find_elements(By.CSS_SELECTOR, "a.tapItem")
    for a in cards[:limit]:
        try:
            title = _text(a.find_element(By.CSS_SELECTOR, "span.jobTitle").text)
        except Exception:
            title = _text(a.text)
        try:
            company = _text(a.find_element(By.CSS_SELECTOR, "span.companyName").text)
        except Exception:
            company = ""
        try:
            location = _text(a.find_element(By.CSS_SELECTOR, "div.companyLocation").text)
        except Exception:
            location = ""
        link = a.get_attribute("href") or ""

        score, label = _score_title(title)
        jobs.append(Job(title=title, company=company, location=location, link=link, source="indeed", score=score, match=label))

    return jobs


def collect_jobs(limit_per_site: int = 25, max_total: int = 100) -> List[Job]:
    urls = build_search_urls(config)
    # Wir starten pragmatisch nur mit Indeed. Weitere Portale können folgen.
    indeed_url = None
    for k, v in urls.items():
        if "indeed" in k.lower() or "indeed" in v.lower():
            indeed_url = v
            break

    all_jobs: List[Job] = []
    if indeed_url:
        driver = _mk_driver(headless=getattr(config, "HEADLESS_MODE", True))
        try:
            all_jobs.extend(_collect_indeed(driver, indeed_url, limit=limit_per_site))
        finally:
            driver.quit()

    # Dedupe/Blacklist + Location-Boost
    seen = set()
    unique: List[Job] = []
    search_locs = getattr(config, "SEARCH_LOCATIONS", []) or []
    for j in all_jobs:
        if (j.company or "").lower() in BLACKLIST:
            continue
        if any(k in (j.title or "").lower() for k in KEYWORD_BLACKLIST):
            continue
        key = _norm_key(j.title, j.company, j.link)
        if key in seen:
            continue
        seen.add(key)
        # Boost
        j.score += _location_boost(j.location, search_locs)
        # Re‑klassifizieren
        if j.score >= 20:  # sehr starke Titel + Boost
            j.match = "exact"
        elif j.score >= 10:
            j.match = "good"
        else:
            j.match = j.match or "weak"
        unique.append(j)

    # Nach Score sortieren
    unique.sort(key=lambda x: x.score, reverse=True)
    return unique[:max_total]


def format_jobs_plain(jobs: List[Job], top: int = 20) -> str:
    out = []
    for i, j in enumerate(jobs[:top], 1):
        out.append(f"{i:02d}. [{j.match:^5}] {j.title} — {j.company} — {j.location}\n    {j.link}")
    return "\n".join(out) if out else "Keine Treffer."


def export_csv(rows: List[Job], path: str = None) -> None:
    if not EXPORT_CSV:
        return
    out_path = path or EXPORT_CSV_PATH
    Path(os.path.dirname(out_path) or ".").mkdir(exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "company", "location", "match", "score", "link", "source"])
        for j in rows:
            w.writerow([j.title, j.company, j.location, j.match, j.score, j.link, j.source])
