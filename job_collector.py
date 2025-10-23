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
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from config import config
from logger import job_logger
from job_adapters_ch import JobsChAdapter, JobupAdapter, JobRow as CHJobRow
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
    opts = Options()
    if headless:
        # moderner Headless-Modus
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,2000")
    opts.add_argument("--user-agent=Bewerbungsagent/1.0 (+job-collector)")
    opts.add_argument("--lang=de-CH,de;q=0.9")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.set_page_load_timeout(20)
    except Exception:
        pass
    try:
        driver.implicitly_wait(5)
    except Exception:
        pass
    return driver


def _get_html(driver, url: str, tries: int = 2) -> str:
    for i in range(tries):
        try:
            driver.get(url)
            return driver.page_source
        except Exception:
            if i + 1 == tries:
                raise
    return ""


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
ENABLED_SOURCES = {x.strip().lower() for x in (os.getenv("ENABLED_SOURCES", "jobs.ch,jobup.ch") or "jobs.ch,jobup.ch").split(",") if x.strip()} 


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
    html = _get_html(driver, url)
    # Warte auf Karten (robuster als Sleep)
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.tapItem"))
        )
    except Exception:
        pass

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
    indeed_url = None
    for k, v in urls.items():
        if "indeed" in k.lower() or "indeed" in v.lower():
            indeed_url = v
            break

    # Query/Location für Adapter (pragmatisch: jeweils erstes Element)
    base_keywords = getattr(config, 'SEARCH_KEYWORDS', ["IT Support"]) or ["IT Support"]
    locations = getattr(config, 'SEARCH_LOCATIONS', ["Zürich"]) or ["Zürich"]
    query = base_keywords[0]
    location = locations[0]
    radius_km = getattr(config, 'LOCATION_RADIUS_KM', 25)

    all_jobs: List[Job] = []
    driver = _mk_driver(headless=getattr(config, "HEADLESS_MODE", True))
    try:
        # Indeed (sofern aktiviert oder keine Einschränkung)
        if indeed_url and (not ENABLED_SOURCES or 'indeed' in ENABLED_SOURCES):
            try:
                indeed_jobs = _collect_indeed(driver, indeed_url, limit=limit_per_site)
                all_jobs.extend(indeed_jobs)
                try:
                    job_logger.info(f"Indeed: {len(indeed_jobs)} Karten gefunden")
                except Exception:
                    pass
            except Exception as e:
                job_logger.warning(f"Indeed Adapter Fehler: {e}")

        # CH-Adapter
        adapters = [JobsChAdapter(), JobupAdapter()]
        for a in adapters:
            if ENABLED_SOURCES and a.source.lower() not in ENABLED_SOURCES:
                continue
            try:
                rows = a.search(driver, query=query, location=location, radius_km=radius_km, limit=limit_per_site)
                # in Job umwandeln
                for r in rows:
                    if isinstance(r, CHJobRow):
                        all_jobs.append(Job(title=r.title, company=r.company, location=r.location, link=r.link, source=a.source))
                try:
                    job_logger.info(f"{a.source}: {len(rows)} Roh-Treffer")
                except Exception:
                    pass
            except Exception as e:
                job_logger.warning(f"Adapter {a.source} Fehler: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Dedupe/Blacklist + Location-Boost
    seen = set()
    unique: List[Job] = []
    search_locs = getattr(config, "SEARCH_LOCATIONS", []) or []
    for j in all_jobs:
        if (j.company or "").lower() in BLACKLIST:
            continue
        if any(k in (j.title or "").lower() for k in KEYWORD_BLACKLIST):
            continue
        # Filter: Kategorie-/Übersichtslinks ohne konkrete Jobs (v. a. jobs.ch/jobup)
        if j.source in ("jobs.ch", "jobup.ch"):
            if not re.search(r"\d", j.link) or "stellenangebote/" in j.link.rstrip("/").split("/")[-2:] and not re.search(r"\d", j.link):
                # Links ohne ID (oft Kategorien) auslassen
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
