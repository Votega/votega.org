#!/usr/bin/env python3
"""Publish Georgia executive orders to the Votega/ga-executive-orders repo.

Source: assets/data/ga-executive-orders-<year>.json (one file per year).
Artifacts published:
  data/<year>.json              Per-year orders (passthrough, one file each year)
  data/executive-orders.csv     ALL orders, every year, one row each — for spreadsheets
  data/executive-orders.schema.json   JSON Schema for a per-year file
  SUMMARY.md                    Human-readable overview: counts by year & category + recent orders

Dry run (no GA_EXECUTIVE_ORDERS_TOKEN): writes to $OUT_DIR (default ./out). See lib/sibling_publish.
"""
import csv
import glob
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-executive-orders"
TOKEN_ENV = "GA_EXECUTIVE_ORDERS_TOKEN"
SCHEMA_VERSION = "1.0.0"


def load_years():
    """Return {year: doc} for every ga-executive-orders-<year>.json in source order."""
    out = {}
    for path in sorted(glob.glob("assets/data/ga-executive-orders-*.json")):
        year = path.replace("\\", "/").split("-")[-1].replace(".json", "")
        out[year] = json.load(open(path, encoding="utf-8"))
    return out


def all_orders(years):
    """Flatten every order across years, tagging each with its file year."""
    rows = []
    for year, doc in years.items():
        for o in doc.get("orders", []):
            rows.append({**o, "_year": year})
    # Newest first, by date then order number.
    rows.sort(key=lambda o: (o.get("date") or "", o.get("number") or ""), reverse=True)
    return rows


def orders_csv(orders):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["year", "date", "number", "title", "category", "url"])
    for o in orders:
        w.writerow([o.get("_year") or (o.get("date") or "")[:4], o.get("date"),
                    o.get("number"), o.get("title"), o.get("category"), o.get("url")])
    return buf.getvalue().encode()


def summary_md(years, orders):
    total = len(orders)
    by_year = Counter(o["_year"] for o in orders)
    by_cat = Counter((o.get("category") or "Uncategorized") for o in orders)
    L = ["# Georgia Executive Orders", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {datetime.now(timezone.utc).isoformat()} · {total} orders across {len(by_year)} years._")
    L.append("")
    L.append("> Full data: per-year JSON in [`data/`](data/), or everything in one file — "
             "[`data/executive-orders.csv`](data/executive-orders.csv).")
    L.append("")
    L.append("## By year")
    L.append("")
    L.append("| Year | Orders |")
    L.append("|------|--------|")
    for year in sorted(by_year, reverse=True):
        L.append(f"| {year} | {by_year[year]} |")
    L.append("")
    L.append("## By category")
    L.append("")
    L.append("| Category | Orders |")
    L.append("|----------|--------|")
    for cat, n in by_cat.most_common():
        L.append(f"| {cat} | {n} |")
    L.append("")
    L.append("## 10 most recent")
    L.append("")
    L.append("| Date | Number | Category | Title |")
    L.append("|------|--------|----------|-------|")
    for o in orders[:10]:
        title = (o.get("title") or "").replace("|", "\\|")
        url = o.get("url")
        num = f"[{o.get('number')}]({url})" if url else (o.get("number") or "")
        L.append(f"| {o.get('date','')} | {num} | {o.get('category','')} | {title} |")
    L.append("")
    return ("\n".join(L) + "\n").encode()


def schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-executive-orders/main/data/executive-orders.schema.json",
        "title": "Georgia Executive Orders (per-year file)",
        "description": "Executive orders issued by the Governor of Georgia in one calendar year. "
                       "One file per year (data/<year>.json).",
        "type": "object",
        "required": ["orders"],
        "properties": {
            "metadata": {"type": "object"},
            "orders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["date", "number", "title"],
                    "properties": {
                        "date": {"type": "string", "description": "Issue date (YYYY-MM-DD)."},
                        "number": {"type": "string", "description": "Executive order number (e.g. '08.18.26.01')."},
                        "title": {"type": "string"},
                        "category": {"type": ["string", "null"], "description": "e.g. Appointment, Emergency, Administrative."},
                        "url": {"type": ["string", "null"], "description": "Link to the official order PDF."},
                        "sha256": {"type": "string", "description": "SHA-256 of the downloaded PDF (integrity)."},
                        "bytes": {"type": "integer", "description": "Size of the PDF in bytes."},
                        "fetchedAt": {"type": "string", "description": "UTC timestamp the PDF was downloaded (ISO-8601)."},
                        "archiveUrl": {"type": ["string", "null"], "description": "Wayback Machine snapshot of the PDF, if archived."},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def build_artifacts():
    years = load_years()
    if not years:
        sys.exit("FATAL: no ga-executive-orders-*.json files found")
    orders = all_orders(years)

    artifacts = {}
    # Per-year JSON passthrough.
    for year, doc in years.items():
        artifacts[f"data/{year}.json"] = build_json(doc)
    artifacts["data/executive-orders.csv"] = orders_csv(orders)
    artifacts["data/executive-orders.schema.json"] = build_json(schema())
    artifacts["SUMMARY.md"] = summary_md(years, orders)
    return artifacts


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
