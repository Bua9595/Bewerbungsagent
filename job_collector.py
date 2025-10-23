from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Dict, Tuple

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
        driver = _mk_driver(headless=True)
        try:
            all_jobs.extend(_collect_indeed(driver, indeed_url, limit=limit_per_site))
        finally:
            driver.quit()

    # Deduplizieren per Link
    seen = set()
    unique: List[Job] = []
    for j in all_jobs:
        key = j.link or (j.title, j.company)
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)

    # Nach Score sortieren
    unique.sort(key=lambda x: x.score, reverse=True)
    return unique[:max_total]


def format_jobs_plain(jobs: List[Job], top: int = 20) -> str:
    out = []
    for i, j in enumerate(jobs[:top], 1):
        out.append(f"{i:02d}. [{j.match:^5}] {j.title} — {j.company} — {j.location}\n    {j.link}")
    return "\n".join(out) if out else "Keine Treffer."

