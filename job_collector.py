from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Tuple
import csv
import os
import re
import json
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
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
    fit: str = ""


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


def compute_fit(match: str, score: int, min_score_apply: int) -> str:
    m = (match or "").lower()
    if m in {"exact", "good"} and score >= min_score_apply:
        return "OK"
    return "DECISION"


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


def _normalize_line(line: str) -> str:
    line = re.sub(r"^\s*\d+\.\s*\[[^\]]+\]\s*", "", line)
    return line.strip().strip('"').strip()


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    if _LABEL_RE.search(line):
        return True
    if _RELDATE_INLINE_RE.search(line):
        return True
    return False


def _extract_from_multiline_title(raw_title: str) -> Tuple[str, str, str]:
    """
    Robustere Heuristik f\u00fcr jobs.ch/jobup title-Blocks:
    - title enth\u00e4lt Zeit, Jobtitel, Labels, Ort, Firma.
    - Wir filtern Labels/relative Zeiten.
    - Jobtitel = erste non-noise Zeile.
    - Firma = letzte non-noise Zeile mit Rechtsform-Hint, sonst letzte non-noise Zeile.
    - Ort = Zeile nach "Arbeitsort:" falls vorhanden, sonst erste non-noise Zeile mit City-Hint.
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


def _normalize_text(value: str) -> str:
    text = (value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ß", "ss")
    text = text.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_terms(items: set[str]) -> set[str]:
    return {_normalize_text(x) for x in items if x}


def _dedupe_terms(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


TRUTHY = {"1", "true", "t", "y", "yes", "ja", "j"}
EXPORT_CSV = str(os.getenv("EXPORT_CSV", "true")).lower() in TRUTHY
EXPORT_CSV_PATH = os.getenv("EXPORT_CSV_PATH", "generated/jobs_latest.csv")
MIN_SCORE_MAIL = int(os.getenv("MIN_SCORE_MAIL", "2") or 2)
LOCATION_BOOST_KM = int(os.getenv("LOCATION_BOOST_KM", "15") or 15)
STRICT_LOCATION_FILTER = str(
    os.getenv("STRICT_LOCATION_FILTER", "true")
).lower() in TRUTHY
ALLOWED_LOCATION_BOOST = int(os.getenv("ALLOWED_LOCATION_BOOST", "2") or 2)
ALLOWED_LOCATIONS = {
    x.strip().lower()
    for x in (os.getenv("ALLOWED_LOCATIONS", "") or "").split(",")
    if x.strip()
}
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
BLOCKLIST_TERMS = _normalize_terms(
    KEYWORD_BLACKLIST | LANGUAGE_BLOCKLIST | REQUIREMENTS_BLOCKLIST
)
ENABLED_SOURCES = {
    x.strip().lower()
    for x in (
        os.getenv("ENABLED_SOURCES", "jobs.ch,jobup.ch,indeed")
        or "jobs.ch,jobup.ch,indeed"
    ).split(",")
    if x.strip()
}
EXPAND_QUERY_VARIANTS = str(
    os.getenv("EXPAND_QUERY_VARIANTS", "true")
).lower() in TRUTHY
QUERY_VARIANTS_LIMIT = int(os.getenv("QUERY_VARIANTS_LIMIT", "6") or 6)
MAX_QUERY_TERMS = int(os.getenv("MAX_QUERY_TERMS", "8") or 8)
EXTRA_QUERY_TERMS = [
    x.strip()
    for x in (os.getenv("EXTRA_QUERY_TERMS", "") or "").split(",")
    if x.strip()
]
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

DETAILS_BLOCKLIST_CACHE: dict[str, bool] = {}
TRANSIT_CACHE: dict[tuple[str, str, str, str], int | None] = {}
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
    parser = _AnchorParser()
    parser.feed(html or "")
    return parser.links


def _company_name_from_url(url: str) -> str:
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
    jl = _normalize_text(job_location or "")
    return (
        1
        if any(_normalize_text(loc) in jl for loc in (search_locations or []) if loc)
        else 0
    )


def _is_remote(job: Job) -> bool:
    if not REMOTE_KEYWORDS:
        return False
    blob = " ".join([job.location or "", job.title or "", job.raw_title or ""])
    normalized = _normalize_text(blob)
    return any(_normalize_text(k) in normalized for k in REMOTE_KEYWORDS)


def _has_blocked_keywords(job: Job, blocked: set[str]) -> bool:
    if not blocked:
        return False
    blob = " ".join([job.title or "", job.raw_title or "", job.location or ""])
    normalized = _normalize_text(blob)
    return any(term in normalized for term in blocked)


_DURATION_RE = re.compile(r"(?:(\d+)d)?(\d{1,2}):(\d{2}):(\d{2})")


def _parse_duration_minutes(value: str) -> int | None:
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


def _detail_page_has_blocked_terms(url: str, blocked: set[str]) -> bool:
    if not url or not blocked:
        return False
    if url in DETAILS_BLOCKLIST_CACHE:
        return DETAILS_BLOCKLIST_CACHE[url]
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
        blocked_found = any(term in normalized for term in blocked)
        DETAILS_BLOCKLIST_CACHE[url] = blocked_found
        return blocked_found
    except Exception as e:
        job_logger.warning(f"Detail-Scan Fehler ({url}): {e}")
        DETAILS_BLOCKLIST_CACHE[url] = False
        return False


def _is_local(job: Job, search_locations: List[str]) -> bool:
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
    t = re.sub(r"\W+", "", (title or "").lower())
    c = re.sub(r"\W+", "", (company or "").lower())
    lnk = re.sub(r"[?#].*$", "", (link or "").lower())
    return f"{t}|{c}|{lnk}"


def export_json(rows: List[Job], path: str | None = None) -> None:
    out_path = Path(path or Path("data") / "jobs.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for j in rows:
        title = j.title
        company = j.company
        location = j.location
        raw_title = j.raw_title

        if (not company or not location) and (raw_title or title):
            t2, c2, l2 = _extract_from_multiline_title(raw_title or title)
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
            }
        )
    out_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


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
            for query in query_terms:
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
            driver.quit()
        except Exception:
            pass

    # Dedupe / Blacklist / Category filter / Location boost
    seen = set()
    unique: List[Job] = []
    search_locs = locations
    detail_scans = 0
    transit_enabled = (
        TRANSIT_ENABLED and bool(TRANSIT_ORIGIN) and TRANSIT_MAX_MINUTES > 0
    )

    for j in all_jobs:
        # Normalize jobs.ch/jobup multi-line titles into fields
        if (not j.company or not j.location) and (j.title or j.raw_title):
            t2, c2, l2 = _extract_from_multiline_title(j.raw_title or j.title)
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
        is_remote = _is_remote(j)

        if is_remote and not ALLOW_REMOTE:
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

        if (j.company or "").lower() in BLACKLIST:
            continue
        if _has_blocked_keywords(j, BLOCKLIST_TERMS):
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
        if (
            DETAILS_BLOCKLIST_SCAN
            and j.link
            and detail_scans < DETAILS_BLOCKLIST_MAX_JOBS
        ):
            if j.link not in DETAILS_BLOCKLIST_CACHE:
                detail_scans += 1
            if _detail_page_has_blocked_terms(j.link, BLOCKLIST_TERMS):
                continue
        seen.add(key)

        j.score += _location_boost(j.location, search_locs)
        if ALLOWED_LOCATIONS and allowed_match:
            j.score += ALLOWED_LOCATION_BOOST

        if j.score >= 20:
            j.match = "exact"
        elif j.score >= 10:
            j.match = "good"
        else:
            j.match = j.match or "weak"

        if AUTO_FIT_ENABLED:
            j.fit = compute_fit(j.match, j.score, MIN_SCORE_APPLY)

        unique.append(j)

    unique.sort(key=lambda x: x.score, reverse=True)
    return unique[:max_total]


def format_jobs_plain(jobs: List[Job], top: int = 20) -> str:
    out: List[str] = []
    for i, j in enumerate(jobs[:top], 1):
        if (not j.company or not j.location) and ("\n" in (j.raw_title or "") or "Arbeitsort" in (j.raw_title or "")):
            t2, c2, l2 = _extract_from_multiline_title(j.raw_title)
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
