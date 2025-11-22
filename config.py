"""Konfigurationseinstellungen für den Bewerbungs-/Job-Finder.

Lädt Standardwerte und überschreibt sie mit .env-Variablen.
"""

import os
from dotenv import load_dotenv

# Lade Umgebungsvariablen aus .env Datei
load_dotenv()


class Config:
    def __init__(self):
        # API Keys (niemals fest codieren  via .env laden)
        self.GROQ_API_KEY = ""

        # E-Mail Konfiguration
        self.SENDER_EMAIL = ""
        self.SENDER_PASSWORD = ""  # Aus .env laden
        self.RECIPIENT_EMAILS = []
        self.SMTP_SERVER = ""
        self.SMTP_PORT = 587

        # Persönliches Profil (für Vorlagen)
        self.PROFILE_NAME = ""
        self.PROFILE_EMAIL = ""
        self.PROFILE_LINKEDIN = ""

        # Erweiterte E-Mail Einstellungen
        self.EMAIL_NOTIFICATIONS_ENABLED = True
        self.WEEKLY_SUMMARY_ENABLED = True
        self.ERROR_NOTIFICATIONS_ENABLED = True

        # Such-Intervalle (in Minuten)
        self.SEARCH_INTERVAL_MINUTES = 60  # Stündliche Suche
        self.DAILY_SEARCH_TIME = "09:00"  # Tägliche Suche um 9:00 Uhr

        # Browser-Einstellungen
        self.HEADLESS_MODE = True  # Browser im Hintergrund laufen lassen
        self.BROWSER_WAIT_TIME = 5  # Sekunden warten nach Laden

        # Logging
        self.LOG_LEVEL = "INFO"
        self.LOG_FILE = "job_finder.log"

        # Job-Suche Einstellungen
        self.MAX_JOBS_PER_SEARCH = 50
        # Fokusregion aktualisiert: Buelach und Umgebung
        self.SEARCH_LOCATIONS = ["Buelach", "Kloten", "Zuerich"]
        self.SEARCH_KEYWORDS = [
            "IT Support",
            "System Administrator",
            "Junior IT",
            "IT Techniker",
        ]

        # Datei-Pfade
        self.TEMPLATES_FILE = "bewerbungsvorlagen.txt"
        self.TRACKING_FILE = "bewerbungen_tracking.csv"

        # Überschreibe/erweitere Suche mit präziseren Vorgaben für das Profil
        # Region (korrigierte Umlaute) und Keywords inkl. Varianten/Filter
        self.SEARCH_LOCATIONS = ["Buelach", "Kloten", "Zuerich"]
        self.SEARCH_KEYWORDS = [
            "IT Support",
            "1st Level Support",
            "Service Desk",
            "Workplace Support",
            "Onsite Support",
            "Field Service",
            "Rollout Techniker",
            "Junior System Administrator",
            "IT Operator",
            "ICT Supporter",
            "Benutzersupport",
            "Systemtechniker",
            "Helpdesk",
            "SAP Support",
            "Logistik IT Support",
        ]
        self.TITLE_VARIANTS_DE = [
            "ICT Supporter",
            "1st Level Support",
            "IT Supporter",
            "Benutzersupport",
            "Servicedesk",
            "Workplace Engineer",
            "Systemtechniker",
            "Onsite Support",
            "Rollout Techniker",
            "Junior Systemadministrator",
            "IT Operator",
            "SAP Support",
        ]
        self.TITLE_VARIANTS_EN = [
            "IT Support",
            "Service Desk",
            "Helpdesk",
            "Workplace Support",
            "Desktop Support",
            "Field Service",
            "Rollout Technician",
            "Junior System Administrator",
            "IT Operator",
        ]
        self.NEGATIVE_KEYWORDS = [
            "Senior",
            "Lead",
            "Manager",
            "Bachelor",
            "Master",
            "Engineer (Senior)",
        ]
        # Logistik-Rollen (für zusätzliche Suche)
        self.SEARCH_KEYWORDS_LOGISTICS = [
            "Lagerlogistik",
            "Kommissionierer",
            "Lagermitarbeiter",
            "Wareneingang",
            "Warenausgang",
            "Versand",
            "Staplerfahrer",
            "Logistiker EFZ",
        ]
        self.LOCATION_RADIUS_KM = 25
        self.ONLY_ENTRY_LEVEL = True
        self.NO_DEGREE_REQUIRED = True

    def load_from_env(self):
        """Lädt Konfiguration aus Umgebungsvariablen und setzt sinnvolle Defaults."""
        # Credentials / Keys
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", self.GROQ_API_KEY)
        self.SENDER_EMAIL = os.getenv("SENDER_EMAIL", self.SENDER_EMAIL)
        self.SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", self.SENDER_PASSWORD)

        # Profilfelder
        self.PROFILE_NAME = os.getenv("PROFILE_NAME", self.PROFILE_NAME)
        self.PROFILE_EMAIL = os.getenv("PROFILE_EMAIL", self.PROFILE_EMAIL)
        self.PROFILE_LINKEDIN = os.getenv("PROFILE_LINKEDIN", self.PROFILE_LINKEDIN)
        # optional, falls vorhanden
        self.PROFILE_PHONE = os.getenv("PROFILE_PHONE", getattr(self, "PROFILE_PHONE", ""))

        # Logging aus ENV
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", self.LOG_LEVEL)

        # SMTP
        env_smtp_server = os.getenv("SMTP_SERVER")
        env_smtp_port = os.getenv("SMTP_PORT")
        if env_smtp_server:
            self.SMTP_SERVER = env_smtp_server
        if env_smtp_port:
            try:
                self.SMTP_PORT = int(env_smtp_port)
            except ValueError:
                pass

        # Empfänger
        recipients_env = os.getenv("RECIPIENT_EMAILS")
        if recipients_env:
            self.RECIPIENT_EMAILS = [e.strip() for e in recipients_env.split(",") if e.strip()]
        elif not self.RECIPIENT_EMAILS and self.SENDER_EMAIL:
            # Fallback: an sich selbst schicken
            self.RECIPIENT_EMAILS = [self.SENDER_EMAIL]

        # Falls kein SMTP-Server gesetzt ist, anhand der Domain ableiten
        if not self.SMTP_SERVER and self.SENDER_EMAIL:
            domain = self.SENDER_EMAIL.split("@")[-1].lower()
            if domain in {"gmail.com", "googlemail.com"}:
                self.SMTP_SERVER, self.SMTP_PORT = "smtp.gmail.com", 587
            elif domain in {"outlook.com", "hotmail.com", "live.com"}:
                self.SMTP_SERVER, self.SMTP_PORT = "smtp-mail.outlook.com", 587
            else:
                # generischer Default
                self.SMTP_SERVER, self.SMTP_PORT = "smtp-mail.outlook.com", 587

        # Optionale Suche-Overrides aus .env
        locs = os.getenv("SEARCH_LOCATIONS")
        if locs:
            self.SEARCH_LOCATIONS = [s.strip() for s in locs.split(",") if s.strip()]
        keys = os.getenv("SEARCH_KEYWORDS")
        if keys:
            self.SEARCH_KEYWORDS = [s.strip() for s in keys.split(",") if s.strip()]
        keys_log = os.getenv("SEARCH_KEYWORDS_LOGISTICS")
        if keys_log:
            self.SEARCH_KEYWORDS_LOGISTICS = [s.strip() for s in keys_log.split(",") if s.strip()]
        neg = os.getenv("NEGATIVE_KEYWORDS")
        if neg:
            self.NEGATIVE_KEYWORDS = [s.strip() for s in neg.split(",") if s.strip()]
        radius = os.getenv("LOCATION_RADIUS_KM")
        if radius:
            try:
                self.LOCATION_RADIUS_KM = int(radius)
            except ValueError:
                pass

        # Feature-Toggles
        def _env_bool(key, default):
            val = os.getenv(key)
            if val is None:
                return default
            return str(val).strip().lower() in {"1", "true", "t", "yes", "y", "ja", "j"}

        self.EMAIL_NOTIFICATIONS_ENABLED = _env_bool(
            "EMAIL_NOTIFICATIONS_ENABLED", getattr(self, "EMAIL_NOTIFICATIONS_ENABLED", True)
        )
        self.WEEKLY_SUMMARY_ENABLED = _env_bool(
            "WEEKLY_SUMMARY_ENABLED", getattr(self, "WEEKLY_SUMMARY_ENABLED", True)
        )
        self.ERROR_NOTIFICATIONS_ENABLED = _env_bool(
            "ERROR_NOTIFICATIONS_ENABLED", getattr(self, "ERROR_NOTIFICATIONS_ENABLED", True)
        )

    def validate_config(self):
        """Validiert die Konfiguration (Minimalanforderungen)."""
        if not self.SENDER_EMAIL:
            raise ValueError("SENDER_EMAIL ist erforderlich")
        if not self.SMTP_SERVER or not self.SMTP_PORT:
            raise ValueError("SMTP_SERVER/SMTP_PORT sind erforderlich")
        return True


# Globale Konfigurationsinstanz
config = Config()
config.load_from_env()

