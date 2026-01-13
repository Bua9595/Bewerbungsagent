import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Optional, List
from urllib.parse import urljoin, urlsplit, urlunsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


@dataclass
class JobRow:
    title: str
    company: str
    location: str
    link: str
    raw_title: str = ""
    date: Optional[str] = ""
    source: str = "unknown"
    cls: str = "weak"
    score: int = 0


# robuster Cookie-Clicker (de/en/fr)
COOKIE_CLICK_JS = r"""
(() => {
  const needles = [
    'akzept', 'zustimm', 'einverstanden',
    'accept', 'agree', 'consent',
    'tout accepter', 'accepter', 'j\'accepte'
  ];

  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const btns = Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]'));
  for (const b of btns) {
    const t = (b.innerText || b.value || b.getAttribute('aria-label') || '').toLowerCase();
    if (!t) continue;
    if (needles.some(n => t.includes(n)) && isVisible(b)) {
      try { b.click(); return true; } catch (e) {}
    }
  }
  return false;
})();
"""


def _normalize_link(link: str) -> str:
    """Dedupe: entferne Tracking-Query + Fragments."""
    if not link:
        return ""
    try:
        parts = urlsplit(link)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return link.strip()


def _is_detail_link(link: str) -> bool:
    if not link:
        return False
    u = link.lower()

    # typische Detailpfade
    if "/detail/" in u or "/job/" in u or "/jobad/" in u:
        return True

    # GUIDs / numeric IDs
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u):
        return True
    if re.search(r"/\d{6,}(/|$)", u):
        return True

    return False


_LINE_LABEL_RE = re.compile(r"(arbeitsort|pensum|vertragsart|einfach bewerben|neu)", re.IGNORECASE)
_LINE_RELDATE_RE = re.compile(
    r"\b(heute|gestern|vorgestern|letzte woche|letzten monat|vor \d+\s*(tagen|wochen|monaten?))\b",
    re.IGNORECASE,
)


def _parse_jsonld(html: str) -> List[dict]:
    out: List[dict] = []
    pattern = r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>'
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


def _to_jobrows(items: List[dict], source: str) -> List[JobRow]:
    rows: List[JobRow] = []
    for it in items:
        raw_title = (it.get("title") or "").strip()
        title = raw_title

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
        loc = (loc or "").strip()

        link = (it.get("url") or "").strip()
        if not link and isinstance(org, dict):
            link = (org.get("sameAs") or "").strip()

        date = (it.get("datePosted") or "").strip()

        if not title or not link or not _is_detail_link(link):
            continue

        rows.append(
            JobRow(
                title=title,
                company=comp,
                location=loc,
                link=link,
                raw_title=raw_title,
                date=date,
                source=source,
            )
        )
    return rows


def _extract_dom_links(driver, source_name: str, base_url: str) -> List[JobRow]:
    """
    DOM-Scrape: sucht nach Anchor-Tags mit detail-typischen hrefs.
    Auch für client-side render.
    """
    rows: List[JobRow] = []

    selectors = [
        'a[href*="/detail/"]',
        'a[href*="/jobs/detail/"]',
        'a[href*="/de/jobs/detail/"]',
        'a[href*="/emploi/detail/"]',
        'a[href*="/jobad/"]',
        'a[href*="/job/"]',
    ]

    anchors = []
    for sel in selectors:
        try:
            anchors += driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue

    for a in anchors:
        try:
            href = (a.get_attribute("href") or "").strip()
            if not href:
                # fallback: relative href
                href = (a.get_attribute("href") or "").strip()
            href = urljoin(base_url, href) if href else ""
            if not _is_detail_link(href):
                continue

            txt = (a.text or "").strip() or (a.get_attribute("aria-label") or "").strip()
            if not txt:
                continue

            lines = [line.strip() for line in txt.splitlines() if line.strip()]
            title = ""
            for line in lines:
                if _LINE_LABEL_RE.search(line) or _LINE_RELDATE_RE.search(line):
                    continue
                title = line
                break
            if not title:
                title = lines[0] if lines else txt
            if not title:
                continue

            rows.append(
                JobRow(
                    title=title,
                    company="",
                    location="",
                    link=href,
                    raw_title=txt,
                    source=source_name,
                )
            )
        except Exception:
            continue

    # dedupe
    seen, out = set(), []
    for r in rows:
        key = _normalize_link(r.link)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


class JobsChAdapter:
    source = "jobs.ch"
    BASE = "https://www.jobs.ch/de/stellenangebote/"

    def search(self, driver, query: str, location: str, radius_km: int, limit: int = 30) -> Iterable[JobRow]:
        params = {"term": query}
        if location:
            params["location"] = location  # konsistent zu Query-Builder
        url = f"{self.BASE}?{urllib.parse.urlencode(params, doseq=True)}"

        rows: List[JobRow] = []

        for p in range(1, 4):
            paged = url + f"&page={p}"
            try:
                driver.get(paged)
                try:
                    driver.execute_script(COOKIE_CLICK_JS)
                except Exception:
                    pass

                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
                except Exception:
                    pass

                html = driver.page_source or ""
                parsed = _to_jobrows(_parse_jsonld(html), self.source)
                if parsed:
                    rows.extend(parsed)
                else:
                    rows.extend(_extract_dom_links(driver, self.source, self.BASE))

            except Exception:
                continue

        seen, out = set(), []
        for r in rows:
            key = _normalize_link(r.link)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
            if len(out) >= limit:
                break
        return out


class JobupAdapter:
    source = "jobup.ch"
    BASE = "https://www.jobup.ch/de/jobs/"

    def search(self, driver, query: str, location: str, radius_km: int, limit: int = 30) -> Iterable[JobRow]:
        params = {"term": query}
        if location:
            params["location"] = location
        url = f"{self.BASE}?{urllib.parse.urlencode(params, doseq=True)}"

        rows: List[JobRow] = []

        for p in range(1, 4):
            paged = url + f"&page={p}"
            try:
                driver.get(paged)
                try:
                    driver.execute_script(COOKIE_CLICK_JS)
                except Exception:
                    pass

                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
                except Exception:
                    pass

                html = driver.page_source or ""
                parsed = _to_jobrows(_parse_jsonld(html), self.source)
                if parsed:
                    rows.extend(parsed)
                else:
                    rows.extend(_extract_dom_links(driver, self.source, self.BASE))

            except Exception:
                continue

        seen, out = set(), []
        for r in rows:
            key = _normalize_link(r.link)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
            if len(out) >= limit:
                break
        return out
