#!/usr/bin/env python3
"""
Test-Skript für die E-Mail-Konfiguration.
Gibt IMMER (success: bool, output_lines: list[str]) zurück.
"""

import os
import sys
import smtplib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bewerbungsagent.config import config
from bewerbungsagent.email_automation import EmailAutomation


def test_config():
    """Prüft ENV/Config und gibt (ok, lines) zurück."""
    output = []
    output.append("=== E-Mail Konfiguration Test ===")

    env_pwd = os.getenv("SENDER_PASSWORD", "")
    output.append(f"Env SENDER_PASSWORD exists: {'Yes' if env_pwd else 'No'}")
    output.append(f"Env SENDER_PASSWORD value length: {len(env_pwd)}")

    output.append(f"Sender Email: {config.SENDER_EMAIL}")
    output.append(f"SMTP Server: {config.SMTP_SERVER}")
    output.append(f"SMTP Port: {config.SMTP_PORT}")
    output.append(f"Recipient Emails: {config.RECIPIENT_EMAILS}")

    pwd_len = len(config.SENDER_PASSWORD or "")
    password_set = pwd_len > 0
    output.append(f"Config Password configured: {'Yes' if password_set else 'No'}")
    output.append(f"Config Password length: {pwd_len}")

    if not password_set:
        output.append("ERROR: SENDER_PASSWORD ist nicht konfiguriert!")
        output.append("Stelle sicher, dass .env SENDER_PASSWORD enthält und geladen wird.")
        return False, output

    output.append("OK. Konfiguration scheint korrekt zu sein.")
    return True, output


def test_email_connection():
    """Testet SMTP Login und gibt (ok, lines) zurück."""
    output = []
    output.append("=== E-Mail Verbindung Test ===")

    config_ok, config_output = test_config()
    output.extend(config_output)

    if not config_ok:
        return False, output

    try:
        email_auto = EmailAutomation()

        server = smtplib.SMTP(email_auto.smtp_server, email_auto.smtp_port, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(email_auto.sender_email, email_auto.sender_password)
        server.quit()

        output.append("OK. E-Mail-Verbindung erfolgreich!")
        return True, output

    except Exception as e:
        output.append(f"ERROR: E-Mail-Verbindung fehlgeschlagen: {e}")
        return False, output


if __name__ == "__main__":
    success, lines = test_email_connection()
    for line in lines:
        print(line)
    sys.exit(0 if success else 1)
