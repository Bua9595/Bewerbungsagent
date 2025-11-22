# Bewerbungsagent

Automatisiert Jobs sammeln -> filtern -> mailen -> Anschreiben erzeugen -> Tracking pflegen. Geheimnisse bleiben in `.env` (nicht im Repo).

## Finales Ziel und aktueller Stand
- AG1 Collector: jobs.ch/jobup/Indeed scrapen, normalisieren, dedupen, scoren, lokal filtern; `data/jobs.json` schreiben; Mail mit allen neuen lokalen Treffern. **Status:** laeuft, Mail-Output korrekt, Hardcut auf Orte aktiv.
- AG2 Applicant: `prepare-applications` liest `data/jobs.json` (fit=="OK"), fuellt DOCX-Templates, schreibt `out/`, tracked in `bewerbungen_tracking.csv`. **Status:** laeuft; Kopie nach `04_Versendete_Bewerbungen/<Firma>/` noch offen.
- AG3 QA/Betrieb: README/Quickstart, env.example, verify, Scheduler (taeglich). **Status:** README aktualisiert; env.example/verify/Scheduler offen.

Roadmap (kurz):
1) Kopie jeder versendeten Bewerbung nach `04_Versendete_Bewerbungen/<Firma>/...`.
2) env.example + verify-script + Scheduler fuer `mail-list` taeglich.
3) Optional: feinere Pendelzeit/PLZ-Filter.

## Quickstart (Windows / PowerShell)
```pwsh
python -m venv .venv
.\\.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env   # .env befuellen
```

### .env ausfuellen (Minimal)
- `SENDER_EMAIL`, `SENDER_PASSWORD`, `SMTP_SERVER`, `SMTP_PORT` (Gmail: smtp.gmail.com / 587, App-Passwort)
- `RECIPIENT_EMAILS` (Komma-getrennt)
- `SEARCH_LOCATIONS=Buelach` (oder nahe Orte), `LOCATION_RADIUS_KM=25`
- Optional: `SEARCH_KEYWORDS`, `ENABLED_SOURCES`, `EMAIL_MAX_JOBS`

## Nutzung (haeufigste Commands)
- `python tasks.py env-check` – zeigt SMTP/Empfaenger/Profil
- `python tasks.py mail-list` – sammelt Jobs, filtert auf lokale Orte, mailt alle Treffer (Soft-Cap per `EMAIL_MAX_JOBS`)
- `python tasks.py list` – sammelt und gibt Textliste + CSV aus
- `python tasks.py prepare-applications [--force-all]` – erzeugt Anschreiben aus `data/jobs.json` (fit=="OK") in `out/`, tracked in `bewerbungen_tracking.csv`
- `python tasks.py gen-templates` – aktualisiert Templates/Tracker-Header
- `python tasks.py email-test` – SMTP-Test

## Verhalten / Filter
- Standard-Orte: Buelach/Kloten/Zuerich (ASCII; per .env setzbar). Harte Ortsfilter: Titel/Location/Raw-Title muss einen Ort enthalten, sonst Drop.
- Score/Match: Keywords/Negativliste steuern Scoring; `MIN_SCORE_MAIL` (Default 2) filtert fuer Mail.
- Mail-Body: parst jobs.ch/jobup-Multiline-Titel (Arbeitsort/Firma), zeigt Quelle/Match/Score; Soft-Cap `EMAIL_MAX_JOBS` (Default 200).

## Dateien/Ordner
- `data/jobs.json` – letzter Job-Snapshot
- `Anschreiben_Templates/` – Templates (`T1_ITSup.docx`, `T2_Systemtechnik.docx`, `T3_Logistik.docx`)
- `out/` – generierte Anschreiben
- `bewerbungen_tracking.csv` – Tracker (wird bei Bedarf angelegt/erweitert)
- `04_Versendete_Bewerbungen/` – Ziel fuer Kopien nach Versand (noch umzusetzen)

## Troubleshooting
- Encoding: Repo ist UTF-8; wenn PowerShell � zeigt, liegt es an der Konsole, nicht an den Dateien.
- Zu wenige Jobs: `SEARCH_LOCATIONS` erweitern oder `MIN_SCORE_MAIL` senken; Cap per `EMAIL_MAX_JOBS`.
- Zu viele/weite Jobs: Orte eng fassen, `LOCATION_RADIUS_KM` niedrig halten; Hardcut aktiv.
- Leere Firma/Ort in Mail: sicherstellen, dass `raw_title` ankommt (collect_jobs tut das). Falls nicht, Payload pruefen.
- SMTP: Bei 2FA Gmail App-Passwort nutzen; Outlook: `smtp-mail.outlook.com:587`. `python tasks.py email-test` prueft Zugang.

## Datenschutz
- `.env`, Logs, generierte Bewerbungen sind per `.gitignore` ausgeschlossen. Keine Geheimnisse committen.

## Erweiterte ENV (optional)
- `EXPORT_CSV=true` – exportiert Treffer nach `generated/jobs_latest.csv`
- `EXPORT_CSV_PATH=generated/jobs_latest.csv` – Zielpfad fuer CSV
- `MIN_SCORE_MAIL=2` – Mindestscore fuer Mail-Versand
- `LOCATION_BOOST_KM=15` – heuristischer Boost (String-Match Location)
- `BLACKLIST_COMPANIES=` – Komma-Liste ignorierter Firmen
- `BLACKLIST_KEYWORDS=junior` – Titel-Keywords zum Ausschluss
- `ENABLED_SOURCES=indeed,jobs.ch,jobup.ch` – Komma-Liste; leer = alle aktiv
- WhatsApp Cloud API (aus, falls nicht gesetzt): `WHATSAPP_ENABLED=false`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TO`
