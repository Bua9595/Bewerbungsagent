"""CV-Profil-basierte Filter.

Liest data/cv_profile.json und leitet daraus Blocklist-Begriffe ab.
Kein Profil vorhanden → leere Menge (kein Fehler).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Set

CV_PROFILE_PATH = Path("data/cv_profile.json")

# Begriffe, die geblockt werden wenn kein Hochschulabschluss vorliegt
_DEGREE_TERMS: Set[str] = {
    "bachelor",
    "master",
    "phd",
    "doktor",
    "doktorat",
    "studium",
    "hochschulabschluss",
    "abgeschlossenes studium",
    "universitaet",
    "universitaetsabschluss",
    "fachhochschule",
    "fh abschluss",
    "hoehere fachschule",
    "eth abschluss",
    "degree required",
    "university degree",
    "abschluss einer hoeherbildung",
}

# Erfahrungs-Begriffe: immer geblockt (mehrjährig = mehr als 1 Jahr)
_EXPERIENCE_MANY_YEARS: Set[str] = {
    "mehrjaehrige erfahrung",
    "mehrjaehrige berufserfahrung",
    "mehrjahrige erfahrung",
    "mehrjahrige berufserfahrung",
    "einschlaegige erfahrung",
    "einschlaegige berufserfahrung",
    "fundierte berufserfahrung",
    "fundierte erfahrung",
    "langjahrige erfahrung",
    "langjahrige berufserfahrung",
    "langjahrig",
    "mehrere jahre erfahrung",
    "mehrere jahre berufserfahrung",
    "jahre berufserfahrung",
    "jahren berufserfahrung",
    "mehrjaehrig",
    "mehrjahrig",
    "nachgewiesene erfahrung",
    "erfahrung erforderlich",
    "proven experience",
    "demonstrated experience",
    "extensive experience",
}

# Erfahrungs-Begriffe: geblockt wenn person < 3 Jahre Erfahrung hat
_EXPERIENCE_3_PLUS_YEARS: Set[str] = {
    "3 jahre erfahrung",
    "4 jahre erfahrung",
    "5 jahre erfahrung",
    "6 jahre erfahrung",
    "7 jahre erfahrung",
    "3 jahre berufserfahrung",
    "4 jahre berufserfahrung",
    "5 jahre berufserfahrung",
    "mindestens 3 jahre",
    "mindestens 4 jahre",
    "mindestens 5 jahre",
    "mind 3 jahre",
    "mind 4 jahre",
    "mind 5 jahre",
    "min 3 jahre",
    "min 4 jahre",
    "min 5 jahre",
    "3+ jahre",
    "4+ jahre",
    "5+ jahre",
    "3 years experience",
    "4 years experience",
    "5 years experience",
    "3+ years",
    "4+ years",
    "5+ years",
    "at least 3 years",
    "at least 4 years",
    "at least 5 years",
    "erfahrung von mindestens",
    "3 5 jahre",
    "2 3 jahre",
}

# Erfahrungs-Begriffe: geblockt wenn person < 2 Jahre Erfahrung hat
_EXPERIENCE_2_PLUS_YEARS: Set[str] = {
    "2 jahre erfahrung",
    "2 jahre berufserfahrung",
    "mindestens 2 jahre",
    "min 2 jahre",
    "2+ jahre",
    "2 years experience",
    "2+ years",
    "at least 2 years",
}

# Führerschein-Begriffe
_DRIVING_TERMS: Set[str] = {
    "fuehrerschein",
    "fuhrerschein",
    "fuehrerausweis",
    "fuhrerausweis",
    "kat b",
    "klasse b",
    "driving license",
    "license required",
    "car required",
}


def load_cv_profile() -> dict:
    """CV-Profil aus JSON laden. Fehler → leeres Dict."""
    try:
        raw = CV_PROFILE_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return {}


def get_cv_blocklist_terms() -> Set[str]:
    """
    Blocklist-Begriffe aus dem CV-Profil ableiten.
    Gibt normalisierte Begriffe zurueck (lowercase, keine Umlaute).
    """
    profile = load_cv_profile()
    if not profile:
        return set()

    terms: Set[str] = set()

    # --- Bildung ---
    education = profile.get("education") or {}
    level = (education.get("level") or "").lower().strip()
    degree = (education.get("degree") or "").strip()
    no_degree = level in {"apprenticeship", "vocational", "highschool", "none"} or not degree
    if no_degree:
        terms |= _DEGREE_TERMS

    # --- Erfahrung ---
    try:
        exp_years = int(profile.get("experience_years") or 0)
    except (ValueError, TypeError):
        exp_years = 0

    # Immer "mehrjährige" und Ähnliches blockieren
    terms |= _EXPERIENCE_MANY_YEARS

    # Ab < 3 Jahren: explizite 3+-Jahreszahlen blockieren
    if exp_years < 3:
        terms |= _EXPERIENCE_3_PLUS_YEARS

    # Ab < 2 Jahren: auch 2 Jahre blockieren
    if exp_years < 2:
        terms |= _EXPERIENCE_2_PLUS_YEARS

    # --- Führerschein ---
    if not profile.get("driving_license", False):
        terms |= _DRIVING_TERMS

    return terms


def print_cv_filter_summary() -> None:
    """Gibt eine Zusammenfassung der abgeleiteten Filter aus (fuer Debugging)."""
    profile = load_cv_profile()
    if not profile:
        print("Kein CV-Profil gefunden (data/cv_profile.json).")
        return

    terms = get_cv_blocklist_terms()
    print(f"CV-Profil geladen: {CV_PROFILE_PATH}")
    print(f"  Bildung:      {profile.get('education', {}).get('level', '?')}")
    print(f"  Erfahrung:    {profile.get('experience_years', '?')} Jahr(e)")
    print(f"  Fuehrerschein:{profile.get('driving_license', False)}")
    print(f"  Abgeleitete Blocklist-Begriffe: {len(terms)}")
    for t in sorted(terms):
        print(f"    - {t}")


if __name__ == "__main__":
    print_cv_filter_summary()
