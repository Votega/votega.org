#!/usr/bin/env python3
"""Assert the AI subject layer in generate_ga_bills_soap.py stays the LAST resort.

AI tags (assets/data/ga-bill-ai.json, written by ai_enrich_ga_bills.py) may only fill a
bill that every other source leaves untagged, only once reviewed, only for the same
session, and must be undone when withdrawn — a preserved bill carries last run's
subjects verbatim, so a stale AI tag would otherwise stick forever.

Usage:
  python scripts/test_ga_bill_ai_subjects.py

Exits 0 on success, 1 on any failure. Standard library only, no network.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_bills_soap as G  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def bill(ident="HB 1", session="2025_26", subjects=None, source=None):
    b = {"identifier": ident, "session": session, "subjects": list(subjects or [])}
    if source:
        b["subjectsSource"] = source
    return b


AI = {"2025_26|HB 1": {"session": "2025_26", "subjects": ["Education"]}}


def layered(b, base=None, overrides=None, ai=AI):
    G.apply_subjects(b, base or {}, overrides or {}, ai)
    return b.get("subjects"), b.get("subjectsSource")


def precedence_cases():
    check("AI fills an untagged bill, marked as AI",
          layered(bill()), (["Education"], "ai"))
    check("manual override beats AI",
          layered(bill(), overrides={"HB 1": ["Health"]}), (["Health"], None))
    check("base snapshot beats AI",
          layered(bill(), base={"HB 1": ["Taxation"]}), (["Taxation"], None))
    check("derived fallback beats AI",
          layered(bill(subjects=["Local / Municipal"])), (["Local / Municipal"], None))
    check("AI for another session is ignored",
          layered(bill(session="2026_ss")), ([], None))
    check("AI for the same number in a later biennium is ignored",
          layered(bill(session="2027_28")), ([], None))
    check("no AI layer leaves an untagged bill untagged",
          layered(bill(), ai={}), ([], None))


def stale_cases():
    check("withdrawn AI tag on a preserved bill is cleared",
          layered(bill(subjects=["Education"], source="ai"), ai={}), ([], None))
    check("preserved AI tag is replaced when a manual override arrives",
          layered(bill(subjects=["Education"], source="ai"), overrides={"HB 1": ["Health"]}),
          (["Health"], None))
    check("preserved AI tag is re-applied when still reviewed",
          layered(bill(subjects=["Education"], source="ai")), (["Education"], "ai"))
    check("the layer never mutates the AI map's list",
          AI["2025_26|HB 1"]["subjects"], ["Education"])


def load_cases():
    data = {"metadata": {"schemaVersion": 2}, "bills": {
        "2025_26|HB 1": {"session": "2025_26", "subjects": ["Education", "Made Up"], "needsReview": False},
        "2025_26|HB 2": {"session": "2025_26", "subjects": ["Health"], "needsReview": True},
        "2025_26|HB 3": {"session": "2025_26", "subjects": ["Health"]},        # no flag = unreviewed
        "2025_26|HB 4": {"subjects": ["Health"], "needsReview": False},        # no session
        "2025_26|HB 5": {"session": "2025_26", "subjects": ["Made Up"], "needsReview": False},
        "2026_ss|HB 6": {"session": "2025_26", "subjects": ["Health"], "needsReview": False},  # key/session disagree
    }}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ga-bill-ai.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        got = G.load_ai_subjects(path, allowed={"Education", "Health"})
        check("only reviewed, session-tagged, in-taxonomy tags load", got,
              {"2025_26|HB 1": {"session": "2025_26", "subjects": ["Education"]}})
        check("missing file means no AI layer",
              G.load_ai_subjects(os.path.join(d, "nope.json")), {})
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        check("unreadable file means no AI layer, not a crash",
              G.load_ai_subjects(path), {})


if __name__ == "__main__":
    print("precedence"); precedence_cases()
    print("stale AI tags"); stale_cases()
    print("loading"); load_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")
