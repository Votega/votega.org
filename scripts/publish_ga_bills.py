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
from collections import Counter

from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             session_name, session_slug, tag_session)
from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-legislation"
TOKEN_ENV = "GA_BILLS_TOKEN"

SRC_JSON = "assets/data/ga-bills.json"
SRC_SUBJECTS = "assets/data/ga-bills-subjects.json"

CHAMBER_LABEL = {"lower": "House", "upper": "Senate"}


def compact_json(obj):
    """Compact UTF-8 JSON bytes for the large per-session bills.json (pretty-printing
    the ~9 MB regular-session file would roughly double it)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


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
    """Split the biennium's bills by session into per-session archive dirs and refresh
    the root latest.json pointer. ga-bills.json now covers the whole biennium (each bill
    tagged with its `session`); each session directory gets a self-contained bills.json
    plus bills.csv, bills.schema.json, and BILLS.md. Closed sessions re-emit byte-stable."""
    doc = json.load(open(SRC_JSON, encoding="utf-8"))
    meta = doc.get("metadata", {})
    all_bills = doc.get("bills", [])
    subjects_bytes = open(SRC_SUBJECTS, "rb").read() if os.path.exists(SRC_SUBJECTS) else None

    bills_by_session = {}
    for b in all_bills:
        bills_by_session.setdefault(tag_session(b.get("session")), []).append(b)

    artifacts = {}
    sessions_index = []
    # Emit every session in the biennium, even one with no bills yet (a just-convened
    # special session), so the archive structure is complete and latest.json's
    # currentSession always resolves. Include any unexpected session id found in data.
    for sid in list(all_session_ids()) + [s for s in bills_by_session if s not in all_session_ids()]:
        sess_bills = bills_by_session.get(sid, [])
        slug = session_slug(sid)
        base = f"sessions/{slug}"
        sess_doc = {
            "metadata": {
                "session": sid,
                "sessionName": session_name(sid),
                "biennium": BIENNIUM,
                "generatedAt": meta.get("generatedAt"),
                "source": meta.get("source", "Open States API"),
                "totalBills": len(sess_bills),
            },
            "bills": sess_bills,
        }
        files = {
            "bills": f"{base}/bills.json",
            "billsCsv": f"{base}/bills.csv",
            "schema": f"{base}/bills.schema.json",
            "summary": f"{base}/BILLS.md",
        }
        artifacts[files["bills"]] = compact_json(sess_doc)
        artifacts[files["billsCsv"]] = bills_csv(sess_bills)
        artifacts[files["schema"]] = build_json(schema())
        artifacts[files["summary"]] = bills_md(sess_doc)
        if subjects_bytes is not None:
            files["subjects"] = f"{base}/bills-subjects.json"
            artifacts[files["subjects"]] = subjects_bytes
        sessions_index.append({
            "id": sid, "name": session_name(sid), "slug": slug,
            "billCount": len(sess_bills), "files": files,
        })

    active_slug = session_slug(meta.get("activeSession") or ACTIVE_SESSION)
    # Root pointer to the biennium and the session in progress; source timestamp avoids
    # churn. Past sessions stay archived under sessions/ and are never overwritten.
    artifacts["latest.json"] = build_json({
        "biennium": BIENNIUM,
        "currentSession": active_slug,
        "activeSession": meta.get("activeSession") or ACTIVE_SESSION,
        "generatedAt": meta.get("generatedAt"),
        "billCount": len(all_bills),
        "sessions": sorted(sessions_index, key=lambda s: s["slug"]),
    })
    return artifacts


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
