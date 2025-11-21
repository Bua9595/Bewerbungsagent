#!/usr/bin/env python3
"""
Einfache Task-CLI für den Bewerbungsagenten.

Beispiele:
  python tasks.py env-check
  python tasks.py gen-templates
  python tasks.py start
  python tasks.py open
  python tasks.py email-test
"""

import argparse
import os


def cmd_env_check(_args=None):
    from config import config
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
    print(
        "Password set:",
        "Yes" if pwd_len else "No",
        "(len=",
        pwd_len,
        ")",
    )


def cmd_gen_templates(_args=None):
    from direkt_job_finder import DirectJobFinder
    app = DirectJobFinder()
    app.save_application_templates()
    app.create_job_tracking_sheet()
    print("Templates/Tracking aktualisiert.")


def cmd_start(_args=None):
    from direkt_job_finder import DirectJobFinder
    DirectJobFinder().run_complete_job_hunt()


def cmd_open(_args=None):
    from direkt_job_finder import DirectJobFinder
    DirectJobFinder().open_job_portals_automatically()


def cmd_email_test(_args=None):
    # nutzt das getestete Testskript, das (bool, lines) zurückgibt
    from test_email_config import test_email_connection

    success, output_lines = test_email_connection()
    for line in output_lines:
        print(line)

    raise SystemExit(0 if success else 1)


def cmd_list(_args=None):
    from job_collector import collect_jobs, format_jobs_plain, export_csv
    jobs = collect_jobs()
    if not jobs:
        print("Keine Treffer. CSV/Mail übersprungen.")
        return
    export_csv(jobs)
    print(format_jobs_plain(jobs))


def cmd_mail_list(_args=None):
    from job_collector import collect_jobs, export_csv
    from email_automation import EmailAutomation

    try:
        from notifier_whatsapp import send_whatsapp
    except Exception:
        def send_whatsapp(_txt: str) -> bool:
            return False

    min_score = int(os.getenv("MIN_SCORE_MAIL", "2") or 2)
    rows = collect_jobs()
    filtered = [
        r for r in rows
        if r.match in {"exact", "good"} and r.score >= min_score
    ]

    if not filtered:
        print("Keine passenden Treffer. Mail/WhatsApp übersprungen.")
        return

    export_csv(filtered)

    jobs_payload = [
        {"title": r.title, "company": r.company, "location": r.location, "link": r.link}
        for r in filtered
    ]
    ok = EmailAutomation().send_job_alert(jobs_payload)
    print("E-Mail gesendet" if ok else "E-Mail nicht gesendet (deaktiviert oder Fehler)")

    try:
        send_whatsapp(f"[Bewerbungsagent] {len(filtered)} Treffer gesendet.")
    except Exception as e:
        print(f"WhatsApp Hinweis fehlgeschlagen: {e}")


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env-check")
    sub.add_parser("gen-templates")
    sub.add_parser("start")
    sub.add_parser("open")
    sub.add_parser("email-test")
    sub.add_parser("list")
    sub.add_parser("mail-list")

    args = p.parse_args(argv)

    if args.cmd == "env-check":
        cmd_env_check(args)
    elif args.cmd == "gen-templates":
        cmd_gen_templates(args)
    elif args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "open":
        cmd_open(args)
    elif args.cmd == "email-test":
        cmd_email_test(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "mail-list":
        cmd_mail_list(args)


if __name__ == "__main__":
    main()
