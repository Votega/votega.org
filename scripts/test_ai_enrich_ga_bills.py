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
        "2025_26|HB 1": entry(),
        "2025_26|HB 2": entry(review=True),                       # unreviewed draft
        "2025_26|HB 3": {"summary": "x", "session": "2025_26"},   # no flag = unreviewed
        "2025_26|HB 4": entry(),                                  # editor override below
        "2026_ss|SB 5": entry(session="2026_ss", refined=True),
        "2027_28|HB 1": entry("2027 text", session="2027_28"),    # same number, next biennium
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
    check("2027 HB 1 and 2025-26 HB 1 coexist",
          (s["2025_26|HB 1"]["text"], s["2027_28|HB 1"]["text"]), ("AI text", "2027 text"))
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


def bills_fixture():
    return {"bills": {
        "2025_26|HB 1": {"summary": "AI one", "subjects": ["HEALTH"], "session": "2025_26",
                 "generatedAt": "t1", "needsReview": True},
        "2025_26|HB 2": {"summary": "AI two", "subjects": [], "session": "2025_26",
                 "generatedAt": "t2", "needsReview": False},
    }}


def dec(key, action, against, **kw):
    return dict(kw, key=key, action=action, against=against, decidedAt="2026-11-23T00:00:00Z")


def review_cases():
    out = bills_fixture()
    r = A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1")])
    check("approve clears needsReview", out["bills"]["2025_26|HB 1"]["needsReview"], False)
    check("approve is reported as a change", r["changed"], ["2025_26|HB 1"])
    r = A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1")])
    check("replaying the same log changes nothing", (r["changed"], r["unchanged"]), ([], ["2025_26|HB 1"]))

    out = bills_fixture()
    A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1", summary="Edited.",
                                subjects=["EDUCATION", "EDUCATION", "MADE UP"])],
                      allowed={"EDUCATION", "HEALTH"})
    e = out["bills"]["2025_26|HB 1"]
    check("edited summary is used", e["summary"], "Edited.")
    check("model's original summary is kept", e["aiSummary"], "AI one")
    check("edited subjects deduped and filtered", e["subjects"], ["EDUCATION"])
    check("model's original subjects are kept", e["aiSubjects"], ["HEALTH"])
    check("edit is marked as a person's", e["humanEdited"], True)
    A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1", summary="Edited again.")])
    check("a second edit keeps the FIRST model original", e["aiSummary"], "AI one")

    out = bills_fixture()
    r = A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "OLD")])
    check("decision on re-drafted text is stale, not applied",
          (r["stale"], out["bills"]["2025_26|HB 1"]["needsReview"]), (["2025_26|HB 1"], True))
    r = A.apply_decisions(out, [dec("2023_24|HB 1", "approve", "t1")])
    check("decision for another biennium's bill is stale", r["stale"], ["2023_24|HB 1"])

    out = bills_fixture()
    r = A.apply_decisions(out, [dec("2025_26|HB 2", "revoke", "t2")])
    check("revoke without a note is refused", (r["invalid"], out["bills"]["2025_26|HB 2"]["needsReview"]),
          (["2025_26|HB 2"], False))
    A.apply_decisions(out, [dec("2025_26|HB 2", "revoke", "t2", note="Wrong amount")])
    check("revoke with a note reopens review", out["bills"]["2025_26|HB 2"]["needsReview"], True)

    out = bills_fixture()
    A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1"),
                            dec("2025_26|HB 1", "redo", "t1", note="Misses the fee")])
    e = out["bills"]["2025_26|HB 1"]
    check("the last decision wins", (e["needsReview"], e.get("redo"), e.get("reviewNote")),
          (True, True, "Misses the fee"))
    A.apply_decisions(out, [dec("2025_26|HB 1", "approve", "t1")])
    check("approving clears redo and the note", ("redo" in e, "reviewNote" in e), (False, False))
    check("review fields list covers what a review writes",
          all(f in A.REVIEW_FIELDS for f in ("needsReview", "reviewedAt", "reviewNote", "redo",
                                              "humanEdited", "aiSummary", "aiSubjects")), True)


def old_bills():
    return [{"identifier": "HB 1", "session": "2025_26"}, {"identifier": "SB 5", "session": "2026_ss"},
            {"identifier": "HB 2", "session": "2025_26"}, {"identifier": "HB 2", "session": "2027_28"}]


def old_file():
    return {"metadata": {"count": 3, "updatedAt": "x"}, "bills": {
        "HB 1": {"summary": "a", "session": "2025_26", "generatedAt": "t1"},
        "SB 5": {"summary": "b", "session": "2026_ss", "generatedAt": "t2"},
        "HB 2": {"summary": "c", "session": "2025_26", "generatedAt": "t3", "needsReview": False}}}


def raises(exc, fn):
    try:
        fn()
    except exc as e:
        return str(e) or True
    return False


def key_cases():
    import copy
    import tempfile
    old = old_file()
    snapshot = copy.deepcopy(old)
    new = A.migrate_keys(old, old_bills())
    check("migration leaves its input untouched", old, snapshot)
    check("migration keeps every entry (3 -> 3)", (len(old["bills"]), len(new["bills"])), (3, 3))
    check("migrated keys are session|identifier",
          sorted(new["bills"]), ["2025_26|HB 1", "2025_26|HB 2", "2026_ss|SB 5"])
    lost = [i for i, v in old["bills"].items() if new["bills"][v["session"] + "|" + i] != v]
    check("migration loses nothing (every entry round-trips unchanged)", lost, [])
    check("schema version stamped", new["metadata"]["schemaVersion"], A.SCHEMA_VERSION)
    new["bills"]["2027_28|HB 2"] = {"summary": "2027", "session": "2027_28", "generatedAt": "t9"}
    check("2027 HB 2 draft coexists with 2025-26 HB 2",
          (new["bills"]["2025_26|HB 2"]["summary"], new["bills"]["2027_28|HB 2"]["summary"]),
          ("c", "2027"))
    check("migration refuses an entry session ga-bills.json does not hold",
          bool(raises(ValueError, lambda: A.migrate_keys(
              {"bills": {"HB 1": {"session": "2027_28"}}}, old_bills()))), True)
    check("migration refuses a bill absent from ga-bills.json",
          bool(raises(ValueError, lambda: A.migrate_keys(
              {"bills": {"HB 99": {"session": "2025_26"}}}, old_bills()))), True)
    check("a session-less entry takes the only session holding its identifier",
          list(A.migrate_keys({"bills": {"SB 5": {"summary": "x"}}}, old_bills())["bills"]),
          ["2026_ss|SB 5"])
    check("a session-less entry with two candidate sessions is refused",
          bool(raises(ValueError, lambda: A.migrate_keys(
              {"bills": {"HB 2": {"summary": "x"}}}, old_bills()))), True)
    msg = raises(SystemExit, lambda: A.require_schema(old_file()))
    check("readers refuse an old-format file and name the fix", "migrate-keys" in str(msg), True)
    check("an empty old file is not an error", A.require_schema({"bills": {}}), None)
    import generate_ga_bills_soap as G
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ga-bill-ai.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(old_file(), f)
        msg = raises(SystemExit, lambda: G.load_ai_subjects(path))
        check("bills generator refuses an old-format AI file", "migrate-keys" in str(msg), True)
    bills = old_bills()
    check("--only bare id with one session resolves", A.resolve_only(["SB 5"], bills), {"2026_ss|SB 5"})
    check("--only session|id resolves", A.resolve_only(["2027_28|HB 2"], bills), {"2027_28|HB 2"})
    check("--only bare id narrowed by --session", A.resolve_only(["HB 2"], bills, "2027_28"),
          {"2027_28|HB 2"})
    check("--only ambiguous bare id is refused",
          bool(raises(SystemExit, lambda: A.resolve_only(["HB 2"], bills))), True)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "tools", "ai-summary-review.html"), encoding="utf-8") as f:
        html = f.read()
    check("review tool refuses an old-format file", "schemaVersion !== 2" in html, True)
    check("review tool takes the entry key, not a bare identifier",
          ("k.startsWith(e.session + '|')" in html and "([ident, e])" not in html), True)


def committed_file_case():
    out, pub = A.load_json(A.OUT_FILE), A.load_json(A.PUBLIC_FILE)
    if out is None or pub is None:
        print("  skip committed-file check (files not present)")
        return
    check("committed ga-bill-ai.json is schemaVersion 2",
          (out.get("metadata") or {}).get("schemaVersion"), 2)
    built = A.build_public(out, A.load_json(A.CURATED_FILE) or {})
    check("ga-bill-summaries.json matches the committed drafts (run `publish` if not)",
          pub.get("summaries"), built["summaries"])


if __name__ == "__main__":
    print("public summaries"); public_cases()
    print("model output parsing"); parse_cases()
    print("hashing and filters"); hash_and_filter_cases()
    print("review decisions"); review_cases()
    print("session keys"); key_cases()
    print("committed files"); committed_file_case()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")
