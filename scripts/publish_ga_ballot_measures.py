#!/usr/bin/env python3
"""Build consumer-friendly ballot-measure artifacts for the Votega/ga-legislation repo.

Source: assets/data/ga-ballot-measures.json (+ its schema).
Artifacts (written to repo root, matching ga-legislation's existing layout):
  ga-ballot-measures.json          Passthrough
  ga-ballot-measures.schema.json   Passthrough (already schema'd upstream)
  ga-ballot-measures.csv           One row per measure — for spreadsheets
  BALLOT-MEASURES.md               Human-readable table (renders on GitHub)

This generator writes artifacts only; the workflow commits them into the checked-out
ga-legislation repo (git-based, with concurrent-push retry). Run standalone to dry-run
into $OUT_DIR. See lib/sibling_publish.
"""
import csv
import io
import json
import os

from lib.sibling_publish import publish_or_dry_run

REPO = "Votega/ga-legislation"
TOKEN_ENV = "GA_BALLOT_MEASURES_TOKEN"  # unused in git-based publishing; enables API dry-run override

SRC_JSON = "assets/data/ga-ballot-measures.json"
SRC_SCHEMA = "assets/data/ga-ballot-measures.schema.json"


def measures_csv(measures):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "electionDate", "type", "status", "title", "subjects",
                "enablingBill", "enablingBillUrl", "summary"])
    for m in measures:
        el = m.get("enablingLegislation") or {}
        w.writerow([
            m.get("id"), m.get("electionDate"), m.get("type"), m.get("status"),
            m.get("title"), "; ".join(m.get("subjects") or []),
            el.get("identifier"), el.get("url"), m.get("summary"),
        ])
    return buf.getvalue().encode()


def measures_md(doc):
    measures = doc.get("measures", [])
    meta = doc.get("metadata", {})
    # Group by election date (newest first).
    dates = sorted({m.get("electionDate") for m in measures if m.get("electionDate")}, reverse=True)
    L = ["# Georgia Ballot Measures", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta.get('generatedAt', '')} · {len(measures)} measures._")
    L.append("")
    L.append("> Machine-readable: [`ga-ballot-measures.json`](ga-ballot-measures.json), "
             "[`ga-ballot-measures.csv`](ga-ballot-measures.csv).")
    L.append("")
    L.append("Status lifecycle: `potential` (passed the General Assembly, not yet certified) → "
             "`certified` (on the ballot) → `passed` / `failed` (outcome recorded after certification).")
    L.append("")
    for d in dates:
        L.append(f"## {d}")
        L.append("")
        L.append("| Measure | Type | Status | What it does |")
        L.append("|---------|------|--------|--------------|")
        for m in [x for x in measures if x.get("electionDate") == d]:
            title = (m.get("title") or "").replace("|", "\\|")
            summary = (m.get("summary") or "").replace("|", "\\|").replace("\n", " ")
            L.append(f"| {title} | {m.get('type', '')} | {m.get('status', '')} | {summary} |")
        L.append("")
    return ("\n".join(L) + "\n").encode()


def build_artifacts():
    doc = json.load(open(SRC_JSON, encoding="utf-8"))
    artifacts = {
        "ga-ballot-measures.json": open(SRC_JSON, "rb").read(),
        "ga-ballot-measures.csv": measures_csv(doc.get("measures", [])),
        "BALLOT-MEASURES.md": measures_md(doc),
    }
    if os.path.exists(SRC_SCHEMA):
        artifacts["ga-ballot-measures.schema.json"] = open(SRC_SCHEMA, "rb").read()
    return artifacts


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
