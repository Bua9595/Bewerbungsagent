"""
web/server.py – FastAPI config server for BewerbungsagentClaude.

Start:  python -m web.server
        (or)  uvicorn web.server:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values, load_dotenv

load_dotenv()
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bwa.web")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
WEB_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="BewerbungsagentClaude Config API", version="1.0.0")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


def _get_token() -> str:
    token = os.environ.get("WEB_CONFIG_TOKEN", "")
    if not token:
        logger.warning("WEB_CONFIG_TOKEN is not set – all requests will be rejected")
    return token


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected = _get_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Server not configured (no token set)")
    if credentials is None or credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter
# ---------------------------------------------------------------------------
_rate_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10   # requests
_RATE_WINDOW = 60  # seconds


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window_start = now - _RATE_WINDOW
    timestamps = _rate_store[key]
    # Remove old entries
    _rate_store[key] = [t for t in timestamps if t > window_start]
    if len(_rate_store[key]) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded (10/min)")
    _rate_store[key].append(now)


# ---------------------------------------------------------------------------
# Pipeline run helpers
# ---------------------------------------------------------------------------

_RUN_STATUS_FILE  = BASE_DIR / "generated" / "web_run_status.json"
_RUN_LOG_FILE     = BASE_DIR / "generated" / "web_run.log"
_PIPELINE_SUMMARY = BASE_DIR / "generated" / "pipeline_summary.json"


def _pipeline_lock_path() -> Path:
    return BASE_DIR / os.environ.get("DAILY_LOCK_FILE", "generated/daily_run.lock")


def _read_pipeline_lock() -> dict | None:
    p = _pipeline_lock_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_last_error(log_path: Path, max_lines: int = 200) -> str | None:
    """Scan last N lines of log for the last error/exception line."""
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-max_lines:]):
            low = line.lower()
            if any(kw in low for kw in ("error", "exception", "traceback", "critical", "fehler")):
                return line.strip()[:300]
    except Exception:
        pass
    return None


def _read_run_status() -> dict:
    try:
        if _RUN_STATUS_FILE.exists():
            return json.loads(_RUN_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _read_pipeline_summary() -> dict:
    try:
        if _PIPELINE_SUMMARY.exists():
            return json.loads(_PIPELINE_SUMMARY.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_run_status(data: dict) -> None:
    _RUN_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUN_STATUS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def _monitor_pipeline(proc: subprocess.Popen) -> None:
    """Wait for pipeline to exit, then write status to web_run_status.json."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, proc.wait)
    last_error = None
    if proc.returncode != 0:
        last_error = _extract_last_error(_RUN_LOG_FILE)
    _write_run_status({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "exit_code":   proc.returncode,
        "last_error":  last_error,
    })
    logger.info("Pipeline PID %d exited (code %d)", proc.pid, proc.returncode)


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------

def _read_env_raw() -> str:
    if not ENV_FILE.exists():
        return ""
    return ENV_FILE.read_text(encoding="utf-8")


def _write_env_raw(content: str) -> None:
    ENV_FILE.write_text(content, encoding="utf-8")


def _get_env_value(key: str) -> str:
    """Read a single key from the .env file."""
    values = dotenv_values(ENV_FILE)
    return values.get(key, "") or ""


def _set_env_keys(updates: dict[str, str]) -> None:
    """Update multiple keys in the .env file in-place using regex."""
    content = _read_env_raw()
    for key, value in updates.items():
        pattern = rf"(?m)^({re.escape(key)}\s*=).*$"
        replacement = rf"\g<1>{value}"
        new_content, count = re.subn(pattern, replacement, content)
        if count:
            content = new_content
        else:
            # Key not found – append it
            if not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"
            logger.info("Appended new key %s to .env", key)
    _write_env_raw(content)


def _csv_to_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _list_to_csv(items: list[str]) -> str:
    return ",".join(items)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Preferences(BaseModel):
    locations: list[str] | None = None
    include_keywords: list[str] | None = None
    sources: list[str] | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_path), media_type="text/html")


@app.get("/preferences")
async def get_preferences(_: None = Depends(require_auth)) -> JSONResponse:
    try:
        locations = _csv_to_list(_get_env_value("SEARCH_LOCATIONS"))
        keywords = _csv_to_list(_get_env_value("SEARCH_KEYWORDS"))
        sources = _csv_to_list(_get_env_value("ENABLED_SOURCES"))
        return JSONResponse({
            "locations": locations,
            "include_keywords": keywords,
            "sources": sources,
        })
    except Exception as exc:
        logger.exception("Error reading preferences: %s", exc)
        return JSONResponse({"error": "Could not read preferences"}, status_code=500)


@app.post("/preferences")
async def set_preferences(
    body: Preferences,
    _: None = Depends(require_auth),
) -> JSONResponse:
    try:
        updates: dict[str, str] = {}

        if body.locations is not None:
            csv_val = _list_to_csv(body.locations)
            updates["SEARCH_LOCATIONS"] = csv_val
            updates["ALLOWED_LOCATIONS"] = csv_val
            updates["HARD_ALLOWED_LOCATIONS"] = csv_val
            logger.info(
                "Updating locations (%d entries): %s",
                len(body.locations),
                csv_val[:80] + ("…" if len(csv_val) > 80 else ""),
            )

        if body.include_keywords is not None:
            updates["SEARCH_KEYWORDS"] = _list_to_csv(body.include_keywords)

        if body.sources is not None:
            updates["ENABLED_SOURCES"] = _list_to_csv(body.sources)

        if updates:
            _set_env_keys(updates)
            logger.info("Preferences updated: %s", list(updates.keys()))

        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.exception("Error saving preferences: %s", exc)
        return JSONResponse({"error": "Could not save preferences"}, status_code=500)


@app.post("/run/start")
async def run_start(_: None = Depends(require_auth)) -> JSONResponse:
    lock = _read_pipeline_lock()
    if lock:
        return JSONResponse({
            "status":     "already_running",
            "pid":        lock.get("pid"),
            "started_at": lock.get("started_at"),
        })
    try:
        _RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(_RUN_LOG_FILE, "a", encoding="utf-8")  # noqa: WPS515
        log_fh.write(
            f"\n\n=== Web-triggered run {datetime.now(timezone.utc).isoformat()} ===\n"
        )
        log_fh.flush()
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.daily_run"],
            cwd=str(BASE_DIR),
            stdout=log_fh,
            stderr=log_fh,
        )
        log_fh.close()  # parent closes its copy; child keeps writing via inherited fd
        asyncio.create_task(_monitor_pipeline(proc))
        logger.info("Pipeline gestartet: PID %d → %s", proc.pid, _RUN_LOG_FILE)
        return JSONResponse({"status": "started", "pid": proc.pid})
    except Exception as exc:
        logger.exception("Pipeline-Start fehlgeschlagen: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/run/status")
async def run_status(_: None = Depends(require_auth)) -> JSONResponse:
    lock    = _read_pipeline_lock()
    last    = _read_run_status()
    summary = _read_pipeline_summary()
    return JSONResponse({
        "running":                 lock is not None,
        "pid":                     lock.get("pid") if lock else None,
        "started_at":              lock.get("started_at") if lock else None,
        "last_finished_at":        last.get("finished_at"),
        "last_exit_code":          last.get("exit_code"),
        "last_error":              last.get("last_error"),
        "scraped":                 summary.get("scraped"),
        "after_hard_filter":       summary.get("after_hard_filter"),
        "after_detail_filter":     summary.get("after_detail_filter"),
        "detail_phrase_hits":      summary.get("detail_phrase_hits"),
        "after_llm":               summary.get("after_llm"),
        "digested":                summary.get("digested"),
    })


@app.get("/locations/nearby")
async def locations_nearby(
    request: Request,
    q: str = Query(..., description="City/place name to geocode"),
    radius_km: int = Query(20, ge=1, le=100, description="Search radius in km (1–100)"),
    _: None = Depends(require_auth),
) -> JSONResponse:
    # Rate limit by IP
    client_ip = request.client.host if request.client else "unknown"
    try:
        _check_rate_limit(client_ip)
    except HTTPException:
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)

    # Clamp radius
    radius_km = max(1, min(100, radius_km))
    radius_m = radius_km * 1000

    logger.info("Nearby search: q=%r radius_km=%d", q, radius_km)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1 – Nominatim geocoding
            nominatim_resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "ch,de,at,li",
                },
                headers={"User-Agent": "BewerbungsagentClaude/1.0"},
                timeout=10,
            )
            nominatim_resp.raise_for_status()
            geo_results = nominatim_resp.json()

            if not geo_results:
                logger.warning("Nominatim returned no results for %r", q)
                return JSONResponse({"locations": [], "center": q, "found": False})

            lat = float(geo_results[0]["lat"])
            lon = float(geo_results[0]["lon"])
            logger.info("Geocoded %r → lat=%f lon=%f", q, lat, lon)

            # Step 2 – Overpass query with exact radius
            overpass_query = (
                f"[out:json][timeout:20];"
                f"(node(around:{radius_m},{lat},{lon})"
                f'["place"~"^(city|town)$"]["name"];);'
                f"out tags;"
            )
            overpass_resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": overpass_query},
                timeout=25,
            )
            overpass_resp.raise_for_status()
            overpass_data = overpass_resp.json()

            elements: list[dict[str, Any]] = overpass_data.get("elements", [])

            if not elements:
                logger.info("Overpass returned no elements for %r radius=%dkm", q, radius_km)
                return JSONResponse({"locations": [], "center": q, "found": False})

            # Step 3 – Extract names, prefer name:de
            seen: set[str] = set()
            names: list[str] = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name:de") or tags.get("name")
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

            sorted_names = sorted(names)
            logger.info(
                "Nearby search for %r radius=%dkm → %d locations",
                q, radius_km, len(sorted_names),
            )
            return JSONResponse({
                "locations": sorted_names,
                "center": q,
                "found": True,
            })

    except httpx.TimeoutException as exc:
        logger.warning("Timeout during nearby search for %r: %s", q, exc)
        return JSONResponse({"locations": [], "center": q, "found": False})
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP error during nearby search for %r: %s", q, exc)
        return JSONResponse({"locations": [], "center": q, "found": False})
    except Exception as exc:
        logger.exception("Unexpected error in nearby search for %r: %s", q, exc)
        return JSONResponse({"locations": [], "center": q, "found": False})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.server:app", host="0.0.0.0", port=8765, reload=False)
