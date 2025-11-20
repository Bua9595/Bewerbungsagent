#!/usr/bin/env python3
"""
Test-Skript für die E-Mail-Konfiguration
"""

from __future__ import annotations

import os
import smtplib
import sys
from typing import List, Tuple

from config import config
from email_automation import EmailAutomation


def _config_check() -> Tuple[bool, List[str]]:
    """Prüft Konfiguration und liefert (ok, output_lines)."""
    output: List[str] = []
    output.append("=== E-Mail Konfiguration Test ===")

    sender_pw_env = os.getenv("SENDER_PASSWORD", "")
    output.append(
        f"Env SENDER_PASSWORD exists: {'Yes' if sender_pw_env else 'No'}"
    )
    output.append(f"Env SENDER_PASSWORD value length: {len(sender_pw_env)}")

    output.append(f"Sender Email: {config.SENDER_EMAIL}")
    output.append(f"SMTP Server: {config.SMTP_SERVER}")
    output.append(f"SMTP Port: {config.SMTP_PORT}")
    output.append(f"Recipient Emails: {config.RECIPIENT_EMAILS}")

    password_set = bool(config.SENDER_PASSWORD)
    output.append(
        f"Config Password configured: {'Yes' if password_set else 'No'}"
    )
    output.append(
        f"Config Password length: {len(config.SENDER_PASSWORD) if password_set else 0}"
    )

    if not password_set:
        output.append("ERROR: SENDER_PASSWORD ist nicht konfiguriert!")
        output.append(
            "Bitte stelle sicher, dass die .env-Datei SENDER_PASSWORD enthält."
        )
        output.append(
            "Oder überprüfe, ob python-dotenv korrekt funktioniert."
        )
        return False, output

    output.append("OK. Konfiguration scheint korrekt zu sein.")
    return True, output


def _email_connection_check() -> Tuple[bool, List[str]]:
    """Testet die SMTP-Verbindung und liefert (ok, output_lines)."""
    output: List[str] = []
    output.append("=== E-Mail Verbindung Test ===")

    config_ok, config_output = _config_check()
    output.extend(config_output)

    if not config_ok:
        return False, output

    try:
        email_auto = EmailAutomation()

        server = smtplib.SMTP(
            email_auto.smtp_server, email_auto.smtp_port, timeout=15
        )
        server.starttls()
        server.login(email_auto.sender_email, email_auto.sender_password)
        server.quit()

        output.append("OK. E-Mail-Verbindung erfolgreich!")
        return True, output

    except Exception as e:
        output.append(f"ERROR: E-Mail-Verbindung fehlgeschlagen: {e}")
        return False, output


def test_config() -> None:
    ok, _ = _config_check()
    assert ok, "E-Mail-Konfiguration ist nicht korrekt (siehe Output)."


def test_email_connection() -> None:
    ok, _ = _email_connection_check()
    assert ok, "E-Mail-Verbindung fehlgeschlagen (siehe Output)."


if __name__ == "__main__":
    success, output_lines = _email_connection_check()

    with open("test_results.txt", "w", encoding="utf-8") as f:
        for line in output_lines:
            f.write(line + "\n")
            print(line)

    if success:
        final_msg = (
            "\nAlle Tests bestanden! Die E-Mail-Funktionalität sollte funktionieren."
        )
    else:
        final_msg = (
            "\nEinige Tests sind fehlgeschlagen. Bitte überprüfe die Konfiguration."
        )

    print(final_msg)
    with open("test_results.txt", "a", encoding="utf-8") as f:
        f.write(final_msg + "\n")

    sys.exit(0 if success else 1)
