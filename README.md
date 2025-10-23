# Bewerbungsagent

Ein schlanker Helfer, der Job-Suchlinks generiert, einfache Vorlagen schreibt und optionale E‑Mail‑Benachrichtigungen ermöglicht. Alle sensiblen Daten werden ausschließlich über Umgebungsvariablen (.env) geladen – nichts davon liegt im öffentlichen Repo.

## Features
- Dynamische Such‑URLs für gängige Portale (LinkedIn, Indeed, jobs.ch, usw.)
- Generische Anschreiben‑Vorlagen mit Profil‑Platzhaltern (Name/Email/LinkedIn)
- E‑Mail‑Automatisierung über SMTP (optional)
- Logging mit rotierenden Logfiles (lokal, per .gitignore ausgeschlossen)

## Setup
1) Python 3.11 installieren und Abhängigkeiten holen

```
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2) .env anlegen (lokal, wird ignoriert) – Beispiel:

```
cp .env.example .env  # Windows: copy .env.example .env
```

Dann `.env` befüllen:
- SENDER_EMAIL, SENDER_PASSWORD, SMTP_SERVER, SMTP_PORT
- RECIPIENT_EMAILS (Komma‑getrennt)
- GROQ_API_KEY (falls genutzt)
- PROFILE_NAME, PROFILE_EMAIL, PROFILE_LINKEDIN
- SEARCH_LOCATIONS, SEARCH_KEYWORDS, LOCATION_RADIUS_KM, AUTO_OPEN_PORTALS (j/n)

Hinweis Gmail/Passwörter:
- Für Gmail‑SMTP nutze ein App‑Passwort (empfohlen, siehe unten). Normale Passwörter sollten nie geteilt werden; durch `.env` bleiben sie nur lokal.

## Verwendung
Schnellprüfung (lädt Config, erzeugt Vorlagen/CSV bei Bedarf):

```
python quick_check.py
```

Portale/Links aktualisieren und optional im Browser öffnen:

```
python -m pip install -r requirements.txt
python tasks.py start            # Aktualisiert Dateien, zeigt Links, fragt optional nach Öffnen
python tasks.py open             # Öffnet Portale direkt
python tasks.py env-check        # Zeigt Konfig-Zusammenfassung (ohne Geheimnisse)
python tasks.py gen-templates    # Schreibt Vorlagen/Tracking-Datei
python tasks.py email-test       # Verbindungs-Test (SMTP) – optional
python tasks.py list             # Jobs sammeln, sortiert anzeigen (+ CSV Export)
python tasks.py mail-list        # Gefilterte Liste per E-Mail senden (+ CSV, optional WhatsApp)
```

## Warum App‑Passwort/OAuth?
- SMTP‑Server verlangen Authentifizierung. Für Gmail ist das normale Konto‑Passwort riskant. App‑Passwörter (bei aktivierter 2FA) sind auf einzelne Apps beschränkt und jederzeit widerrufbar.
- OAuth2 ist moderner und vermeidet Passwörter, ist aber aufwendiger. Für einfache SMTP‑Benachrichtigungen reicht ein App‑Passwort.

### Gmail App‑Passwort erstellen
1. Unter "Google Konto" → Sicherheit → 2‑Stufen‑Verifizierung aktivieren
2. Danach: "App‑Passwörter" → App „Mail“ und Gerät „Sonstiges (z. B. Bewerbungsagent)“ wählen
3. 16‑stelliges App‑Passwort kopieren → in `.env` als `SENDER_PASSWORD=` eintragen
4. SMTP‑Werte: `SMTP_SERVER=smtp.gmail.com`, `SMTP_PORT=587`

### GROQ API Key rotieren
1. https://console.groq.com → API Keys → alten Key revoke, neuen Key erstellen
2. Neuen Key in `.env` als `GROQ_API_KEY=` eintragen (nicht committen)

## CI (GitHub Actions)
- Lint (Style‑Hinweise) und Checks (baubare Python‑Dateien, Import‑Smoke‑Test)
- Workflow liegt unter `.github/workflows/ci.yml` und läuft bei Push/PR
- Lint ist in diesem Projekt "soft" (nicht blockierend). Zum Strenger‑Machen siehe Kommentare im Workflow.

## Sicherheit & Privates
- `.gitignore` schließt `.env`, Logs, generierte Vorlagen/CSV und persönliche Dokumente (PDF/DOCX) aus
- Falls sensible Dateien jemals gepusht wurden, Historie mit `git filter-repo` oder BFG bereinigen

## Lizenz / Hinweise
- Nur zu Demo-/Privatzwecken. Webseitenbedingungen der Portale beachten.

## Erweiterte Einstellungen (optional)

Nicht-sensible ENV für Jobliste/Scoring:
- `EXPORT_CSV=true` – exportiert Treffer nach `generated/jobs_latest.csv`
- `EXPORT_CSV_PATH=generated/jobs_latest.csv` – Zielpfad für CSV-Export
- `MIN_SCORE_MAIL=2` – Mindestscore für E-Mail-Versand
- `LOCATION_BOOST_KM=15` – heuristischer Boost (String-Match Location)
- `BLACKLIST_COMPANIES=` – Komma‑getrennte Firmen, die ignoriert werden
- `BLACKLIST_KEYWORDS=junior` – Titel‑Keywords, die ausgeschlossen werden (z. B. "junior,praktikum")

WhatsApp Cloud API (optional; Standard: aus):
- `WHATSAPP_ENABLED=false`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TO`
  – Wird nur genutzt, wenn aktiviert; ist kein Ersatz für E‑Mail.
