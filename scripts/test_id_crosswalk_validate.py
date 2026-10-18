#!/usr/bin/env python3
"""Assert validate_id_crosswalk.py gates on the crosswalk contradicting its INPUTS
and only reports coverage movement.

The old guard was `people >= 600`, `keyed >= 550` and a 20% shrink on four
coverage counters. 480 of the 747 records are ballot candidates, so those were
facts about the 2026 cycle; each case below pins which side of the line a
condition falls on. Stdlib only.

Usage:
  python scripts/test_id_crosswalk_validate.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_id_crosswalk as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def person(vg, ocd=None, bio=None, cands=()):
    return {"vgId": vg, "ids": {"ocdPersonId": ocd, "bioguideId": bio,
                                "votegaCandidateIds": list(cands)}}


MEMBERS = [{"id": "ocd-1"}, {"id": "ocd-2"}]
FEDERAL = [{"bioguideId": "B1", "state": "Georgia"}, {"bioguideId": "TX1", "state": "Texas"}]
PEOPLE = [person("vg1", ocd="ocd-1", cands=["c1"]), person("vg2", ocd="ocd-2"),
          person("vg3", bio="B1"), person("vg4", cands=["c2", "c3"])]
CANDS = {"c1", "c2", "c3"}


def tier1_cases():
    print("tier 1 (the crosswalk vs its own inputs)")
    check("complete build passes", V.unaccounted_inputs(PEOPLE, MEMBERS, FEDERAL, CANDS), [])
    check("a THIN cycle is not an error (old floor was people>=600)",
          V.unaccounted_inputs([person("vg1", ocd="ocd-1"), person("vg2", ocd="ocd-2"),
                                person("vg3", bio="B1")], MEMBERS, FEDERAL, set()), [])
    check("non-Georgia federal member is not required",
          V.unaccounted_inputs(PEOPLE, MEMBERS, FEDERAL, CANDS), [])
    check("roster member dropped", len(V.unaccounted_inputs(PEOPLE[:1] + PEOPLE[2:], MEMBERS,
                                                            FEDERAL, CANDS)), 1)
    check("federal member dropped", len(V.unaccounted_inputs(
        [p for p in PEOPLE if p["vgId"] != "vg3"], MEMBERS, FEDERAL, CANDS)), 1)
    check("candidate id unclaimed", len(V.unaccounted_inputs(PEOPLE, MEMBERS, FEDERAL,
                                                             CANDS | {"c9"})), 1)
    check("everything dropped reports all three kinds",
          len(V.unaccounted_inputs([], MEMBERS, FEDERAL, CANDS)), 3)


def cov(**kw):
    base = {"people": 100, "officeholders": 40, "candidateOnly": 60, "withVgId": 90,
            "withAnyFiling": 80, "candidacies": 95}
    base.update(kw)
    return {"coverage": base}


def tier2_cases():
    print("tier 2 (reports, never gates)")
    check("no baseline -> nothing", V.tier2(cov(), None), [])
    check("unchanged -> nothing", V.tier2(cov(), cov()), [])
    check("small move -> nothing", V.tier2(cov(people=90), cov()), [])
    heads = [h for h, _ in V.tier2(cov(people=30, candidateOnly=0), cov())]
    check("two-thirds shrink (a cycle rolling over) is reported, not gated", len(heads), 1)
    sec = V.tier2(cov(), cov(), ambiguous=["Jane Doe"])
    check("ambiguous queue surfaced", [h for h, _ in sec], ["Ambiguous filing matches awaiting review"])
    check("render with no sections says no material change",
          "No material change" in V.render([]), True)


def main():
    tier1_cases()
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
