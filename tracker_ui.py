from __future__ import annotations

import json
from datetime import datetime
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
      max-width: 1200px;
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
    .controls input[type="text"] {
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
      overflow: hidden;
      box-shadow: 0 10px 32px rgba(15, 23, 42, 0.08);
    }
    table {
      width: 100%;
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
        <p>Erledigt anklicken setzt den Status auf "applied".</p>
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
      <input type="text" id="search" placeholder="Suche nach Titel, Firma, Ort">
      <span class="muted" id="lastUpdated"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Erledigt</th>
            <th>Titel</th>
            <th>Firma</th>
            <th>Ort</th>
            <th>Status</th>
            <th>Score</th>
            <th>Quelle</th>
            <th>Zuletzt gesehen</th>
            <th>Aktion</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div class="empty" id="empty" style="display:none;">Keine passenden Jobs.</div>
    </div>
  </div>
  <script>
    const state = { includeDone: false, query: "" };
    let lastPayload = null;

    const rowsEl = document.getElementById("rows");
    const emptyEl = document.getElementById("empty");
    const statsEl = document.getElementById("stats");
    const lastUpdatedEl = document.getElementById("lastUpdated");

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
      }
      span.textContent = label;
      return span;
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
        job.title, job.company, job.location, job.source, job.status
      ].join(" ").toLowerCase();
      return text.includes(query);
    }

    async function api(path, options) {
      const res = await fetch(path, options);
      if (!res.ok) {
        throw new Error("Request failed");
      }
      return await res.json();
    }

    async function loadJobs() {
      const qs = state.includeDone ? "?include_done=1" : "";
      lastPayload = await api("/api/jobs" + qs);
      render(lastPayload);
    }

    function render(payload) {
      const jobs = (payload.jobs || []).filter((job) =>
        jobMatches(job, state.query)
      );
      rowsEl.innerHTML = "";
      for (const job of jobs) {
        const tr = document.createElement("tr");

        const doneTd = document.createElement("td");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = job.status === "applied" || job.status === "ignored";
        checkbox.addEventListener("change", async () => {
          const next = checkbox.checked ? "applied" : "open";
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
        locationTd.textContent = job.location || "";
        tr.appendChild(locationTd);

        const statusTd = document.createElement("td");
        statusTd.appendChild(statusBadge(job.status));
        tr.appendChild(statusTd);

        const scoreTd = document.createElement("td");
        scoreTd.textContent = job.score || "";
        tr.appendChild(scoreTd);

        const sourceTd = document.createElement("td");
        sourceTd.textContent = job.source || "";
        tr.appendChild(sourceTd);

        const seenTd = document.createElement("td");
        seenTd.textContent = fmt(job.last_seen_at);
        tr.appendChild(seenTd);

        const actionTd = document.createElement("td");
        if (job.status === "new" || job.status === "notified") {
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
          actionTd.appendChild(ignoreBtn);
        } else {
          actionTd.textContent = "-";
        }
        tr.appendChild(actionTd);

        rowsEl.appendChild(tr);
      }

      emptyEl.style.display = jobs.length ? "none" : "block";
      renderStats(payload.counts || {});
      lastUpdatedEl.textContent = payload.generated_at
        ? "Updated: " + fmt(payload.generated_at)
        : "";
    }

    document.getElementById("refresh").addEventListener("click", loadJobs);
    document.getElementById("sync").addEventListener("click", async () => {
      await api("/api/sync", { method: "POST" });
      await loadJobs();
    });
    document.getElementById("showDone").addEventListener("change", (ev) => {
      state.includeDone = ev.target.checked;
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


def _collect_jobs(include_done: bool) -> Dict[str, Any]:
    state = load_state()
    items: List[Dict[str, Any]] = []
    counts = {
        "open": 0,
        "applied": 0,
        "ignored": 0,
        "closed": 0,
        "total": len(state),
    }
    for uid, record in state.items():
        status = record.get("status") or STATUS_NEW
        if status == STATUS_CLOSED:
            counts["closed"] += 1
            continue
        if status == STATUS_APPLIED:
            counts["applied"] += 1
        elif status == STATUS_IGNORED:
            counts["ignored"] += 1
        else:
            counts["open"] += 1

        if not include_done and status not in (STATUS_NEW, STATUS_NOTIFIED):
            continue

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
                "last_seen_at": record.get("last_seen_at") or "",
            }
        )

    items.sort(
        key=lambda item: parse_ts(item.get("last_seen_at")) or datetime.min,
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
            payload = _collect_jobs(include_done=include_done)
            self._send_json(payload)
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

