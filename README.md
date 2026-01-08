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
if (!(Test-Path .env)) { Copy-Item .env.example .env }   # legt .env nur an, wenn sie fehlt
```

### .env ausfüllen (Minimal)
- `SENDER_EMAIL`, `SENDER_PASSWORD`, `SMTP_SERVER`, `SMTP_PORT` (Gmail: smtp.gmail.com / 587, App-Passwort)
- `RECIPIENT_EMAILS` (Komma-getrennt)
- `SEARCH_LOCATIONS=Buelach` (oder nahe Orte), `LOCATION_RADIUS_KM=25`
- Optional: `SEARCH_KEYWORDS`, `ENABLED_SOURCES`, `EMAIL_MAX_JOBS`

## Nutzung (häufigste Commands)
- `python tasks.py env-check` – zeigt SMTP/Empfänger/Profil
- `python tasks.py verify` – Config/compileall/Verzeichnis-Check
- `python tasks.py mail-list` - sammelt Jobs, filtert auf lokale Orte, mailt neue Jobs + Erinnerungen fuer offene Jobs (Lifecycle in `generated/job_state.json`, mit `--dry-run` nur simulieren)
- `python tasks.py tracker-sync` - synchronisiert Markierungen aus `generated/job_tracker.csv` in den Status
- `python tasks.py mark-applied <job_uid> [--url <link>]` - markiert Job als angewendet (stoppt Erinnerungen)
- `python tasks.py mark-ignored <job_uid> [--url <link>]` - markiert Job als ignoriert (stoppt Erinnerungen)
- `python tasks.py list` – sammelt und gibt Textliste + CSV aus
- `python tasks.py prepare-applications [--force-all] [--mirror-sent] [--copy-sent-dir <pfad>]` – erzeugt Anschreiben aus `data/jobs.json` (fit=="OK") in `out/`, tracked in `bewerbungen_tracking.csv`; optional Kopie in `04_Versendete_Bewerbungen/<Firma>/`
- `python tasks.py archive-sent --file out/<datei>.docx [--company Firma] [--dest <pfad>]` – manuelles Archivieren einer versendeten Bewerbung nach `04_Versendete_Bewerbungen/`
- `python tasks.py gen-templates` – aktualisiert Templates/Tracker-Header
- `python tasks.py email-test` – SMTP-Test

## Verhalten / Filter
- Standard-Orte: Buelach/Kloten/Zuerich (ASCII; per .env setzbar). Ortsfilter ist hart; mit `STRICT_LOCATION_FILTER=false` wird soft gefiltert.
- Score/Match: Keywords/Negativliste steuern Scoring; `MIN_SCORE_MAIL` (Default 2) filtert fuer Mail.
- Sprache: Begriffe aus `LANGUAGE_BLOCKLIST` in Titel/Raw-Title/Ort filtern Jobs heraus.
- Anforderungen: `REQUIREMENTS_BLOCKLIST` filtert z.B. Führerschein-Pflicht.
- Mail-Body: parst jobs.ch/jobup-Multiline-Titel (Arbeitsort/Firma), zeigt Quelle/Match/Score; Soft-Cap `EMAIL_MAX_JOBS` (Default 200).
- Lifecycle: Jobs werden in `generated/job_state.json` verwaltet (new/notified/applied/ignored/closed).
  - Tracker: `generated/job_tracker.csv` wird nach jedem Lauf aktualisiert (Spalten `erledigt` + `aktion`).
  - `mail-list` liest den Tracker automatisch ein; alternativ `python tasks.py tracker-sync`.
  - Job-UID wird in der Mail angezeigt (fuer mark-applied/mark-ignored).
  - Erinnerungen fuer offene Jobs nach `REMINDER_DAYS` (oder taeglich via `REMINDER_DAILY=true`).
  - Jobs werden als closed markiert, wenn sie `CLOSE_MISSING_RUNS` Laeufe fehlen oder seit `CLOSE_NOT_SEEN_DAYS` Tagen nicht gesehen wurden.
  - Migration: vorhandene `generated/seen_jobs.json` wird beim ersten Lauf in `job_state.json` uebernommen.

### Auto-Fit & Filter
- `AUTO_FIT_ENABLED=true`, `MIN_SCORE_APPLY=0.6` -> fit="OK" bei match in {exact,good} und Score >= MIN_SCORE_APPLY
- `ALLOWED_LOCATIONS` wirkt als Hard-Allow bei `STRICT_LOCATION_FILTER=true`, sonst nur als Soft-Boost (kommagetrennt, z.B. `Buelach,Zuerich,Kloten,Winterthur,Baden,Zug`).
- Typische Entry Points:
  - Suche + Mail: `python tasks.py mail-list`
  - Manuelle Liste: `python tasks.py list`
  - Bewerbungen erstellen: `python tasks.py prepare-applications`

## Dateien/Ordner
- `data/jobs.json` - letzter Job-Snapshot
- `generated/job_state.json` - Lifecycle-Status je Job (single source of truth fuer Mailings)
- `generated/job_tracker.csv` - Tabelle zum Abhaken/Notizen (erledigt/aktion)
- `Anschreiben_Templates/` - Templates (`T1_ITSup.docx`, `T2_Systemtechnik.docx`, `T3_Logistik.docx`)
- `out/` - generierte Anschreiben
- `bewerbungen_tracking.csv` - Tracker (wird bei Bedarf angelegt/erweitert)
- `04_Versendete_Bewerbungen/` - Ziel fuer Kopien nach Versand (wird bei `--mirror-sent` genutzt, sonst manuell)

## Troubleshooting
- Encoding: Repo ist UTF-8; wenn PowerShell ??? zeigt, liegt es an der Konsole, nicht an den Dateien.
- Zu wenige Jobs: `SEARCH_LOCATIONS` erweitern oder `MIN_SCORE_MAIL` senken; Cap per `EMAIL_MAX_JOBS`.
- Zu viele/weite Jobs: Orte eng fassen, `LOCATION_RADIUS_KM` niedrig halten; Hardcut aktiv.
- Leere Firma/Ort in Mail: sicherstellen, dass `raw_title` ankommt (collect_jobs tut das). Falls nicht, Payload pruefen.
- SMTP: Bei 2FA Gmail App-Passwort nutzen; Outlook: `smtp-mail.outlook.com:587`. `python tasks.py email-test` prueft Zugang.

## Scheduler (optional, Windows)
- Task Scheduler: Aktion `Program/Script: powershell`, Argument `-Command "cd <pfad-zum-projekt>; .\.venv\Scripts\activate; python .\tasks.py mail-list"`, Trigger taeglich.
- Log-Ausgabe umleiten, falls noetig: `...; python .\tasks.py mail-list *> logs\mail-list.log`
- `tools/run_mail_list.cmd` ist ein lokales Beispiel; in anderen Umgebungen (z.B. AG/Cron) direkt `python tasks.py mail-list` zyklisch ausfuehren.

## Datenschutz
- `.env`, Logs, generierte Bewerbungen sind per `.gitignore` ausgeschlossen. Keine Geheimnisse committen.

## Erweiterte ENV (optional)
- `EXPORT_CSV=true` - exportiert Treffer nach `generated/jobs_latest.csv`
- `EXPORT_CSV_PATH=generated/jobs_latest.csv` - Zielpfad fuer CSV
- `JOB_TRACKER_FILE=generated/job_tracker.csv` - Pfad fuer die Haken-Tabelle
- `MIN_SCORE_MAIL=2` - Mindestscore fuer Mail-Versand
- `LOCATION_BOOST_KM=15` - heuristischer Boost (String-Match Location)
- `BLACKLIST_COMPANIES=` - Komma-Liste ignorierter Firmen
- `BLACKLIST_KEYWORDS=junior` - Titel-Keywords zum Ausschluss
- `ENABLED_SOURCES=indeed,jobs.ch,jobup.ch` - Komma-Liste; leer = alle aktiv
- WhatsApp Cloud API (aus, falls nicht gesetzt): `WHATSAPP_ENABLED=false`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TO`
- `ALLOWED_LOCATIONS=Buelach,Zuerich,Kloten,Winterthur,Baden,Zug` - optionaler Orts-Boost; mit `STRICT_LOCATION_FILTER=true` wird daraus Hard-Allow
- `AUTO_FIT_ENABLED=true`, `MIN_SCORE_APPLY=0.6` - fit="OK" bei match in {exact,good} und Score >= MIN_SCORE_APPLY
- `REMINDER_DAYS=2` - Tage zwischen Erinnerungen fuer offene Jobs
- `REMINDER_DAILY=false` - true = taegliche Erinnerungen
- `CLOSE_MISSING_RUNS=3` - schliesst Jobs nach N fehlenden Laeufen
- `CLOSE_NOT_SEEN_DAYS=7` - schliesst Jobs nach N Tagen ohne Treffer
- `STRICT_LOCATION_FILTER=true`, `ALLOWED_LOCATION_BOOST=2` - harter Ortsfilter (mit Soft-Boost)
- `LANGUAGE_BLOCKLIST=franzosisch,francais,french,...` - filtert Jobs mit Sprach-Anforderungen
- `REQUIREMENTS_BLOCKLIST=fuehrerschein,kat b,...` - filtert Führerschein/Auto-Pflicht
- ÖV-Zeitfilter: `TRANSIT_ENABLED`, `TRANSIT_ORIGIN`, `TRANSIT_MAX_MINUTES`, `TRANSIT_TIME`, `TRANSIT_DATE`
- Optional: `DETAILS_BLOCKLIST_SCAN=true` scannt Stellen-Details nach blockierten Begriffen
- Optional: `EXPAND_QUERY_VARIANTS`, `QUERY_VARIANTS_LIMIT`, `MAX_QUERY_TERMS`, `EXTRA_QUERY_TERMS` für breitere Suche
- Company-Career-Scan (optional): `COMPANY_CAREERS_ENABLED`, `COMPANY_CAREER_URLS`, `COMPANY_CAREER_NAMES`, `CAREER_LINK_KEYWORDS`, `CAREER_MAX_LINKS`, `CAREER_MIN_SCORE`

## Final Acceptance (Checkliste)
- `python tasks.py env-check` ok (SMTP/Profil gesetzt).
- `python tasks.py verify` ok (Config, compileall, Templates, Dirs vorhanden).
- `python tasks.py mail-list` - sammelt Jobs, filtert auf lokale Orte, mailt neue Jobs + Erinnerungen fuer offene Jobs (Lifecycle in `generated/job_state.json`)
- `python tasks.py prepare-applications` erzeugt DOCX in `out/`, Tracker ergaenzt, optional Kopie via `--mirror-sent`/`archive-sent`.
- Scheduler aktiv (taeglich) mit Log; keine Duplikat-Mails ueber mehrere Tage.
