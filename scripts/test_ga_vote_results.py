#!/usr/bin/env python3
"""Offline tests for re-deriving published GA results and cross-checking them.

Covers lib/ga_vote_results.py (re-derivation from a record's own fields, the abstract
lookup), rederive_ga_vote_results.py, publish_ga_legislators.py correct-results (only
`result` and two metadata keys change, byte-for-byte), and check_ga_vote_status.py
(status-history matching, including a lost vote that was retaken the same day).
No network: every legis.ga.gov call is a stub.

Usage:
  python scripts/test_ga_vote_results.py
"""

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_vote_results import (amendment_ids_from_soap, legislation_id,  # noqa: E402
                                 rederive_bill_passage_votes, rederive_votes,
                                 two_thirds_candidate_ids)
import check_ga_vote_status as chk  # noqa: E402
import publish_ga_legislators as pub  # noqa: E402
import rederive_ga_vote_results as rdr  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def vote(bill, lid, chamber, date, yea, nay, result="Pass", motion="PASSAGE", time=None,
         title="", session="2017_18"):
    v = {"bill": bill, "billUrl": "https://www.legis.ga.gov/legislation/%d" % lid,
         "title": title, "session": session, "motionText": motion, "chamber": chamber,
         "date": date, "yea": yea, "nay": nay, "result": result}
    if time:
        v["time"] = time
    return v


H, S = "House of Representatives", "Senate"
VOTES = {
    "15309-49598": vote("SB 1", 49598, H, "2017-03-28", 85, 83, time="10:39 PM"),
    "15311-49598": vote("SB 1", 49598, H, "2017-03-28", 84, 83, time="10:42 PM"),
    "15476-49827": vote("HB 125", 49827, S, "2017-03-30", 35, 16, time="8:06 PM",
                        motion="PASSAGE BY SUBSTITUTE"),
    "15501-49827": vote("HB 125", 49827, S, "2017-03-30", 27, 14, time="10:54 PM",
                        motion="AGREE TO HOUSE AMENDMENT TO HOUSE SUBSTITUTE"),
    "15503-49827": vote("HB 125", 49827, S, "2017-03-30", 32, 15, time="10:57 PM",
                        motion="AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE"),
    "14955-50033": vote("SR 104", 50033, S, "2017-02-28", 34, 16, time="11:00 AM"),
    "17771-57775": vote("HB 1029", 57775, H, "2020-06-17", 90, 69, time="11:40 AM",
                        session="2019_20"),
    "15652-52082": vote("HB 707", 52082, H, "2018-02-14", 107, 50, motion="Local Calendar",
                        title="Roswell, City of; homestead exemption; provide"),
    "1-1": vote("HB 9", 1, H, "2017-01-12", 157, 0, title="Jefferson County; levy tax"),
}
ABSTRACTS = {
    50033: ("SR 104", "A RESOLUTION proposing an amendment to the Constitution so as to"),
    52082: ("HB 707", "A BILL to provide for a new homestead exemption from City of Roswell "
                      "ad valorem taxes for municipal purposes; to provide for a referendum"),
}


def fake_record(lid):
    ident, summary = ABSTRACTS.get(lid, ("", ""))
    return {"identifier": ident, "summary": summary, "statusHistory": HISTORY.get(lid, [])}


def st(date, desc):
    return {"date": date, "code": "", "description": desc}


HISTORY = {
    49598: [st("2017-03-28T22:41:00", "House Third Readers"),
            st("2017-03-28T22:44:00", "House Third Reading Lost"),
            st("2017-03-28T22:44:30", "House Reconsidered"),
            st("2017-03-28T22:45:00", "House Lost Reconsidered Bill/Resolution")],
    # The 27-14 concurrence was lost without a "Lost" entry, then retaken at 32-15.
    49827: [st("2017-03-30T20:08:00", "Senate Passed/Adopted By Substitute"),
            st("2017-03-30T21:47:00", "House Agreed Senate Amend or Sub As Amended"),
            st("2017-03-30T23:00:00", "Senate Agreed House Amend or Sub")],
    50033: [st("2017-02-28T11:01:00", "Senate Lost")],
    57775: [st("2020-06-17T11:41:00", "House Passed/Adopted"),
            st("2020-06-17T12:16:00", "House Notice to Reconsider")],
    52082: [st("2018-02-14T11:00:00", "House Third Reading Lost")],
    1: [],
}

# --- candidates for the abstract lookup ---------------------------------------
cands = two_thirds_candidate_ids(VOTES)
check("resolution is a candidate", 50033 in cands, True)
check("homestead title is a candidate", 52082 in cands, True)
check("ordinary bill is not", 1 in cands, False)
check("bill with no title is", 49598 in cands, True)
ids = amendment_ids_from_soap(cands, fetch=fake_record)
check("two-thirds ids", ids, {50033, 52082})
try:
    amendment_ids_from_soap({50033}, fetch=lambda lid: None)
    failures.append("a failed lookup must raise")
except RuntimeError:
    pass
check("legislation id", legislation_id(VOTES["1-1"]), 1)

# --- re-derivation ---------------------------------------------------------------
votes = copy.deepcopy(VOTES)
changes = rederive_votes(votes, ids)
check("flipped", sorted(c[0] for c in changes),
      ["14955-50033", "15309-49598", "15311-49598", "15501-49827", "15652-52082"])
check("HB 125 re-vote stays Pass", votes["15503-49827"]["result"], "Pass")
check("HB 1029 exception stays Pass", votes["17771-57775"]["result"], "Pass")
check("idempotent", rederive_votes(votes, ids), [])

bill = {"legislationId": 70344, "billType": "bill", "abstract": "A BILL to prohibit",
        "passageVotes": [{"chamber": "upper", "date": "2025-03-03", "yea": 36, "nay": 19,
                          "result": "pass", "motionText": "PASSAGE"},
                         {"chamber": "lower", "date": "2026-03-31", "yea": 89, "nay": 73,
                          "result": "pass", "motionText": "PASSAGE"}]}
check("ga-bills SB 175 changed", rederive_bill_passage_votes(bill), 1)
check("ga-bills SB 175 House fail", bill["passageVotes"][1]["result"], "fail")
check("ga-bills SB 175 Senate pass", bill["passageVotes"][0]["result"], "pass")

# --- rederive_ga_vote_results + publish correct-results: only results change ------
doc = {"metadata": {"session": "2017_18", "archive": True, "amendmentRuleApplied": False},
       "votes": copy.deepcopy(VOTES),
       "memberVotes": {"p1": [{"voteId": "15309-49598", "vote": "Yea"}]}}
with tempfile.TemporaryDirectory() as tmp:
    src, out, rep = (os.path.join(tmp, n) for n in ("in.json", "out.json", "rep.json"))
    with open(src, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    rows = rdr.main([src, out, "--report", rep, "--amendment-ids", "50033,52082"])
    check("cli rows", len(rows), 5)
    fixed = json.load(open(out, encoding="utf-8"))
    check("rule recorded", fixed["metadata"]["amendmentRuleApplied"], True)
    check("rule text", bool(fixed["metadata"].get("resultRule")), True)
    a, b = copy.deepcopy(doc), copy.deepcopy(fixed)
    for d in (a, b):
        d.pop("metadata")
        for v in d["votes"].values():
            v.pop("result")
    check("nothing else changed", a, b)
    arts = pub.build_correct_results("2017_18", out)
    check("artifact paths", sorted(arts), ["sessions/2017-2018/votes.csv",
                                           "sessions/2017-2018/votes.json"])
    check("votes.json bytes", arts["sessions/2017-2018/votes.json"], pub.compact_json(fixed))
    check("csv carries Fail", b",Fail," in arts["sessions/2017-2018/votes.csv"], True)
    # Refuses a file that was not corrected, and a live session.
    for tag, path in (("2017_18", src), ("2025_26", out)):
        try:
            pub.build_correct_results(tag, path)
            failures.append("correct-results should refuse %s %s" % (tag, path))
        except SystemExit:
            pass

# --- status cross-check ------------------------------------------------------------
check("lost", chk.outcome_of("House Third Reading Lost"), "fail")
check("lost reconsidered", chk.outcome_of("House Lost Reconsidered Bill/Resolution"), "fail")
check("passed", chk.outcome_of("Senate Passed/Adopted By Substitute"), "pass")
check("agreed", chk.outcome_of("Senate Agreed House Amend or Sub"), "pass")
check("disagreed is not an outcome", chk.outcome_of("House Disagreed Senate Amend or Sub"), None)
check("CCR adopted", chk.outcome_of("House Conference Committee Report Adopted"), "pass")
check("CCR lost", chk.outcome_of("House Conference Committee Lost"), "fail")
check("committee report", chk.outcome_of("Senate Committee Favorably Reported"), None)
check("notice", chk.outcome_of("House Notice to Reconsider"), None)

quiet = lambda *a, **k: None  # noqa: E731
before = chk.check(VOTES, fake_record, margin=10, log=quiet)
check("old results disagree", sorted(r["voteId"] for r in before["disagree"]),
      ["14955-50033", "15309-49598", "15311-49598", "15652-52082"])
after = chk.check(votes, fake_record, margin=10, log=quiet)
check("corrected results agree", after["disagree"], [])
check("unlogged lost concurrence is unverified, not wrong",
      [r["voteId"] for r in after["unverified"]], ["15501-49827"])
check("exception reported", [r["voteId"] for r in after["officialExceptions"]], ["17771-57775"])
check("far-from-threshold votes skipped", after["checked"] < len(votes), True)
check("--all checks everything",
      chk.check(votes, fake_record, check_all=True, log=quiet)["checked"], len(votes))
failed = chk.check(votes, lambda lid: None, log=quiet)
check("failed lookups listed", bool(failed["fetchFailed"]), True)

bills_doc = {"bills": [dict(bill, identifier="SB 175", session="2025_26",
                            billUrl="https://www.legis.ga.gov/legislation/70344")]}
check("ga-bills votes load", [v["result"] for v in chk.load_votes(bills_doc).values()],
      ["Pass", "Fail"])

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
