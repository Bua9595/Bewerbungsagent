from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Tuple
import csv
import os
import re
import json
import time
import threading
import random
import unicodedata
import multiprocessing as mp
from urllib.parse import urljoin, urlparse

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# webdriver_manager kept as optional fallback; primary driver discovery uses
# selenium's built-in selenium-manager to avoid Windows Smart App Control blocks
# on freshly-downloaded binaries in ~/.wdm/
try:
    from webdriver_manager.chrome import ChromeDriverManager as _ChromeDriverManager
except ImportError:
    _ChromeDriverManager = None  # type: ignore

from .config import config
from .logger import job_logger
from .job_adapters_ch import JobsChAdapter, JobupAdapter, JobRow as CHJobRow
from .job_adapters_extra import (
    CareerjetAdapter,
    IctJobsAdapter,
    IctCareerAdapter,
    ItJobsAdapter,
    JoobleAdapter,
    JoraAdapter,
    MyItJobAdapter,
    JobrapidoAdapter,
    JobScout24Adapter,
    JobWinnerAdapter,
    MonsterAdapter,
    SwissDevJobsAdapter,
    ExtraJobRow,
)
from .job_query_builder import build_search_urls
from .job_text_utils import extract_from_multiline_title
from .cv_filter import get_cv_blocklist_terms


# Kanonisches Job-Objekt fuer Sammeln/Export.
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
    fit: str = ""
    application_email: str = ""
    contact_name: str = ""
    commute_min: int | None = None


def _mk_driver(headless: bool = True) -> webdriver.Chrome:
    # Selenium-Driver mit stabilen Optionen konfigurieren.
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1200,2000")
    opts.add_argument("--user-agent=Bewerbungsagent/1.0 (+job-collector)")
    opts.add_argument("--lang=de-CH,de;q=0.9")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-logging")
    opts.add_argument("--disable-features=WebGPU")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

    # Driver discovery order:
    # 1. CHROMEDRIVER_PATH env var (manually specified, already trusted binary)
    # 2. selenium-manager built into selenium package (avoids ~/.wdm/ downloads
    #    that Windows Smart App Control may block as unsigned internet-downloads)
    # 3. webdriver_manager fallback (legacy, downloads to ~/.wdm/)
    driver_path = os.getenv("CHROMEDRIVER_PATH", "").strip()
    if driver_path:
        service = Service(driver_path)
    else:
        # Service() with no path → selenium-manager auto-discovers/downloads
        # chromedriver into %LOCALAPPDATA%\selenium\ which avoids SAC issues
        service = Service()

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
    # Seite laden mit Retry.
    for i in range(tries):
        try:
            driver.get(url)
            return driver.page_source
        except Exception:
            if i + 1 == tries:
                raise
    return ""


def _text(v: str | None) -> str:
    # Sicheres Trimmen von Text.
    return (v or "").strip()


def _score_title(title: str) -> Tuple[int, str]:
    # Titel anhand positiver/negativer Keywords bewerten.
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


def compute_fit(match: str, score: int, min_score_apply: int) -> str:
    # Fit-Entscheid aus Match + Score ableiten.
    m = (match or "").lower()
    if m in {"exact", "good"} and score >= min_score_apply:
        return "OK"
    return "DECISION"




def _normalize_text(value: str) -> str:
    # Text normalisieren (Umlaute/Leerzeichen/Zeichen).
    text = (value or "").lower()
    text = (
        text.replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00df", "ss")
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_SOURCE_ALIASES = {
    "jobs": "jobs.ch",
    "jobs.ch": "jobs.ch",
    "jobup": "jobup.ch",
    "jobup.ch": "jobup.ch",
    "jobscout24": "jobscout24",
    "jobscout24.ch": "jobscout24",
    "jobwinner": "jobwinner",
    "jobwinner.ch": "jobwinner",
    "monster": "monster",
    "monster.ch": "monster",
    "careerjet": "careerjet",
    "careerjet.ch": "careerjet",
    "jobrapido": "jobrapido",
    "jobrapido.com": "jobrapido",
    "jooble": "jooble",
    "jooble.org": "jooble",
    "jora": "jora",
    "jora.com": "jora",
    "indeed": "indeed",
    "indeed.ch": "indeed",
    "indeed.com": "indeed",
}


def _normalize_source_name(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        raw = urlparse(raw).netloc or raw
    raw = raw.replace("www.", "").strip().strip("/")
    return _SOURCE_ALIASES.get(raw, raw)


def _parse_commute_map(raw: str) -> list[tuple[str, int]]:
    # Pendelzeiten-Map aus ENV-String parsen.
    if not raw:
        return []
    items: list[tuple[str, int]] = []
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part:
            continue
        if ":" in part:
            name, minutes_raw = part.split(":", 1)
        elif "=" in part:
            name, minutes_raw = part.split("=", 1)
        else:
            continue
        key = _normalize_text(name)
        if not key:
            continue
        nums = [int(x) for x in re.findall(r"\d+", minutes_raw)]
        if not nums:
            continue
        minutes = max(nums)
        items.append((key, minutes))
    items.sort(key=lambda item: len(item[0]), reverse=True)
    return items


def _commute_minutes_for(
    job: "Job", commute_map: list[tuple[str, int]]
) -> int | None:
    # Passende Pendelzeit fuer Job anhand Standort-Keywords finden.
    if not commute_map:
        return None
    texts = [
        _normalize_text(job.location or ""),
        _normalize_text(job.title or ""),
        _normalize_text(job.raw_title or ""),
    ]
    for key, minutes in commute_map:
        if key and any(key in t for t in texts):
            return minutes
    return None


# Marker fuer "Job nicht gefunden" bei Aggregatoren.
AGGREGATOR_NOT_FOUND_MARKERS = (
    "404",
    "page not found",
    "seite nicht gefunden",
    "not found",
    "nicht gefunden",
    "job not found",
    "no longer available",
    "not available",
)


def _aggregator_link_ok(url: str) -> bool:
    # Link pruefen, ob Detailseite erreichbar ist (mit Cache).
    if not url:
        return False
    if url in AGGREGATOR_LINK_CACHE:
        return AGGREGATOR_LINK_CACHE[url]
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Bewerbungsagent/1.0 (+aggregator-check)"},
            timeout=AGGREGATOR_VALIDATE_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
    except Exception:
        AGGREGATOR_LINK_CACHE[url] = False
        return False

    ok = True
    if resp.status_code >= 400:
        ok = False
    else:
        data = b""
        try:
            for chunk in resp.iter_content(chunk_size=4096):
                if not chunk:
                    break
                data += chunk
                if len(data) >= AGGREGATOR_VALIDATE_MAX_BYTES:
                    break
        except Exception:
            ok = False
        if ok:
            text = data.decode("utf-8", errors="ignore").lower()
            if any(marker in text for marker in AGGREGATOR_NOT_FOUND_MARKERS):
                ok = False

    AGGREGATOR_LINK_CACHE[url] = ok
    return ok


def _normalize_terms(items: set[str]) -> set[str]:
    # Begriffe vereinheitlichen (normalisieren).
    return {_normalize_text(x) for x in items if x}


def _dedupe_terms(items: List[str]) -> List[str]:
    # Duplikate entfernen, Reihenfolge behalten.
    seen = set()
    out: List[str] = []
    for item in items:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _batch_terms(terms: List[str], batch_size: int, joiner: str) -> List[str]:
    if batch_size <= 1:
        return terms
    joiner = (joiner or "OR").strip()
    joiner = f" {joiner} " if joiner else " OR "
    out: List[str] = []
    for i in range(0, len(terms), batch_size):
        chunk = [t for t in terms[i : i + batch_size] if t]
        if not chunk:
            continue
        if len(chunk) == 1:
            out.append(chunk[0])
        else:
            out.append(joiner.join(chunk))
    return out


def _split_tasks(tasks: List[tuple], workers: int) -> List[List[tuple]]:
    if workers <= 1 or not tasks:
        return [tasks]
    chunks: List[List[tuple]] = [[] for _ in range(workers)]
    for idx, task in enumerate(tasks):
        chunks[idx % workers].append(task)
    return [chunk for chunk in chunks if chunk]


def _selenium_worker(
    tasks: List[tuple[str, str, str]],
    radius_km: int,
    limit_per_site: int | None,
    headless: bool,
) -> dict:
    adapter_map = {
        "jobs.ch": JobsChAdapter,
        "jobup.ch": JobupAdapter,
    }
    driver = _mk_driver(headless=headless)
    results: list[dict] = []
    errors: list[str] = []
    try:
        adapters: dict[str, object] = {}
        for source, query, loc in tasks:
            adapter = adapters.get(source)
            if adapter is None:
                cls = adapter_map.get(source)
                if cls is None:
                    errors.append(f"unknown adapter '{source}'")
                    continue
                adapter = cls()
                adapters[source] = adapter
            started = time.perf_counter()
            try:
                _adapter_pause()
                rows = adapter.search(
                    driver,
                    query=query,
                    location=loc,
                    radius_km=radius_km,
                    limit=limit_per_site,
                )
            except Exception as exc:
                errors.append(f"{source} (query='{query}', loc='{loc}'): {exc}")
                continue
            duration = time.perf_counter() - started
            payload_rows: list[dict] = []
            for row in rows:
                payload_rows.append(
                    {
                        "title": getattr(row, "title", "") or "",
                        "raw_title": getattr(row, "raw_title", "") or "",
                        "company": getattr(row, "company", "") or "",
                        "location": getattr(row, "location", "") or "",
                        "link": getattr(row, "link", "") or "",
                        "date": getattr(row, "date", "") or "",
                        "source": getattr(row, "source", source) or source,
                    }
                )
            results.append(
                {
                    "source": source,
                    "query": query,
                    "loc": loc,
                    "rows": payload_rows,
                    "duration": duration,
                }
            )
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return {"results": results, "errors": errors}


def _empty_cache_key(source: str, query: str, location: str, radius_km: int) -> str:
    src = (source or "").strip().lower()
    q = _normalize_text(query or "")
    loc = _normalize_text(location or "")
    return f"{src}|{q}|{loc}|{radius_km}"


def _load_empty_search_cache(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in data.items():
        try:
            out[str(key)] = float(value)
        except Exception:
            continue
    return out


def _prune_empty_search_cache(
    cache: dict[str, float],
    ttl_seconds: float,
    now_ts: float,
) -> dict[str, float]:
    if ttl_seconds <= 0:
        return {}
    return {k: v for k, v in cache.items() if (now_ts - v) <= ttl_seconds}


def _save_empty_search_cache(path: Path, cache: dict[str, float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception:
        return


# ENV/Feature-Flags und Grenzen fuer das Sammeln.
TRUTHY = {"1", "true", "t", "y", "yes", "ja", "j"}
EXPORT_CSV = str(os.getenv("EXPORT_CSV", "true")).lower() in TRUTHY
EXPORT_CSV_PATH = os.getenv("EXPORT_CSV_PATH", "generated/jobs_latest.csv")
MIN_SCORE_MAIL = int(os.getenv("MIN_SCORE_MAIL", "2") or 2)
LOCATION_BOOST_KM = int(os.getenv("LOCATION_BOOST_KM", "15") or 15)
STRICT_LOCATION_FILTER = str(
    os.getenv("STRICT_LOCATION_FILTER", "true")
).lower() in TRUTHY
ADAPTER_REQUEST_DELAY = float(os.getenv("ADAPTER_REQUEST_DELAY", "0") or 0)
REQUESTS_ADAPTER_WORKERS = int(os.getenv("REQUESTS_ADAPTER_WORKERS", "6") or 6)
REQUESTS_ADAPTER_TIMEOUT = float(os.getenv("REQUESTS_ADAPTER_TIMEOUT", "15") or 15)
REQUESTS_ADAPTER_RETRIES = int(os.getenv("REQUESTS_ADAPTER_RETRIES", "1") or 1)
REQUESTS_RETRY_BACKOFF_SEC = float(os.getenv("REQUESTS_RETRY_BACKOFF_SEC", "1") or 1)
REQUESTS_RETRY_JITTER_SEC = float(os.getenv("REQUESTS_RETRY_JITTER_SEC", "0.3") or 0.3)
REQUESTS_FUTURE_TIMEOUT_SEC = float(os.getenv("REQUESTS_FUTURE_TIMEOUT_SEC", "180") or 180)
EMPTY_SEARCH_TTL_HOURS = float(os.getenv("EMPTY_SEARCH_TTL_HOURS", "0") or 0)
EMPTY_SEARCH_CACHE_PATH = Path(
    os.getenv("EMPTY_SEARCH_CACHE_PATH", "generated/empty_search_cache.json")
)
TIMING_ENABLED = str(os.getenv("TIMING_ENABLED", "false")).lower() in TRUTHY
FILTER_STATS = str(os.getenv("FILTER_STATS", "false")).lower() in TRUTHY
SELENIUM_WORKERS = int(os.getenv("SELENIUM_WORKERS", "1") or 1)
SELENIUM_WORKERS_RECOMMENDED_MAX = 3
SELENIUM_EXECUTION_MODE = (os.getenv("SELENIUM_EXECUTION_MODE", "auto") or "auto").strip().lower()
SELENIUM_FUTURE_TIMEOUT_SEC = float(os.getenv("SELENIUM_FUTURE_TIMEOUT_SEC", "240") or 240)
COLLECT_RUN_DEADLINE_SEC = float(os.getenv("COLLECT_RUN_DEADLINE_SEC", "240") or 240)
COLLECT_RAW_CAP_MULTIPLIER = int(os.getenv("COLLECT_RAW_CAP_MULTIPLIER", "2") or 2)
ALLOWED_LOCATION_BOOST = int(os.getenv("ALLOWED_LOCATION_BOOST", "2") or 2)
ALLOWED_LOCATIONS = {
    x.strip().lower()
    for x in (os.getenv("ALLOWED_LOCATIONS", "") or "").split(",")
    if x.strip()
}
HARD_ALLOWED_LOCATIONS = {
    x.strip().lower()
    for x in (os.getenv("HARD_ALLOWED_LOCATIONS", "") or "").split(",")
    if x.strip()
}
COMMUTE_MINUTES = _parse_commute_map(os.getenv("COMMUTE_MINUTES", "") or "")
try:
    COMMUTE_PENALTY_MIN = int(os.getenv("COMMUTE_PENALTY_MIN", "75") or 75)
except Exception:
    COMMUTE_PENALTY_MIN = 75
try:
    COMMUTE_PENALTY = int(os.getenv("COMMUTE_PENALTY", "5") or 5)
except Exception:
    COMMUTE_PENALTY = 5
AUTO_FIT_ENABLED = str(os.getenv("AUTO_FIT_ENABLED", "false")).lower() in TRUTHY
MIN_SCORE_APPLY = float(os.getenv("MIN_SCORE_APPLY", "1") or 1)

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
LANGUAGE_BLOCKLIST = {
    x.strip().lower()
    for x in (os.getenv("LANGUAGE_BLOCKLIST", "") or "").split(",")
    if x.strip()
}
REQUIREMENTS_BLOCKLIST = {
    x.strip().lower()
    for x in (os.getenv("REQUIREMENTS_BLOCKLIST", "") or "").split(",")
    if x.strip()
}
INCLUDE_KEYWORDS = _normalize_terms(
    {
        x.strip()
        for x in (os.getenv("INCLUDE_KEYWORDS", "") or "").split(",")
        if x.strip()
    }
)
BLOCKLIST_TERMS = _normalize_terms(
    KEYWORD_BLACKLIST | LANGUAGE_BLOCKLIST | REQUIREMENTS_BLOCKLIST | get_cv_blocklist_terms()
)
AGGREGATOR_SOURCES = {"careerjet", "jobrapido", "jooble"}
ALLOW_AGGREGATORS = str(os.getenv("ALLOW_AGGREGATORS", "false")).lower() in TRUTHY
AGGREGATOR_VALIDATE_LINKS = (
    str(os.getenv("AGGREGATOR_VALIDATE_LINKS", "true")).lower() in TRUTHY
)
AGGREGATOR_VALIDATE_TIMEOUT = float(
    os.getenv("AGGREGATOR_VALIDATE_TIMEOUT", "8") or 8
)
AGGREGATOR_VALIDATE_MAX_BYTES = int(
    os.getenv("AGGREGATOR_VALIDATE_MAX_BYTES", "20000") or 20000
)
DISABLED_SOURCES = {
    _normalize_source_name(x)
    for x in (os.getenv("DISABLED_SOURCES", "") or "").split(",")
    if _normalize_source_name(x)
}
BLOCKED_SOURCES = DISABLED_SOURCES | (
    set() if ALLOW_AGGREGATORS else AGGREGATOR_SOURCES
)
ENABLED_SOURCES = {
    _normalize_source_name(x)
    for x in (
        os.getenv(
            "ENABLED_SOURCES",
            "jobs.ch,jobup.ch,jobscout24,indeed,monster",
        )
        or "jobs.ch,jobup.ch,jobscout24,indeed,monster"
    ).split(",")
    if _normalize_source_name(x)
}
if BLOCKED_SOURCES:
    ENABLED_SOURCES = {s for s in ENABLED_SOURCES if s not in BLOCKED_SOURCES}
EXPAND_QUERY_VARIANTS = str(
    os.getenv("EXPAND_QUERY_VARIANTS", "true")
).lower() in TRUTHY
QUERY_VARIANTS_LIMIT = int(os.getenv("QUERY_VARIANTS_LIMIT", "6") or 6)
MAX_QUERY_TERMS = int(os.getenv("MAX_QUERY_TERMS", "8") or 8)
QUERY_BATCH_SIZE = int(os.getenv("QUERY_BATCH_SIZE", "1") or 1)
QUERY_BATCH_JOINER = os.getenv("QUERY_BATCH_JOINER", " OR ")
QUERY_BATCH_SOURCES = {
    _normalize_source_name(x)
    for x in (os.getenv("QUERY_BATCH_SOURCES", "") or "").split(",")
    if _normalize_source_name(x)
}
EXTRA_QUERY_TERMS = [
    x.strip()
    for x in (os.getenv("EXTRA_QUERY_TERMS", "") or "").split(",")
    if x.strip()
]
COLLECT_LIMIT_PER_SITE = int(os.getenv("COLLECT_LIMIT_PER_SITE", "25") or 25)
COLLECT_MAX_TOTAL = int(os.getenv("COLLECT_MAX_TOTAL", "100") or 100)
DETAILS_BLOCKLIST_SCAN = str(
    os.getenv("DETAILS_BLOCKLIST_SCAN", "false")
).lower() in TRUTHY
DETAILS_BLOCKLIST_MAX_BYTES = int(
    os.getenv("DETAILS_BLOCKLIST_MAX_BYTES", "200000") or 200000
)
DETAILS_BLOCKLIST_MAX_JOBS = int(
    os.getenv("DETAILS_BLOCKLIST_MAX_JOBS", "80") or 80
)
DETAILS_BLOCKLIST_TIMEOUT = float(
    os.getenv("DETAILS_BLOCKLIST_TIMEOUT", "12") or 12
)
DETAILS_INCLUDE_SCAN = str(
    os.getenv("DETAILS_INCLUDE_SCAN", "false")
).lower() in TRUTHY
DETAILS_INCLUDE_MAX_BYTES = int(
    os.getenv("DETAILS_INCLUDE_MAX_BYTES", DETAILS_BLOCKLIST_MAX_BYTES)
    or DETAILS_BLOCKLIST_MAX_BYTES
)
DETAILS_INCLUDE_MAX_JOBS = int(
    os.getenv("DETAILS_INCLUDE_MAX_JOBS", DETAILS_BLOCKLIST_MAX_JOBS)
    or DETAILS_BLOCKLIST_MAX_JOBS
)
DETAILS_INCLUDE_TIMEOUT = float(
    os.getenv("DETAILS_INCLUDE_TIMEOUT", DETAILS_BLOCKLIST_TIMEOUT)
    or DETAILS_BLOCKLIST_TIMEOUT
)
DETAILS_BLOCKLIST_SKIP_DOMAINS = {
    x.strip().lower()
    for x in (os.getenv("DETAILS_BLOCKLIST_SKIP_DOMAINS", "") or "").split(",")
    if x.strip()
}
DETAILS_CONTACT_SCAN = str(
    os.getenv("DETAILS_CONTACT_SCAN", "false")
).lower() in TRUTHY
DETAILS_CONTACT_MAX_BYTES = int(
    os.getenv("DETAILS_CONTACT_MAX_BYTES", "200000") or 200000
)
DETAILS_CONTACT_MAX_JOBS = int(
    os.getenv("DETAILS_CONTACT_MAX_JOBS", "40") or 40
)
DETAILS_CONTACT_TIMEOUT = float(
    os.getenv("DETAILS_CONTACT_TIMEOUT", "12") or 12
)
ALLOW_REMOTE = str(os.getenv("ALLOW_REMOTE", "true")).lower() in TRUTHY
REMOTE_KEYWORDS = [
    x.strip().lower()
    for x in (
        os.getenv("REMOTE_KEYWORDS", "remote,homeoffice,home office,hybrid,hybride")
        or ""
    ).split(",")
    if x.strip()
]
TRANSIT_ENABLED = str(os.getenv("TRANSIT_ENABLED", "false")).lower() in TRUTHY
TRANSIT_ORIGIN = os.getenv("TRANSIT_ORIGIN", "").strip()
TRANSIT_MAX_MINUTES = int(os.getenv("TRANSIT_MAX_MINUTES", "60") or 60)
TRANSIT_TIME = os.getenv("TRANSIT_TIME", "").strip()
TRANSIT_DATE = os.getenv("TRANSIT_DATE", "").strip()
TRANSIT_TIMEOUT = float(os.getenv("TRANSIT_TIMEOUT", "12") or 12)
TRANSIT_REQUEST_DELAY = float(os.getenv("TRANSIT_REQUEST_DELAY", "0.5") or 0.5)

# In-Memory-Caches fuer Detail-Scans und Checks.
DETAILS_BLOCKLIST_CACHE: dict[str, bool] = {}
DETAILS_INCLUDE_CACHE: dict[str, bool] = {}
DETAILS_TEXT_CACHE: dict[str, str] = {}
DETAILS_LOCATION_CACHE: dict[str, str] = {}
DETAILS_CONTACT_CACHE: dict[str, tuple[str, str]] = {}
TRANSIT_CACHE: dict[tuple[str, str, str, str], int | None] = {}
AGGREGATOR_LINK_CACHE: dict[str, bool] = {}
COMPANY_CAREERS_ENABLED = str(
    os.getenv("COMPANY_CAREERS_ENABLED", "false")
).lower() in TRUTHY
COMPANY_CAREER_URLS = [
    x.strip()
    for x in (os.getenv("COMPANY_CAREER_URLS", "") or "").split(",")
    if x.strip()
]
COMPANY_CAREER_NAMES = [
    x.strip()
    for x in (os.getenv("COMPANY_CAREER_NAMES", "") or "").split(",")
    if x.strip()
]
CAREER_LINK_KEYWORDS = [
    x.strip().lower()
    for x in (
        os.getenv(
            "CAREER_LINK_KEYWORDS",
            "career,karriere,stellen,job,jobs,position,positions,vacancy,vacancies",
        )
        or ""
    ).split(",")
    if x.strip()
]
CAREER_MAX_LINKS = int(os.getenv("CAREER_MAX_LINKS", "40") or 40)
CAREER_MIN_SCORE = int(os.getenv("CAREER_MIN_SCORE", "0") or 0)

_LOCATION_ALIAS_HINTS = [
    ("zuerich oerlikon", "Zuerich Oerlikon"),
    ("zurich oerlikon", "Zuerich Oerlikon"),
    ("zuerich flughafen", "Zuerich Flughafen"),
    ("zurich flughafen", "Zuerich Flughafen"),
    ("zurich airport", "Zuerich Flughafen"),
    ("glattbrugg", "Glattbrugg"),
    ("wallisellen", "Wallisellen"),
    ("duebendorf", "Duebendorf"),
    ("dubendorf", "Duebendorf"),
    ("opfikon", "Opfikon"),
    ("kloten", "Kloten"),
    ("winterthur", "Winterthur"),
    ("buelach", "Buelach"),
    ("bulach", "Buelach"),
    ("wangen bruettisellen", "Wangen-Bruettisellen"),
    ("wangen bruttisellen", "Wangen-Bruettisellen"),
    ("schlieren", "Schlieren"),
    ("urdorf", "Urdorf"),
    ("dietikon", "Dietikon"),
    ("volketswil", "Volketswil"),
    ("adliswil", "Adliswil"),
    ("thalwil", "Thalwil"),
    ("wetzikon", "Wetzikon"),
    ("schaffhausen", "Schaffhausen"),
    ("baden", "Baden"),
    ("aarau", "Aarau"),
    ("zug", "Zug"),
    ("zuerich", "Zuerich"),
    ("zurich", "Zuerich"),
    ("bern", "Bern"),
    ("basel", "Basel"),
    ("luzern", "Luzern"),
    ("st gallen", "St. Gallen"),
    ("lausanne", "Lausanne"),
    ("geneve", "Geneve"),
    ("geneva", "Geneve"),
]


class _AnchorParser(HTMLParser):
    # Minimaler HTML-Parser fuer Links + Text.
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = ""
        for k, v in attrs:
            if k.lower() == "href":
                href = v or ""
                break
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._href is None:
            return
        text = " ".join("".join(self._text_parts).split())
        self.links.append((self._href, text))
        self._href = None
        self._text_parts = []


def _extract_links(html: str) -> List[Tuple[str, str]]:
    # Alle Anchor-Hrefs + Text extrahieren.
    parser = _AnchorParser()
    parser.feed(html or "")
    return parser.links


def _company_name_from_url(url: str) -> str:
    # Firmenname heuristisch aus Domain ableiten.
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Unbekannt"
    parts = host.split(".")
    base = parts[-2] if len(parts) >= 2 else host
    base = base.replace("-", " ").strip()
    return base.title() if base else host


def _collect_company_careers(urls: List[str], names: List[str]) -> List[Job]:
    # Eigene Karriere-Seiten nach Links durchsuchen.
    jobs: List[Job] = []
    if not urls:
        return jobs

    for idx, url in enumerate(urls):
        company = names[idx] if idx < len(names) and names[idx] else _company_name_from_url(url)
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Bewerbungsagent/1.0 (+company-scan)"},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            job_logger.warning(f"Career-Scan Fehler ({company}): {e}")
            continue

        anchors = _extract_links(resp.text)
        seen = set()
        kept = 0
        for href, text in anchors:
            if not href:
                continue
            href = href.strip()
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            abs_url = urljoin(url, href)
            if abs_url == url or abs_url in seen:
                continue
            seen.add(abs_url)

            link_l = abs_url.lower()
            text_l = (text or "").lower()
            score, label = _score_title(text or abs_url)
            has_signal = score > 0 or any(k in text_l for k in CAREER_LINK_KEYWORDS)
            if CAREER_LINK_KEYWORDS and not any(k in link_l for k in CAREER_LINK_KEYWORDS) and not has_signal:
                continue
            if score < CAREER_MIN_SCORE:
                continue

            title = text.strip() or abs_url.rsplit("/", 1)[-1]
            jobs.append(
                Job(
                    raw_title=title,
                    title=title,
                    company=company,
                    location="",
                    link=abs_url,
                    source="company-site",
                    score=score,
                    match=label,
                )
            )
            kept += 1
            if kept >= CAREER_MAX_LINKS:
                break

        job_logger.info(f"company-site: {company} {kept} Links")

    return jobs


def _location_boost(job_location: str, search_locations: List[str]) -> int:
    # Bonus, wenn Standort zu Suchorten passt.
    jl = _normalize_text(job_location or "")
    return (
        1
        if any(_normalize_text(loc) in jl for loc in (search_locations or []) if loc)
        else 0
    )


def _is_remote(job: Job) -> bool:
    # Remote-Job anhand Keywords erkennen.
    if not REMOTE_KEYWORDS:
        return False
    blob = " ".join([job.location or "", job.title or "", job.raw_title or ""])
    normalized = _normalize_text(blob)
    return any(_normalize_text(k) in normalized for k in REMOTE_KEYWORDS)


def _tokens_in_order(tokens: list[str], terms: list[str]) -> bool:
    # Pruefen, ob Term-Tokens in Reihenfolge vorkommen.
    if not tokens or not terms:
        return False
    idx = 0
    for tok in tokens:
        if tok == terms[idx]:
            idx += 1
            if idx == len(terms):
                return True
    return False


def _contains_blocked_terms(normalized: str, blocked: set[str]) -> bool:
    # Blockierte Begriffe im Text finden.
    if not normalized or not blocked:
        return False
    if any(term in normalized for term in blocked):
        return True
    tokens = normalized.split()
    for term in blocked:
        if " " not in term:
            continue
        term_tokens = [t for t in term.split() if t]
        if _tokens_in_order(tokens, term_tokens):
            return True
    return False


def _has_blocked_keywords(job: Job, blocked: set[str]) -> bool:
    # Jobtext gegen Blocklist pruefen.
    if not blocked:
        return False
    blob = " ".join([job.title or "", job.raw_title or "", job.location or ""])
    normalized = _normalize_text(blob)
    return _contains_blocked_terms(normalized, blocked)


def _has_required_keywords(job: Job, required: set[str]) -> bool:
    # Jobtext gegen Required-Keywords pruefen.
    if not required:
        return True
    blob = " ".join(
        [
            job.title or "",
            job.raw_title or "",
            job.company or "",
            job.location or "",
            job.link or "",
        ]
    )
    normalized = _normalize_text(blob)
    if not normalized:
        return False
    tokens = set(normalized.split())
    for term in required:
        if not term:
            continue
        if len(term) <= 2:
            if term in tokens:
                return True
        else:
            if term in normalized:
                return True
    return False


_DURATION_RE = re.compile(r"(?:(\d+)d)?(\d{1,2}):(\d{2}):(\d{2})")


def _parse_duration_minutes(value: str) -> int | None:
    # Opendata-Dauerstring in Minuten umrechnen.
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    return days * 24 * 60 + hours * 60 + minutes


_transit_last_request: float = 0.0


def _get_transit_minutes(
    origin: str, destination: str, date: str, time_str: str
) -> int | None:
    # Opendata Transit-API abfragen (mit Cache + Rate-Limit-Schutz).
    global _transit_last_request
    key = (origin, destination, date, time_str)
    if key in TRANSIT_CACHE:
        return TRANSIT_CACHE[key]
    params = {"from": origin, "to": destination, "limit": 1}
    if date:
        params["date"] = date
    if time_str:
        params["time"] = time_str
    # Mindest-Pause zwischen Requests einhalten (Rate-Limit transport.opendata.ch)
    elapsed = time.time() - _transit_last_request
    if elapsed < TRANSIT_REQUEST_DELAY:
        time.sleep(TRANSIT_REQUEST_DELAY - elapsed)
    try:
        _transit_last_request = time.time()
        resp = requests.get(
            "https://transport.opendata.ch/v1/connections",
            params=params,
            timeout=TRANSIT_TIMEOUT,
        )
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5"))
            job_logger.warning(
                f"Transit-API 429 fuer {destination}, warte {retry_after:.0f}s"
            )
            time.sleep(retry_after)
            _transit_last_request = time.time()
            resp = requests.get(
                "https://transport.opendata.ch/v1/connections",
                params=params,
                timeout=TRANSIT_TIMEOUT,
            )
        resp.raise_for_status()
        data = resp.json()
        connections = data.get("connections") or []
        if not connections:
            TRANSIT_CACHE[key] = None
            return None
        duration = connections[0].get("duration") or ""
        minutes = _parse_duration_minutes(duration)
        TRANSIT_CACHE[key] = minutes
        return minutes
    except Exception as e:
        job_logger.warning(
            f"Transit-Check Fehler ({origin} -> {destination}): {e}"
        )
        TRANSIT_CACHE[key] = None
        return None


_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?is)<[^>]+>")
_NOISE_SECTION_RE = re.compile(
    r"(?is)<(header|nav|footer|aside|form|noscript|svg)[^>]*>.*?</\1>"
)
_MAIN_ARTICLE_RE = re.compile(r"(?is)<(main|article)[^>]*>(.*?)</\1>")
_JSONLD_SCRIPT_RE = re.compile(
    r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_EMAIL_HINTS = ("bewerbung", "recruit", "hr", "jobs", "career")
_EMAIL_DOMAIN_BLOCKLIST = {"jobs.ch", "jobup.ch", "indeed.com"}
_CONTACT_LABEL_RE = re.compile(
    r"(ansprech(?:partner|person)(?:/in)?|kontakt(?:person)?|contact|bewerbung|recruiter)",
    re.IGNORECASE,
)


def _extract_emails_from_html(html: str) -> List[str]:
    # E-Mails aus HTML/Links extrahieren und filtern.
    if not html:
        return []
    candidates: List[str] = []
    for href, _text in _extract_links(html):
        if not href:
            continue
        href_l = href.strip().lower()
        if not href_l.startswith("mailto:"):
            continue
        addr = href.split(":", 1)[1].split("?", 1)[0].strip()
        addr = addr.strip(" \t\r\n,.;:")
        if addr:
            candidates.append(addr)

    for email in _EMAIL_RE.findall(html):
        if email:
            candidates.append(email.strip(" \t\r\n,.;:"))

    seen = set()
    out: List[str] = []
    for email in candidates:
        email_l = email.lower()
        if email_l in seen:
            continue
        seen.add(email_l)
        domain = email_l.split("@")[-1].strip()
        if domain in _EMAIL_DOMAIN_BLOCKLIST:
            continue
        out.append(email)
    return out


def _pick_email(candidates: List[str]) -> str:
    # Passendste E-Mail anhand von Hinweisen auswaehlen.
    if not candidates:
        return ""
    for hint in _EMAIL_HINTS:
        for email in candidates:
            if hint in email.lower():
                return email
    return candidates[0]


def _html_to_lines(html: str) -> List[str]:
    # HTML in bereinigte Textzeilen umwandeln.
    if not html:
        return []
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</(p|div|li|tr|section|article)>", "\n", text)
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    lines: List[str] = []
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean:
            lines.append(clean)
    return lines


def _looks_like_name(text: str) -> bool:
    # Heuristik, ob String wie ein Personenname aussieht.
    if not text or "@" in text:
        return False
    if len(text) > 80:
        return False
    if re.search(r"\b(http|www\.)", text, re.I):
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z\.'-]*", text)
    return 1 < len(tokens) <= 4


def _clean_contact_line(line: str) -> str:
    # Kontaktzeile bereinigen und Label entfernen.
    candidate = line.strip()
    if ":" in candidate:
        head, tail = candidate.split(":", 1)
        if _CONTACT_LABEL_RE.search(head):
            candidate = tail.strip()
    candidate = re.sub(
        r"(?i)\b(e-mail|email|telefon|phone|tel)\b.*",
        "",
        candidate,
    ).strip()
    return candidate


def _extract_contact_name(lines: List[str]) -> str:
    # Kontaktname anhand von Label + Folgelinien suchen.
    for idx, line in enumerate(lines):
        if not _CONTACT_LABEL_RE.search(line):
            continue
        candidate = _clean_contact_line(line)
        if _looks_like_name(candidate):
            return candidate
        for offset in (1, 2):
            if idx + offset >= len(lines):
                continue
            candidate = _clean_contact_line(lines[idx + offset])
            if _looks_like_name(candidate):
                return candidate
    return ""


def _detail_page_contact(url: str) -> Tuple[str, str]:
    # Detailseite scannen und Kontaktinfos cachen.
    if not url:
        return "", ""
    if url in DETAILS_CONTACT_CACHE:
        return DETAILS_CONTACT_CACHE[url]
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Bewerbungsagent/1.0 (+contact-scan)"},
            timeout=DETAILS_CONTACT_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.text or ""
        if DETAILS_CONTACT_MAX_BYTES and len(text) > DETAILS_CONTACT_MAX_BYTES:
            text = text[:DETAILS_CONTACT_MAX_BYTES]
    except Exception as e:
        job_logger.warning(f"Contact-Scan Fehler ({url}): {e}")
        DETAILS_CONTACT_CACHE[url] = ("", "")
        return "", ""

    emails = _extract_emails_from_html(text)
    email = _pick_email(emails)
    name = _extract_contact_name(_html_to_lines(text))
    DETAILS_CONTACT_CACHE[url] = (email, name)
    return email, name


def extract_application_contact(url: str) -> Tuple[str, str]:
    # Oeffentliche API fuer Kontakt-Extraktion.
    return _detail_page_contact(url)


def _detail_page_has_blocked_terms(url: str, blocked: set[str]) -> bool:
    # Detailseite auf blockierte Begriffe pruefen (mit Cache).
    if not url or not blocked:
        return False
    if url in DETAILS_BLOCKLIST_CACHE:
        return DETAILS_BLOCKLIST_CACHE[url]
    normalized = _detail_page_text(
        url,
        timeout=DETAILS_BLOCKLIST_TIMEOUT,
        max_bytes=DETAILS_BLOCKLIST_MAX_BYTES,
    )
    if not normalized:
        DETAILS_BLOCKLIST_CACHE[url] = False
        return False
    blocked_found = _contains_blocked_terms(normalized, blocked)
    DETAILS_BLOCKLIST_CACHE[url] = blocked_found
    return blocked_found


def _extract_jobposting_payload(html: str) -> tuple[str, str]:
    chunks: list[str] = []
    locations: list[str] = []
    for match in _JSONLD_SCRIPT_RE.finditer(html or ""):
        raw = (match.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, dict) and "@graph" in obj and isinstance(obj["@graph"], list):
                stack.extend(obj["@graph"])
                continue
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get("@type")
            is_job = obj_type == "JobPosting" or (
                isinstance(obj_type, list) and "JobPosting" in obj_type
            )
            if not is_job:
                continue
            fields = [
                obj.get("title"),
                obj.get("description"),
                obj.get("qualifications"),
                obj.get("skills"),
                obj.get("experienceRequirements"),
                obj.get("responsibilities"),
            ]
            hiring_org = obj.get("hiringOrganization")
            if isinstance(hiring_org, dict):
                fields.append(hiring_org.get("name"))
            loc_parts: list[str] = []
            job_location = obj.get("jobLocation")
            if isinstance(job_location, list) and job_location:
                first = job_location[0] if isinstance(job_location[0], dict) else {}
                addr = first.get("address") or {}
                loc_parts = [
                    addr.get("addressLocality"),
                    addr.get("addressRegion"),
                    addr.get("addressCountry"),
                ]
                fields.extend(loc_parts)
            elif isinstance(job_location, dict):
                addr = job_location.get("address") or {}
                loc_parts = [
                    addr.get("addressLocality"),
                    addr.get("addressRegion"),
                    addr.get("addressCountry"),
                ]
                fields.extend(loc_parts)
            location = ", ".join(
                [part.strip() for part in loc_parts if isinstance(part, str) and part.strip()]
            )
            if location:
                locations.append(location)
            for field in fields:
                if isinstance(field, str) and field.strip():
                    chunks.append(field)
    return " ".join(chunks), (locations[0] if locations else "")


def _extract_jobposting_text(html: str) -> str:
    return _extract_jobposting_payload(html)[0]


def _extract_jobposting_location(html: str) -> str:
    return _extract_jobposting_payload(html)[1]


def _extract_primary_html_text(html: str) -> str:
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html or "")
    cleaned = _NOISE_SECTION_RE.sub(" ", cleaned)
    fragments = [m.group(2) for m in _MAIN_ARTICLE_RE.finditer(cleaned)]
    source = " ".join(fragments) if fragments else cleaned
    source = _TAG_RE.sub(" ", source)
    return unescape(source)


def _extract_relevant_detail_text(html: str) -> str:
    jsonld_text = _extract_jobposting_text(html)
    if jsonld_text.strip():
        return jsonld_text
    return _extract_primary_html_text(html)


def _infer_location_from_normalized_text(normalized: str) -> str:
    # Standort heuristisch aus Detailtext ableiten.
    if not normalized:
        return ""

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    env_locations = list(getattr(config, "SEARCH_LOCATIONS", []) or []) + list(
        ALLOWED_LOCATIONS
    )
    for value in env_locations:
        display = (value or "").strip()
        needle = _normalize_text(display)
        if not display or not needle or needle in seen:
            continue
        seen.add(needle)
        candidates.append((needle, display))

    for needle, display in _LOCATION_ALIAS_HINTS:
        needle_norm = _normalize_text(needle)
        if not needle_norm or needle_norm in seen:
            continue
        seen.add(needle_norm)
        candidates.append((needle_norm, display))

    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    for needle, display in candidates:
        if needle and needle in normalized:
            return display
    return ""


def _detail_page_payload(url: str, timeout: float, max_bytes: int) -> tuple[str, str]:
    # Detailseite als normalisierten Text plus Ort cachen.
    if not url:
        return "", ""
    if url in DETAILS_TEXT_CACHE and url in DETAILS_LOCATION_CACHE:
        return DETAILS_TEXT_CACHE[url], DETAILS_LOCATION_CACHE[url]
    if _is_skipped_detail_domain(url):
        DETAILS_TEXT_CACHE[url] = ""
        DETAILS_LOCATION_CACHE[url] = ""
        return "", ""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Bewerbungsagent/1.0 (+detail-scan)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.text or ""
        if max_bytes and len(text) > max_bytes:
            text = text[:max_bytes]
        normalized = _normalize_text(_extract_relevant_detail_text(text))
        location = _extract_jobposting_location(text).strip()
        if not location:
            location = _infer_location_from_normalized_text(normalized)
        DETAILS_TEXT_CACHE[url] = normalized
        DETAILS_LOCATION_CACHE[url] = location
        return normalized, location
    except Exception as e:
        job_logger.warning(f"Detail-Scan Fehler ({url}): {e}")
        DETAILS_TEXT_CACHE[url] = ""
        DETAILS_LOCATION_CACHE[url] = ""
        return "", ""


def _detail_page_text(url: str, timeout: float, max_bytes: int) -> str:
    return _detail_page_payload(url, timeout, max_bytes)[0]


def _detail_page_location(url: str, timeout: float, max_bytes: int) -> str:
    return _detail_page_payload(url, timeout, max_bytes)[1]


def _detail_page_has_required_terms(url: str, required: set[str]) -> bool:
    # Detailseite auf Required-Keywords pruefen (mit Cache).
    if not url or not required:
        return False
    if url in DETAILS_INCLUDE_CACHE:
        return DETAILS_INCLUDE_CACHE[url]
    normalized = _detail_page_text(
        url,
        timeout=DETAILS_INCLUDE_TIMEOUT,
        max_bytes=DETAILS_INCLUDE_MAX_BYTES,
    )
    if not normalized:
        DETAILS_INCLUDE_CACHE[url] = False
        return False
    tokens = set(normalized.split())
    found = False
    for term in required:
        if not term:
            continue
        if len(term) <= 2:
            if term in tokens:
                found = True
                break
        else:
            if term in normalized:
                found = True
                break
    DETAILS_INCLUDE_CACHE[url] = found
    return found


def _is_skipped_detail_domain(url: str) -> bool:
    # Domains aus dem Detail-Scan ausschliessen.
    if not url or not DETAILS_BLOCKLIST_SKIP_DOMAINS:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    for domain in DETAILS_BLOCKLIST_SKIP_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _is_local(job: Job, search_locations: List[str]) -> bool:
    # Job mit Suchorten abgleichen.
    if not search_locations:
        return True
    texts = [
        _normalize_text(job.location or ""),
        _normalize_text(job.title or ""),
        _normalize_text(job.raw_title or ""),
    ]
    for loc in search_locations:
        lo = _normalize_text(loc)
        if lo and any(lo in t for t in texts):
            return True
    return False


def _is_allowed_location(job: Job, allowed: set[str]) -> bool:
    # Job gegen erlaubte Orte pruefen.
    if not allowed:
        return True
    texts = [
        _normalize_text(job.location or ""),
        _normalize_text(job.title or ""),
        _normalize_text(job.raw_title or ""),
    ]
    for a in allowed:
        aa = _normalize_text(a)
        if aa and any(aa in t for t in texts):
            return True
    return False


def _norm_key(title: str, company: str, link: str) -> str:
    # Dedupe-Schluessel aus Titel/Firma/Link.
    t = re.sub(r"\W+", "", (title or "").lower())
    c = re.sub(r"\W+", "", (company or "").lower())
    lnk = re.sub(r"[?#].*$", "", (link or "").lower())
    return f"{t}|{c}|{lnk}"


def export_json(rows: List[Job], path: str | None = None) -> None:
    # JSON-Export fuer weitere Verarbeitung.
    out_path = Path(path or Path("data") / "jobs.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for j in rows:
        title = j.title
        company = j.company
        location = j.location
        raw_title = j.raw_title

        if (not company or not location) and (raw_title or title):
            t2, c2, l2 = extract_from_multiline_title(raw_title or title)
            if t2:
                title = t2
            if not company and c2:
                company = c2
            if not location and l2:
                location = l2

        serializable.append(
            {
                "title": title,
                "raw_title": raw_title,
                "company": company,
                "location": location,
                "link": j.link,
                "source": j.source,
                "match": j.match,
                "score": j.score,
                "date": j.date,
                "fit": getattr(j, "fit", ""),
                "application_email": getattr(j, "application_email", ""),
                "contact_name": getattr(j, "contact_name", ""),
            }
        )
    out_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_indeed(
    driver: webdriver.Chrome,
    url: str,
    limit: int | None = 25,
) -> List[Job]:
    # Indeed-Resultate per Selenium auslesen.
    jobs: List[Job] = []
    _get_html(driver, url)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.tapItem"))
        )
    except Exception:
        pass

    cards = driver.find_elements(By.CSS_SELECTOR, "a.tapItem")
    card_items = cards if limit is None else cards[:limit]
    for a in card_items:
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


def _normalize_limit(value: int | None) -> int | None:
    # Limit nur akzeptieren, wenn > 0.
    if value is None:
        return None
    return value if value > 0 else None


def _adapter_pause() -> None:
    # Pause zwischen Adapter-Requests.
    if ADAPTER_REQUEST_DELAY > 0:
        time.sleep(ADAPTER_REQUEST_DELAY)


def _timing_log(label: str, seconds: float, extra: str = "") -> None:
    if not TIMING_ENABLED:
        return
    suffix = f" {extra}" if extra else ""
    job_logger.info(f"timing {label}={seconds:.2f}s{suffix}")


def _retry_backoff_sleep(attempt: int) -> None:
    if REQUESTS_RETRY_BACKOFF_SEC <= 0:
        return
    base = REQUESTS_RETRY_BACKOFF_SEC * (2**max(0, attempt - 1))
    jitter = random.uniform(0, max(0.0, REQUESTS_RETRY_JITTER_SEC))
    time.sleep(base + jitter)


def _normalized_selenium_mode() -> str:
    mode = (SELENIUM_EXECUTION_MODE or "auto").strip().lower()
    if mode in {"process", "thread", "sequential"}:
        return mode
    if os.name == "nt":
        # Windows + ThreadPool + Selenium kann Threads offen halten.
        # Auto waehlt daher bewusst sequential fuer sauberes Prozessende.
        return "sequential"
    return "process"


def collect_jobs(
    limit_per_site: int | None = None,
    max_total: int | None = None,
    sources: list[str] | None = None,
) -> List[Job]:
    total_start = time.perf_counter() if TIMING_ENABLED else 0.0
    run_started = time.monotonic()
    run_deadline = (
        run_started + COLLECT_RUN_DEADLINE_SEC
        if COLLECT_RUN_DEADLINE_SEC > 0
        else None
    )
    deadline_logged = False
    raw_cap = None
    # Hauptsammlung: alle Quellen durchsuchen und filtern.
    # Limits konsolidieren.
    if limit_per_site is None:
        limit_per_site = _normalize_limit(COLLECT_LIMIT_PER_SITE)
    else:
        limit_per_site = _normalize_limit(limit_per_site)

    if max_total is None:
        max_total = _normalize_limit(COLLECT_MAX_TOTAL)
    else:
        max_total = _normalize_limit(max_total)
    if max_total:
        raw_cap = max_total * max(1, COLLECT_RAW_CAP_MULTIPLIER)

    def _deadline_exceeded() -> bool:
        nonlocal deadline_logged
        if run_deadline is None:
            return False
        exceeded = time.monotonic() >= run_deadline
        if exceeded and not deadline_logged:
            deadline_logged = True
            job_logger.warning(
                "Collect-Deadline erreicht (COLLECT_RUN_DEADLINE_SEC=%ss), stoppe Restaufgaben.",
                COLLECT_RUN_DEADLINE_SEC,
            )
        return exceeded

    def _raw_cap_reached() -> bool:
        return bool(raw_cap and len(all_jobs) >= raw_cap)

    # Such-URLs und Query-Terme vorbereiten.
    urls = build_search_urls(config)

    base_keywords = getattr(config, "SEARCH_KEYWORDS", []) or ["IT Support"]
    locations = getattr(config, "SEARCH_LOCATIONS", []) or ["Zuerich"]
    radius_km = getattr(config, "LOCATION_RADIUS_KM", 25)

    query_terms = _dedupe_terms(base_keywords + EXTRA_QUERY_TERMS)
    if EXPAND_QUERY_VARIANTS:
        variants = _dedupe_terms(
            getattr(config, "TITLE_VARIANTS_DE", [])
            + getattr(config, "TITLE_VARIANTS_EN", [])
        )
        for term in variants[:QUERY_VARIANTS_LIMIT]:
            if _normalize_text(term) in {_normalize_text(t) for t in query_terms}:
                continue
            query_terms.append(term)
    if MAX_QUERY_TERMS > 0:
        query_terms = query_terms[:MAX_QUERY_TERMS]

    batched_queries = _batch_terms(
        query_terms,
        max(1, QUERY_BATCH_SIZE),
        QUERY_BATCH_JOINER,
    )
    source_filter = None
    if sources:
        source_filter = {
            _normalize_source_name(s) for s in sources if _normalize_source_name(s)
        }
    empty_cache_ttl_sec = max(0.0, EMPTY_SEARCH_TTL_HOURS * 3600.0)
    empty_cache: dict[str, float] = {}
    empty_cache_updates: dict[str, float] = {}
    empty_cache_skips = 0
    cache_now = time.time()
    if empty_cache_ttl_sec > 0:
        empty_cache = _prune_empty_search_cache(
            _load_empty_search_cache(EMPTY_SEARCH_CACHE_PATH),
            empty_cache_ttl_sec,
            cache_now,
        )

    # Trefferliste und optionaler Selenium-Driver.
    all_jobs: List[Job] = []
    driver = None
    headless = getattr(config, "HEADLESS_MODE", True)
    selenium_init_error: str | None = None

    def _ensure_driver() -> bool:
        nonlocal driver, selenium_init_error
        if selenium_init_error:
            return False
        if driver is None:
            driver_start = time.perf_counter() if TIMING_ENABLED else 0.0
            try:
                driver = _mk_driver(headless=headless)
            except Exception as exc:
                selenium_init_error = str(exc)
                job_logger.warning(
                    "Selenium-Initialisierung fehlgeschlagen; Selenium-Quellen werden uebersprungen: %s",
                    exc,
                )
                return False
            if TIMING_ENABLED:
                _timing_log("driver_init", time.perf_counter() - driver_start)
        return True

    try:
        # Indeed (falls URL vorhanden)
        indeed_url = None
        for k, v in urls.items():
            if "indeed" in k.lower() or "indeed" in v.lower():
                indeed_url = v
                break

        if (
            indeed_url
            and (not ENABLED_SOURCES or "indeed" in ENABLED_SOURCES)
            and "indeed" not in BLOCKED_SOURCES
            and (not source_filter or "indeed" in source_filter)
        ):
            try:
                if not _ensure_driver():
                    raise RuntimeError("Selenium-Driver nicht verfuegbar")
                _adapter_pause()
                adapter_start = time.perf_counter() if TIMING_ENABLED else 0.0
                indeed_jobs = _collect_indeed(
                    driver,
                    indeed_url,
                    limit=limit_per_site,
                )
                all_jobs.extend(indeed_jobs)
                job_logger.info(f"Indeed: {len(indeed_jobs)} Karten gefunden")
                if TIMING_ENABLED:
                    _timing_log(
                        "adapter.indeed",
                        time.perf_counter() - adapter_start,
                        f"count={len(indeed_jobs)}",
                    )
            except Exception as e:
                job_logger.warning(f"Indeed Adapter Fehler: {e}")

        adapter_totals: dict[str, float] = {}
        selenium_adapters = [JobsChAdapter(), JobupAdapter()]
        request_adapters = [
            IctJobsAdapter(),
            ItJobsAdapter(),
            IctCareerAdapter(),
            MyItJobAdapter(),
            SwissDevJobsAdapter(),
            JobScout24Adapter(),
            JobWinnerAdapter(),
            CareerjetAdapter(),
            JobrapidoAdapter(),
            MonsterAdapter(),
            JoraAdapter(),
            JoobleAdapter(),
        ]
        source_counts: dict[str, int] = {}
        known_sources = {
            "indeed",
            "jobs.ch",
            "jobup.ch",
            "jobscout24",
            "jobwinner",
            "ictjobs.ch",
            "ictcareer.ch",
            "itjobs.ch",
            "myitjob.ch",
            "swissdevjobs.ch",
            "careerjet",
            "jobrapido",
            "monster",
            "jora",
            "jooble",
        }
        selenium_source_names = {
            _normalize_source_name(adapter.source) for adapter in selenium_adapters
        }
        request_source_names = {
            _normalize_source_name(adapter.source) for adapter in request_adapters
        }
        if ENABLED_SOURCES:
            unknown = ENABLED_SOURCES - known_sources
            if unknown:
                job_logger.warning(
                    "ENABLED_SOURCES ohne Adapter: %s",
                    ", ".join(sorted(unknown)),
                )
            blocked = ENABLED_SOURCES & BLOCKED_SOURCES
            if blocked:
                job_logger.info(
                    "ENABLED_SOURCES blockiert: %s",
                    ", ".join(sorted(blocked)),
                )

        def _allowed(adapter) -> bool:
            source = _normalize_source_name(adapter.source)
            if source in BLOCKED_SOURCES:
                return False
            if ENABLED_SOURCES and source not in ENABLED_SOURCES:
                return False
            if source_filter and source not in source_filter:
                return False
            return True

        selenium_adapters = [a for a in selenium_adapters if _allowed(a)]
        request_adapters = [a for a in request_adapters if _allowed(a)]
        requested_sources = (
            source_filter if source_filter is not None else set(ENABLED_SOURCES)
        )
        if not requested_sources:
            requested_sources = known_sources
        if not selenium_adapters and requested_sources & selenium_source_names:
            job_logger.warning(
                "Keine Selenium-Adapter aktiv (ENABLED_SOURCES/BLOCKED_SOURCES prüfen)."
            )
        if not request_adapters and requested_sources & request_source_names:
            job_logger.warning(
                "Keine Request-Adapter aktiv (ENABLED_SOURCES/BLOCKED_SOURCES prüfen)."
            )

        request_tasks: list[tuple[object, str, str]] = []
        request_futures: dict = {}
        request_executor: ThreadPoolExecutor | None = None
        request_local = threading.local()

        def _get_request_session() -> requests.Session:
            session = getattr(request_local, "session", None)
            if session is None:
                session = requests.Session()
                request_local.session = session
            return session

        def _run_request_search(adapter, query: str, loc: str):
            if _deadline_exceeded():
                return adapter.source, query, loc, [], 0.0
            session = _get_request_session()
            started = time.perf_counter()
            attempts = max(1, REQUESTS_ADAPTER_RETRIES + 1)
            last_exc: Exception | None = None
            rows = []
            for attempt in range(1, attempts + 1):
                try:
                    rows = adapter.search(
                        None,
                        query=query,
                        location=loc,
                        radius_km=radius_km,
                        limit=limit_per_site,
                        session=session,
                        timeout=float(REQUESTS_ADAPTER_TIMEOUT),
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt >= attempts or _deadline_exceeded():
                        break
                    try:
                        session.close()
                    except Exception:
                        pass
                    request_local.session = None
                    session = _get_request_session()
                    _retry_backoff_sleep(attempt)
            if last_exc is not None:
                raise last_exc
            duration = time.perf_counter() - started
            return adapter.source, query, loc, rows, duration

        def _append_rows(
            adapter_source: str,
            rows,
            query: str,
            loc: str,
        ) -> int:
            converted = 0
            for r in rows:
                if isinstance(r, dict):
                    title = r.get("title") or ""
                    link = r.get("link") or ""
                    if not title or not link:
                        continue
                    raw_title = r.get("raw_title") or title
                    company = r.get("company") or ""
                    location = r.get("location") or ""
                    date = r.get("date") or ""
                else:
                    if not isinstance(r, (CHJobRow, ExtraJobRow)):
                        if not getattr(r, "title", None) or not getattr(
                            r, "link", None
                        ):
                            continue
                    title = r.title
                    link = r.link
                    raw_title = getattr(r, "raw_title", "") or title
                    company = getattr(r, "company", "")
                    location = getattr(r, "location", "")
                    date = getattr(r, "date", "") or ""

                score, label = _score_title(title)
                all_jobs.append(
                    Job(
                        raw_title=raw_title,
                        title=title,
                        company=company,
                        location=location,
                        link=link,
                        source=adapter_source,
                        score=score,
                        match=label,
                        date=date,
                    )
                )
                converted += 1
                if _raw_cap_reached():
                    break

            job_logger.info(
                f"{adapter_source}: {converted} Roh-Treffer "
                f"(query='{query}', loc='{loc}')"
            )
            source_counts[adapter_source] = (
                source_counts.get(adapter_source, 0) + converted
            )
            return converted

        def _handle_request_result(
            source: str,
            query: str,
            loc: str,
            rows,
            duration: float,
        ) -> None:
            converted = _append_rows(source, rows, query, loc)
            if empty_cache_ttl_sec > 0 and converted == 0:
                key = _empty_cache_key(source, query, loc, radius_km)
                empty_cache_updates[key] = time.time()
            adapter_totals[source.lower()] = (
                adapter_totals.get(source.lower(), 0.0) + duration
            )

        if request_adapters:
            for adapter in request_adapters:
                if _deadline_exceeded() or _raw_cap_reached():
                    break
                source = _normalize_source_name(adapter.source)
                source_queries = (
                    batched_queries
                    if QUERY_BATCH_SIZE > 1 and source in QUERY_BATCH_SOURCES
                    else query_terms
                )
                source_locations = (
                    locations if getattr(adapter, "supports_location", True) else [""]
                )
                for query in source_queries:
                    if _deadline_exceeded() or _raw_cap_reached():
                        break
                    for loc in source_locations:
                        if _deadline_exceeded() or _raw_cap_reached():
                            break
                        if empty_cache_ttl_sec > 0:
                            key = _empty_cache_key(source, query, loc, radius_km)
                            if key in empty_cache:
                                empty_cache_skips += 1
                                continue
                        request_tasks.append((adapter, query, loc))

            if request_tasks and REQUESTS_ADAPTER_WORKERS > 1:
                max_workers = min(
                    max(1, REQUESTS_ADAPTER_WORKERS),
                    len(request_tasks),
                )
                request_executor = ThreadPoolExecutor(max_workers=max_workers)
                for adapter, query, loc in request_tasks:
                    future = request_executor.submit(
                        _run_request_search,
                        adapter,
                        query,
                        loc,
                    )
                    request_futures[future] = (adapter, query, loc)

        selenium_workers = max(1, SELENIUM_WORKERS)
        if selenium_workers > SELENIUM_WORKERS_RECOMMENDED_MAX:
            job_logger.warning(
                "SELENIUM_WORKERS=%s kann instabil sein (empfohlen max %s).",
                selenium_workers,
                SELENIUM_WORKERS_RECOMMENDED_MAX,
            )

        # Selenium-Adapter: optional parallelisieren (multiprocessing).
        if selenium_adapters:
            selenium_tasks: list[tuple[str, str, str]] = []
            for adapter in selenium_adapters:
                if _deadline_exceeded() or _raw_cap_reached():
                    break
                source = _normalize_source_name(adapter.source)
                for query in query_terms:
                    if _deadline_exceeded() or _raw_cap_reached():
                        break
                    for loc in locations:
                        if _deadline_exceeded() or _raw_cap_reached():
                            break
                        if empty_cache_ttl_sec > 0:
                            key = _empty_cache_key(source, query, loc, radius_km)
                            if key in empty_cache:
                                empty_cache_skips += 1
                                continue
                        selenium_tasks.append((source, query, loc))

            selenium_mode = _normalized_selenium_mode()
            if selenium_tasks:
                job_logger.info(
                    "Selenium-Plan: %s Aufgaben fuer %s Quellen, %s Suchbegriffe, %s Orte (Modus=%s).",
                    len(selenium_tasks),
                    len(selenium_adapters),
                    len(query_terms),
                    len(locations),
                    selenium_mode,
                )
                if SELENIUM_EXECUTION_MODE == "auto" and os.name == "nt":
                    job_logger.info(
                        "SELENIUM_EXECUTION_MODE=auto -> sequential (Windows Stabilitaet)."
                    )
                if not _ensure_driver():
                    job_logger.warning(
                        "Selenium-Quellen werden uebersprungen: Driver konnte nicht gestartet werden."
                    )
                    selenium_tasks = []
                    selenium_adapters = []

            if selenium_tasks and selenium_workers > 1 and selenium_mode != "sequential":
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None

                worker_count = min(selenium_workers, len(selenium_tasks))
                batches = _split_tasks(selenium_tasks, worker_count)

                def _consume_selenium_result(result: dict) -> None:
                    for error in result.get("errors", []):
                        job_logger.warning("Selenium Worker Fehler: %s", error)
                    for payload in result.get("results", []):
                        source = _normalize_source_name(payload.get("source", "unknown"))
                        query = payload.get("query", "")
                        loc = payload.get("loc", "")
                        rows = payload.get("rows", [])
                        duration = float(payload.get("duration", 0.0) or 0.0)
                        converted = _append_rows(source, rows, query, loc)
                        if empty_cache_ttl_sec > 0 and converted == 0:
                            key = _empty_cache_key(source, query, loc, radius_km)
                            empty_cache_updates[key] = time.time()
                        adapter_totals[source] = adapter_totals.get(source, 0.0) + duration

                def _run_selenium_parallel(use_process_pool: bool) -> None:
                    ex = None
                    futures = []
                    try:
                        if use_process_pool:
                            ctx = mp.get_context("spawn")
                            ex = ProcessPoolExecutor(max_workers=worker_count, mp_context=ctx)
                        else:
                            ex = ThreadPoolExecutor(max_workers=worker_count)
                        futures = [
                            ex.submit(
                                _selenium_worker,
                                batch,
                                radius_km,
                                limit_per_site,
                                headless,
                            )
                            for batch in batches
                        ]
                        timeout = SELENIUM_FUTURE_TIMEOUT_SEC if SELENIUM_FUTURE_TIMEOUT_SEC > 0 else None
                        for future in as_completed(futures, timeout=timeout):
                            if _deadline_exceeded() or _raw_cap_reached():
                                break
                            result = future.result()
                            _consume_selenium_result(result)
                    except FuturesTimeoutError:
                        job_logger.warning(
                            "Selenium-Parallellauf Timeout nach %ss.",
                            SELENIUM_FUTURE_TIMEOUT_SEC,
                        )
                    finally:
                        for future in futures:
                            if not future.done():
                                future.cancel()
                        if ex is not None:
                            try:
                                ex.shutdown(wait=False, cancel_futures=True)
                            except TypeError:
                                ex.shutdown(wait=False)

                if selenium_mode == "sequential":
                    for batch in batches:
                        if _deadline_exceeded() or _raw_cap_reached():
                            break
                        try:
                            _consume_selenium_result(
                                _selenium_worker(
                                    batch, radius_km, limit_per_site, headless
                                )
                            )
                        except Exception as exc:
                            job_logger.warning(
                                "Selenium Sequential Fehler: %s", exc
                            )
                elif selenium_mode == "process":
                    try:
                        _run_selenium_parallel(use_process_pool=True)
                    except Exception as exc:
                        job_logger.warning(
                            "Selenium ProcessPool Fehler (%s), fallback auf sequential.",
                            exc,
                        )
                        for batch in batches:
                            if _deadline_exceeded() or _raw_cap_reached():
                                break
                            try:
                                _consume_selenium_result(
                                    _selenium_worker(
                                        batch, radius_km, limit_per_site, headless
                                    )
                                )
                            except Exception as seq_exc:
                                job_logger.warning(
                                    "Selenium Sequential Fallback Fehler: %s", seq_exc
                                )
                else:
                    try:
                        _run_selenium_parallel(use_process_pool=False)
                    except Exception as exc:
                        job_logger.warning("Selenium ThreadPool Fehler: %s", exc)
            elif selenium_tasks:
                for adapter in selenium_adapters:
                    if _deadline_exceeded() or _raw_cap_reached():
                        break
                    adapter_start = time.perf_counter() if TIMING_ENABLED else 0.0
                    for query in query_terms:
                        if _deadline_exceeded() or _raw_cap_reached():
                            break
                        for loc in locations:
                            if _deadline_exceeded() or _raw_cap_reached():
                                break
                            if empty_cache_ttl_sec > 0:
                                key = _empty_cache_key(
                                    _normalize_source_name(adapter.source),
                                    query,
                                    loc,
                                    radius_km,
                                )
                                if key in empty_cache:
                                    empty_cache_skips += 1
                                    continue
                            try:
                                _adapter_pause()
                                rows = adapter.search(
                                    driver,
                                    query=query,
                                    location=loc,
                                    radius_km=radius_km,
                                    limit=limit_per_site,
                                )

                                converted = _append_rows(
                                    adapter.source,
                                    rows,
                                    query,
                                    loc,
                                )
                                if empty_cache_ttl_sec > 0 and converted == 0:
                                    key = _empty_cache_key(
                                        _normalize_source_name(adapter.source),
                                        query,
                                        loc,
                                        radius_km,
                                    )
                                    empty_cache_updates[key] = time.time()

                                if _raw_cap_reached():
                                    break
                            except Exception as e:
                                job_logger.warning(
                                    f"Adapter {adapter.source} Fehler "
                                    f"(query='{query}', loc='{loc}'): {e}"
                                )
                        if _raw_cap_reached():
                            break
                    if TIMING_ENABLED:
                        adapter_totals[_normalize_source_name(adapter.source)] = (
                            adapter_totals.get(_normalize_source_name(adapter.source), 0.0)
                            + (time.perf_counter() - adapter_start)
                        )

        if request_executor:
            timeout = REQUESTS_FUTURE_TIMEOUT_SEC if REQUESTS_FUTURE_TIMEOUT_SEC > 0 else None
            try:
                for future in as_completed(request_futures, timeout=timeout):
                    if _deadline_exceeded() or _raw_cap_reached():
                        break
                    adapter, query, loc = request_futures[future]
                    try:
                        source, query, loc, rows, duration = future.result()
                    except Exception as e:
                        job_logger.warning(
                            f"Adapter {adapter.source} Fehler "
                            f"(query='{query}', loc='{loc}'): {e}"
                        )
                        continue
                    _handle_request_result(source, query, loc, rows, duration)
            except FuturesTimeoutError:
                job_logger.warning(
                    "Request-Adapter Timeout nach %ss; verbleibende Aufgaben werden abgebrochen.",
                    REQUESTS_FUTURE_TIMEOUT_SEC,
                )
            finally:
                for future in request_futures:
                    if not future.done():
                        future.cancel()
                try:
                    request_executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    request_executor.shutdown(wait=False)
        elif request_tasks:
            for adapter, query, loc in request_tasks:
                if _deadline_exceeded() or _raw_cap_reached():
                    break
                try:
                    source, query, loc, rows, duration = _run_request_search(
                        adapter,
                        query,
                        loc,
                    )
                except Exception as e:
                    job_logger.warning(
                        f"Adapter {adapter.source} Fehler "
                        f"(query='{query}', loc='{loc}'): {e}"
                    )
                    continue
                _handle_request_result(source, query, loc, rows, duration)

        if source_counts:
            summary = ", ".join(
                f"{source}={count}" for source, count in sorted(source_counts.items())
            )
            job_logger.info("Adapter Summary: %s", summary)
            if ENABLED_SOURCES:
                zero_hits = [
                    src
                    for src in sorted(ENABLED_SOURCES)
                    if src in known_sources and source_counts.get(src, 0) == 0
                ]
                if zero_hits:
                    job_logger.info(
                        "ENABLED_SOURCES ohne Treffer (dieser Lauf): %s",
                        ", ".join(zero_hits),
                    )

        if TIMING_ENABLED and adapter_totals:
            for source, seconds in sorted(adapter_totals.items()):
                _timing_log(f"adapter.{source}", seconds)

        # Optional: eigene Karriere-Seiten scannen.
        if COMPANY_CAREERS_ENABLED and COMPANY_CAREER_URLS:
            try:
                company_jobs = _collect_company_careers(
                    COMPANY_CAREER_URLS, COMPANY_CAREER_NAMES
                )
                all_jobs.extend(company_jobs)
                job_logger.info(f"company-site: {len(company_jobs)} Roh-Treffer")
            except Exception as e:
                job_logger.warning(f"Career-Scan Fehler: {e}")

    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass

    # Dedupe / Blacklist / Category filter / Location boost
    seen = set()
    unique: List[Job] = []
    search_locs = locations
    detail_scans = 0
    contact_scans = 0
    detail_scan_time = 0.0
    contact_scan_time = 0.0
    include_scans = 0
    include_scan_time = 0.0
    transit_enabled = (
        TRANSIT_ENABLED and bool(TRANSIT_ORIGIN) and TRANSIT_MAX_MINUTES > 0
    )
    filter_stats: dict[str, int] = {}
    if FILTER_STATS:
        filter_stats["total"] = len(all_jobs)

    def _bump(key: str) -> None:
        if FILTER_STATS:
            filter_stats[key] = filter_stats.get(key, 0) + 1

    # Alle Treffer filtern, anreichern und bewerten.
    for j in all_jobs:
        # Normalize jobs.ch/jobup multi-line titles into fields
        if (not j.company or not j.location) and (j.title or j.raw_title):
            t2, c2, l2 = extract_from_multiline_title(j.raw_title or j.title)
            if t2:
                j.title = t2
            if not j.company and c2:
                j.company = c2
            if not j.location and l2:
                j.location = l2

        is_remote = _is_remote(j)

        if is_remote and not ALLOW_REMOTE:
            _bump("remote_blocked")
            continue

        if transit_enabled and not is_remote and not j.location and j.link:
            detail_location = _detail_page_location(
                j.link,
                timeout=max(DETAILS_INCLUDE_TIMEOUT, DETAILS_BLOCKLIST_TIMEOUT),
                max_bytes=max(DETAILS_INCLUDE_MAX_BYTES, DETAILS_BLOCKLIST_MAX_BYTES),
            )
            if detail_location:
                j.location = detail_location

        local_match = _is_local(j, search_locs) if search_locs else True
        allowed_match = (
            _is_allowed_location(j, ALLOWED_LOCATIONS) if ALLOWED_LOCATIONS else True
        )
        hard_allowed_match = (
            _is_allowed_location(j, HARD_ALLOWED_LOCATIONS)
            if HARD_ALLOWED_LOCATIONS
            else True
        )

        if HARD_ALLOWED_LOCATIONS and not hard_allowed_match:
            _bump("hard_location")
            continue

        if transit_enabled and not is_remote:
            if j.location:
                transit_minutes = _get_transit_minutes(
                    TRANSIT_ORIGIN, j.location, TRANSIT_DATE, TRANSIT_TIME
                )
                if (
                    transit_minutes is None
                    or transit_minutes > TRANSIT_MAX_MINUTES
                ):
                    _bump("transit_blocked")
                    continue
            else:
                if not (local_match or allowed_match):
                    _bump("location_unknown")
                    continue
        elif STRICT_LOCATION_FILTER:
            if search_locs and not local_match:
                _bump("local_mismatch")
                continue
            if ALLOWED_LOCATIONS and not allowed_match:
                _bump("allowed_mismatch")
                continue

        if not _has_required_keywords(j, INCLUDE_KEYWORDS):
            if (
                DETAILS_INCLUDE_SCAN
                and j.link
                and include_scans < DETAILS_INCLUDE_MAX_JOBS
            ):
                if j.link not in DETAILS_INCLUDE_CACHE:
                    include_scans += 1
                scan_start = time.perf_counter() if TIMING_ENABLED else 0.0
                if _detail_page_has_required_terms(j.link, INCLUDE_KEYWORDS):
                    if TIMING_ENABLED:
                        include_scan_time += time.perf_counter() - scan_start
                else:
                    if TIMING_ENABLED:
                        include_scan_time += time.perf_counter() - scan_start
                    _bump("include_keywords")
                    continue
            else:
                _bump("include_keywords")
                continue

        if (j.company or "").lower() in BLACKLIST:
            _bump("company_blacklist")
            continue
        if _has_blocked_keywords(j, BLOCKLIST_TERMS):
            _bump("blocked_keywords")
            continue

        if (
            ALLOW_AGGREGATORS
            and AGGREGATOR_VALIDATE_LINKS
            and j.source in AGGREGATOR_SOURCES
            and not _aggregator_link_ok(j.link)
        ):
            _bump("aggregator_link")
            continue

        if j.source in ("jobs.ch", "jobup.ch"):
            link_has_digit = bool(re.search(r"\d", j.link))
            tail = "/".join(j.link.rstrip("/").split("/")[-2:])
            is_category = "stellenangebote" in tail and "detail" not in tail
            if (not link_has_digit) or is_category:
                _bump("category_link")
                continue

        key = _norm_key(j.title, j.company, j.link)
        if key in seen:
            _bump("duplicate")
            continue
        # Detailseiten auf Blocklist und Kontakte scannen.
        if (
            DETAILS_BLOCKLIST_SCAN
            and j.link
            and detail_scans < DETAILS_BLOCKLIST_MAX_JOBS
        ):
            if _is_skipped_detail_domain(j.link):
                DETAILS_BLOCKLIST_CACHE[j.link] = False
            else:
                if j.link not in DETAILS_BLOCKLIST_CACHE:
                    detail_scans += 1
                scan_start = time.perf_counter() if TIMING_ENABLED else 0.0
                if _detail_page_has_blocked_terms(j.link, BLOCKLIST_TERMS):
                    if TIMING_ENABLED:
                        detail_scan_time += time.perf_counter() - scan_start
                    _bump("detail_blocklist")
                    continue
                if TIMING_ENABLED:
                    detail_scan_time += time.perf_counter() - scan_start
        seen.add(key)

        if (
            DETAILS_CONTACT_SCAN
            and j.link
            and contact_scans < DETAILS_CONTACT_MAX_JOBS
        ):
            if j.link not in DETAILS_CONTACT_CACHE:
                contact_scans += 1
            scan_start = time.perf_counter() if TIMING_ENABLED else 0.0
            email, name = extract_application_contact(j.link)
            if TIMING_ENABLED:
                contact_scan_time += time.perf_counter() - scan_start
            if email:
                j.application_email = email
            if name:
                j.contact_name = name

        # Score-Booster (Ort/Commute) und Match-Klasse setzen.
        j.score += _location_boost(j.location, search_locs)
        if ALLOWED_LOCATIONS and allowed_match:
            j.score += ALLOWED_LOCATION_BOOST
        commute_min = _commute_minutes_for(j, COMMUTE_MINUTES)
        if commute_min is not None:
            j.commute_min = commute_min
            if COMMUTE_PENALTY and commute_min >= COMMUTE_PENALTY_MIN:
                j.score = max(0, j.score - COMMUTE_PENALTY)

        if j.score >= 20:
            j.match = "exact"
        elif j.score >= 10:
            j.match = "good"
        else:
            j.match = j.match or "weak"

        if AUTO_FIT_ENABLED:
            j.fit = compute_fit(j.match, j.score, MIN_SCORE_APPLY)

        unique.append(j)
        _bump("kept")

    if TIMING_ENABLED:
        if detail_scans:
            _timing_log("detail_scan", detail_scan_time, f"count={detail_scans}")
        if contact_scans:
            _timing_log("contact_scan", contact_scan_time, f"count={contact_scans}")
        if include_scans:
            _timing_log("include_scan", include_scan_time, f"count={include_scans}")
    if empty_cache_ttl_sec > 0:
        if empty_cache_updates:
            empty_cache.update(empty_cache_updates)
        empty_cache = _prune_empty_search_cache(
            empty_cache,
            empty_cache_ttl_sec,
            time.time(),
        )
        _save_empty_search_cache(EMPTY_SEARCH_CACHE_PATH, empty_cache)
        job_logger.info(
            "empty-cache "
            f"skip={empty_cache_skips} add={len(empty_cache_updates)} "
            f"keep={len(empty_cache)}"
        )
    if FILTER_STATS:
        kept = filter_stats.get("kept", 0)
        total = filter_stats.get("total", len(all_jobs))
        drops = {
            k: v
            for k, v in filter_stats.items()
            if k not in {"total", "kept"} and v
        }
        drop_summary = ", ".join(
            f"{k}={v}"
            for k, v in sorted(drops.items(), key=lambda item: item[1], reverse=True)
        )
        if drop_summary:
            job_logger.info(
                "filter-stats total=%s kept=%s drops=%s",
                total,
                kept,
                drop_summary,
            )
        else:
            job_logger.info("filter-stats total=%s kept=%s", total, kept)

    unique.sort(key=lambda x: x.score, reverse=True)
    if max_total:
        if TIMING_ENABLED:
            _timing_log("collect_jobs_total", time.perf_counter() - total_start)
        return unique[:max_total]
    if TIMING_ENABLED:
        _timing_log("collect_jobs_total", time.perf_counter() - total_start)
    return unique


def format_jobs_plain(jobs: List[Job], top: int = 20) -> str:
    # Textausgabe fuer CLI.
    out: List[str] = []
    for i, j in enumerate(jobs[:top], 1):
        if (not j.company or not j.location) and ("\n" in (j.raw_title or "") or "Arbeitsort" in (j.raw_title or "")):
            t2, c2, l2 = extract_from_multiline_title(j.raw_title)
            if t2:
                j.title = t2
            if not j.company and c2:
                j.company = c2
            if not j.location and l2:
                j.location = l2
        out.append(
            f"{i:02d}. [{j.match:^5}] {j.title} - {j.company} - {j.location}\n"
            f"    {j.link}"
        )
    return "\n".join(out) if out else "Keine Treffer."


def export_csv(rows: List[Job], path: str | None = None) -> None:
    # CSV-Export fuer schnelle Sichtung.
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
