#!/usr/bin/env python3
"""The Governor's veto messages and signing statements (scripts/import_governor_statements.py
and generate_ga_bills_soap.attach_governor_statements).

Pins: blocks are split on "VETO n" / "SIGNING STATEMENT n"; the bill comes from the
closing line, not the first bill mentioned; wrapped lines are rejoined and paragraphs kept;
page furniture is dropped; the import refuses a veto the data does not have, a vetoed
bill with no message, and gapped numbering; statements reach their bills with the veto
number, and the tracker's Governor step names it.

Usage: python scripts/test_governor_statements.py     (no network)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_bills_soap as G  # noqa: E402
import import_governor_statements as I  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


PDF = """                             GOVERNOR BRIAN P. KEMP
                  2026 SESSION OF THE GEORGIA GENERAL ASSEMBLY
                     VETO MESSAGES AND SIGNING STATEMENTS

                                            VETO 1

House Bill 14 would establish a Georgia Music Office. Unlike Senate Bill 9, which
the General Assembly funded, this bill carries costs.

For the foregoing reasons, I VETO HOUSE BILL 14.

                                        Page 1 of 5
                                            VETO 2

At the request of the sponsor, I VETO SENATE BILL 46.

                                 SIGNING STATEMENT 1

House Bill 1247 revises the statutes relating to agency rules.

I therefore sign House Bill 1247 into law.

                                             ++
"""
parsed = I.parse(PDF)
check("three blocks", [(s["kind"], s["number"], s["bill"]) for s in parsed],
      [("veto", 1, "HB 14"), ("veto", 2, "SB 46"), ("signing", 1, "HB 1247")])
check("closing line wins over a bill mentioned earlier", parsed[0]["bill"], "HB 14")
check("lines rejoined, paragraphs kept", parsed[0]["text"],
      "House Bill 14 would establish a Georgia Music Office. Unlike Senate Bill 9, which the General "
      "Assembly funded, this bill carries costs.\n\nFor the foregoing reasons, I VETO HOUSE BILL 14.")
check("page furniture dropped", any("Page 1" in s["text"] or "++" in s["text"] for s in parsed), False)


def bill(ident, status=None, decided="2026-05-12", session="2025_26"):
    ga = {"status": status, "decisionDate": decided} if status else None
    return {"identifier": ident, "session": session, "governorAction": ga}


BILLS = [bill("HB 14", "Vetoed"), bill("SB 46", "Vetoed"), bill("HB 1247", "Signed"),
         bill("SB 9", "Vetoed", "2025-05-14")]
check("matches", I.check_against_bills(parsed, 2026, "2025_26", BILLS), [])
check("a veto the data lacks", I.check_against_bills(parsed, 2026, "2025_26", BILLS[1:]),
      ["VETO 1 names HB 14, which ga-bills.json does not have as vetoed in 2026"])
check("a vetoed bill with no message",
      I.check_against_bills(parsed, 2026, "2025_26", BILLS + [bill("SB 5", "Vetoed")]),
      ["SB 5 was vetoed in 2026 but has no veto message"])
gap = [dict(parsed[0]), dict(parsed[1], number=3), parsed[2]]
check("gapped numbering", I.check_against_bills(gap, 2026, "2025_26", BILLS)[0],
      "veto numbers are not 1..2: [1, 3]")

# --- attached to the bills, with the veto number --------------------------------
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "s.json")
    json.dump({"statements": [dict(s, year=2026, session="2025_26", sourceUrl="https://example/x")
                              for s in parsed]}, open(path, "w"))
    bills = [bill("HB 14", "Vetoed"), bill("HB 1247", "Signed"), bill("HB 14", "Vetoed", session="2027_28"),
             dict(bill("HB 2"), governorStatements=["stale"])]
    check("attached", G.attach_governor_statements(bills, path), 2)
    check("veto number", bills[0]["governorAction"].get("vetoNumber"), 1)
    check("statement text", bills[0]["governorStatements"][0]["text"].endswith("I VETO HOUSE BILL 14."), True)
    check("signing statement", bills[1]["governorStatements"][0]["kind"], "signing")
    check("other session untouched", "governorStatements" in bills[2], False)
    check("stale statements removed", "governorStatements" in bills[3], False)
    check("missing file", G.attach_governor_statements(bills, os.path.join(d, "none.json")), 0)

from lib.ga_bill_stage import bill_stage  # noqa: E402
vetoed = {"chamber": "lower", "billType": "bill", "legislationType": "GEN", "committees": [],
          "statusHistory": [["2026-02-05T10:00:00", "HPA"], ["2026-03-20T10:00:00", "SPA"],
                            ["2026-04-10T10:00:00", "HSG"]], "passageVotes": [],
          "governorAction": {"status": "Vetoed", "decisionDate": "2026-05-12", "vetoNumber": 1}}
check("tracker names the veto", bill_stage(vetoed, True)["steps"][5], ["stopped", "Vetoed", "May 12, 2026 · Veto 1"])

# --- the committed file matches the committed bills -----------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
committed = json.load(open(os.path.join(ROOT, "assets", "data", "ga-governor-statements.json"), encoding="utf-8"))
all_bills = json.load(open(os.path.join(ROOT, "assets", "data", "ga-bills.json"), encoding="utf-8"))["bills"]
for src in committed["metadata"]["sources"]:
    st = [s for s in committed["statements"] if s["year"] == src["year"]]
    check("committed %d matches ga-bills.json" % src["year"],
          I.check_against_bills(st, src["year"], src["session"], all_bills), [])

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
