"""Behebt Mojibake und Sonder-Unicode in .md-Dateien.

Mojibake: UTF-8-Bytes wurden als Windows-1252 eingelesen und dann
als UTF-8 zurueckgespeichert -> Umlaute erscheinen als Zeichenmuell.
"""
import os


def _build_mojibake_map():
    """Generiert Mojibake->Original Mapping automatisch."""
    mapping = {}
    # Alle relevanten Unicode-Zeichen (Latin Extended, Pfeile, Satzzeichen)
    candidates = list(range(0xC0, 0x180)) + list(range(0x2000, 0x2070)) + [0x2192, 0x2190, 0x2194]
    for cp in candidates:
        ch = chr(cp)
        try:
            utf8_bytes = ch.encode("utf-8")
            mojibake = utf8_bytes.decode("cp1252")
            if mojibake != ch and len(mojibake) >= 2:
                mapping[mojibake] = ch
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return mapping


# Mojibake-Map generieren
MOJIBAKE_MAP = _build_mojibake_map()

# Zusaetzliche Normalisierungen (Sonder-Unicode -> ASCII)
NORMALIZE = [
    ("\u2011", "-"),   # non-breaking hyphen
    ("\u2012", "-"),   # figure dash
    ("\u2013", "-"),   # en dash
    ("\u2014", "-"),   # em dash
    ("\u2018", "'"),   # left single quote
    ("\u2019", "'"),   # right single quote
    ("\u201c", '"'),   # left double quote
    ("\u201d", '"'),   # right double quote
    ("\u2026", "..."), # ellipsis
    ("\u00a0", " "),   # non-breaking space
    ("\u200b", ""),    # zero-width space
    ("\u2192", "->"),  # right arrow
    ("\u2190", "<-"),  # left arrow
    ("\r\n", "\n"),    # CRLF -> LF
    ("\r", "\n"),
]


def fix_file(path):
    original = open(path, encoding="utf-8", errors="replace").read()
    text = original

    # 1. Mojibake-Muster reparieren (laengste zuerst)
    for bad in sorted(MOJIBAKE_MAP, key=len, reverse=True):
        good = MOJIBAKE_MAP[bad]
        text = text.replace(bad, good)

    # 2. Sonder-Unicode normalisieren
    for bad, good in NORMALIZE:
        text = text.replace(bad, good)

    if text != original:
        open(path, "w", encoding="utf-8", newline="").write(text)
        return True
    return False


def main():
    files = []
    for root, dirs, flist in os.walk("."):
        dirs[:] = [d for d in dirs if d not in {".venv", ".git", "__pycache__", ".pytest_cache"}]
        for f in flist:
            if f.endswith(".md"):
                files.append(os.path.join(root, f))

    changed = []
    for path in sorted(files):
        if fix_file(path):
            changed.append(path)
            print(f"Fixed: {path}")

    if not changed:
        print("Keine Aenderungen noetig.")
    else:
        print(f"\nGesamt: {len(changed)} Dateien korrigiert.")


if __name__ == "__main__":
    main()
