#!/usr/bin/env python3
"""The static legislator-record prose (lib/ga_legislator_record.py).

Pins: each sentence appears only when its data does (a missing figure is left
out, never printed as zero), singular/plural wording, rounding, and that the
presiding officer (who casts no ordinary votes) gets no voting sentence.

Run: python scripts/test_ga_legislator_record.py        (no network, no writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_legislator_record import legislator_record

failures = []


def check(name, cond):
    if not cond:
        failures.append(name)
        print("FAIL", name)


M = {"name": "Jane Roe", "party": "Republican", "leadershipRole": None,
     "committeeRoles": [{"name": "Rules", "role": "Member"}]}
U = {"totalRollCalls": 790, "cast": 782, "participationRate": 0.9899,
     "partyUnity": 0.9802, "partyLineVotes": 101, "votedWithParty": 99}

text = " ".join(legislator_record(M, U, [31, 79]))
check("participation rounded", "782 of 790" in text and "(99% participation)" in text)
check("unity rounded", "the Republican caucus 98% of the time (99 of 101)" in text)
check("sponsorship both", "primary sponsor of 31 bills and resolutions and a cosponsor of 79 other measures" in text)
check("plain member has no leadership sentence", "serves as" not in text and "holds the position" not in text)

check("no data -> no paragraphs", legislator_record({"name": "X"}, None, None) == [])
check("zero sponsorship omitted", "sponsor" not in " ".join(legislator_record(M, None, [0, 0])))
check("singular", "1 bill or resolution" in " ".join(legislator_record(M, None, [1, 0])))
check("cosponsor only", "is a cosponsor of 3 bills and resolutions" in " ".join(legislator_record(M, None, [0, 3])))
check("presiding officer: no voting sentence",
      "participation" not in " ".join(legislator_record(M, dict(U, presidingOfficer=True), None)))
check("unity null: participation only",
      "party-line" not in " ".join(legislator_record(M, dict(U, partyUnity=None), None))
      and "participation" in " ".join(legislator_record(M, dict(U, partyUnity=None), None)))

lead = " ".join(legislator_record(
    dict(M, leadershipRole="Governor's Floor Leader",
         committeeRoles=[{"name": "Rules", "role": "Chairman"}, {"name": "Ethics", "role": "Secretary"}]),
    None, None))
check("leadership + committee roles",
      "holds the position of Governor's Floor Leader, and serves as Chairman of Rules; Secretary of Ethics." in lead)

if failures:
    sys.exit(1)
print("ok")
