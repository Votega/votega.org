#!/usr/bin/env python3
"""Roll calls legis.ga.gov links to no bill.

GetVote's ItemVotedOn is empty on a few final votes (2026 SS "Veto Override" on HB 1192,
a 2025-26 bill; 2025-26 House "Adopt CCR" on HB 973), and the bill's own Votes list
leaves them out too, so only the GetVotes listing's text names the bill. Pins: the
listing text is resolved to the right bill (own session first, then a unique match in
the biennium), the vote is attached once with the right result, a linked roll call is
not attached from its listing, and the votes producer uses the same resolver.

Usage: python scripts/test_ga_unlinked_votes.py     (no network)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_bills_soap as G  # noqa: E402
from lib.ga_passage import listing_bill_refs, resolve_listing_bills  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


# --- the resolver -----------------------------------------------------------
check("refs", listing_bill_refs("HB 1192"), ["HB 1192"])
check("refs EX", listing_bill_refs("HB 9EX, HB 10 EX"), ["HB 9EX", "HB 10EX"])
check("refs empty", listing_bill_refs(""), [])
IDX = {("2025_26", "HB 1192"): 72000, ("2025_26", "HB 973"): 71000, ("2026_ss", "HB 1EX"): 74000}
check("cross-session", resolve_listing_bills("HB 1192", "2026_ss", IDX), [("HB 1192", "2025_26", 72000)])
check("own session first",
      resolve_listing_bills("HB 1192", "2025_26", {**IDX, ("2026_ss", "HB 1192"): 1}),
      [("HB 1192", "2025_26", 72000)])
check("ambiguous left out",
      resolve_listing_bills("HB 5", "2026_ss", {("2025_26", "HB 5"): 1, ("2023_24", "HB 5"): 2}), [])
check("unknown left out", resolve_listing_bills("SB 999", "2026_ss", IDX), [])


# --- attaching in the bills producer ----------------------------------------
def bill(session, ident, lid, votes=(), abstract="A BILL to amend the Official Code of Georgia"):
    return {"session": session, "identifier": ident, "legislationId": lid, "billType": "bill",
            "abstract": abstract, "legislationType": "GEN", "passageVotes": list(votes)}


def listing(vid, caption, date, yea, nay, text, time="3:22 PM"):
    return {"voteId": vid, "caption": caption, "date": date, "time": time, "yea": yea,
            "nay": nay, "excused": 5, "notVoting": 4, "legislation": text}


LISTINGS = {
    (1034, "House"): [listing(26675, "Veto Override", "2026-06-22", 94, 77, "HB 1192"),
                      listing(26700, "PASSAGE", "2026-06-22", 150, 10, "HB 1EX")],
    (1034, "Senate"): [listing(26701, "MORNING ROLL CALL", "2026-06-22", 50, 0, "")],
    (1033, "House"): [listing(25910, "Adopt CCR", "2026-02-25", 169, 2, "HB 973", "2:16 PM")],
    (1033, "Senate"): [listing(25000, "PASSAGE", "2025-03-03", 50, 2, "HB 1192")],
}
LINKED = {26700: [{"legislationId": 74000, "description": "HB 1EX"}],
          25000: [{"legislationId": 72000, "description": "HB 1192"}]}
calls = []


def detail_for(vid):
    calls.append(vid)
    return ("", "", LINKED.get(vid, []), [])


existing = {"chamber": "upper", "date": "2025-03-03", "time": "10:00", "result": "pass",
            "motionText": "PASSAGE", "yea": 50, "nay": 2, "other": 4}
bills = [bill("2025_26", "HB 1192", 72000, [existing]), bill("2025_26", "HB 973", 71000),
         bill("2026_ss", "HB 1EX", 74000)]
n = G.attach_unlinked_votes(bills, listings_for=lambda s, b: LISTINGS.get((s, b), []),
                            detail_for=detail_for)
check("attached count", n, 2)
hb1192, hb973, hb1ex = bills
override = [v for v in hb1192["passageVotes"] if v["motionText"] == "Veto Override"]
check("override attached once", len(override), 1)
if override:
    v = override[0]
    check("override result (two-thirds)", v["result"], "fail")
    check("override chamber", v["chamber"], "lower")
    check("override time", v["time"], "15:22")
    check("override other", v["other"], 9)
    check("override linkedBy", v["linkedBy"], "listing")
check("override sorted last", hb1192["passageVotes"][-1]["motionText"], "Veto Override")
check("CCR attached", [(v["motionText"], v["result"], v["time"]) for v in hb973["passageVotes"]],
      [("Adopt CCR", "pass", "14:16")])
check("linked vote not added from listing", len(hb1ex["passageVotes"]), 0)
check("existing vote not re-fetched", 25000 in calls, False)

again = G.attach_unlinked_votes(bills, listings_for=lambda s, b: LISTINGS.get((s, b), []),
                                detail_for=detail_for)
check("second run adds nothing", again, 0)
check("clock", (G._clock24("12:05 AM"), G._clock24("12:05 PM"), G._clock24("x")),
      ("00:05", "12:05", None))

# --- ga-legislators documents billSession ------------------------------------
import publish_ga_legislators as PL  # noqa: E402
vote_props = PL.votes_schema("sessions/2026-ss/votes.schema.json")["properties"]["votes"][
    "additionalProperties"]["properties"]
check("votes schema describes billSession", vote_props.get("billSession", {}).get("type"), "string")
check("votes schema version", PL.SCHEMA_VERSION, "1.1.0")

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
