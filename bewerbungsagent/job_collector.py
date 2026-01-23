from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
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
from webdriver_manager.chrome import ChromeDriverManager

from .config import config
from .logger import job_logger
from .job_adapters_ch import JobsChAdapter, JobupAdapter, JobRow as CHJobRow
from .job_adapters_extra import (
    CareerjetAdapter,
    JoobleAdapter,
    JoraAdapter,
    JobrapidoAdapter,
    JobScout24Adapter,
    JobWinnerAdapter,
    MonsterAdapter,
    ExtraJobRow,
)
from .job_query_builder import build_search_urls
from .job_text_utils import extract_from_multiline_title


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
    opts.add_argument("--window-size=1200,2000")
    opts.add_argument("--user-agent=Bewerbungsagent/1.0 (+job-collector)")
    opts.add_argument("--lang=de-CH,de;q=0.9")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-logging")
    opts.add_argument("--disable-features=WebGPU")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

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
SELENIUM_WORKERS = int(os.getenv("SELENIUM_WORKERS", "1") or 1)
REQUESTS_ADAPTER_WORKERS = int(os.getenv("REQUESTS_ADAPTER_WORKERS", "6") or 6)
REQUESTS_ADAPTER_TIMEOUT = float(os.getenv("REQUESTS_ADAPTER_TIMEOUT", "15") or 15)
EMPTY_SEARCH_TTL_HOURS = float(os.getenv("EMPTY_SEARCH_TTL_HOURS", "0") or 0)
EMPTY_SEARCH_CACHE_PATH = Path(
    os.getenv("EMPTY_SEARCH_CACHE_PATH", "generated/empty_search_cache.json")
)
TIMING_ENABLED = str(os.getenv("TIMING_ENABLED", "false")).lower() in TRUTHY
SELENIUM_WORKERS_RECOMMENDED_MAX = 3
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
    KEYWORD_BLACKLIST | LANGUAGE_BLOCKLIST | REQUIREMENTS_BLOCKLIST
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
    x.strip().lower()
    for x in (os.getenv("DISABLED_SOURCES", "") or "").split(",")
    if x.strip()
}
BLOCKED_SOURCES = DISABLED_SOURCES | (
    set() if ALLOW_AGGREGATORS else AGGREGATOR_SOURCES
)
ENABLED_SOURCES = {
    x.strip().lower()
    for x in (
        os.getenv(
            "ENABLED_SOURCES",
            "jobs.ch,jobup.ch,jobscout24,indeed,monster",
        )
        or "jobs.ch,jobup.ch,jobscout24,indeed,monster"
    ).split(",")
    if x.strip()
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
    x.strip().lower()
    for x in (os.getenv("QUERY_BATCH_SOURCES", "") or "").split(",")
    if x.strip()
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

# In-Memory-Caches fuer Detail-Scans und Checks.
DETAILS_BLOCKLIST_CACHE: dict[str, bool] = {}
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
        [job.title or "", job.raw_title or "", job.company or "", job.location or ""]
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


def _get_transit_minutes(
    origin: str, destination: str, date: str, time_str: str
) -> int | None:
    # Opendata Transit-API abfragen (mit Cache).
    key = (origin, destination, date, time_str)
    if key in TRANSIT_CACHE:
        return TRANSIT_CACHE[key]
    params = {"from": origin, "to": destination, "limit": 1}
    if date:
        params["date"] = date
    if time_str:
        params["time"] = time_str
    try:
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
    if _is_skipped_detail_domain(url):
        DETAILS_BLOCKLIST_CACHE[url] = False
        return False
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Bewerbungsagent/1.0 (+detail-scan)"},
            timeout=DETAILS_BLOCKLIST_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.text or ""
        if DETAILS_BLOCKLIST_MAX_BYTES and len(text) > DETAILS_BLOCKLIST_MAX_BYTES:
            text = text[:DETAILS_BLOCKLIST_MAX_BYTES]
        text = _SCRIPT_STYLE_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
        normalized = _normalize_text(text)
        blocked_found = _contains_blocked_terms(normalized, blocked)
        DETAILS_BLOCKLIST_CACHE[url] = blocked_found
        return blocked_found
    except Exception as e:
        job_logger.warning(f"Detail-Scan Fehler ({url}): {e}")
        DETAILS_BLOCKLIST_CACHE[url] = False
        return False


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


def collect_jobs(
    limit_per_site: int | None = None,
    max_total: int | None = None,
) -> List[Job]:
    total_start = time.perf_counter() if TIMING_ENABLED else 0.0
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

    def _ensure_driver():
        nonlocal driver
        if driver is None:
            driver_start = time.perf_counter() if TIMING_ENABLED else 0.0
            driver = _mk_driver(headless=headless)
            if TIMING_ENABLED:
                _timing_log("driver_init", time.perf_counter() - driver_start)

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
        ):
            try:
                _ensure_driver()
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
            "careerjet",
            "jobrapido",
            "monster",
            "jora",
            "jooble",
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
            source = adapter.source.lower()
            if source in BLOCKED_SOURCES:
                return False
            if ENABLED_SOURCES and source not in ENABLED_SOURCES:
                return False
            return True

        selenium_adapters = [a for a in selenium_adapters if _allowed(a)]
        request_adapters = [a for a in request_adapters if _allowed(a)]
        if not selenium_adapters:
            job_logger.warning(
                "Keine Selenium-Adapter aktiv (ENABLED_SOURCES/BLOCKED_SOURCES prüfen)."
            )
        if not request_adapters:
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
            session = _get_request_session()
            started = time.perf_counter()
            rows = adapter.search(
                None,
                query=query,
                location=loc,
                radius_km=radius_km,
                limit=limit_per_site,
                session=session,
                timeout=float(REQUESTS_ADAPTER_TIMEOUT),
            )
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
                if max_total and len(all_jobs) >= max_total * 2:
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
                source = adapter.source.lower()
                source_queries = (
                    batched_queries
                    if QUERY_BATCH_SIZE > 1 and source in QUERY_BATCH_SOURCES
                    else query_terms
                )
                for query in source_queries:
                    for loc in locations:
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
                source = adapter.source.lower()
                for query in query_terms:
                    for loc in locations:
                        if empty_cache_ttl_sec > 0:
                            key = _empty_cache_key(source, query, loc, radius_km)
                            if key in empty_cache:
                                empty_cache_skips += 1
                                continue
                        selenium_tasks.append((source, query, loc))

            if selenium_tasks and selenium_workers > 1:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None

                worker_count = min(selenium_workers, len(selenium_tasks))
                ctx = mp.get_context("spawn")
                batches = _split_tasks(selenium_tasks, worker_count)
                with ProcessPoolExecutor(
                    max_workers=worker_count,
                    mp_context=ctx,
                ) as ex:
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
                    for future in as_completed(futures):
                        result = future.result()
                        for error in result.get("errors", []):
                            job_logger.warning("Selenium Worker Fehler: %s", error)
                        for payload in result.get("results", []):
                            source = payload.get("source", "unknown")
                            query = payload.get("query", "")
                            loc = payload.get("loc", "")
                            rows = payload.get("rows", [])
                            duration = float(payload.get("duration", 0.0) or 0.0)
                            converted = _append_rows(source, rows, query, loc)
                            if empty_cache_ttl_sec > 0 and converted == 0:
                                key = _empty_cache_key(source, query, loc, radius_km)
                                empty_cache_updates[key] = time.time()
                            adapter_totals[source.lower()] = (
                                adapter_totals.get(source.lower(), 0.0) + duration
                            )
            elif selenium_tasks:
                _ensure_driver()
                for adapter in selenium_adapters:
                    adapter_start = time.perf_counter() if TIMING_ENABLED else 0.0
                    for query in query_terms:
                        for loc in locations:
                            if empty_cache_ttl_sec > 0:
                                key = _empty_cache_key(
                                    adapter.source.lower(),
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
                                        adapter.source.lower(),
                                        query,
                                        loc,
                                        radius_km,
                                    )
                                    empty_cache_updates[key] = time.time()

                                if max_total and len(all_jobs) >= max_total * 2:
                                    break
                            except Exception as e:
                                job_logger.warning(
                                    f"Adapter {adapter.source} Fehler "
                                    f"(query='{query}', loc='{loc}'): {e}"
                                )
                        if max_total and len(all_jobs) >= max_total * 2:
                            break
                    if TIMING_ENABLED:
                        adapter_totals[adapter.source.lower()] = (
                            adapter_totals.get(adapter.source.lower(), 0.0)
                            + (time.perf_counter() - adapter_start)
                        )

        if request_executor:
            for future in as_completed(request_futures):
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
            request_executor.shutdown(wait=True)
        elif request_tasks:
            for adapter, query, loc in request_tasks:
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
    transit_enabled = (
        TRANSIT_ENABLED and bool(TRANSIT_ORIGIN) and TRANSIT_MAX_MINUTES > 0
    )

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

        local_match = _is_local(j, search_locs) if search_locs else True
        allowed_match = (
            _is_allowed_location(j, ALLOWED_LOCATIONS) if ALLOWED_LOCATIONS else True
        )
        hard_allowed_match = (
            _is_allowed_location(j, HARD_ALLOWED_LOCATIONS)
            if HARD_ALLOWED_LOCATIONS
            else True
        )
        is_remote = _is_remote(j)

        if is_remote and not ALLOW_REMOTE:
            continue

        if HARD_ALLOWED_LOCATIONS and not hard_allowed_match:
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
                    continue
            else:
                if STRICT_LOCATION_FILTER and not (local_match or allowed_match):
                    continue
        elif STRICT_LOCATION_FILTER:
            if search_locs and not local_match:
                continue
            if ALLOWED_LOCATIONS and not allowed_match:
                continue

        if not _has_required_keywords(j, INCLUDE_KEYWORDS):
            continue

        if (j.company or "").lower() in BLACKLIST:
            continue
        if _has_blocked_keywords(j, BLOCKLIST_TERMS):
            continue

        if (
            ALLOW_AGGREGATORS
            and AGGREGATOR_VALIDATE_LINKS
            and j.source in AGGREGATOR_SOURCES
            and not _aggregator_link_ok(j.link)
        ):
            continue

        if j.source in ("jobs.ch", "jobup.ch"):
            link_has_digit = bool(re.search(r"\d", j.link))
            tail = "/".join(j.link.rstrip("/").split("/")[-2:])
            is_category = "stellenangebote" in tail and "detail" not in tail
            if (not link_has_digit) or is_category:
                continue

        key = _norm_key(j.title, j.company, j.link)
        if key in seen:
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

    if TIMING_ENABLED:
        if detail_scans:
            _timing_log("detail_scan", detail_scan_time, f"count={detail_scans}")
        if contact_scans:
            _timing_log("contact_scan", contact_scan_time, f"count={contact_scans}")
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
