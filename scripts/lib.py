"""Shared paths and helpers for the apparel image eval scripts."""

import csv
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CASES = DATA / "cases"
RESULTS = ROOT / "results"
MANIFEST = DATA / "manifest.json"
SOURCES = DATA / "SOURCES.csv"

SOURCES_FIELDS = [
    "file", "case", "role", "source_url", "license", "author", "title",
    "object_date", "retrieved", "derived_from", "synthetic", "notes",
]


def load_manifest():
    return json.loads(MANIFEST.read_text())


def save_manifest(m):
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")


def get_case(m, case_id):
    for c in m["cases"]:
        if c["id"] == case_id:
            return c
    raise SystemExit(f"unknown case {case_id}")


def case_dir(case_id):
    return CASES / case_id


def rel(path):
    return str(Path(path).resolve().relative_to(ROOT))


def add_source(row):
    """Append or replace the SOURCES.csv row for row['file']."""
    rows = []
    if SOURCES.exists():
        with SOURCES.open(newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["file"] != row["file"]]
    rows.append({k: row.get(k, "") for k in SOURCES_FIELDS})
    rows.sort(key=lambda r: r["file"])
    with SOURCES.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SOURCES_FIELDS)
        w.writeheader()
        w.writerows(rows)


def today():
    return time.strftime("%Y-%m-%d")
