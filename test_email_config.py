#!/usr/bin/env python3
"""
Test-Skript für die E-Mail-Konfiguration
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from email_automation import EmailAutomation


def test_config():
    """Testet die Konfiguration"""
    output = []
    output.append("=== E-Mail Konfiguration Test ===")

    # Debug: Überprüfe Umgebungsvariablen direkt
    output.append(f"Env SENDER_PASSWORD exists: {'Yes' if os.getenv('SENDER_PASSWORD') else 'No'}")
    output.append(f"Env SENDER_PASSWORD value length: {len(os.getenv('SENDER_PASSWORD', ''))}")

    output.append(f"Sender Email: {config.SENDER_EMAIL}")
    output.append(f"SMTP Server: {config.SMTP_SERVER}")
    output.append(f"SMTP Port: {config.SMTP_PORT}")
    output.append(f"Recipient Emails: {config.RECIPIENT_EMAILS}")

    # Passwort-Status (ohne das Passwort selbst anzuzeigen)
    password_set = bool(config.SENDER_PASSWORD)
    output.append(f"Config Password configured: {'Yes' if password_set else 'No'}")
    output.append(f"Config Password length: {len(config.SENDER_PASSWORD) if config.SENDER_PASSWORD else 0}")

    if not password_set:
        output.append("ERROR: SENDER_PASSWORD ist nicht konfiguriert!")
        output.append("Bitte stelle sicher, dass die .env-Datei SENDER_PASSWORD enthält.")
        output.append("Oder überprüfe, ob python-dotenv korrekt funktioniert.")
        return False, output

    output.append("OK. Konfiguration scheint korrekt zu sein.")
    return True, output


def test_email_connection():
    """Testet die E-Mail-Verbindung"""
    output = []
    output.append("\n=== E-Mail Verbindung Test ===")

    config_ok, config_output = test_config()
    output.extend(config_output)

    if not config_ok:
        return False, output

    try:
        email_auto = EmailAutomation()
        # Test-Verbindung ohne E-Mail zu senden
        import smtplib

        server = smtplib.SMTP(email_auto.smtp_server, email_auto.smtp_port)
        server.starttls()
        server.login(email_auto.sender_email, email_auto.sender_password)
        server.quit()

        output.append("OK. E-Mail-Verbindung erfolgreich!")
        return True, output

    except Exception as e:
        output.append(f"ERROR: E-Mail-Verbindung fehlgeschlagen: {str(e)}")
        return False, output


if __name__ == "__main__":
    success, output_lines = test_email_connection()

    # Schreibe Ausgabe in Datei
    with open("test_results.txt", "w", encoding="utf-8") as f:
        for line in output_lines:
            f.write(line + "\n")
            print(line)  # Auch auf Konsole ausgeben

    if success:
        final_msg = "\nAlle Tests bestanden! Die E-Mail-Funktionalität sollte funktionieren."
    else:
        final_msg = "\nEinige Tests sind fehlgeschlagen. Bitte überprüfe die Konfiguration."

    print(final_msg)
    with open("test_results.txt", "a", encoding="utf-8") as f:
        f.write(final_msg + "\n")

    sys.exit(0 if success else 1)
