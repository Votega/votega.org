#!/usr/bin/env python3
"""Offline checks for scripts/lib/candidate_standing.py: who is live, off the ballot, lost, or won.

Stdlib only; no races.json read. Exits 0 on success, 1 on any failure.

Usage:
  python scripts/test_candidate_standing.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import candidate_standing as C  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def c(i):
    return {"id": i, "name": f"Person {i}"}


A, B, X = c("a"), c("b"), c("x")
ALL = {"a", "b", "x"}
OPEN = {"status": None}
CERT_A = {"status": "certified", "winner": {"candidateId": "a", "name": "Person a"}}

# --- before a result is certified -------------------------------------------
check("on the active ballot is live", C.standing(OPEN, [A, B], "a", ALL), C.LIVE)
check("off the active ballot is off-ballot", C.standing(OPEN, [A, B], "x", ALL), C.OFF_BALLOT)
check("no active ballot yet retires nobody", C.standing(OPEN, [], "x", ALL), C.LIVE)

# --- certified ---------------------------------------------------------------
check("the certified winner won", C.standing(CERT_A, [A, B], "a", ALL), C.WON)
check("a certified loser on the ballot lost", C.standing(CERT_A, [A, B], "b", ALL), C.LOST)
check("a certified loser off the ballot lost", C.standing(CERT_A, [A, B], "x", ALL), C.LOST)

unofficial = {"status": "unofficial", "winner": {"candidateId": "a"}}
check("an unofficial result changes nothing (winner)", C.standing(unofficial, [A, B], "a", ALL), C.LIVE)
check("an unofficial result changes nothing (loser)", C.standing(unofficial, [A, B], "b", ALL), C.LIVE)

certified_no_winner = {"status": "certified"}
check("certified with no winner recorded changes nothing", C.standing(certified_no_winner, [A, B], "b", ALL), C.LIVE)

typo = {"status": "certified", "winner": {"candidateId": "zzz"}}
check("a winner id that is not in the race is ignored, not obeyed", C.standing(typo, [A, B], "a", ALL), C.LIVE)
check("...so nobody is marked lost either", C.standing(typo, [A, B], "b", ALL), C.LIVE)
check("a winner id with no candidateId is ignored", C.certified_winner_id({"status": "certified", "winner": {"name": "A"}}, ALL), None)
check("no race, no winner", C.certified_winner_id(None, ALL), None)

# candidates without an id fall back to their name as the key
N = {"name": "Solo"}
check("name-keyed candidate on the ballot is live", C.standing(OPEN, [N], "Solo", set()), C.LIVE)

# --- a person in several races ------------------------------------------------
check("still running anywhere stays live", C.overall([C.WON, C.LIVE, C.LOST]), C.LIVE)
check("a win with nothing live is won", C.overall([C.WON, C.OFF_BALLOT]), C.WON)
check("lost outranks off-ballot", C.overall([C.OFF_BALLOT, C.LOST]), C.LOST)
check("off-ballot alone", C.overall([C.OFF_BALLOT]), C.OFF_BALLOT)
check("no races is live", C.overall([]), C.LIVE)

# --- officeholder redirect ----------------------------------------------------
PEOPLE = [
    {"ids": {"votegaCandidateIds": ["cand-fed"], "bioguideId": "B1"}},
    {"ids": {"votegaCandidateIds": ["cand-ga"], "rosterId": "ocd-person/r1"}},
    {"ids": {"votegaCandidateIds": ["cand-unseated"], "bioguideId": "B2"}},
    {"ids": {"votegaCandidateIds": ["cand-none"]}},
]
URLS = {"us-congress": {"B1": "/us-congress/fed/"}, "ga-legislator": {"ocd-person/r1": "/ga-legislators/ga/"}}
check("federal winner goes to the member page", C.officeholder_target("cand-fed", PEOPLE, URLS), "/us-congress/fed/")
check("state winner goes to the legislator page", C.officeholder_target("cand-ga", PEOPLE, URLS), "/ga-legislators/ga/")
check("no page yet means no redirect (not sworn in)", C.officeholder_target("cand-unseated", PEOPLE, URLS), None)
check("a candidate with no officeholder identity", C.officeholder_target("cand-none", PEOPLE, URLS), None)
check("an unknown candidate", C.officeholder_target("nobody", PEOPLE, URLS), None)
check("empty maps never raise", C.officeholder_target("cand-fed", PEOPLE, {}), None)

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nall candidate-standing checks passed")
