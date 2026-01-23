#!/usr/bin/env python3
"""
Einfache Task-CLI fuer den Bewerbungsagenten.

Beispiele:
  python tasks.py env-check
  python tasks.py verify
  python tasks.py gen-templates
  python tasks.py start
  python tasks.py open
  python tasks.py email-test
  python tasks.py list
  python tasks.py mail-list
  python tasks.py mail-list --dry-run
  python tasks.py mail-open
  python tasks.py mail-open --dry-run
  python tasks.py tracker-sync
  python tasks.py tracker-ui
  python tasks.py mark-applied <job_uid>
  python tasks.py mark-ignored --url <link>
  python tasks.py prepare-applications --force-all
  python tasks.py send-applications --dry-run
  python tasks.py archive-sent --file out/example.docx
"""

import argparse

from tools.commands.applications import archive_sent, prepare_applications, send_applications
from tools.commands.basic import (
    email_test,
    env_check,
    generate_templates,
    list_jobs,
    open_portals,
    start_job_hunt,
    verify,
)
from tools.commands.mail_list import send_job_alerts
from tools.commands.tracker import mark_applied, mark_ignored, run_tracker_ui, sync_tracker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env-check")
    sub.add_parser("verify")

    arch = sub.add_parser("archive-sent")
    arch.add_argument("--file", required=True, help="Pfad zur versendeten DOCX (z.B. aus out/)")
    arch.add_argument("--company", default="", help="Optional Firmenname override")
    arch.add_argument(
        "--dest",
        default="",
        help="Basis-Ordner fuer Kopie (default: 04_Versendete_Bewerbungen)",
    )

    sub.add_parser("gen-templates")
    sub.add_parser("start")
    sub.add_parser("open")
    sub.add_parser("email-test")
    sub.add_parser("list")

    mail = sub.add_parser("mail-list")
    mail.add_argument("--dry-run", action="store_true", help="Nur simulieren, keine Mails senden")
    mail.add_argument(
        "--send-open",
        action="store_true",
        help="Statt nur neue Jobs: alle offenen, aktuell gefundenen Jobs senden",
    )

    mail_open = sub.add_parser("mail-open")
    mail_open.add_argument("--dry-run", action="store_true", help="Nur simulieren, keine Mails senden")
    mail_open.set_defaults(send_open=True)

    sub.add_parser("tracker-sync")
    tracker_ui = sub.add_parser("tracker-ui")
    tracker_ui.add_argument("--host", default="127.0.0.1")
    tracker_ui.add_argument("--port", type=int, default=8765)
    tracker_ui.add_argument("--open", action="store_true", help="Browser oeffnen")

    mark_applied_cmd = sub.add_parser("mark-applied")
    mark_applied_cmd.add_argument("job_uid", nargs="?", help="Job UID")
    mark_applied_cmd.add_argument("--url", default="", help="Job URL")

    mark_ignored_cmd = sub.add_parser("mark-ignored")
    mark_ignored_cmd.add_argument("job_uid", nargs="?", help="Job UID")
    mark_ignored_cmd.add_argument("--url", default="", help="Job URL")

    prep = sub.add_parser("prepare-applications")
    prep.add_argument("--proj", default="", help="Projekt-Root (default: cwd)")
    prep.add_argument("--in", dest="in_file", default="", help="Input jobs.json")
    prep.add_argument("--out", dest="out_dir", default="", help="Output-Ordner out/")
    prep.add_argument("--templates", dest="templates_dir", default="", help="Templates-Ordner")
    prep.add_argument("--tracker", default="", help="Tracker CSV")
    prep.add_argument("--force-all", action="store_true", help="Alle Jobs verarbeiten, egal fit")
    prep.add_argument(
        "--mirror-sent",
        action="store_true",
        help=(
            "Optional Kopie der erzeugten Anschreiben in "
            "04_Versendete_Bewerbungen/<Firma>/ ablegen"
        ),
    )
    prep.add_argument(
        "--copy-sent-dir",
        default="",
        help=(
            "Alternativer Basis-Ordner fuer die Kopien (default: "
            "04_Versendete_Bewerbungen im Projekt)"
        ),
    )

    send = sub.add_parser("send-applications")
    send.add_argument("--proj", default="", help="Projekt-Root")
    send.add_argument("--in", dest="in_file", default="", help="Input jobs.json")
    send.add_argument("--out", dest="out_dir", default="", help="Output-Ordner out/")
    send.add_argument("--tracker", default="", help="Tracker CSV")
    send.add_argument("--dry-run", action="store_true", help="Nur simulieren, keine Mails senden")

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "env-check": env_check,
        "verify": verify,
        "archive-sent": archive_sent,
        "gen-templates": generate_templates,
        "start": start_job_hunt,
        "open": open_portals,
        "email-test": email_test,
        "list": list_jobs,
        "mail-list": send_job_alerts,
        "mail-open": send_job_alerts,
        "tracker-sync": sync_tracker,
        "tracker-ui": run_tracker_ui,
        "mark-applied": mark_applied,
        "mark-ignored": mark_ignored,
        "prepare-applications": prepare_applications,
        "send-applications": send_applications,
    }

    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
