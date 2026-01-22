# Outlook E-Mail Authentifizierung - Fehlerbehebung

## Problem
Die Authentifizierung bei Outlook ist fehlgeschlagen mit der Fehlermeldung:
```
Authentication unsuccessful [AS8PR04CA0060.eurprd04.prod.outlook.com]
```

## Mögliche Ursachen und Lösungen

### 1. Falsches Passwort
**Lösung:** Überprüfen Sie Ihr Outlook-Passwort in der `.env` Datei.

### 2. Zwei-Faktor-Authentifizierung aktiviert
Wenn Sie Zwei-Faktor-Authentifizierung für Ihr Outlook-Konto aktiviert haben, benötigen Sie ein **App-Password**.

**So erstellen Sie ein App-Password:**
1. Gehen Sie zu https://account.microsoft.com/security/app-passwords
2. Melden Sie sich mit Ihrem Outlook-Konto an
3. Klicken Sie auf "App-Password erstellen"
4. Geben Sie einen Namen ein (z.B. "Job-Finder")
5. Kopieren Sie das generierte 16-stellige Passwort
6. Verwenden Sie dieses Passwort in der `.env` Datei anstelle Ihres normalen Passworts

### 3. Konto-Sicherheitseinstellungen
Möglicherweise blockiert Microsoft den Zugriff von "weniger sicheren Apps".

**Lösung:**
1. Gehen Sie zu https://account.microsoft.com/security
2. Aktivieren Sie "Zugriff für weniger sichere Apps zulassen"
3. Oder verwenden Sie ein App-Password (siehe Punkt 2)

### 4. SMTP-Server Einstellungen
Stellen Sie sicher, dass die SMTP-Einstellungen korrekt sind:
- Server: `smtp-mail.outlook.com`
- Port: `587`
- Verschlüsselung: `STARTTLS`

## Test nach der Fehlerbehebung
Führen Sie das Test-Skript erneut aus:
```bash
python scripts/test_email_config.py
```

## Gmail-Konfiguration mit OAuth2 (empfohlen)

Da App-Passwords für Ihr Konto nicht verfügbar sind, verwenden wir die moderne OAuth2-Authentifizierung:

### Schritt 1: Google Cloud Console Projekt erstellen

1. **Gehe zu Google Cloud Console:**
   - Besuchen Sie: https://console.cloud.google.com/
   - Melden Sie sich mit Ihrem Gmail-Konto an

2. **Erstelle ein neues Projekt:**
   - Klicken Sie auf "Projekt auswählen" (oben links)
   - Klicken Sie auf "Neues Projekt"
   - Geben Sie "Job-Finder" als Namen ein
   - Klicken Sie auf "Erstellen"

3. **Aktiviere die Gmail API:**
   - Gehen Sie zu "APIs & Dienste" → "Bibliothek"
   - Suchen Sie nach "Gmail API"
   - Klicken Sie auf "Gmail API" → "Aktivieren"

4. **Erstelle OAuth2-Anmeldedaten:**
   - Gehen Sie zu "APIs & Dienste" → "Anmeldedaten"
   - Klicken Sie auf "+ ANMELDEDATEN ERSTELLEN"
   - Wählen Sie "OAuth-Client-ID"
   - Wählen Sie "Desktop-Anwendung"
   - Geben Sie "Job-Finder" als Namen ein
   - Klicken Sie auf "Erstellen"
   - Laden Sie die `credentials.json` herunter und speichern Sie sie im Projektordner

### Schritt 2: Python-Abhängigkeiten installieren

Fügen Sie diese zu Ihrer `requirements.txt` hinzu:
```
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
```

### Schritt 3: Code für OAuth2-Authentifizierung

Ich werde ein neues Skript erstellen, das OAuth2 verwendet.
