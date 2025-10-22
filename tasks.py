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
import sys


def cmd_env_check():
    from config import config
    print("=== ENV/Cfg ===")
    print("Sender:", config.SENDER_EMAIL or "<leer>")
    print("SMTP:", config.SMTP_SERVER or "<leer>", config.SMTP_PORT)
    print("Recipients:", config.RECIPIENT_EMAILS or [])
    print("Profile:", getattr(config, "PROFILE_NAME", ""), getattr(config, "PROFILE_EMAIL", ""))
    pwd_len = len(config.SENDER_PASSWORD or "")
    print("Password set:", "Yes" if pwd_len else "No", "(len=", pwd_len, ")")


def cmd_gen_templates():
    from direkt_job_finder import DirectJobFinder
    app = DirectJobFinder()
    app.save_application_templates()
    app.create_job_tracking_sheet()
    print("Templates/Tracking aktualisiert.")


def cmd_start():
    from direkt_job_finder import DirectJobFinder
    DirectJobFinder().run_complete_job_hunt()


def cmd_open():
    from direkt_job_finder import DirectJobFinder
    DirectJobFinder().open_job_portals_automatically()


def cmd_email_test():
    try:
        import test_email_config as t
        ok, out = t.test_email_connection()
        for line in out:
            print(line)
        print("Result:", "OK" if ok else "FAILED")
        sys.exit(0 if ok else 1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("env-check")
    sub.add_parser("gen-templates")
    sub.add_parser("start")
    sub.add_parser("open")
    sub.add_parser("email-test")
    args = p.parse_args(argv)

    if args.cmd == "env-check":
        cmd_env_check()
    elif args.cmd == "gen-templates":
        cmd_gen_templates()
    elif args.cmd == "start":
        cmd_start()
    elif args.cmd == "open":
        cmd_open()
    elif args.cmd == "email-test":
        cmd_email_test()


if __name__ == "__main__":
    main()

