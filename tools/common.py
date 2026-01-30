from __future__ import annotations

from typing import Any
import os


TRUTHY = {"1", "true", "t", "yes", "y", "ja", "j"}


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return str(value).strip().lower() in TRUTHY


def env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def is_dry_run(args: Any) -> bool:
    return bool(args and getattr(args, "dry_run", False))


def as_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def score_value(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def parse_sources(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for raw in values:
        for part in (raw or "").split(","):
            item = part.strip()
            if item:
                out.append(item)
    return out
