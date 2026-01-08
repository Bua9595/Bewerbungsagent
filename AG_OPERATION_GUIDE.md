# AG-Betriebsleitfaden (Operation Guide)

Dieser Leitfaden richtet sich an nachgelagerte Agents oder Cron-Jobs, die den `Bewerbungsagent` betreiben.

## 1. Systemvoraussetzungen & Setup

### Umgebung
- **OS**: Windows (primär) oder Linux (Docker/Server).
- **Python**: 3.11+ erforderlich.
- **Browser**: Chrome/Chromium muss installiert sein (für Selenium).

### Installation (Einmalig)
1.  Repo clonen.
2.  Venv erstellen: `python -m venv .venv`
3.  Aktivieren:
    - Windows: `.\.venv\Scripts\activate`
    - Linux: `source .venv/bin/activate`
4.  Installieren: `pip install -r requirements.txt`
5.  Konfiguration: Nur wenn `.env` noch fehlt -> `.env.example` nach `.env` kopieren und anpassen.

## 2. Konfiguration (.env)

Die folgenden Variablen sind für den produktiven Betrieb **zwingend**:

| Variable | Beschreibung | Beispiel / Wichtig |
| :--- | :--- | :--- |
| `SENDER_EMAIL` | Absender für Reports | `bot@example.com` |
| `SENDER_PASSWORD` | App-Passwort (Gmail) | `xxxx xxxx xxxx xxxx` |
| `SMTP_SERVER` | SMTP Host | `smtp.gmail.com` |
| `RECIPIENT_EMAILS` | Empfänger (Komma-getrennt) | `user@example.com` |
| `GROQ_API_KEY` | (Optional) Für AI-Features | `gsk_...` |
| `SEARCH_LOCATIONS` | Suchorte | `Zürich,Kloten` |
| `SEARCH_KEYWORDS` | Suchbegriffe | `IT Support,System Engineer` |
| `AUTO_FIT_ENABLED` | Auto-Matching aktivieren | `true` (empfohlen für Auto-Apply) |
| `MIN_SCORE_APPLY` | Min. Score für Bewerbung | `1` (1-10 Skala) |

## 3. Routine-Betrieb (Cron / Agent Tasks)

### Tägliche Job-Suche & Reporting
Führt die Suche aus, filtert Jobs und sendet eine E-Mail mit den besten Treffern.
```bash
python tasks.py mail-list
```
*Hinweis: `mail-list` synchronisiert automatisch Markierungen aus `generated/job_tracker.xlsx`.*
*CSV wird weiterhin unterstuetzt via `JOB_TRACKER_FILE=generated/job_tracker.csv`.*
*Run-Lock: `RUN_LOCK_FILE` + `RUN_LOCK_TTL_MIN` verhindern parallele Laeufe.*
*Empfehlung: Täglich morgens (z.B. 09:00).*

### Interaktive Tracker-UI (optional)
Lokale Klick-UI fuer erledigt/ignored:
```bash
python tasks.py tracker-ui
```
*URL: http://127.0.0.1:8765*
*Erledigt/closed Anzeige standardmaessig fuer die letzten `TRACKER_UI_DAYS` Tage.*

### Bewerbungen vorbereiten (Batch)
Erstellt DOCX-Anschreiben für alle "passenden" Jobs (Status "OK" oder manuell geprüft).
```bash
python tasks.py prepare-applications
```
*Output: Generiert DOCX-Dateien im `out/` Ordner und aktualisiert `bewerbungen_tracking.csv`.*

### Manuelle / Interaktive Prüfung
Nur Job-Liste anzeigen (ohne Mail):
```bash
python tasks.py list
```

## 4. Wichtige Pfade & Artefakte

- `data/jobs.json`: Cache der letzten Suche (wird von `list`/`mail-list` geschrieben).
- `generated/job_state.json`: Lifecycle-Status der Jobs (Mailing-Quelle)
- `generated/job_tracker.xlsx`: Tabelle zum Abhaken (erledigt/aktion)
- `out/`: Zielordner für generierte Bewerbungen (`.docx`).
- `bewerbungen_tracking.csv`: Logbuch aller erstellten Bewerbungen.
- `logs/`: Logfiles (rotierend).

## 5. Bekannte Risiken & Hinweise

- **Selenium**: Kann fehlschlagen, wenn Chrome-Version und Driver nicht matchen. `webdriver-manager` regelt das meistens, aber auf Headless-Servern muss `--headless` im Code sichergestellt sein (aktuell im Code prüfen).
- **Anti-Bot**: Portale (Indeed, Jobs.ch) können IPs blockieren. Zu häufige Anfragen vermeiden.
- **Encoding**: Auf Windows sicherstellen, dass Terminals UTF-8 nutzen, sonst Darstellungsprobleme bei Sonderzeichen.
