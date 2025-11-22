from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
import csv
import os
import re

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
    raw_title: str
    title: str
    company: str
    location: str
    link: str
    source: str
    score: int = 0
    match: str = "unknown"  # exact | good | weak | unknown
    date: str = ""


def _mk_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,2000")
    opts.add_argument("--user-agent=Bewerbungsagent/1.0 (+job-collector)")
    opts.add_argument("--lang=de-CH,de;q=0.9")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)

    try:
        driver.set_page_load_timeout(25)
    except Exception:
        pass
    try:
        driver.implicitly_wait(5)
    except Exception:
        pass
    return driver


def _get_html(driver: webdriver.Chrome, url: str, tries: int = 2) -> str:
    for i in range(tries):
        try:
            driver.get(url)
            return driver.page_source
        except Exception:
            if i + 1 == tries:
                raise
    return ""


def _text(v: str | None) -> str:
    return (v or "").strip()


def _score_title(title: str) -> Tuple[int, str]:
    t = title.lower()

    positives_raw = (
        getattr(config, "SEARCH_KEYWORDS", [])
        + getattr(config, "TITLE_VARIANTS_DE", [])
        + getattr(config, "TITLE_VARIANTS_EN", [])
    )
    positives = {p.lower() for p in positives_raw if p}
    negatives = {n.lower() for n in getattr(config, "NEGATIVE_KEYWORDS", []) if n}

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


# ---------------------------
# Normalisierung jobs.ch/jobup Multi-Line-Titel
# ---------------------------

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

TRUTHY = {"1", "true", "t", "y", "yes", "ja", "j"}
EXPORT_CSV = str(os.getenv("EXPORT_CSV", "true")).lower() in TRUTHY
EXPORT_CSV_PATH = os.getenv("EXPORT_CSV_PATH", "generated/jobs_latest.csv")
MIN_SCORE_MAIL = int(os.getenv("MIN_SCORE_MAIL", "2") or 2)
LOCATION_BOOST_KM = int(os.getenv("LOCATION_BOOST_KM", "15") or 15)
ALLOWED_LOCATIONS = {
    x.strip().lower()
    for x in (os.getenv("ALLOWED_LOCATIONS", "") or "").split(",")
    if x.strip()
}

BLACKLIST = {
    x.strip().lower()
    for x in (os.getenv("BLACKLIST_COMPANIES", "") or "").split(",")
    if x.strip()
}
KEYWORD_BLACKLIST = {
    x.strip().lower()
    for x in (os.getenv("BLACKLIST_KEYWORDS", "") or "").split(",")
    if x.strip()
}
ENABLED_SOURCES = {
    x.strip().lower()
    for x in (
        os.getenv("ENABLED_SOURCES", "jobs.ch,jobup.ch,indeed")
        or "jobs.ch,jobup.ch,indeed"
    ).split(",")
    if x.strip()
}


def _location_boost(job_location: str, search_locations: List[str]) -> int:
    jl = (job_location or "").lower()
    return 1 if any(loc.lower() in jl for loc in (search_locations or [])) else 0


def _is_local(job: Job, search_locations: List[str]) -> bool:
    if not search_locations:
        return True
    texts = [(job.location or ""), (job.title or ""), (job.raw_title or "")]
    for loc in search_locations:
        lo = loc.lower()
        if lo and any(lo in t.lower() for t in texts):
            return True
    return False


def _is_allowed_location(job: Job, allowed: set[str]) -> bool:
    if not allowed:
        return True
    texts = [(job.location or ""), (job.title or ""), (job.raw_title or "")]
    for a in allowed:
        if a and any(a in t.lower() for t in texts):
            return True
    return False


def _norm_key(title: str, company: str, link: str) -> str:
    t = re.sub(r"\W+", "", (title or "").lower())
    c = re.sub(r"\W+", "", (company or "").lower())
    lnk = re.sub(r"[?#].*$", "", (link or "").lower())
    return f"{t}|{c}|{lnk}"


def _collect_indeed(
    driver: webdriver.Chrome,
    url: str,
    limit: int = 25,
) -> List[Job]:
    jobs: List[Job] = []
    _get_html(driver, url)

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
            location = _text(
                a.find_element(By.CSS_SELECTOR, "div.companyLocation").text
            )
        except Exception:
            location = ""

        link = a.get_attribute("href") or ""
        score, label = _score_title(title)

        jobs.append(
            Job(
                raw_title=title,
                title=title,
                company=company,
                location=location,
                link=link,
                source="indeed",
                score=score,
                match=label,
            )
        )

    return jobs


def collect_jobs(
    limit_per_site: int = 25,
    max_total: int = 100,
) -> List[Job]:
    urls = build_search_urls(config)

    base_keywords = getattr(config, "SEARCH_KEYWORDS", []) or ["IT Support"]
    locations = getattr(config, "SEARCH_LOCATIONS", []) or ["Zürich"]
    radius_km = getattr(config, "LOCATION_RADIUS_KM", 25)

    all_jobs: List[Job] = []
    driver = _mk_driver(headless=getattr(config, "HEADLESS_MODE", True))

    try:
        # Indeed (falls URL vorhanden)
        indeed_url = None
        for k, v in urls.items():
            if "indeed" in k.lower() or "indeed" in v.lower():
                indeed_url = v
                break

        if indeed_url and (not ENABLED_SOURCES or "indeed" in ENABLED_SOURCES):
            try:
                indeed_jobs = _collect_indeed(
                    driver,
                    indeed_url,
                    limit=limit_per_site,
                )
                all_jobs.extend(indeed_jobs)
                job_logger.info(f"Indeed: {len(indeed_jobs)} Karten gefunden")
            except Exception as e:
                job_logger.warning(f"Indeed Adapter Fehler: {e}")

        adapters = [JobsChAdapter(), JobupAdapter()]
        for adapter in adapters:
            if ENABLED_SOURCES and adapter.source.lower() not in ENABLED_SOURCES:
                continue

            # über Keywords + Locations iterieren, aber früh abbrechen
            for query in base_keywords:
                for loc in locations:
                    try:
                        rows = adapter.search(
                            driver,
                            query=query,
                            location=loc,
                            radius_km=radius_km,
                            limit=limit_per_site,
                        )

                        converted = 0
                        for r in rows:
                            if not isinstance(r, CHJobRow):
                                continue
                            score, label = _score_title(r.title)
                            all_jobs.append(
                                Job(
                                    raw_title=getattr(r, "raw_title", "") or r.title,
                                    title=r.title,
                                    company=r.company,
                                    location=r.location,
                                    link=r.link,
                                    source=adapter.source,
                                    score=score,
                                    match=label,
                                    date=r.date or "",
                                )
                            )
                            converted += 1

                        job_logger.info(
                            f"{adapter.source}: {converted} Roh-Treffer "
                            f"(query='{query}', loc='{loc}')"
                        )

                        if len(all_jobs) >= max_total * 2:
                            break
                    except Exception as e:
                        job_logger.warning(
                            f"Adapter {adapter.source} Fehler "
                            f"(query='{query}', loc='{loc}'): {e}"
                        )
                if len(all_jobs) >= max_total * 2:
                    break

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Dedupe / Blacklist / Category filter / Location boost
    seen = set()
    unique: List[Job] = []
    search_locs = locations

    for j in all_jobs:
        # Normalize jobs.ch/jobup multi-line titles into fields
        if (
            (not j.company or not j.location)
            and (("\n" in (j.title or "")) or ("Arbeitsort" in (j.title or "")))
        ):
            t2, c2, l2 = _extract_from_multiline_title(j.title)
            if t2:
                j.title = t2
            if not j.company and c2:
                j.company = c2
            if not j.location and l2:
                j.location = l2

        if search_locs and not _is_local(j, search_locs):
            continue
        if ALLOWED_LOCATIONS and not _is_allowed_location(j, ALLOWED_LOCATIONS):
            continue

        if (j.company or "").lower() in BLACKLIST:
            continue
        if any(k in (j.title or "").lower() for k in KEYWORD_BLACKLIST):
            continue

        if j.source in ("jobs.ch", "jobup.ch"):
            link_has_digit = bool(re.search(r"\d", j.link))
            tail = "/".join(j.link.rstrip("/").split("/")[-2:])
            is_category = "stellenangebote" in tail and not "detail" in tail
            if (not link_has_digit) or is_category:
                continue

        key = _norm_key(j.title, j.company, j.link)
        if key in seen:
            continue
        seen.add(key)

        j.score += _location_boost(j.location, search_locs)

        if j.score >= 20:
            j.match = "exact"
        elif j.score >= 10:
            j.match = "good"
        else:
            j.match = j.match or "weak"

        unique.append(j)

    unique.sort(key=lambda x: x.score, reverse=True)
    return unique[:max_total]


def format_jobs_plain(jobs: List[Job], top: int = 20) -> str:
    out: List[str] = []
    for i, j in enumerate(jobs[:top], 1):
        out.append(
            f"{i:02d}. [{j.match:^5}] {j.title} — {j.company} — {j.location}\n"
            f"    {j.link}"
        )
    return "\n".join(out) if out else "Keine Treffer."


def export_csv(rows: List[Job], path: str | None = None) -> None:
    if not EXPORT_CSV:
        return
    out_path = path or EXPORT_CSV_PATH
    Path(os.path.dirname(out_path) or ".").mkdir(exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "company", "location", "match", "score", "link", "source"])
        for j in rows:
            w.writerow(
                [j.title, j.company, j.location, j.match, j.score, j.link, j.source]
            )
