#!/usr/bin/env python3
import csv, json, pathlib, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_IN = ROOT / "generated" / "jobs_latest.csv"
JSON_OUT = ROOT / "data" / "jobs.json"

def main():
    rows = []
    if not CSV_IN.exists():
        raise SystemExit(f"CSV not found: {CSV_IN}")

    with CSV_IN.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # jobs_latest.csv hat Spalten: title,company,location,match,score,link,source
            rows.append({
                "source": r.get("source") or "",
                "company": r.get("company") or "",
                "title": r.get("title") or "",
                "location": r.get("location") or "",
                "url": r.get("link") or "",
                "match": r.get("match") or "",
                "score": int(r.get("score") or 0),
                "date_found": datetime.date.today().isoformat(),
                "commute_min": None,
                "salary_text": "",
                "fit": "DECISION",   # AG2/du entscheiden später OK/NO
                "reason": ""
            })

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} jobs -> {JSON_OUT}")

if __name__ == "__main__":
    main()
