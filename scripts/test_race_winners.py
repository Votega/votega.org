#!/usr/bin/env python3
"""Offline checks for scripts/lib/race_winners.py and the races_guard winner check.

Fixtures only: no races.json, no results files, no network. Exits 0 on success, 1 on failure.

Usage:
  python scripts/test_race_winners.py
"""

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import race_winners as W  # noqa: E402
from lib.races_guard import RacesGuardError, assert_only_winners_changed  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def raises(label, fn):
    try:
        fn()
    except RacesGuardError:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: did not raise")
        failures.append(label)


# --- names ------------------------------------------------------------------
def fits(a, b):
    return bool(W.name_variants(a) & W.name_variants(b))


check("nickname in quotes matches the plain nickname", fits('Michael "Mike" Collins', "Mike Collins"), True)
check("nickname in quotes matches the formal name", fits('Michael "Mike" Collins', "Michael Collins"), True)
check("a title and a '(Dem)' tag are ignored", fits("Dr. Everton Blair", 'Everton "EJ" Blair (Dem)'), True)
check("a middle initial is ignored", fits("Keisha Lance Bottoms", "Keisha R. Lance Bottoms"), True)
check("a numeral suffix is ignored", fits("Herbert Lehman Franklin Iii", "Herbert Lehman Franklin III"), True)
check("a different first name does not match", fits("Jon Ossoff", "Mike Collins"), False)
check("same last name, different first name does not match", fits("Amy Smith", "Bob Smith"), False)

BALLOT = [
    {"id": "c1", "name": 'Michael "Mike" Collins', "party": "Republican"},
    {"id": "c2", "name": "Jon Ossoff", "party": "Democrat"},
]
c, why = W.match_candidate("Jon Ossoff", BALLOT)
check("match returns the one candidate", c and c["id"], "c2")
check("no fit is reported", W.match_candidate("Nobody Here", BALLOT), (None, "no candidate on the ballot fits this name"))
twin = BALLOT + [{"id": "c3", "name": "Mike Collins Jr."}]
check("two fits is ambiguous, not a guess", W.match_candidate("Mike Collins", twin)[1], "2 candidates fit this name")


# --- one contest --------------------------------------------------------------
def cand(name, votes):
    return {"name": name, "votes": votes}


d = W.decide([cand("Jon Ossoff", 600), cand("Mike Collins", 400)], 1000, BALLOT)
check("a majority wins", (d["kind"], d["candidate"]["id"], d["share"]), ("winner", "c2", 0.6))
d = W.decide([cand("Jon Ossoff", 480), cand("Mike Collins", 470), cand("Third", 50)], 1000, BALLOT)
check("a plurality is a runoff, never a winner", (d["kind"], d["leader"]), ("runoff", "Jon Ossoff"))
d = W.decide([cand("Jon Ossoff", 502), cand("Mike Collins", 498)], 1000, BALLOT)
check("within half a point of 50% is flagged", d["kind"], "flag")
d = W.decide([cand("Jon Ossoff", 500), cand("Mike Collins", 500)], 1000, BALLOT)
check("a tie is flagged", d["kind"], "flag")
d = W.decide([cand("Jon Ossoff", 0), cand("Mike Collins", 0)], 0, BALLOT)
check("no votes counted yet decides nothing", d["kind"], "no-votes")
d = W.decide([cand("Jon Ossoff", 900)], 900, BALLOT)
check("an unopposed candidate with votes wins", d["kind"], "winner")
d = W.decide([cand("Unknown Person", 700), cand("Jon Ossoff", 300)], 1000, BALLOT)
check("a winner who matches nobody is flagged", d["kind"], "flag")
withdrawn = [{"id": "w", "name": "Wendy Out", "withdrawn": True}, {"id": "o", "name": "Ola Other"}]
check("a withdrawn winner is flagged", W.decide([cand("Wendy Out", 700), cand("Ola Other", 300)], 1000, withdrawn)["kind"], "flag")
d = W.decide([cand("Jon Ossoff", 600), cand("Mike Collins", 400)], 900, BALLOT)
check("a total row that undercounts the candidates is not trusted", d["total"], 1000)

# a staged general file splits an office into a contest per party; the sum is still the denominator
office = {"contests": [{"party": "rep", "totalVotes": 400, "candidates": [cand("Mike Collins", 400)]},
                       {"party": "dem", "totalVotes": 600, "candidates": [cand("Jon Ossoff", 600)]}]}
cands, total = W.flatten_office(office)
check("per-party contests are summed", (len(cands), total), (2, 1000))

# --- race resolution ------------------------------------------------------------
RACES = [
    {"id": "senate-2026", "chamber": "U.S. Senate", "phases": {"primary": {"electionDate": "2026-05-19"}, "general": {"electionDate": "2026-11-03", "candidates": BALLOT}}},
    {"id": "ga-13-2026", "chamber": "U.S. House", "district": 13, "phases": {"general": {"electionDate": "2026-11-03", "candidates": [{"id": "g1", "name": "Gina One"}, {"id": "g2", "name": "Gus Two"}]}}},
    {"id": "ga-13-special-2026", "chamber": "U.S. House", "district": 13, "phases": {"special": {"electionDate": "2026-07-28"}, "runoff": {"electionDate": "2026-08-25", "candidates": [{"id": "s1", "name": "Dr. Everton Blair"}, {"id": "s2", "name": "Marcye Scott"}]}}},
    {"id": "ga-psc-3-2026", "chamber": "Public Service Commissioner", "district": 3, "phases": {"general": {"electionDate": "2026-11-03", "candidates": [{"id": "p1", "name": "Pat One"}, {"id": "p2", "name": "Pam Two"}]}}},
    {"id": "ga-house-7-2026", "chamber": "Georgia House of Representatives", "district": 7, "phases": {"general": {"electionDate": "2026-11-03", "candidates": [{"id": "h1", "name": "Hal One"}, {"id": "h2", "name": "Hope Two"}]}}},
    {"id": "ga-house-8-2026", "chamber": "Georgia House of Representatives", "district": 8, "phases": {"general": {"electionDate": "2026-11-03", "candidates": [{"id": "u1", "name": "Una Only"}]}}},
]
nov = W.races_on_date(RACES, "2026-11-03")
check("races are found by election date", sorted(r["id"] for r, _ in nov), ["ga-13-2026", "ga-house-7-2026", "ga-house-8-2026", "ga-psc-3-2026", "senate-2026"])
check("US Senate alias", W.resolve_race("statewide", "US Senate", nov)[0][0]["id"], "senate-2026")
check("PSC carries its district", W.resolve_race("statewide", "PSC - District 3", nov)[0][0]["id"], "ga-psc-3-2026")
check("a state house district", W.resolve_race("state-house", "District 7", nov)[0][0]["id"], "ga-house-7-2026")
check("district 13 on the general date is the full-term race, not the special",
      W.resolve_race("us-house", "District 13", nov)[0][0]["id"], "ga-13-2026")
check("the special's date finds the special", W.resolve_race("us-house", "District 13", W.races_on_date(RACES, "2026-08-25"))[0][0]["id"], "ga-13-special-2026")
check("courts are not handled", W.resolve_race("courts", "Judge - X", nov)[0], None)
check("an unknown statewide office is reported", W.resolve_race("statewide", "Dog Catcher", nov)[0], None)
check("a district with no race that day is reported", W.resolve_race("state-house", "District 99", nov)[1], "no race held on that date")


# --- the whole proposal ---------------------------------------------------------
def rset(key, date, status, sections):
    return {"data_key": key, "election_date": date, "status": status, "sections": sections}


def sec(sid, *rows):
    return {"id": sid, "races": [{"office": o, "contests": [{"party": "np", "totalVotes": t, "candidates": cs}]} for o, t, cs in rows]}


general = rset("gen", "2026-11-03", "certified", [
    sec("statewide", ("US Senate", 1000, [cand("Jon Ossoff", 560), cand("Mike Collins", 440)]),
                     ("PSC - District 3", 1000, [cand("Pat One", 480), cand("Pam Two", 470), cand("Other", 50)])),
    sec("state-house", ("District 7", 1000, [cand("Hope Two", 700), cand("Hal One", 300)])),
])
out = W.propose([general], RACES)
check("winners are proposed with the recorded shape", out["proposals"]["senate-2026"]["winner"],
      {"name": "Jon Ossoff", "candidateId": "c2", "party": "Democrat", "phase": "general"})
check("a house winner", out["proposals"]["ga-house-7-2026"]["winner"]["candidateId"], "h2")
check("no majority goes to the runoff list", list(out["runoffs"]), ["ga-psc-3-2026"])
check("an unopposed race with no results row is flagged, not recorded",
      [f["raceId"] for f in out["flagged"] if "unopposed" in f["reason"]], ["ga-house-8-2026"])
check("an unopposed race is not proposed", "ga-house-8-2026" in out["proposals"], False)

unofficial = rset("gen", "2026-11-03", "unofficial", general["sections"])
out = W.propose([unofficial], RACES)
check("an unofficial election decides nothing", (out["proposals"], out["flagged"]), ({}, []))
check("...and is listed as skipped", out["skipped"][0]["status"], "unofficial")

# the December runoff supersedes the November "runoff" for the same race
runoff_races = copy.deepcopy(RACES)
runoff_races[3]["phases"]["runoff"] = {"electionDate": "2026-12-01", "candidates": [{"id": "p1", "name": "Pat One"}, {"id": "p2", "name": "Pam Two"}]}
dec = rset("dec", "2026-12-01", "certified", [sec("statewide", ("PSC - District 3", 900, [cand("Pam Two", 500), cand("Pat One", 400)]))])
out = W.propose([dec, general], runoff_races)  # given out of order on purpose
check("a later certified runoff decides what the general left open", out["proposals"]["ga-psc-3-2026"]["winner"], {"name": "Pam Two", "candidateId": "p2", "party": None, "phase": "runoff"})
check("...and clears it from the runoff list", out["runoffs"], {})
dec_unofficial = rset("dec", "2026-12-01", "unofficial", dec["sections"])
check("an uncertified runoff leaves the race in the runoff list",
      list(W.propose([general, dec_unofficial], runoff_races)["runoffs"]), ["ga-psc-3-2026"])

# --- plan / apply / guard ----------------------------------------------------------
doc = {"updatedAt": "t0", "races": copy.deepcopy(RACES)}
props = W.propose([general], doc["races"])["proposals"]
changes, conflicts = W.plan_changes(props, doc["races"])
check("changes are planned", sorted(p["raceId"] for p in changes), ["ga-house-7-2026", "senate-2026"])
check("no conflicts", conflicts, [])

before = copy.deepcopy(doc)
ids = W.apply_changes(doc, changes)
doc["updatedAt"] = "t1"
assert_only_winners_changed(before, doc, ids)
print("  ok   the guard accepts exactly the planned winners")
senate = next(r for r in doc["races"] if r["id"] == "senate-2026")
check("a race is stamped certified with its winner", (senate["status"], senate["winner"]["candidateId"]), ("certified", "c2"))
again, _ = W.plan_changes(props, doc["races"])
check("re-running is a no-op", again, [])

other = copy.deepcopy(props)
other["senate-2026"]["winner"] = {"name": "Mike Collins", "candidateId": "c1", "party": "Republican", "phase": "general"}
check("a different recorded winner is a conflict, never overwritten",
      W.plan_changes(other, doc["races"])[1], [{"raceId": "senate-2026", "recorded": "Jon Ossoff", "proposed": "Mike Collins"}])

sneaky = copy.deepcopy(doc)
sneaky["races"][0]["phases"]["general"]["candidates"].pop()
raises("the guard rejects a changed ballot", lambda: assert_only_winners_changed(before, sneaky, ids))
extra = copy.deepcopy(doc)
extra["races"][1]["status"] = "certified"
raises("the guard rejects a race outside the plan", lambda: assert_only_winners_changed(before, extra, ids))
raises("the guard rejects a planned race that did not change", lambda: assert_only_winners_changed(before, before, ids))
dropped = copy.deepcopy(doc)
dropped["races"].pop()
raises("the guard rejects a dropped race", lambda: assert_only_winners_changed(before, dropped, ids))

# --- an incumbent listed only by member id ------------------------------------------------
INC_RACE = {"id": "ga-14-2026", "chamber": "U.S. House", "district": 14, "phases": {"general": {
    "electionDate": "2026-11-03",
    "candidates": [{"type": "incumbent", "memberId": "F000485"}, {"id": "ch1", "name": "Shawn Harris", "party": "Democrat"}]}}}
MEMBERS = {"F000485": {"name": "Clay Fuller", "party": "Republican"}}
ballot = W.phase_candidates(INC_RACE["phases"]["general"], MEMBERS)
check("an unnamed incumbent is given their roster name and party", (ballot[0]["name"], ballot[0]["party"]), ("Clay Fuller", "Republican"))
check("...and without a roster they are left out (nothing to match)", len(W.phase_candidates(INC_RACE["phases"]["general"], {})), 1)
inc = rset("gen", "2026-11-03", "certified", [sec("us-house", ("District 14", 1000, [cand("Clay Fuller", 640), cand("Shawn Harris", 360)]))])
out = W.propose([inc], [INC_RACE], MEMBERS)
check("an incumbent win is recorded against their member id", out["proposals"]["ga-14-2026"]["winner"],
      {"name": "Clay Fuller", "memberId": "F000485", "party": "Republican", "phase": "general"})
inc2 = rset("gen", "2026-11-03", "certified", [sec("us-house", ("District 14", 1000, [cand("Shawn Harris", 640), cand("Clay Fuller", 360)]))])
check("a challenger win is recorded against their candidate id",
      W.propose([inc2], [INC_RACE], MEMBERS)["proposals"]["ga-14-2026"]["winner"]["candidateId"], "ch1")
check("without the roster the incumbent win cannot be matched, so it is flagged",
      W.propose([inc], [INC_RACE], {})["flagged"][0]["reason"].startswith("winner 'Clay Fuller'"), True)
planned = W.plan_changes(W.propose([inc], [INC_RACE], MEMBERS)["proposals"], [INC_RACE])
check("a member-id winner is planned", [p["raceId"] for p in planned[0]], ["ga-14-2026"])
recorded = copy.deepcopy(INC_RACE)
recorded.update({"status": "certified", "winner": {"name": "Clay Fuller", "memberId": "F000485", "phase": "general"}})
check("re-running against a recorded member-id winner is a no-op", W.plan_changes(W.propose([inc], [recorded], MEMBERS)["proposals"], [recorded]), ([], []))
check("judicial races are counted, not matched", W.propose([general], RACES + [{"id": "court-1", "chamber": "Superior Court", "phases": {"general": {"electionDate": "2026-11-03", "candidates": [{"id": "j1", "name": "Jo Judge"}]}}}])["unhandled"], ["court-1"])

# --- front matter --------------------------------------------------------------------
fm = W.parse_front_matter("---\nlayout: election_results\nstatus: certified\nelection_date: 2026-11-03\nnotice_upcoming: >-\n  long text\n---\n<p>x</p>")
check("front matter scalars", (fm["layout"], fm["status"], fm["election_date"]), ("election_results", "certified", "2026-11-03"))
check("a folded block is skipped, not mangled", "notice_upcoming" in fm, False)

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nall race-winner checks passed")
