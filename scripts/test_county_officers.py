#!/usr/bin/env python3
"""Invariants of the county-officers validator and the sheriff importer's name match.
No network. Run: python scripts/test_county_officers.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import validate_county_officers as V  # noqa: E402
import import_sheriffs as S  # noqa: E402

failures = []


def check(cond, msg):
    print("  %s  %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


PLACES = {"newton": {"type": "county"}, "covington": {"type": "city"}}


def officer(**kw):
    o = {"name": "A B", "role": "Sheriff", "seat": "Countywide", "party": "Republican",
         "last_elected": 2024, "next_election": 2028, "source": "https://x"}
    o.update(kw)
    return o


def run(counties):
    return V.validate({"counties": counties}, PLACES)


print("Validator")
e, w = run([{"id": "newton", "officers": [officer()]}])
check(not e and not w, "a complete sheriff validates")
e, _ = run([{"id": "nowhere", "officers": [officer()]}])
check(any("no matching place" in x for x in e), "an id with no place slug fails")
e, _ = run([{"id": "covington", "officers": [officer()]}])
check(any("not a county" in x for x in e), "a city is rejected")
e, _ = run([{"id": "newton", "officers": [officer(), officer()]}])
check(any("exactly one" in x for x in e), "two sheriffs in one county fails")
e, _ = run([{"id": "newton", "officers": [officer(party="Green")]}])
check(any("party must be" in x for x in e), "an unknown party fails")
e, w = run([{"id": "newton", "officers": [officer(party=None)]}])
check(not e and any("party is blank" in x for x in w), "a blank party warns, never fails")
e, _ = run([{"id": "newton", "officers": [officer(next_election=2024)]}])
check(any("must be after" in x for x in e), "next_election must follow last_elected")
e, _ = run([{"id": "newton", "officers": [officer(source="")]}])
check(any("source" in x for x in e), "an officer with no source fails")
e, _ = run([{"id": "newton", "officers": [officer(role="Coroner")]}])
check(any("role must be" in x for x in e), "an unknown role fails")
e, _ = run([{"id": "newton", "officers": [officer()]}, {"id": "newton", "officers": [officer()]}])
check(any("duplicate" in x for x in e), "a duplicate county fails")

print("Name match (association vs SoS)")
check(S.same_person("Darrell Dix", 'James "Darrell" Dix'), "a nickname in the SoS name matches")
check(S.same_person("Gene Scarbrough", "Gene Scarborough"), "a one-letter surname spelling matches")
check(S.same_person("William Massee, Jr.", 'W.C. "Bill" Massee, Jr.'), "suffix and initials are ignored")
check(not S.same_person("Mark Melton", "Ezell Brown"), "a different person does not match")
check(not S.same_person("Mark Brown", "Ezell Brown"), "same surname, different first name does not match")

if failures:
    print("\n%d check(s) FAILED" % len(failures))
    sys.exit(1)
print("\nAll county-officer invariants hold.")
