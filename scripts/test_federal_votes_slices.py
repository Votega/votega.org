#!/usr/bin/env python3
"""Invariants of the federal roll-call slice format (build_federal_votes_slices.py).

Two things here can break silently, which is why they are tested rather than
commented:

  * The row format is split across two languages. This script writes positional
    rows; _includes/entity/federal-legislator.html reads them by FV_* position and
    rebuilds each bill's label and permalink from a type table of its own. A drift
    in either shifts every field by one, or renders every permalink wrong, with no
    error anywhere.
  * A bill-less vote must round-trip as null. Now that the generator enumerates the
    chambers' own indexes rather than enacted laws, quorum calls, procedural motions
    and Senate nominations are a large share of the record and have no measure at
    all. CLAUDE.md: optional fields are null, never "".

Run: python scripts/test_federal_votes_slices.py        (no network, no repo writes)
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_federal_votes_slices as B
from lib.votes_schema import VOTE_CODES

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def fixture():
    """Four roll calls covering every bill shape the two chambers produce: a House
    bill, a Senate measure, a House quorum call and a Senate nomination — the last
    two with no measure at all."""
    votes = {
        "H2025_0001": {
            "bill": None, "billUrl": None, "billType": None, "billNumber": None,
            "title": None, "motionText": "Call by States", "date": "2025-01-03",
            # A Speaker election records the WINNER'S NAME as its result, which
            # pass_fail() carries through rather than asserting a defeat.
            "yea": 0, "nay": 0, "chamber": "House", "result": "Johnson (LA)",
            "partyTally": {"Republican": {"yea": 0, "nay": 0, "other": 219},
                           "Democratic": {"yea": 0, "nay": 0, "other": 215}},
        },
        "H2026_0081": {
            "bill": "S. 723", "billUrl": "https://example.invalid/723",
            "billType": "s", "billNumber": "723",
            "title": "Tribal Trust Land Homeownership Act",
            "motionText": "On Motion to Suspend the Rules and Pass",
            "date": "2026-03-04", "yea": 384, "nay": 40, "chamber": "House",
            "result": "Pass",
            "partyTally": {"Republican": {"yea": 176, "nay": 39, "other": 3},
                           "Democratic": {"yea": 208, "nay": 1, "other": 5},
                           "Independent": {"yea": 0, "nay": 0, "other": 0}},
        },
        "S119_1_00050": {
            "bill": None, "billUrl": None, "billType": None, "billNumber": None,
            "title": "Tulsi Gabbard, of Hawaii, to be Director of National Intelligence",
            "motionText": "On the Nomination", "date": "2025-02-12",
            "yea": 52, "nay": 48, "chamber": "Senate", "result": "Pass",
            "partyTally": {"Republican": {"yea": 52, "nay": 1, "other": 0},
                           "Democratic": {"yea": 0, "nay": 45, "other": 2}},
        },
        "S119_2_00100": {
            "bill": "S.Con.Res. 33", "billUrl": "https://example.invalid/33",
            "billType": "sconres", "billNumber": "33",
            "title": "To establish a deficit-neutral reserve fund",
            "motionText": "On the Amendment", "date": "2026-04-23",
            "yea": 46, "nay": 52, "chamber": "Senate", "result": "Fail",
            "partyTally": None,
        },
    }
    member_votes = {
        # A House member votes only on House rolls, a senator only on Senate ones;
        # the compact index must stay aligned across both.
        "A000372": [{"voteId": "H2025_0001", "vote": "Not Voting"},
                    {"voteId": "H2026_0081", "vote": "Yea"}],
        "O000174": [{"voteId": "S119_1_00050", "vote": "Nay"},
                    {"voteId": "S119_2_00100", "vote": "Yea"}],
    }
    return {"metadata": {"congress": 119, "sessionName": "119th Congress"},
            "votes": votes, "memberVotes": member_votes}


def run_builder(data):
    """Run the builder against a temp data dir and return (index, {bioguide: slice})."""
    with tempfile.TemporaryDirectory() as tmp:
        votes_file = os.path.join(tmp, "federal-member-votes.json")
        with open(votes_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        saved = (B.VOTES_FILE, B.INDEX_OUT, B.SLICES_DIR)
        B.VOTES_FILE = votes_file
        B.INDEX_OUT = os.path.join(tmp, "federal-votes-index.json")
        B.SLICES_DIR = os.path.join(tmp, "federal-votes")
        try:
            rc = B.main()
            with open(B.INDEX_OUT, encoding="utf-8") as fh:
                index = json.load(fh)
            slices = {}
            for name in sorted(os.listdir(B.SLICES_DIR)):
                with open(os.path.join(B.SLICES_DIR, name), encoding="utf-8") as fh:
                    slices[name[:-5]] = json.load(fh)
            return rc, index, slices
        finally:
            B.VOTES_FILE, B.INDEX_OUT, B.SLICES_DIR = saved


data = fixture()
rc, index, slices = run_builder(data)

print("Index shape:")
check("builder succeeded", rc, 0)
check("voteIds cover every vote, in the monolith's order",
      index["voteIds"], list(data["votes"].keys()))
check("one row per voteId", len(index["rows"]), len(index["voteIds"]))
check("row field order is published in the metadata",
      index["metadata"]["sliceFormat"], list(B.ROW_FIELDS))

print("Bill-less votes:")
quorum = index["rows"][index["voteIds"].index("H2025_0001")]
check("a quorum call carries no bill type", quorum[B.R_BILLTYPE], None)
check("a result that is neither pass nor fail is carried through verbatim",
      quorum[B.R_RESULT], "Johnson (LA)")
check("pass and fail still encode to one letter",
      (B.compact_result("Pass"), B.compact_result("Fail")), ("P", "F"))
check("a quorum call carries no bill number", quorum[B.R_BILLNUM], None)
nomination = index["rows"][index["voteIds"].index("S119_1_00050")]
check("a nomination carries no bill type", nomination[B.R_BILLTYPE], None)
check("a nomination keeps its subject as the title",
      nomination[B.R_TITLE].startswith("Tulsi Gabbard"), True)
check("no row uses an empty string where null is meant",
      [f for row in index["rows"] for f in row if f == ""], [])

print("Row contents:")
house = index["rows"][index["voteIds"].index("H2026_0081")]
check("chamber is a single letter", (house[B.R_CHAMBER], nomination[B.R_CHAMBER]), ("H", "S"))
check("bill type/number survive for a measure", (house[B.R_BILLTYPE], house[B.R_BILLNUM]), ("s", "723"))
check("result is a single letter", house[B.R_RESULT], "P")
check("motion text is interned, not repeated",
      index["motions"][house[B.R_MOTION]], "On Motion to Suspend the Rules and Pass")
check("motion table holds one entry per distinct motion", len(index["motions"]), 4)
check("tally is six flat ints, Dem then Rep", house[B.R_TALLY], [208, 1, 5, 176, 39, 3])
check("an absent tally stays null",
      index["rows"][index["voteIds"].index("S119_2_00100")][B.R_TALLY], None)

print("Per-member slices:")
check("one slice per member with votes", sorted(slices), ["A000372", "O000174"])
check("slice names its member", slices["A000372"]["bioguideId"], "A000372")
# Compact keys are indices into voteIds; decoding them must give back the member's
# own roll calls and nobody else's.
decoded = {index["voteIds"][int(i)]: code for i, code in slices["O000174"]["compact"].items()}
check("senator's slice decodes to their own votes",
      decoded, {"S119_1_00050": "N", "S119_2_00100": "Y"})
check("codes come from the shared codec",
      set(slices["A000372"]["compact"].values()) <= set(VOTE_CODES.values()), True)

print("Determinism:")
rc2, index2, slices2 = run_builder(fixture())
check("a re-run is byte-identical",
      (json.dumps(index2, sort_keys=False), json.dumps(slices2, sort_keys=True)),
      (json.dumps(index, sort_keys=False), json.dumps(slices, sort_keys=True)))

# ---------------------------------------------------------------------------
# The format is split across two languages: this builder writes the rows,
# _includes/entity/federal-legislator.html reads them by position and rebuilds each
# bill label from its own prefix table. A comment asking the next person to keep
# them in step is not enforcement, so the test reads the include and compares.

INCLUDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "_includes", "entity", "federal-legislator.html")

print("Cross-language constants (python <-> the entity include):")
with open(INCLUDE, encoding="utf-8") as fh:
    include_src = fh.read()

js_positions = dict((name, int(pos)) for name, pos in
                    re.findall(r"FV_([A-Z_]+)\s*=\s*(\d+)", include_src))
check("row positions in the include match ROW_FIELDS",
      js_positions,
      {"CHAMBER": 0, "DATE": 1, "BILLTYPE": 2, "BILLNUM": 3, "TITLE": 4,
       "MOTION": 5, "RESULT": 6, "YEA": 7, "NAY": 8, "TALLY": 9})
check("python writes exactly that many fields", len(B.ROW_FIELDS), len(js_positions))

# The label table is the include's own; the generator holds the authoritative copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "fedvotes", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "generate_federal_votes_data.py"))
fedvotes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fedvotes)

js_label = re.search(r"const FED_BILL_LABEL = \{(.*?)\};", include_src, re.S)
check("include still declares FED_BILL_LABEL", bool(js_label), True)
if js_label:
    check("bill-type labels match TYPE_LABEL in the generator",
          dict(re.findall(r"(\w+):\s*'([^']+)'", js_label.group(1))),
          fedvotes.TYPE_LABEL)

# Every type the generator can emit must be renderable by the include: a label from
# FED_BILL_LABEL and a permalink slug from BILL_TYPE_SLUG (uppercased keys there).
js_slug = re.search(r"const BILL_TYPE_SLUG = \{(.*?)\};", include_src, re.S)
if js_slug:
    slugs = dict(re.findall(r"(\w+):\s*'([^']+)'", js_slug.group(1)))
    check("every generator bill type has a permalink slug in the include",
          sorted(t for t in fedvotes.TYPE_SLUG if t.upper() not in slugs), [])

# The vote-code table the slices are written with must be the one the include decodes.
js_code = re.search(r"const FED_VOTE_CODE = \{(.*?)\};", include_src, re.S)
check("include still declares FED_VOTE_CODE", bool(js_code), True)
if js_code:
    check("vote codes match lib/votes_schema.py",
          dict((v, k) for k, v in re.findall(r"(\w+):\s*'([^']+)'", js_code.group(1))),
          VOTE_CODES)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    raise SystemExit(1)
print("All federal vote slice invariants hold.")
