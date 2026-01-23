# Code Map (Python)

Kurze Uebersicht der wichtigsten Python-Dateien und wofuer Agenten sie brauchen.

- `tasks.py` - CLI-Entry (Parser + Dispatch) fuer `mail-list`, `tracker-ui`, `mark-*`, `prepare-applications`, `send-applications`.
- `tools/commands/` - CLI-Command-Implementierungen (aus tasks.py ausgelagert).
- `bewerbungsagent/job_collector.py` - Kern-Scraper/Collector; sammelt Jobs, filtert, scored, exportiert `jobs.json`/CSV.
- `bewerbungsagent/job_adapters_ch.py` - Portal-spezifische Scraper fuer jobs.ch/jobup.ch inkl. Detail-Parsing.
- `bewerbungsagent/job_adapters_extra.py` - Adapter fuer weitere Jobportale (z.B. jobscout24, jobwinner, careerjet, jobrapido, monster, jora, jooble).
- `bewerbungsagent/job_state.py` - Lifecycle-State Store (job_state.json), UID-Building, Reminder-Logik.
- `bewerbungsagent/job_tracker.py` - XLSX/CSV Tracker-Export + Sync von Markierungen (erledigt/aktion).
- `bewerbungsagent/tracker_ui.py` - Lokale UI fuer Klick-Markierungen und Dokument-Download.
- `bewerbungsagent/email_automation.py` - Baut/sendet Job-Alert E-Mails und formatiert Listen.
- `bewerbungsagent/job_query_builder.py` - Baut Such-URLs fuer Portale aus Config.
- `bewerbungsagent/job_text_utils.py` - Gemeinsame Text-Parser/Heuristiken (Multi-Line-Titel).
- `bewerbungsagent/config.py` - Laedt `.env` und stellt Konfigwerte bereit.
- `bewerbungsagent/logger.py` - Zentrales Logging (Konsole + rotierende Logs).
- `bewerbungsagent/notifier_whatsapp.py` - Optionaler WhatsApp-Notifier (falls aktiviert).
- `scripts/direkt_job_finder.py` - Direkter Portal-Opener + Template/Tracking-Generator fuer manuelle Nutzung.
- `tools/test_email_config.py` - SMTP/Testskript fuer E-Mail-Setup.

Tools/Helper:
- `tools/update_templates.py` - Erstellt/aktualisiert DOCX-Templates.
- `tools/csv_to_jobs_json.py` - Konvertiert `generated/jobs_latest.csv` zu `data/jobs.json`.
- `tools/check_env_writes.py` - Sucht nach unsicheren `.env`-Writes im Repo.

## Wiederverwendbar
- `bewerbungsagent/job_state.py` ? UID-/State-Logik (mehrfach genutzt)
- `bewerbungsagent/job_tracker.py` ? Tracker-IO (CSV/XLSX)
- `bewerbungsagent/job_text_utils.py` ? Text-Parsing/Heuristiken
- `bewerbungsagent/email_automation.py` ? Mail-Rendering/Versand

## Kritische Abhaengigkeiten
- Selenium + `webdriver_manager` (Browser/Driver)
- `requests` (HTTP-Adapter, Detail-Scans)
- `openpyxl` (Tracker XLSX)
- `python-docx` (Bewerbungs-Templates)

## Vorsicht bei Aenderungen
- `bewerbungsagent/job_state.py`: UID-Bildung und State-Schema
- `bewerbungsagent/job_collector.py`: Filter/Scoring beeinflusst Mail-Output
- `tools/commands/mail_list.py`: Reminder-/Lifecycle-Flow
- `bewerbungsagent/tracker_ui.py`: API/Download-Paths
