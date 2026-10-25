#!/usr/bin/env python3
"""Invariants of the Voteview fallback for Senate roll calls (lib/voteview.py).

senate.gov has refused every non-browser request since 2026-10-25, so new Senate
roll calls and VP tie-breaks come from Voteview's CSVs. What must not drift:

  * The join. Voteview numbers Senate roll calls across the whole Congress; ours
    restart each session, so (session, clerk_rollnumber) is the key. Keying on
    `rollnumber` would put session-2 votes under session-1 numbers.
  * Votes resolve to a bioguide id through the members file, never a name.
  * A tie-break is inferred from an equal tally on a question that CARRIED; a tied
    tally that failed is not one.
  * Missing input is None, not an empty dataset (a tally with no member votes
    would publish an empty party breakdown).

Run: python scripts/test_voteview.py        (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import voteview as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


ROLLS = (
    "congress,chamber,rollnumber,date,session,clerk_rollnumber,yea_count,nay_count,"
    "bill_number,vote_result,vote_desc,vote_question\n"
    "119,House,1,2025-01-03,1,2,218,216,,Passed,House thing,On Passage\n"
    "119,Senate,2,2025-01-04,1,1,60,40,PN9,Nomination Confirmed,A. Person to be X,On the Nomination\n"
    "119,Senate,3,2026-01-05,2,1,50,50,HR1,Bill Passed,\"A bill, long title\",On Passage of the Bill\n"
    "119,Senate,4,2026-01-06,2,2,50,50,S5,Motion Rejected,Failed tie,On the Motion\n"
)
VOTES = (
    "congress,chamber,rollnumber,icpsr,cast_code,prob\n"
    "119,Senate,2,1,1,99\n119,Senate,2,2,6,99\n119,Senate,2,3,9,99\n"
    "119,Senate,3,1,6,99\n119,Senate,3,2,1,99\n"
    "119,House,1,1,1,99\n"
)
MEMBERS = (
    "congress,chamber,icpsr,party_code,bioname,bioguide_id\n"
    "119,Senate,1,100,OSSOFF,O000174\n119,Senate,2,200,SMITH,S000001\n"
    "119,Senate,3,328,KING,K000383\n"
)


def fake_fetch(files):
    def fetch(url, label):
        for kind, raw in files.items():
            if f"/{kind}/" in url:
                return raw.encode()
        return None
    return fetch


data = V.load_senate(119, fake_fetch({"rollcalls": ROLLS, "votes": VOTES, "members": MEMBERS}))

check("only Senate rolls, keyed (session, clerk number)", sorted(data["rolls"]), [(1, 1), (2, 1), (2, 2)])
check("same clerk number in two sessions stays distinct",
      data["rolls"][(1, 1)]["rollnumber"] != data["rolls"][(2, 1)]["rollnumber"], True)

r = V.senate_roll(data, 1, 1, {"O000174"})
check("member vote resolved by bioguide", r["member_votes"], {"O000174": "Yea"})
check("party tally covers every senator who cast",
      r["party_tally"], {"Democratic": {"yea": 1, "nay": 0, "other": 0},
                         "Republican": {"yea": 0, "nay": 1, "other": 0},
                         "Independent": {"yea": 0, "nay": 0, "other": 1}})
check("nomination has no bill", (r["bill_type"], r["bill_number"]), (None, None))
r2 = V.senate_roll(data, 2, 1, set())
check("bill number split to type slug", (r2["bill_type"], r2["bill_number"]), ("hr", "1"))
check("quoted comma survives in title", r2["title"], "A bill, long title")
check("unknown roll is None", V.senate_roll(data, 9, 9, set()), None)

check("missing file -> None, not empty data",
      V.load_senate(119, fake_fetch({"rollcalls": ROLLS, "votes": VOTES})), None)

check("cast codes", [V.cast_label(c) for c in ("1", "3", "4", "6", "7", "9", "0")],
      ["Yea", "Yea", "Nay", "Nay", "Not Voting", "Not Voting", "Other"])
check("bill spellings", [V.split_bill_number(x) for x in ("SCONRES7", "sjres98", "PN1129", "", None)],
      [("sconres", "7"), ("sjres", "98"), (None, None), (None, None), (None, None)])

# VP inference, via the generator's helper.
import generate_vp_tie_votes as G  # noqa: E402
G.voteview.load_senate = lambda congress, fetch=None: data
found = G.voteview_tie_breaks(119, set())
check("only the tie that carried is a tie-break", [(v["session"], v["voteNumber"]) for v in found],
      [(2, "00001")])
check("tie-break shape", (found[0]["vpVote"], found[0]["document"], found[0]["yeas"], found[0]["nays"]),
      ("Yea", "H.R. 1", 50, 50))
check("already-held tie-break is not re-added", G.voteview_tie_breaks(119, {(2, "00001")}), [])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
