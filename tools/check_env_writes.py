#!/usr/bin/env python3
"""Detect unsafe writes/copies of .env files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", "logs", "generated", "out", "data", "04_Versendete_Bewerbungen"}
INCLUDE_EXTS = {".py", ".sh", ".ps1", ".bat", ".cmd", ".js", ".ts", ".md", ".yml", ".yaml", ".json", ".txt"}

WRITE_RULES = [
    (re.compile(r"open\([^)]*\.env[^)]*['\"]\s*,\s*['\"][wax]"), "open() writes .env"),
    (re.compile(r"write_text\([^)]*\.env"), "Path.write_text() to .env"),
    (re.compile(r"write_bytes\([^)]*\.env"), "Path.write_bytes() to .env"),
    (re.compile(r"writeFile(?:Sync)?\s*\([^)]*\.env", re.IGNORECASE), "writeFile* to .env"),
    (re.compile(r"Set-Content\s+[^\n]*\.env", re.IGNORECASE), "Set-Content .env"),
    (re.compile(r"Add-Content\s+[^\n]*\.env", re.IGNORECASE), "Add-Content .env"),
    (re.compile(r"Copy-Item\s+[^\n]*\.env\.example\s+\.env", re.IGNORECASE), "Copy-Item .env.example .env"),
    (re.compile(r"\bcopy\s+[^\n]*\.env\.example\s+\.env", re.IGNORECASE), "copy .env.example .env"),
    (re.compile(r"\bcp\s+[^\n]*\.env\.example\s+\.env", re.IGNORECASE), "cp .env.example .env"),
    (re.compile(r">\s*\.env"), "Shell redirect to .env"),
]

SAFE_GUARDS = (
    "Test-Path .env",
    "-f .env",
    "if not exist .env",
    "if not exist \".env\"",
    "if(!(Test-Path .env))",
    "if (! (Test-Path .env))",
)

ENV_ALIAS_ASSIGN = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]\.env['\"]")


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def has_guard(line: str) -> bool:
    return any(token in line for token in SAFE_GUARDS)


def scan_file(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []

    env_aliases = {
        m.group("name")
        for m in (ENV_ALIAS_ASSIGN.match(l.strip()) for l in lines)
        if m
    }

    findings = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if ".env" not in stripped and not any(alias in stripped for alias in env_aliases):
            continue

        for pattern, message in WRITE_RULES:
            if pattern.search(stripped):
                if has_guard(stripped):
                    break
                findings.append((path, lineno, message, stripped))
                break
        else:
            if env_aliases and any(alias in stripped for alias in env_aliases):
                if re.search(r"open\([^)]*['\"][wax]", stripped):
                    if not has_guard(stripped):
                        findings.append((path, lineno, "open() on env alias with write/append", stripped))
    return findings


def main() -> int:
    findings = []
    for path in ROOT.rglob("*"):
        if path.is_dir() or is_excluded(path):
            continue
        if path.resolve() == THIS_FILE:
            continue
        if path.suffix.lower() not in INCLUDE_EXTS:
            continue
        findings.extend(scan_file(path))

    if findings:
        print("Unsafe .env writes/copies detected:")
        for path, lineno, message, snippet in findings:
            rel = path.relative_to(ROOT)
            print(f"- {rel}:{lineno}: {message}: {snippet}")
        return 1

    print("Env write guard: no unsafe .env writes/copies detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
