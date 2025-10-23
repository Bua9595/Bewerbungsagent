import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Optional, List
import urllib.parse


@dataclass
class JobRow:
    title: str
    company: str
    location: str
    link: str
    date: Optional[str] = ""
    source: str = "unknown"
    cls: str = "weak"
    score: int = 0


def _parse_jsonld(html: str) -> List[dict]:
    """Sammelt JobPosting-Objekte aus JSON-LD Blöcken der Seite."""
    out: List[dict] = []
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
        chunk = m.group(1)
        if not chunk:
            continue
        try:
            data = json.loads(chunk.strip())
        except Exception:
            continue
        # Normalisieren auf Liste
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


def _to_jobrows(items: List[dict], source: str) -> List[JobRow]:
    rows: List[JobRow] = []
    for it in items:
        title = it.get("title") or ""
        comp = ""
        org = it.get("hiringOrganization")
        if isinstance(org, dict):
            comp = org.get("name") or ""
        elif isinstance(org, str):
            comp = org

        loc = ""
        jl = it.get("jobLocation")
        if isinstance(jl, list) and jl:
            a = (jl[0].get("address") or {}) if isinstance(jl[0], dict) else {}
            loc = ", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")]))
        elif isinstance(jl, dict):
            a = jl.get("address") or {}
            loc = ", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")]))

        link = ""
        if isinstance(org, dict):
            link = org.get("sameAs") or ""
        link = it.get("url") or link or ""
        date = it.get("datePosted") or ""

        if not title or not link:
            continue
        rows.append(JobRow(title=title.strip(), company=comp.strip(), location=loc.strip(), link=link.strip(), date=date, source=source))
    return rows


class JobsChAdapter:
    source = "jobs.ch"
    BASE = "https://www.jobs.ch/de/stellenangebote/"

    def search(self, driver, query: str, location: str, radius_km: int, limit: int = 30) -> Iterable[JobRow]:
        params = {"term": query}
        if location:
            params["region"] = location
        url = f"{self.BASE}?{urllib.parse.urlencode(params, doseq=True)}"
        def _get_html(u: str) -> str:
            try:
                driver.get(u)
                # Cookie‑Banner wegklicken (best effort)
                try:
                    driver.execute_script("document.querySelectorAll('[id*="consent"], [class*="cookie" i]').forEach(e=>{try{(e.querySelector('button[aria-label*="kzept" i]')||e.querySelector('button'))?.click()}catch(_){}})")
                except Exception:
                    pass
                return driver.page_source
            except Exception:
                return ""

        # Pagination (bis 3 Seiten)
        html_pages = []
        for p in range(1, 3 + 1):
            paged = url + (f"&page={p}" if "?" in url else f"?page={p}")
            html_pages.append(_get_html(paged))

        rows: List[JobRow] = []
        for html in html_pages:
            if not html:
                continue
            parsed = _to_jobrows(_parse_jsonld(html), self.source)
            rows.extend(parsed)

            # Fallback, falls JSON‑LD fehlt
            if not parsed:
                for m in re.finditer(r'<a[^>]+href="(/de/stellen[^"#?]+)"[^>]*>([^<]+)</a>', html, re.I):
                    link = urllib.parse.urljoin(self.BASE, m.group(1))
                    title = m.group(2).strip()
                    rows.append(JobRow(title=title, company="", location="", link=link, source=self.source))
        seen, out = set(), []
        for r in rows:
            if r.link in seen:
                continue
            seen.add(r.link)
            out.append(r)
            if len(out) >= limit:
                break
        return out


class JobupAdapter:
    source = "jobup.ch"
    BASE = "https://www.jobup.ch/de/stellenangebote/"

    def search(self, driver, query: str, location: str, radius_km: int, limit: int = 30) -> Iterable[JobRow]:
        params = {"term": query}
        if location:
            params["location"] = location
        url = f"{self.BASE}?{urllib.parse.urlencode(params, doseq=True)}"
        def _get_html(u: str) -> str:
            try:
                driver.get(u)
                try:
                    driver.execute_script("document.querySelectorAll('[id*="consent"], [class*="cookie" i]').forEach(e=>{try{(e.querySelector('button[aria-label*="kzept" i]')||e.querySelector('button'))?.click()}catch(_){}})")
                except Exception:
                    pass
                return driver.page_source
            except Exception:
                return ""

        html_pages = []
        for p in range(1, 3 + 1):
            paged = url + (f"&page={p}" if "?" in url else f"?page={p}")
            html_pages.append(_get_html(paged))

        rows: List[JobRow] = []
        for html in html_pages:
            if not html:
                continue
            parsed = _to_jobrows(_parse_jsonld(html), self.source)
            rows.extend(parsed)
            if not parsed:
                for m in re.finditer(r'<a[^>]+href="(/de/stellen[^"#?]+)"[^>]*>([^<]+)</a>', html, re.I):
                    link = urllib.parse.urljoin(self.BASE, m.group(1))
                    title = m.group(2).strip()
                    rows.append(JobRow(title=title, company="", location="", link=link, source=self.source))
        seen, out = set(), []
        for r in rows:
            if r.link in seen:
                continue
            seen.add(r.link)
            out.append(r)
            if len(out) >= limit:
                break
        return out
