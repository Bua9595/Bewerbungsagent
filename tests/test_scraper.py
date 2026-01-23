"""
Selenium Smoke Test.

Wird bei pytest standardmäßig übersprungen, um keine Browser-Side-Effects
im CI/Default-Run zu erzeugen. Manuell starten via:
RUN_SELENIUM_TESTS=true pytest -k selenium_smoke
oder direkt:
python test_scraper.py
"""

import os
import sys
from pathlib import Path

# Projekt-Root ins sys.path aufnehmen, damit lokale Imports funktionieren.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    # Pytest nur laden, wenn verfuegbar.
    import pytest
except ImportError as exc:
    raise SystemExit(
        "pytest not installed. Run: pip install -r requirements-dev.txt"
    ) from exc


def test_selenium_smoke() -> None:
    # Test nur ausfuehren, wenn explizit aktiviert.
    if str(os.getenv("RUN_SELENIUM_TESTS", "false")).lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "ja",
        "j",
    }:
        pytest.skip("RUN_SELENIUM_TESTS not enabled")

    # Selenium-Setup fuer einen kurzen Smoke-Test.
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    # Browser starten, Seite laden, wieder schliessen.
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    driver.get("https://www.jobscout24.ch")
    driver.quit()


if __name__ == "__main__":
    # Direkter Run: Test aktivieren und pytest starten.
    os.environ["RUN_SELENIUM_TESTS"] = "true"
    raise SystemExit(pytest.main(["-k", "selenium_smoke"]))
