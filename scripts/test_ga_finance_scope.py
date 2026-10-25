#!/usr/bin/env python3
"""Which terminated PeachFile committees stay in ga-campaign-finance.json (lib/ga_finance_scope.py).

The generator used to drop every closed committee, erasing a sitting legislator's
$257K the day their committee terminated. It now keeps a terminated committee only
when its person still holds or is running for that seat. What must hold:

  * a sitting member's closed committee for their own seat is kept, even though the
    roster says "Bill" and the filing says "William" (seat + last name, not name);
  * a closed committee for a seat the person no longer holds or contests is dropped
    (a statewide run that ended; a lost primary who is not sitting);
  * a person with a live committee in the seat does not get their closed one added
    (it would make a clean match ambiguous);
  * statewide filers need a full-name match on an active ballot.

Run: python scripts/test_ga_finance_scope.py        (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_finance_scope as S  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


H, SEN = "House of Representatives", "Senate"
members = [
    {"name": "Bill Werkheiser", "lastName": "Werkheiser", "chamber": H, "district": 157, "status": None},
    {"name": "Gone Member", "lastName": "Gone", "chamber": H, "district": 12, "status": "Resigned"},
    {"name": "Susp Ended", "lastName": "Ended", "chamber": SEN, "district": 3, "status": "Suspended"},
]
races = [
    {"id": "ga-house-157-2026", "level": "state", "activePhase": "general", "phases": {"general": {
        "ballots": {"Republican": [{"name": "Bradley B. Anderson"}],
                    "Democrat": [{"name": "Micah M. King"}, {"name": "Out Ofrace", "withdrawn": True}]}}}},
    {"id": "ga-senate-10-2026", "level": "state", "activePhase": "general", "phases": {"general": {
        "candidates": [{"name": "Furquan Stafford"}]}}},
    {"id": "ga-psc-5-2026", "level": "state", "activePhase": "general", "phases": {"primary": {
        "candidates": [{"name": "Craig Cupid"}]}, "general": {"candidates": [{"name": "Someone Else"}]}}},
    {"id": "ga-governor-2026", "level": "state", "activePhase": "general", "phases": {"general": {
        "ballots": {"Republican": [{"name": "Jane Doe Jr."}]}}}},
    {"id": "senate-2026", "level": "federal", "activePhase": "general", "phases": {"general": {
        "candidates": [{"name": "Federal Person"}]}}},
]
scope = S.build_scope(races, members)


def filer(first, last, district=None, office="State Representative"):
    return {"firstName": first, "lastName": last, "filerName": f"{last}, {first}",
            "district": district, "office": office}


check("sitting member is in scope under the filing's different first name",
      S.keep_terminated(filer("William", "Werkheiser", "157"), H, scope), True)
check("a candidate on the district's active ballot is in scope",
      S.keep_terminated(filer("Micah", "King", "157"), H, scope), True)
check("a withdrawn candidate is not on the ballot",
      S.keep_terminated(filer("Out", "Ofrace", "157"), H, scope), False)
check("same last name in a different district is not in scope",
      S.keep_terminated(filer("William", "Werkheiser", "158"), H, scope), False)
check("a resigned member does not count as sitting",
      S.keep_terminated(filer("Gone", "Gone", "12"), H, scope), False)
check("a suspended member still holds the seat",
      S.keep_terminated(filer("Susp", "Ended", "3"), SEN, scope), True)
check("senate candidate on a 'candidates' list is in scope",
      S.keep_terminated(filer("Furquan", "Stafford", "10", "State Senator"), SEN, scope), True)

check("statewide: a primary-only candidate is NOT on the active (general) ballot",
      S.keep_terminated(filer("Craig", "Cupid", None, "Public Service Commissioner"), None, scope), False)
check("statewide: full-name match on the active ballot, suffix ignored",
      S.keep_terminated(filer("Jane", "Doe", None, "Governor"), None, scope), True)
check("statewide: a sitting legislator's closed statewide run is not in scope",
      S.keep_terminated(filer("Bill", "Werkheiser", None, "Lieutenant Governor"), None, scope), False)
check("federal races do not feed the state scope", "federal person" in scope["statewide"], False)

# A live committee in the seat supersedes the closed one.
live = filer("William", "Werkheiser", "157")
active = {S.person_key(live)}
check("a person with an active committee in the seat is not duplicated",
      S.keep_terminated(filer("William", "Werkheiser", "157"), H, scope, active), False)
check("person_key ignores case and a Jr. suffix",
      S.person_key({"filerName": "JONES, ANISSA M.", "district": "143"})
      == S.person_key({"filerName": "Jones, Anissa M.", "district": "143"}), True)
check("an empty ballot yields no names", S.active_ballot_names({"phases": {}}), [])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
