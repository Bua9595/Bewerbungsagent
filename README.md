# Bewerbungsagent

Automatisiert Jobs sammeln -> filtern -> mailen -> Anschreiben erstellen -> Tracking pflegen. Alle Geheimnisse bleiben in `.env` (nicht im Repo).

## Finales Ziel, Stand, Roadmap
- **AG1 Collector**: jobs.ch/jobup/Indeed scrapen, normalisieren, dedupen, scoren, lokal filtern; `data/jobs.json` schreiben; Mail mit allen neuen lokalen Treffern. **Status:** läuft, Mail-Output korrekt, Hardcut auf Orte aktiv.
- **AG2 Applicant**: `prepare-applications` liest `data/jobs.json` (fit=="OK"), füllt DOCX-Templates, schreibt `out/`, tracked in `bewerbungen_tracking.csv`. **Status:** läuft; Kopie nach `04_Versendete_Bewerbungen/<Firma>/` noch offen.
- **AG3 QA/Betrieb**: README/Quickstart, env.example, verify, Scheduler (täglich). **Status:** README aktualisiert; env.example/verify/Scheduler noch offen.

**Roadmap kurz**  
1) Kopie jeder versendeten Bewerbung nach `04_Versendete_Bewerbungen/<Firma>/...`.  
2) env.example vervollständigen, leichtes verify-Script/Task, Scheduler für `mail-list` täglich.  
3) Optional: feinere Pendelzeit-/PLZ-Filter.

## Quickstart (Windows / PowerShell)
```pwsh
python -m venv .venv
.\\.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env   # .env befüllen
```

### .env ausfüllen (Minimal)
- `SENDER_EMAIL`, `SENDER_PASSWORD`, `SMTP_SERVER`, `SMTP_PORT` (Gmail: smtp.gmail.com / 587, App-Passwort)
- `RECIPIENT_EMAILS` (Komma-getrennt)
- `SEARCH_LOCATIONS=Buelach` (oder nahe Orte), `LOCATION_RADIUS_KM=25`
- Optional: `SEARCH_KEYWORDS`, `ENABLED_SOURCES`, `EMAIL_MAX_JOBS`

## Nutzung (häufigste Commands)
- `python tasks.py env-check` – zeigt SMTP/Empfänger/Profil
- `python tasks.py verify` – Config/compileall/Verzeichnis-Check
- `python tasks.py mail-list` – sammelt Jobs, filtert auf lokale Orte, mailt alle Treffer (Soft-Cap per `EMAIL_MAX_JOBS`)
- `python tasks.py list` – sammelt und gibt Textliste + CSV aus
- `python tasks.py prepare-applications [--force-all] [--mirror-sent] [--copy-sent-dir <pfad>]` – erzeugt Anschreiben aus `data/jobs.json` (fit=="OK") in `out/`, tracked in `bewerbungen_tracking.csv`; optional Kopie in `04_Versendete_Bewerbungen/<Firma>/`
- `python tasks.py archive-sent --file out/<datei>.docx [--company Firma] [--dest <pfad>]` – manuelles Archivieren einer versendeten Bewerbung nach `04_Versendete_Bewerbungen/`
- `python tasks.py gen-templates` – aktualisiert Templates/Tracker-Header
- `python tasks.py email-test` – SMTP-Test

## Verhalten / Filter
- Standard-Orte: Buelach/Kloten/Zuerich (ASCII; per .env setzbar). Harte Ortsfilter: Titel/Location/Raw-Title muss einen Ort enthalten, sonst Drop.
- Score/Match: Keywords/Negativliste steuern Scoring; `MIN_SCORE_MAIL` (Default 2) filtert für Mail.
- Mail-Body: parst jobs.ch/jobup-Multiline-Titel (Arbeitsort/Firma), zeigt Quelle/Match/Score; Soft-Cap `EMAIL_MAX_JOBS` (Default 200).
- Delta-Mailing: Mail verschickt nur neue Jobs (persistiert in `generated/seen_jobs.json`).

## Dateien/Ordner
- `data/jobs.json` – letzter Job-Snapshot
- `Anschreiben_Templates/` – Templates (`T1_ITSup.docx`, `T2_Systemtechnik.docx`, `T3_Logistik.docx`)
- `out/` – generierte Anschreiben
- `bewerbungen_tracking.csv` – Tracker (wird bei Bedarf angelegt/erweitert)
- `04_Versendete_Bewerbungen/` – Ziel für Kopien nach Versand (wird bei `--mirror-sent` genutzt, sonst manuell)

## Troubleshooting
- Encoding: Repo ist UTF-8; wenn PowerShell � zeigt, liegt es an der Konsole, nicht an den Dateien.
- Zu wenige Jobs: `SEARCH_LOCATIONS` erweitern oder `MIN_SCORE_MAIL` senken; Cap per `EMAIL_MAX_JOBS`.
- Zu viele/weite Jobs: Orte eng fassen, `LOCATION_RADIUS_KM` niedrig halten; Hardcut aktiv.
- Leere Firma/Ort in Mail: sicherstellen, dass `raw_title` ankommt (collect_jobs tut das). Falls nicht, Payload prüfen.
- SMTP: Bei 2FA Gmail App-Passwort nutzen; Outlook: `smtp-mail.outlook.com:587`. `python tasks.py email-test` prüft Zugang.

## Scheduler (optional, Windows)
- Task Scheduler: Aktion `Program/Script: powershell`, Argument `-Command "cd <pfad-zum-projekt>; .\\.venv\\Scripts\\activate; python .\\tasks.py mail-list"`, Trigger täglich.
- Log-Ausgabe umleiten, falls nötig: `...; python .\\tasks.py mail-list *> logs\\mail-list.log`

## Datenschutz
- `.env`, Logs, generierte Bewerbungen sind per `.gitignore` ausgeschlossen. Keine Geheimnisse committen.

## Erweiterte ENV (optional)
- `EXPORT_CSV=true` – exportiert Treffer nach `generated/jobs_latest.csv`
- `EXPORT_CSV_PATH=generated/jobs_latest.csv` – Zielpfad für CSV
- `MIN_SCORE_MAIL=2` – Mindestscore für Mail-Versand
- `LOCATION_BOOST_KM=15` – heuristischer Boost (String-Match Location)
- `BLACKLIST_COMPANIES=` – Komma-Liste ignorierter Firmen
- `BLACKLIST_KEYWORDS=junior` – Titel-Keywords zum Ausschluss
- `ENABLED_SOURCES=indeed,jobs.ch,jobup.ch` – Komma-Liste; leer = alle aktiv
- WhatsApp Cloud API (aus, falls nicht gesetzt): `WHATSAPP_ENABLED=false`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TO`
- `ALLOWED_LOCATIONS=` – optionale Hard-Allow-Liste; wenn gesetzt, müssen Titel/Ort/Raw-Title einen dieser Werte enthalten
- `AUTO_FIT_ENABLED=false`, `MIN_SCORE_APPLY=1` – wenn aktiv, setzt fit="OK" bei match in {exact,good} und Score >= MIN_SCORE_APPLY

## Final Acceptance (Checkliste)
- `python tasks.py env-check` ok (SMTP/Profil gesetzt).
- `python tasks.py verify` ok (Config, compileall, Templates, Dirs vorhanden).
- `python tasks.py mail-list` schickt nur neue Jobs (Delta), Titel/Firma/Ort korrekt geparst, lokal gefiltert.
- `python tasks.py prepare-applications` erzeugt DOCX in `out/`, Tracker ergänzt, optional Kopie via `--mirror-sent`/`archive-sent`.
- Scheduler aktiv (täglich) mit Log; keine Duplikat-Mails über mehrere Tage.
