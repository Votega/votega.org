#!/usr/bin/env python3
"""Assert what ai_enrich_ga_bills.py lets reach the public site, and how it parses models.

The site shows ga-bill-summaries.json, never ga-bill-ai.json. The rules pinned here:
an unreviewed draft never reaches it, an editor summaryOverride always beats AI text,
and keys carry the session because bill numbers restart each biennium. The committed
public file must also match what the committed drafts build, so approving an entry
without running `publish` fails here instead of silently never showing.

Usage:
  python scripts/test_ai_enrich_ga_bills.py

Exits 0 on success, 1 on any failure. Standard library only, no network.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_enrich_ga_bills as A  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def entry(summary="AI text", session="2025_26", review=False, refined=False):
    return {"summary": summary, "session": session, "needsReview": review, "refined": refined}


def public_cases():
    out = {"bills": {
        "HB 1": entry(),
        "HB 2": entry(review=True),                       # unreviewed draft
        "HB 3": {"summary": "x", "session": "2025_26"},   # no flag = unreviewed
        "HB 4": entry(),                                  # editor override below
        "SB 5": entry(session="2026_ss", refined=True),
    }}
    curated = {"ga": [
        {"identifier": "HB 4", "session": "2025_26", "summaryOverride": "Editor text"},
        {"identifier": "HB 1", "session": "2023_24", "summaryOverride": "Old biennium"},
        {"identifier": "HB 9", "session": "2025_26", "summaryOverride": "  "},
    ]}
    s = A.build_public(out, curated)["summaries"]
    check("reviewed AI summary is published", s.get("2025_26|HB 1"),
          {"text": "AI text", "source": "ai", "refined": False})
    check("unreviewed drafts are not published",
          [k for k in s if k.endswith(("HB 2", "HB 3"))], [])
    check("editor summary beats AI text", s.get("2025_26|HB 4"),
          {"text": "Editor text", "source": "editor"})
    check("same number in another biennium is a separate entry", s.get("2023_24|HB 1"),
          {"text": "Old biennium", "source": "editor"})
    check("blank override is skipped", "2025_26|HB 9" in s, False)
    check("refined flag carried", s.get("2026_ss|SB 5", {}).get("refined"), True)


def parse_cases():
    allowed = ["EDUCATION", "HEALTH"]
    r = A.clean_result('```json\n{"summary": "S", "subjects": ["HEALTH"], "confidence": "high"}\n```', allowed)
    check("code fences stripped", r, {"summary": "S", "subjects": ["HEALTH"], "confidence": "high"})
    r = A.clean_result('{"summary": "S", "subjects": [], "confidence": "high"}\n\nNote: I kept it short.', allowed)
    check("text after the JSON is ignored", r["summary"], "S")
    r = A.clean_result({"summary": "S", "subjects": ["HEALTH", "HEALTH", "MADE UP", "EDUCATION"],
                        "confidence": "sure"}, allowed)
    check("subjects deduped and filtered to the taxonomy", r["subjects"], ["HEALTH", "EDUCATION"])
    check("unknown confidence becomes low", r["confidence"], "low")
    try:
        A.clean_result({"summary": " ", "subjects": []}, allowed)
        check("empty summary rejected", "no error", "ValueError")
    except ValueError:
        check("empty summary rejected", True, True)


def hash_and_filter_cases():
    b = {"identifier": "HB 1", "title": "T", "abstract": "A"}
    check("hash changes with the model", A.input_hash(b, "m1") != A.input_hash(b, "m2"), True)
    check("hash stable for same inputs", A.input_hash(b, "m1"), A.input_hash(dict(b), "m1"))
    check("honorary resolution is ceremonial",
          A.is_ceremonial({"identifier": "HR 5", "title": "Smith, Jane; commend"}), True)
    check("a bill is never ceremonial",
          A.is_ceremonial({"identifier": "HB 5", "title": "Smith Day; recognize"}), False)
    check("substantive resolution is not ceremonial",
          A.is_ceremonial({"identifier": "SR 7", "title": "Congress; pass the Act; urge"}), False)


def committed_file_case():
    out, pub = A.load_json(A.OUT_FILE), A.load_json(A.PUBLIC_FILE)
    if out is None or pub is None:
        print("  skip committed-file check (files not present)")
        return
    built = A.build_public(out, A.load_json(A.CURATED_FILE) or {})
    check("ga-bill-summaries.json matches the committed drafts (run `publish` if not)",
          pub.get("summaries"), built["summaries"])


if __name__ == "__main__":
    print("public summaries"); public_cases()
    print("model output parsing"); parse_cases()
    print("hashing and filters"); hash_and_filter_cases()
    print("committed files"); committed_file_case()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")
