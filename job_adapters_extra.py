from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable, List
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import requests


@dataclass
class ExtraJobRow:
    title: str
    company: str
    location: str
    link: str
    raw_title: str = ""
    date: str = ""
    source: str = "unknown"


DEFAULT_HEADERS = {
    "User-Agent": "Bewerbungsagent/1.0 (+adapter)",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
    "yclid",
}


def _normalize_link(link: str) -> str:
    if not link:
        return ""
    try:
        parts = urlsplit(link)
        query_pairs = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k and k.lower() not in _TRACKING_QUERY_KEYS
        ]
        clean_query = urlencode(query_pairs, doseq=True) if query_pairs else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, ""))
    except Exception:
        return link.strip()


def _is_detail_link(link: str) -> bool:
    if not link:
        return False
    u = link.lower()
    try:
        path = urlsplit(u).path
    except Exception:
        path = u
    if "/detail/" in path or "/job/" in path or "/jobad/" in path or "/stellenangebot" in path:
        return True
    if "/jobs/" in path and re.search(r"/jobs/[^/]+", path):
        return True
    if "/stellenangebote/" in path and re.search(r"/stellenangebote/[^/]+", path):
        return True
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u):
        return True
    if re.search(r"/\d{6,}(/|$)", u):
        return True
    return False


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[tuple[str, str]] = []
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


def _fetch_html(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text or ""


def _parse_jsonld(html: str) -> List[dict]:
    out: List[dict] = []
    pattern = r'<script[^>]+type=["\\\']application/ld\+json["\\\'][^>]*>(.*?)</script>'
    for m in re.finditer(pattern, html, re.S | re.I):
        chunk = m.group(1)
        if not chunk:
            continue
        try:
            data = json.loads(chunk.strip())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, dict) and "@graph" in obj and isinstance(obj["@graph"], list):
                stack.extend(obj["@graph"])
                continue
            if isinstance(obj, dict):
                t = obj.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    out.append(obj)
    return out


def _jsonld_to_rows(items: Iterable[dict], source: str, fallback_location: str = "") -> List[ExtraJobRow]:
    rows: List[ExtraJobRow] = []
    for it in items:
        title = (it.get("title") or it.get("jobTitle") or "").strip()
        if not title:
            continue

        comp = ""
        org = it.get("hiringOrganization")
        if isinstance(org, dict):
            comp = (org.get("name") or "").strip()
        elif isinstance(org, str):
            comp = org.strip()

        loc = ""
        jl = it.get("jobLocation")
        if isinstance(jl, list) and jl:
            first = jl[0] if isinstance(jl[0], dict) else {}
            addr = first.get("address") or {}
            loc = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]))
        elif isinstance(jl, dict):
            addr = jl.get("address") or {}
            loc = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]))
        loc = (loc or fallback_location or "").strip()

        link = it.get("url")
        if isinstance(link, list):
            link = next((u for u in link if isinstance(u, str)), "")
        if not link and isinstance(org, dict):
            link = org.get("sameAs") or ""
        link = (link or "").strip()

        if not link or not _is_detail_link(link):
            continue

        date = (it.get("datePosted") or "").strip()
        rows.append(
            ExtraJobRow(
                title=title,
                company=comp,
                location=loc,
                link=link,
                raw_title=title,
                date=date,
                source=source,
            )
        )
    return rows


def _rows_from_links(
    html: str,
    source: str,
    base_url: str,
    domain_hint: str,
    link_patterns: list[re.Pattern],
    fallback_location: str,
    limit: int,
) -> List[ExtraJobRow]:
    parser = _LinkParser()
    parser.feed(html)

    rows: List[ExtraJobRow] = []
    seen = set()

    for href, text in parser.links:
        text = (text or "").strip()
        if not href or not text or len(text) < 6:
            continue

        link = urljoin(base_url, href)
        if domain_hint and domain_hint not in link:
            continue

        # harte Detail-Filterung
        if not _is_detail_link(link):
            continue

        if link_patterns and not any(p.search(link) for p in link_patterns):
            continue

        key = _normalize_link(link)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            ExtraJobRow(
                title=text,
                company="",
                location=fallback_location or "",
                link=link,
                raw_title=text,
                date="",
                source=source,
            )
        )
        if len(rows) >= limit:
            break

    return rows


class _BaseRequestsAdapter:
    source = "unknown"
    base_url = ""
    domain_hint = ""
    link_patterns: list[re.Pattern] = []

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        raise NotImplementedError

    def search(self, _driver, query: str, location: str, radius_km: int = 25, limit: int = 25) -> List[ExtraJobRow]:
        url = self.build_url(query, location, radius_km)
        try:
            html = _fetch_html(url)
        except Exception:
            return []

        rows = _jsonld_to_rows(_parse_jsonld(html), self.source, location)
        if rows:
            return rows[:limit]

        return _rows_from_links(
            html=html,
            source=self.source,
            base_url=self.base_url or url,
            domain_hint=self.domain_hint,
            link_patterns=self.link_patterns,
            fallback_location=location,
            limit=limit,
        )


class JobScout24Adapter(_BaseRequestsAdapter):
    source = "jobscout24"
    base_url = "https://www.jobscout24.ch/de/jobs/"
    domain_hint = "jobscout24.ch"
    link_patterns = [re.compile(r"/jobs?/|/de/jobs?/")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?term={q}&place={loc}"


class JobWinnerAdapter(_BaseRequestsAdapter):
    source = "jobwinner"
    base_url = "https://www.jobwinner.ch/jobs/"
    domain_hint = "jobwinner.ch"
    link_patterns = [re.compile(r"/jobs?/")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?q={q}&l={loc}"


class CareerjetAdapter(_BaseRequestsAdapter):
    source = "careerjet"
    base_url = "https://www.careerjet.ch/suchen/stellenangebote"
    domain_hint = "careerjet.ch"
    link_patterns = [re.compile(r"/jobad/")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?s={q}&l={loc}"


class JobrapidoAdapter(_BaseRequestsAdapter):
    source = "jobrapido"
    base_url = "https://ch.jobrapido.com/"
    domain_hint = "jobrapido.com"
    link_patterns = [re.compile(r"jobrapido")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?w={q}&l={loc}"


class MonsterAdapter(_BaseRequestsAdapter):
    source = "monster"
    base_url = "https://www.monster.ch/jobs/suche/"
    domain_hint = "monster.ch"
    link_patterns = [re.compile(r"/job/|/stellenangebot/")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?q={q}&where={loc}"


class JoraAdapter(_BaseRequestsAdapter):
    source = "jora"
    base_url = "https://ch.jora.com/j"
    domain_hint = "jora.com"
    link_patterns = [re.compile(r"/job/|/j\?")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus(query)
        loc = quote_plus(location)
        return f"{self.base_url}?q={q}&l={loc}"


class JoobleAdapter(_BaseRequestsAdapter):
    source = "jooble"
    base_url = "https://ch.jooble.org/SearchResult"
    domain_hint = "jooble.org"
    link_patterns = [re.compile(r"/\d+|/job/|/SearchResult/")]

    def build_url(self, query: str, location: str, radius_km: int) -> str:
        q = quote_plus((query or "").strip())
        loc = quote_plus((location or "").strip())
        return f"{self.base_url}?ukw={q}&rgns={loc}"
