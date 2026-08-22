#!/usr/bin/env python3
"""Build consumer-friendly bill artifacts for the Votega/ga-legislation repo.

Source: assets/data/ga-bills.json (+ ga-bills-subjects.json overrides).
Artifacts (repo root, matching ga-legislation's layout):
  ga-bills.json            Passthrough
  ga-bills-subjects.json   Passthrough (manual subject overrides)
  ga-bills.csv             One row per bill (flattened) — for spreadsheets
  ga-bills.schema.json     JSON Schema for ga-bills.json
  BILLS.md                 Overview: counts by chamber, status, type, and top subjects

Writes artifacts only; the workflow commits them. Dry-run to $OUT_DIR standalone.
"""
import csv
import io
import json
import os
import re
from collections import Counter

from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-legislation"
TOKEN_ENV = "GA_BILLS_TOKEN"

SRC_JSON = "assets/data/ga-bills.json"
SRC_SUBJECTS = "assets/data/ga-bills-subjects.json"

CHAMBER_LABEL = {"lower": "House", "upper": "Senate"}


def session_slug(meta):
    """Directory-friendly session label, e.g. '2025-2026'. Georgia runs two-year
    sessions, so past sessions are archived under sessions/<slug>/ and never overwritten
    when the source flips to a new session."""
    m = re.search(r"(\d{4})\D+(\d{4})", meta.get("sessionName") or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return (meta.get("session") or "unknown").replace("_", "-")


def bills_csv(bills):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["identifier", "billType", "chamber", "title", "status", "statusDate",
                "subjects", "primarySponsors", "sponsorCount", "billUrl"])
    for b in bills:
        sponsors = b.get("sponsors") or []
        primary = [s.get("name") for s in sponsors if s.get("primary")]
        w.writerow([
            b.get("identifier"), b.get("billType"),
            CHAMBER_LABEL.get(b.get("chamber"), b.get("chamber")),
            b.get("title"), b.get("status"), b.get("statusDate"),
            "; ".join(b.get("subjects") or []),
            "; ".join(primary), len(sponsors), b.get("billUrl"),
        ])
    return buf.getvalue().encode()


def bills_md(doc):
    bills = doc.get("bills", [])
    meta = doc.get("metadata", {})
    by_chamber = Counter(CHAMBER_LABEL.get(b.get("chamber"), b.get("chamber") or "?") for b in bills)
    by_type = Counter(b.get("billType") or "?" for b in bills)
    by_status = Counter(b.get("status") or "?" for b in bills)
    subjects = Counter(s for b in bills for s in (b.get("subjects") or []))

    L = ["# Georgia Bills", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta.get('generatedAt', '')} · {len(bills)} bills · "
             f"{meta.get('sessionName', '')}._")
    L.append("")
    L.append("> Full data in this session folder: [`bills.json`](bills.json) (richest — sponsors, "
             "votes, links) or [`bills.csv`](bills.csv) (one row per bill, for spreadsheets).")
    L.append("")

    def table(title, counter, cols=("Value", "Bills"), limit=None):
        out = [f"## {title}", "", f"| {cols[0]} | {cols[1]} |", "|---|---|"]
        items = counter.most_common(limit) if limit else sorted(counter.items())
        for k, n in items:
            out.append(f"| {k} | {n} |")
        out.append("")
        return out

    L += table("By chamber", by_chamber, ("Chamber", "Bills"))
    L += table("By type", by_type, ("Type", "Bills"))
    L += table("By status", by_status, ("Status", "Bills"), limit=15)
    L += table("Top subjects", subjects, ("Subject", "Bills"), limit=20)
    return ("\n".join(L) + "\n").encode()


def schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-legislation/main/ga-bills.schema.json",
        "title": "Georgia Bills",
        "description": "Bills and resolutions from the Georgia General Assembly (Open States), "
                       "enriched with party vote tallies where available.",
        "type": "object",
        "required": ["metadata", "bills"],
        "properties": {
            "metadata": {"type": "object"},
            "bills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "identifier", "title"],
                    "properties": {
                        "id": {"type": "string", "description": "Open States OCD bill id."},
                        "identifier": {"type": "string", "description": "e.g. 'HB 1', 'SB 264'."},
                        "billType": {"type": ["string", "null"], "description": "e.g. bill, resolution."},
                        "chamber": {"type": ["string", "null"], "enum": ["lower", "upper", None],
                                    "description": "'lower' = House, 'upper' = Senate."},
                        "title": {"type": "string"},
                        "abstract": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"]},
                        "statusDate": {"type": ["string", "null"]},
                        "subjects": {"type": "array", "items": {"type": "string"}},
                        "sponsors": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "primary": {"type": "boolean"}}}},
                        "billUrl": {"type": ["string", "null"]},
                        "textUrl": {"type": ["string", "null"]},
                        "passageVotes": {"type": "array"},
                        "governorAction": {"type": ["object", "string", "null"]},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }


def build_artifacts():
    doc = json.load(open(SRC_JSON, encoding="utf-8"))
    meta = doc.get("metadata", {})
    slug = session_slug(meta)
    base = f"sessions/{slug}"

    files = {
        "bills": f"{base}/bills.json",
        "billsCsv": f"{base}/bills.csv",
        "schema": f"{base}/bills.schema.json",
        "summary": f"{base}/BILLS.md",
    }
    artifacts = {
        files["bills"]: open(SRC_JSON, "rb").read(),
        files["billsCsv"]: bills_csv(doc.get("bills", [])),
        files["schema"]: build_json(schema()),
        files["summary"]: bills_md(doc),
    }
    if os.path.exists(SRC_SUBJECTS):
        subj_path = f"{base}/bills-subjects.json"
        artifacts[subj_path] = open(SRC_SUBJECTS, "rb").read()
        files["subjects"] = subj_path

    # Root pointer to the current session, so consumers can find "the latest bills"
    # without hard-coding a session; past sessions stay archived under sessions/.
    artifacts["latest.json"] = build_json({
        "currentSession": slug,
        "sessionName": meta.get("sessionName"),
        "generatedAt": meta.get("generatedAt"),  # source data timestamp (avoids churn)
        "billCount": len(doc.get("bills", [])),
        "files": files,
    })
    return artifacts


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
