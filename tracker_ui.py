from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse
import webbrowser

from job_state import (
    STATUS_APPLIED,
    STATUS_CLOSED,
    STATUS_IGNORED,
    STATUS_NEW,
    STATUS_NOTIFIED,
    load_state,
    now_iso,
    parse_ts,
    save_state,
)
from job_tracker import get_tracker_path, load_tracker, write_tracker

ROOT_DIR = Path.cwd().resolve()
ALLOWED_DOC_DIRS = [
    ROOT_DIR / "out",
    ROOT_DIR / "04_Versendete_Bewerbungen",
]
ALLOWED_DOC_SUFFIXES = {".docx", ".pdf"}

HTML_PAGE = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Tracker</title>
  <style>
    :root {
      --bg1: #f5f2ea;
      --bg2: #e8f2f4;
      --card: #ffffff;
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #0f766e;
      --accent-2: #c2410c;
      --line: #e5e7eb;
      --ok: #059669;
      --warn: #b45309;
      --bad: #b91c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Trebuchet MS", "Segoe UI", "Tahoma", sans-serif;
      color: var(--ink);
      background: radial-gradient(1400px circle at 20% 10%, #ffffff 0, var(--bg1) 45%, var(--bg2) 100%);
      min-height: 100vh;
    }
    .shell {
      max-width: 100%;
      margin: 0 auto;
      padding: 28px 20px 50px;
      animation: fadeUp 0.6s ease-out;
    }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .hero {
      display: flex;
      gap: 24px;
      justify-content: space-between;
      align-items: center;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px 20px;
      box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
    }
    h1 {
      margin: 0 0 6px 0;
      font-size: 28px;
      letter-spacing: 0.2px;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
    }
    .stats {
      display: grid;
      grid-auto-flow: column;
      gap: 14px;
      font-size: 13px;
      color: var(--muted);
    }
    .stats span {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: #f8fafc;
      border: 1px solid var(--line);
      color: var(--ink);
    }
    .controls {
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }
    .controls input[type="text"], .controls select {
      padding: 10px 12px;
      min-width: 240px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #ffffff;
    }
    .btn {
      border: none;
      padding: 10px 14px;
      border-radius: 10px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font-weight: 600;
      letter-spacing: 0.2px;
    }
    .btn.secondary {
      background: #fff;
      color: var(--accent);
      border: 1px solid var(--accent);
    }
    .btn.ghost {
      background: transparent;
      border: 1px dashed var(--line);
      color: var(--muted);
      font-weight: 500;
    }
    .table-wrap {
      margin-top: 18px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow-x: auto;
      box-shadow: 0 10px 32px rgba(15, 23, 42, 0.08);
    }
    table {
      width: 100%;
      min-width: 1400px;
      border-collapse: collapse;
      font-size: 14px;
    }
    thead {
      background: #f8fafc;
      text-align: left;
    }
    th, td {
      padding: 12px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: middle;
    }
    th.sortable {
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }
    th.sortable::after {
      content: "";
      margin-left: 6px;
      font-size: 11px;
      color: var(--muted);
    }
    th.sortable.active[data-dir="asc"]::after {
      content: "▲";
    }
    th.sortable.active[data-dir="desc"]::after {
      content: "▼";
    }
    tbody tr:hover {
      background: #f9fafb;
    }
    .muted { color: var(--muted); }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: #f8fafc;
      border: 1px solid var(--line);
    }
    .badge.ok { color: var(--ok); border-color: rgba(5, 150, 105, 0.3); }
    .badge.warn { color: var(--warn); border-color: rgba(180, 83, 9, 0.35); }
    .badge.bad { color: var(--bad); border-color: rgba(185, 28, 28, 0.35); }
    .commute {
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: #f8fafc;
    }
    .commute.good { color: var(--ok); border-color: rgba(5, 150, 105, 0.3); }
    .commute.mid { color: #0f766e; border-color: rgba(15, 118, 110, 0.3); }
    .commute.warn { color: var(--warn); border-color: rgba(180, 83, 9, 0.35); }
    .commute.bad { color: var(--bad); border-color: rgba(185, 28, 28, 0.35); }
    .link {
      color: var(--accent);
      text-decoration: none;
    }
    .link:hover { text-decoration: underline; }
    .empty {
      padding: 20px;
      text-align: center;
      color: var(--muted);
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--muted);
    }
    @media (max-width: 900px) {
      .hero {
        flex-direction: column;
        align-items: flex-start;
      }
      .stats {
        grid-auto-flow: row;
      }
      table {
        min-width: 760px;
      }
      .table-wrap {
        overflow-x: auto;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1>Job Tracker</h1>
        <p>Ignorieren markiert Jobs, die nicht passen.</p>
      </div>
      <div class="stats" id="stats"></div>
    </div>
    <div class="controls">
      <button class="btn" id="refresh">Refresh</button>
      <button class="btn secondary" id="sync">Sync Tracker</button>
      <label class="toggle">
        <input type="checkbox" id="showDone">
        Show done
      </label>
      <label class="toggle">
        <input type="checkbox" id="showClosed">
        Show closed
      </label>
      <input type="text" id="search" placeholder="Suche nach Titel, Firma, Ort">
      <span class="muted" id="lastUpdated"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ignorieren</th>
            <th class="sortable" data-sort="title">Titel</th>
            <th class="sortable" data-sort="company">Firma</th>
            <th class="sortable" data-sort="commute">Ort</th>
            <th class="sortable" data-sort="status">Status</th>
            <th class="sortable" data-sort="score">Score</th>
            <th class="sortable" data-sort="match">Match</th>
            <th class="sortable" data-sort="source">Quelle</th>
            <th class="sortable" data-sort="first_seen">Erst gesehen</th>
            <th class="sortable" data-sort="last_seen">Zuletzt gesehen</th>
            <th class="sortable" data-sort="uid">UID</th>
            <th>Bewerbung</th>
            <th>Aktion</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div class="empty" id="empty" style="display:none;">Keine passenden Jobs.</div>
    </div>
  </div>
  <script>
    const state = {
      includeDone: false,
      includeClosed: false,
      query: "",
      sortKey: "last_seen",
      sortDir: "desc",
    };
    let lastPayload = null;

    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const statsEl = document.getElementById("stats");
    const lastUpdatedEl = document.getElementById("lastUpdated");
    const headerEls = document.querySelectorAll("th.sortable");

    function statusBadge(status) {
      const span = document.createElement("span");
      span.className = "badge";
      let label = status;
      if (status === "new") {
        span.classList.add("warn");
      } else if (status === "notified") {
        span.classList.add("ok");
      } else if (status === "applied") {
        span.classList.add("ok");
        label = "applied";
      } else if (status === "ignored") {
        span.classList.add("bad");
      } else if (status === "closed") {
        span.classList.add("warn");
      }
      span.textContent = label;
      return span;
    }

    function commuteClass(mins) {
      if (mins <= 30) return "good";
      if (mins <= 45) return "mid";
      if (mins <= 60) return "warn";
      if (mins <= 75) return "warn";
      return "bad";
    }

    function renderStats(counts) {
      statsEl.innerHTML = "";
      const items = [
        ["Open", counts.open || 0],
        ["Applied", counts.applied || 0],
        ["Ignored", counts.ignored || 0],
        ["Closed", counts.closed || 0],
        ["Total", counts.total || 0],
      ];
      for (const [label, value] of items) {
        const chip = document.createElement("span");
        chip.textContent = label + ": " + value;
        statsEl.appendChild(chip);
      }
    }

    function fmt(ts) {
      if (!ts) return "";
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return ts;
      return d.toLocaleString();
    }

    function jobMatches(job, query) {
      if (!query) return true;
      const text = [
        job.title,
        job.company,
        job.location,
        job.source,
        job.status,
        job.job_uid,
      ].join(" ").toLowerCase();
      return text.includes(query);
    }

    function sortJobs(jobs) {
      const sorted = [...jobs];
      const statusRank = {
        "new": 0,
        "notified": 1,
        "applied": 2,
        "ignored": 3,
        "closed": 4,
      };
      const matchRank = {
        "exact": 0,
        "good": 1,
        "weak": 2,
        "unknown": 3,
      };
      function ts(value) {
        const d = new Date(value || "");
        return Number.isNaN(d.getTime()) ? 0 : d.getTime();
      }
      function num(value, fallback = 0) {
        const s = parseFloat(value);
        return Number.isNaN(s) ? fallback : s;
      }
      function getValue(job) {
        switch (state.sortKey) {
          case "title":
            return (job.title || "").toLowerCase();
          case "company":
            return (job.company || "").toLowerCase();
          case "commute":
            return num(job.commute_min, 9999);
          case "status":
            return statusRank[job.status] ?? 99;
          case "score":
            return num(job.score, 0);
          case "match":
            return matchRank[(job.match || "").toLowerCase()] ?? 99;
          case "source":
            return (job.source || "").toLowerCase();
          case "first_seen":
            return ts(job.first_seen_at);
          case "last_seen":
            return ts(job.last_seen_at);
          case "uid":
            return (job.job_uid || "").toLowerCase();
          default:
            return ts(job.last_seen_at);
        }
      }
      const dir = state.sortDir === "asc" ? 1 : -1;
      sorted.sort((a, b) => {
        const av = getValue(a);
        const bv = getValue(b);
        if (typeof av === "string" || typeof bv === "string") {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - bv) * dir;
      });
      return sorted;
    }

    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) {
        throw new Error("Request failed");
      }
      return await res.json();
    }

    async function loadJobs() {
      const qs = new URLSearchParams();
      if (state.includeDone) qs.set("include_done", "1");
      if (state.includeClosed) qs.set("include_closed", "1");
      const query = qs.toString();
      lastPayload = await api("/api/jobs" + (query ? "?" + query : ""));
      render(lastPayload);
    }

    function render(payload) {
      const filtered = (payload.jobs || []).filter((job) =>
        jobMatches(job, state.query)
      );
      const jobs = sortJobs(filtered);
      rowsEl.innerHTML = "";
      for (const job of jobs) {
        const tr = document.createElement("tr");

        const doneTd = document.createElement("td");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = job.status === "ignored";
        checkbox.addEventListener("change", async () => {
          const next = checkbox.checked ? "ignored" : "open";
          await api("/api/mark", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ job_uid: job.job_uid, status: next }),
          });
          await loadJobs();
        });
        doneTd.appendChild(checkbox);
        tr.appendChild(doneTd);

        const titleTd = document.createElement("td");
        const link = document.createElement("a");
        link.className = "link";
        link.href = job.link || "#";
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = job.title || "Ohne Titel";
        titleTd.appendChild(link);
        tr.appendChild(titleTd);

        const companyTd = document.createElement("td");
        companyTd.textContent = job.company || "";
        tr.appendChild(companyTd);

        const locationTd = document.createElement("td");
        const commute = Number(job.commute_min);
        if (!Number.isNaN(commute) && commute > 0) {
          const badge = document.createElement("span");
          badge.className = "commute " + commuteClass(commute);
          badge.textContent = `${job.location || ""} (${commute}m)`;
          locationTd.appendChild(badge);
        } else {
          locationTd.textContent = job.location || "";
        }
        tr.appendChild(locationTd);

        const statusTd = document.createElement("td");
        statusTd.appendChild(statusBadge(job.status));
        tr.appendChild(statusTd);

        const scoreTd = document.createElement("td");
        scoreTd.textContent = job.score || "";
        tr.appendChild(scoreTd);

        const matchTd = document.createElement("td");
        matchTd.textContent = job.match || "";
        tr.appendChild(matchTd);

        const sourceTd = document.createElement("td");
        sourceTd.textContent = job.source || "";
        tr.appendChild(sourceTd);

        const firstSeenTd = document.createElement("td");
        firstSeenTd.textContent = fmt(job.first_seen_at);
        tr.appendChild(firstSeenTd);

        const seenTd = document.createElement("td");
        seenTd.textContent = fmt(job.last_seen_at);
        tr.appendChild(seenTd);

        const uidTd = document.createElement("td");
        uidTd.textContent = job.job_uid ? job.job_uid.slice(0, 10) : "";
        uidTd.title = job.job_uid || "";
        tr.appendChild(uidTd);

        const docTd = document.createElement("td");
        if (job.has_application_doc) {
          const docLink = document.createElement("a");
          docLink.className = "link";
          docLink.href = `/api/doc?job_uid=${encodeURIComponent(job.job_uid)}`;
          docLink.target = "_blank";
          docLink.rel = "noreferrer";
          docLink.textContent = "Download";
          docTd.appendChild(docLink);
        } else {
          docTd.textContent = "-";
        }
        tr.appendChild(docTd);

        const actionTd = document.createElement("td");
        if (job.status === "closed") {
          actionTd.textContent = "-";
        } else {
          const appliedBtn = document.createElement("button");
          appliedBtn.className = "btn ghost";
          appliedBtn.textContent = "Applied";
          appliedBtn.addEventListener("click", async () => {
            await api("/api/mark", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ job_uid: job.job_uid, status: "applied" }),
            });
            await loadJobs();
          });

          const ignoreBtn = document.createElement("button");
          ignoreBtn.className = "btn ghost";
          ignoreBtn.textContent = "Ignore";
          ignoreBtn.addEventListener("click", async () => {
            await api("/api/mark", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ job_uid: job.job_uid, status: "ignored" }),
            });
            await loadJobs();
          });

          const openBtn = document.createElement("button");
          openBtn.className = "btn ghost";
          openBtn.textContent = "Open";
          openBtn.addEventListener("click", async () => {
            await api("/api/mark", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ job_uid: job.job_uid, status: "open" }),
            });
            await loadJobs();
          });

          if (job.status === "new" || job.status === "notified") {
            actionTd.appendChild(appliedBtn);
            actionTd.appendChild(ignoreBtn);
          } else if (job.status === "applied") {
            actionTd.appendChild(ignoreBtn);
            actionTd.appendChild(openBtn);
          } else if (job.status === "ignored") {
            actionTd.appendChild(appliedBtn);
            actionTd.appendChild(openBtn);
          } else {
            actionTd.textContent = "-";
          }
        }
        tr.appendChild(actionTd);

        rowsEl.appendChild(tr);
      }

      emptyEl.style.display = jobs.length ? "none" : "block";
      renderStats(payload.counts || {});
      lastUpdatedEl.textContent = payload.generated_at
        ? "Updated: " + fmt(payload.generated_at)
        : "";
      updateSortHeaders();
    }

    const defaultSortDir = {
      title: "asc",
      company: "asc",
      commute: "asc",
      status: "asc",
      score: "desc",
      match: "asc",
      source: "asc",
      first_seen: "desc",
      last_seen: "desc",
      uid: "asc",
    };

    function updateSortHeaders() {
      headerEls.forEach((th) => {
        const key = th.dataset.sort;
        if (key === state.sortKey) {
          th.classList.add("active");
          th.setAttribute("data-dir", state.sortDir);
        } else {
          th.classList.remove("active");
          th.removeAttribute("data-dir");
        }
      });
    }

    headerEls.forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (!key) return;
        if (state.sortKey === key) {
          state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        } else {
          state.sortKey = key;
          state.sortDir = defaultSortDir[key] || "asc";
        }
        if (lastPayload) {
          render(lastPayload);
        }
      });
    });

    document.getElementById("refresh").addEventListener("click", loadJobs);
    document.getElementById("sync").addEventListener("click", async () => {
      await api("/api/sync", { method: "POST" });
      await loadJobs();
    });
    document.getElementById("showDone").addEventListener("change", (ev) => {
      state.includeDone = ev.target.checked;
      loadJobs();
    });
    document.getElementById("showClosed").addEventListener("change", (ev) => {
      state.includeClosed = ev.target.checked;
      loadJobs();
    });
    document.getElementById("search").addEventListener("input", (ev) => {
      state.query = ev.target.value.trim().toLowerCase();
      if (lastPayload) {
        render(lastPayload);
      }
    });

    loadJobs();
  </script>
</body>
</html>
"""


def _status_for_open(record: Dict[str, Any]) -> str:
    return STATUS_NOTIFIED if record.get("last_sent_at") else STATUS_NEW


UI_HISTORY_DAYS = int(os.getenv("TRACKER_UI_DAYS", "60") or 60)


def _normalize_text(value: str) -> str:
    text = (value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_commute_map(raw: str) -> list[tuple[str, int]]:
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


COMMUTE_MINUTES = _parse_commute_map(os.getenv("COMMUTE_MINUTES", "") or "")


def _commute_minutes_from_text(value: str) -> int | None:
    if not value or not COMMUTE_MINUTES:
        return None
    normalized = _normalize_text(value)
    for key, minutes in COMMUTE_MINUTES:
        if key and key in normalized:
            return minutes
    return None


def _commute_minutes_for_record(record: Dict[str, Any]) -> int | None:
    raw = record.get("commute_min")
    if raw not in (None, ""):
        try:
            return int(raw)
        except Exception:
            pass
    candidates = [
        record.get("location") or "",
        record.get("title") or "",
        record.get("company") or "",
    ]
    for text in candidates:
        minutes = _commute_minutes_from_text(text)
        if minutes is not None:
            return minutes
    return None


def _safe_doc_path(path_value: str) -> Path | None:
    if not path_value:
        return None
    raw = Path(path_value)
    try:
        resolved = raw if raw.is_absolute() else (ROOT_DIR / raw)
        resolved = resolved.resolve()
    except Exception:
        return None
    if resolved.suffix.lower() not in ALLOWED_DOC_SUFFIXES:
        return None
    for base in ALLOWED_DOC_DIRS:
        try:
            resolved.relative_to(base.resolve())
            return resolved
        except Exception:
            continue
    return None


def _pick_application_doc(record: Dict[str, Any]) -> Path | None:
    candidates = [
        record.get("application_doc_archived"),
        record.get("application_doc"),
    ]
    for value in candidates:
        path = _safe_doc_path(str(value)) if value else None
        if path and path.exists():
            return path
    return None


def _collect_jobs(include_done: bool, include_closed: bool) -> Dict[str, Any]:
    state = load_state()
    items: List[Dict[str, Any]] = []
    counts = {
        "open": 0,
        "applied": 0,
        "ignored": 0,
        "closed": 0,
        "total": len(state),
    }
    now = datetime.now(timezone.utc)
    cutoff = None
    if UI_HISTORY_DAYS > 0:
        cutoff = now - timedelta(days=UI_HISTORY_DAYS)

    for uid, record in state.items():
        status = record.get("status") or STATUS_NEW
        last_seen = parse_ts(record.get("last_seen_at"))
        recent = True
        if cutoff and last_seen:
            recent = last_seen >= cutoff
        if status == STATUS_CLOSED:
            counts["closed"] += 1
            if not include_closed or not recent:
                continue
        if status == STATUS_APPLIED:
            counts["applied"] += 1
            if not include_done or not recent:
                continue
        elif status == STATUS_IGNORED:
            counts["ignored"] += 1
            if not include_done or not recent:
                continue
        else:
            counts["open"] += 1

        doc_path = _pick_application_doc(record)
        commute_min = _commute_minutes_for_record(record)

        items.append(
            {
                "job_uid": uid,
                "status": status,
                "title": record.get("title") or "",
                "company": record.get("company") or "",
                "location": record.get("location") or "",
                "source": record.get("source") or "",
                "link": record.get("link") or record.get("canonical_url") or "",
                "score": record.get("score") or "",
                "match": record.get("match") or "",
                "first_seen_at": record.get("first_seen_at") or "",
                "last_seen_at": record.get("last_seen_at") or "",
                "has_application_doc": bool(doc_path),
                "commute_min": commute_min,
            }
        )

    items.sort(
        key=lambda item: parse_ts(item.get("last_seen_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "jobs": items,
        "counts": counts,
        "generated_at": now_iso(),
    }


class TrackerHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            content_type = "application/pdf"
        elif suffix == ".docx":
            content_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        else:
            content_type = "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition", f'attachment; filename="{path.name}"'
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(HTML_PAGE)
            return
        if parsed.path == "/api/jobs":
            params = parse_qs(parsed.query)
            include_done = params.get("include_done", ["0"])[0] == "1"
            include_closed = params.get("include_closed", ["0"])[0] == "1"
            payload = _collect_jobs(
                include_done=include_done,
                include_closed=include_closed,
            )
            self._send_json(payload)
            return
        if parsed.path == "/api/doc":
            params = parse_qs(parsed.query)
            job_uid = (params.get("job_uid", [""])[0] or "").strip()
            if not job_uid:
                self._send_json({"ok": False, "error": "missing job_uid"}, 400)
                return
            state = load_state()
            record = state.get(job_uid)
            if not record:
                self._send_json({"ok": False, "error": "unknown job_uid"}, 404)
                return
            doc_path = _pick_application_doc(record)
            if not doc_path:
                self._send_json(
                    {"ok": False, "error": "doc not found"}, 404
                )
                return
            self._send_file(doc_path)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        data = {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        if parsed.path == "/api/mark":
            job_uid = (data.get("job_uid") or "").strip()
            status = (data.get("status") or "").strip()
            if not job_uid:
                self._send_json({"ok": False, "error": "missing job_uid"}, 400)
                return
            state = load_state()
            record = state.get(job_uid)
            if not record:
                self._send_json({"ok": False, "error": "unknown job_uid"}, 404)
                return

            if status in ("open", STATUS_NEW, STATUS_NOTIFIED):
                status = _status_for_open(record)
            elif status not in (STATUS_APPLIED, STATUS_IGNORED):
                self._send_json({"ok": False, "error": "invalid status"}, 400)
                return

            record["status"] = status
            save_state(state)
            tracker_path = get_tracker_path()
            tracker_rows = load_tracker(tracker_path)
            write_tracker(state, tracker_path, tracker_rows)
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/sync":
            state = load_state()
            tracker_path = get_tracker_path()
            tracker_rows = load_tracker(tracker_path)
            write_tracker(state, tracker_path, tracker_rows)
            self._send_json({"ok": True})
            return

        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_tracker_ui(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), TrackerHandler)
    url = f"http://{host}:{port}/"
    print(f"Tracker UI laeuft: {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server.serve_forever()
