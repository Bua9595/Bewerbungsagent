"""Direkt-Job-Finder: Öffnet relevante Jobportale, pflegt Vorlagen und Tracking.

Fokus: IT-Support/Workplace/Onsite/Rollout + passende Lager/Logistikrollen
im Raum Bülach/Kloten/Zürich (ÖV ≤ 60 Min.). UTF-8 bereinigt.
"""

import webbrowser
import time
from datetime import datetime
import schedule
import logging
import os

from config import config
from job_query_builder import build_search_urls


class DirectJobFinder:
    def __init__(self):
        # Dynamisch generierte Portal-Suchlinks aus Konfiguration
        self.direct_job_urls = build_search_urls(config)

        # Profil für personalisierte Anschreiben
        self.profile = {
            "name": getattr(config, "PROFILE_NAME", "") or os.getenv("PROFILE_NAME", ""),
            "email": getattr(config, "PROFILE_EMAIL", "") or os.getenv("PROFILE_EMAIL", ""),
            "linkedin": getattr(config, "PROFILE_LINKEDIN", "") or os.getenv("PROFILE_LINKEDIN", ""),
            "skills": [
                "IT-Support (1st/2nd Level)",
                "Windows 10/11, M365, AD",
                "Ticketing (z. B. ServiceNow/Jira)",
                "Hardware/Imaging, Remote Support",
                "Netzwerk-Grundlagen (TCP/IP, VLAN)",
                "SAP (lagerrelevante Prozesse)",
                "Python/SQL (Grundlagen)",
            ],
        }

    # ------------------ Datei-Helfer ------------------
    def save_application_templates(self):
        """Schreibt optimierte Anschreiben-Vorlagen (IT + Logistik) nach UTF-8."""
        name = (self.profile.get("name") or "Ihr Name").strip()
        templates = f"""
{name.upper()} – BEWERBUNGSVORLAGEN
==================================================
LinkedIn: {self.profile['linkedin']}
E-Mail: {self.profile['email']}

============================================================
ANSCHREIBEN: IT SUPPORT / SERVICE DESK / WORKPLACE
============================================================
Sehr geehrte Damen und Herren,

mit großer Motivation bewerbe ich mich als ICT Supporter (1st/2nd Level). Nach meiner Ausbildung zum Technischen Assistenten für Informatik bringe ich praxisnahe Kenntnisse in Windows 10/11, Microsoft 365, Active Directory sowie Ticketing-Systemen mit. Aus meiner mehrjährigen Erfahrung in der Logistik mit SAP kenne ich den Wert stabiler IT-Prozesse im operativen Alltag.

Stärken:
• Zuverlässiger 1st-Level-Support, höflich und lösungsorientiert
• Benutzer- und Geräteverwaltung (AD/M365), Hardware-/Software-Rollouts
• Basis Netzwerk (TCP/IP, VLAN) und Remote-Support
• Strukturierte Dokumentation und Teamarbeit

Gern unterstütze ich Ihr Team vor Ort im Raum Bülach/Zürich. Beginn: ab sofort.

Mit freundlichen Grüßen
{name}

============================================================
ANSCHREIBEN: ONSITE / FIELD SERVICE / ROLLOUT
============================================================
Sehr geehrte Damen und Herren,

ich bewerbe mich für eine Position im Onsite-/Field-Service. Ich arbeite sorgfältig, kundenorientiert und zuverlässig, auch im Schichtbetrieb. Aufgaben wie Gerätevorbereitung/Imaging, Arbeitsplatzaufbau, Peripherie, Migrationen und Vor-Ort-Support setze ich strukturiert um. Öffentliche Verkehrsmittel nutze ich flexibel im Raum Bülach/Zürich (Fahrzeit < 60 Min.).

Mit freundlichen Grüßen
{name}

============================================================
ANSCHREIBEN: JUNIOR SYSTEMADMINISTRATOR / IT OPERATOR
============================================================
Sehr geehrte Damen und Herren,

als technisch versierter Berufseinsteiger mit hands-on Erfahrung in AD/M365, Grundkenntnissen in Skripting (Python) und soliden Netzwerk-Basics unterstütze ich gerne Ihr Team im Betrieb. Durch meine Logistikerfahrung mit SAP handle ich zuverlässig und prozesssicher – auch unter Zeitdruck.

Mit freundlichen Grüßen
{name}

============================================================
ANSCHREIBEN: SAP-/LOGISTIK-IT-SUPPORT
============================================================
Sehr geehrte Damen und Herren,

aufgrund meiner Ausbildung in der Informatik und meiner mehrjährigen Tätigkeit in der Logistik (Wareneingang/-ausgang, Kommissionierung, SAP-Buchungen) kann ich sowohl technische Anliegen als auch Prozessfragen kompetent bearbeiten. Ich verbinde IT-Support mit Verständnis für Lagerabläufe und sorge für reibungslose IT-gestützte Prozesse.

Mit freundlichen Grüßen
{name}

============================================================
ANSCHREIBEN: LAGER / LOGISTIK (Fachkraft Lagerlogistik)
============================================================
Sehr geehrte Damen und Herren,

ich bewerbe mich als Fachkraft für Lagerlogistik. Ich bringe Erfahrung in Wareneingang/-ausgang, Kommissionierung, Milkrun, Gefahrgut, Inventur und SAP-Buchungen mit. Ich arbeite präzise, zuverlässig und teamorientiert – Schichtarbeit ist in Ordnung. Einsatzort bevorzugt Bülach/Zürich, Anfahrt mit ÖV.

Mit freundlichen Grüßen
{name}
""".strip() + "\n"

        # Entferne harte Namenseinträge zugunsten des Profils

        with open(config.TEMPLATES_FILE, "w", encoding="utf-8") as f:
            f.write(templates)
        print("Bewerbungsvorlagen aktualisiert (UTF-8)")

    def create_job_tracking_sheet(self):
        """Erstellt Tracking-CSV, falls nicht vorhanden."""
        if os.path.exists(config.TRACKING_FILE):
            return
        header = "Datum,Unternehmen,Position,Portal,Link,Status,Notizen"
        example = f"{datetime.now().strftime('%Y-%m-%d')},Beispiel AG,IT Support,JobScout24,https://example.com,Vorbereitet,Anschreiben anpassen"
        with open(config.TRACKING_FILE, "w", encoding="utf-8") as f:
            f.write(header + "\n")
            f.write(example + "\n")
        print("Tracking-Sheet erstellt: bewerbungen_tracking.csv")

    # ------------------ Suche/Läufe ------------------
    def open_job_portals_automatically(self):
        """Öffnet relevante Job-Portale in neuen Browser-Tabs."""
        print("Öffne Job-Portale im Standardbrowser…")
        for desc, url in self.direct_job_urls.items():
            try:
                webbrowser.open_new_tab(url)
                time.sleep(0.4)
            except Exception:
                pass

    def run_automated_job_hunt(self):
        """Automatisierte Job-Suche ohne Benutzereingaben."""
        print(f"Automatische Job-Suche gestartet: {datetime.now()}")
        logging.info(f"Automatische Job-Suche gestartet: {datetime.now()}")

        # Dateien prüfen/erstellen
        if not os.path.exists(config.TEMPLATES_FILE):
            print("Erstelle Bewerbungsvorlagen…")
            self.save_application_templates()
        if not os.path.exists(config.TRACKING_FILE):
            print("Erstelle Tracking-Sheet…")
            self.create_job_tracking_sheet()

        # Links dynamisch aus Config neu aufbauen
        self.direct_job_urls = build_search_urls(config)

        # Überblick
        print("\nZIEL-ROLLEN (IT + Logistik):")
        print("- IT Support (1st/2nd Level), Service Desk/Workplace")
        print("- Onsite/Field Service, Rollout/Migrationen")
        print("- Junior Systemadministrator / IT Operator")
        print("- SAP-/Logistik-IT-Support")
        print("- Lagerlogistik (WE/WA, Kommissionierung, SAP)")

        print("\nSUCH-LINKS:")
        for desc, url in self.direct_job_urls.items():
            print(f"{desc}: {url}")

        print(f"\nAutomatische Job-Suche abgeschlossen: {datetime.now()}")
        logging.info(f"Automatische Job-Suche abgeschlossen: {datetime.now()}")

    def schedule_job_search(self):
        """Plant die automatische Job-Suche täglich zur Config-Zeit."""
        schedule.every().day.at(getattr(config, "DAILY_SEARCH_TIME", "09:00")).do(self.run_automated_job_hunt)
        print("Job-Suche geplant!")
        logging.info("Job-Suche geplant")

    def run_complete_job_hunt(self):
        """Aktualisiert Dateien, zeigt Links und öffnet optional Portale."""
        print("AKTUALISIERE JOB-SUCHE!")
        print("=" * 60)

        if not os.path.exists(config.TEMPLATES_FILE):
            print("Erstelle Bewerbungsvorlagen…")
            self.save_application_templates()
        if not os.path.exists(config.TRACKING_FILE):
            print("Erstelle Tracking-Sheet…")
            self.create_job_tracking_sheet()

        # Links aktualisieren
        self.direct_job_urls = build_search_urls(config)

        print("\nZIEL-ROLLEN (IT + Logistik):")
        print("- IT Support (1st/2nd Level), Service Desk/Workplace")
        print("- Onsite/Field Service, Rollout/Migrationen")
        print("- Junior Systemadministrator / IT Operator")
        print("- SAP-/Logistik-IT-Support")
        print("- Lagerlogistik (WE/WA, Kommissionierung, SAP)")

        choice = os.getenv("AUTO_OPEN_PORTALS")
        if choice is None:
            try:
                choice = input("Job-Portale jetzt im Browser öffnen? (j/n): ")
            except EOFError:
                choice = 'n'

        if str(choice).lower() in ["j", "ja", "y", "yes"]:
            self.open_job_portals_automatically()
        else:
            print("\nSUCH-LINKS:")
            for desc, url in self.direct_job_urls.items():
                print(f"{desc}: {url}")

        print("\nOPTIMIERTE PARAMETER:")
        print("- Region: Bülach/Kloten/Zürich, Radius ≤ 25 km")
        print("- Filter: ohne Senior/Lead/Bachelor/Master")
        print("- Sprachen: Deutsch (sehr gut), Englisch (B2)")


if __name__ == "__main__":
    finder = DirectJobFinder()
    finder.run_complete_job_hunt()
