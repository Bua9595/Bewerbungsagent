from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bewerbungsagent.job_text_utils import extract_from_multiline_title


def env_check(_args=None) -> None:
    from bewerbungsagent.config import config

    print("=== ENV/Cfg ===")
    print("Sender:", config.SENDER_EMAIL or "<leer>")
    print("SMTP:", config.SMTP_SERVER or "<leer>", config.SMTP_PORT)
    print("Recipients:", config.RECIPIENT_EMAILS or [])
    print(
        "Profile:",
        getattr(config, "PROFILE_NAME", ""),
        getattr(config, "PROFILE_EMAIL", ""),
    )
    pwd_len = len(config.SENDER_PASSWORD or "")
    print("Password set:", "Yes" if pwd_len else "No", "(len=", pwd_len, ")")


def generate_templates(_args=None) -> None:
    from scripts.direkt_job_finder import DirectJobFinder

    app = DirectJobFinder()
    app.save_application_templates()
    app.create_job_tracking_sheet()
    print("Templates/Tracking aktualisiert.")


def start_job_hunt(_args=None) -> None:
    from scripts.direkt_job_finder import DirectJobFinder

    DirectJobFinder().run_complete_job_hunt()


def open_portals(_args=None) -> None:
    from scripts.direkt_job_finder import DirectJobFinder

    DirectJobFinder().open_job_portals_automatically()


def email_test(_args=None) -> None:
    from tools.test_email_config import test_email_connection

    success, output_lines = test_email_connection()
    for line in output_lines:
        print(line)
    raise SystemExit(0 if success else 1)


def list_jobs(_args=None) -> None:
    from bewerbungsagent.job_collector import collect_jobs, export_csv, export_json

    jobs = collect_jobs()
    if not jobs:
        print("Keine Treffer. CSV/Mail uebersprungen.")
        return
    export_csv(jobs)
    export_json(jobs)
    for i, job in enumerate(jobs[:20], 1):
        company = job.company
        location = job.location
        if (not company or not location) and (job.raw_title or job.title):
            t2, c2, l2 = extract_from_multiline_title(job.raw_title or job.title)
            if t2:
                job.title = t2
            if not company and c2:
                company = c2
            if not location and l2:
                location = l2

        company = company or "Firma unbekannt"
        location = location or "Ort unbekannt"
        print(f"{i:02d}. [{job.match:^5}] {job.title} - {company} - {location}")
        print(f"    {job.link}")


def verify(_args=None) -> None:
    ok = True
    try:
        from bewerbungsagent.config import config

        config.validate_config()
        print("Config: OK")
    except Exception as exc:
        ok = False
        print(f"Config-Check fehlgeschlagen: {exc}")

    required_dirs = ["Anschreiben_Templates", "out", "data"]
    for d in required_dirs:
        if not Path(d).exists():
            ok = False
            print(f"FEHLT: {d}")
    for tpl in ["T1_ITSup.docx", "T2_Systemtechnik.docx", "T3_Logistik.docx"]:
        if not (Path("Anschreiben_Templates") / tpl).exists():
            ok = False
            print(f"Template fehlt: Anschreiben_Templates/{tpl}")

    try:
        subprocess.check_call(
            [sys.executable, "-m", "compileall", "."],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("compileall: OK")
    except Exception as exc:
        ok = False
        print(f"compileall fehlgeschlagen: {exc}")

    print("Verify: OK" if ok else "Verify: FEHLER")
