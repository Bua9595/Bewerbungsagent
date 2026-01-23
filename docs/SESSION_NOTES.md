# Sitzungsnotizen – Bewerbungsagent

Datum: automatisch erstellt

## Status
- Öffentliches Repo angelegt und initialer Push erfolgt.
- CLI-Commands nach `tools/commands/` ausgelagert; `tasks.py` ist nur Parser/Dispatch.
- .gitignore schützt `.env`, Logs, generierte Dateien und persönliche Dokumente.
- `.env.example` vorhanden; reale `.env` bleibt lokal.
- PII aus Code entfernt; Profilfelder (Name/Email/LinkedIn) kommen aus ENV.
- Tasks-CLI (`tasks.py`) und README hinzugefügt.
- GitHub Actions (CI) mit Lint (soft) + Syntax/Import‑Checks aktiv.
- E‑Mail‑Versand über ENV‑Flags steuerbar (`EMAIL_NOTIFICATIONS_ENABLED` usw.).

## Wichtige Entscheidungen
- Keine Geheimnisse im Repo; `.env` wird ignoriert.
- Gmail: Empfehlung App‑Passwort statt Kontopasswort; OAuth2 optional später.
- Lint nicht blockierend, um Entwicklung nicht zu bremsen.

## Nächste Schritte (Vorschläge)
- Falls SMTP produktiv: Gmail‑App‑Passwort erstellen und in `.env` setzen.
- GROQ‑Key ggf. rotieren und lokal in `.env` aktualisieren.
- CI verschärfen (Lint blocking) – optional.
- Optional: zusätzliche Portale/Filter in `job_query_builder.py` erweitern.
- Optional: OAuth2‑Flow für Gmail/Outlook ergänzen (separates Skript).

## Nützliche Befehle
- `python tasks.py env-check` – Übersicht der geladenen ENV (ohne Secrets)
- `python tasks.py gen-templates` – Vorlagen/Tracking erzeugen
- `python tasks.py start` – Links aktualisieren, Anzeige/optional öffnen
- `python tasks.py open` – Portale direkt öffnen
- `python tasks.py email-test` – SMTP‑Verbindung testen (wenn aktiviert)
- `python tools/test_email_config.py` - SMTP-Test (Script)

## Hinweise
- Auf neuem Gerät: Repo klonen, `pip install -r requirements.txt`, `.env` aus `.env.example` anlegen und füllen.
- E‑Mails deaktivieren: `EMAIL_NOTIFICATIONS_ENABLED=false` in `.env`.

