#!/usr/bin/env python3
"""Show that each races_guard check aborts on the failure it exists for, and passes
on the edit its writer is allowed to make.

The winner and editorial-field checks are covered by test_race_winners.py and
test_races_rebuild_preserves_curation.py. This file covers the other six. Fixtures
only: no races.json, no network. Exits 0 on success, 1 on failure.

Usage:
  python scripts/test_races_guard.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import races_guard as G  # noqa: E402

failures = []


def passes(label, fn):
    try:
        fn()
    except G.RacesGuardError as e:
        print(f"  FAIL {label}: raised {e}")
        failures.append(label)
    else:
        print(f"  ok   {label}")


def raises(label, fn):
    try:
        fn()
    except G.RacesGuardError:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: did not raise")
        failures.append(label)


def cand(cid, name, typ="candidate"):
    return {"id": cid, "name": name, "type": typ}


def doc():
    return {
        "_note": "n",
        "_incumbentIds": ["i1"],
        "updatedAt": "2026-11-01T00:00:00Z",
        "races": [
            {"id": "r1", "activePhase": "primary", "phases": {
                "primary": {"ballots": {"D": [cand("c1", "A")], "R": [cand("c2", "B")]}},
                "general": {"candidates": [cand("c3", "C")]},
            }},
            {"id": "r2", "activePhase": "general", "phases": {
                "general": {"candidates": [cand("c4", "D"), cand("c5", "E")]},
            }},
            {"id": "r3", "activePhase": "primary", "phases": {
                "primary": {"ballots": {"R": [cand("c6", "F")]}},
                "general": {"candidates": []},
            }},
        ],
    }


def race(d, rid):
    return next(r for r in d["races"] if r["id"] == rid)


def edited(fn):
    d = doc()
    fn(d)
    return d


def race_set_cases():
    print("assert_race_set_preserved")
    passes("an unchanged document passes", lambda: G.assert_race_set_preserved(doc(), doc()))
    passes("editing a race in place passes", lambda: G.assert_race_set_preserved(
        doc(), edited(lambda d: race(d, "r1").update(activePhase="general"))))
    raises("a dropped race aborts", lambda: G.assert_race_set_preserved(
        doc(), edited(lambda d: d["races"].pop())))
    raises("an added race aborts", lambda: G.assert_race_set_preserved(
        doc(), edited(lambda d: d["races"].append({"id": "r9"}))))
    raises("a duplicated race id aborts", lambda: G.assert_race_set_preserved(
        doc(), edited(lambda d: d["races"].append(copy.deepcopy(d["races"][0])))))
    for key in G.TOP_LEVEL_KEYS:
        raises(f"dropping top-level {key!r} aborts", lambda key=key: G.assert_race_set_preserved(
            doc(), edited(lambda d: d.pop(key))))
    raises("emptying the race list aborts", lambda: G.assert_race_set_preserved(
        doc(), edited(lambda d: d.update(races=[]))))


def phase_transition_cases():
    print("assert_phase_transitions")
    allowed = {("primary", "general")}
    promote = edited(lambda d: race(d, "r1").update(activePhase="general"))
    passes("an allowed flip to a populated phase passes",
           lambda: G.assert_phase_transitions(doc(), promote, allowed=allowed, expected_count=1))
    passes("no change passes", lambda: G.assert_phase_transitions(doc(), doc(), allowed=allowed))
    raises("a flip outside the allowed set aborts", lambda: G.assert_phase_transitions(
        doc(), edited(lambda d: race(d, "r2").update(activePhase="primary")), allowed=allowed))
    raises("a flip onto an empty phase aborts", lambda: G.assert_phase_transitions(
        doc(), edited(lambda d: race(d, "r3").update(activePhase="general")), allowed=allowed))
    passes("an empty phase is allowed when require_populated=False",
           lambda: G.assert_phase_transitions(
               doc(), edited(lambda d: race(d, "r3").update(activePhase="general")),
               allowed=allowed, require_populated=False))
    raises("a count that differs from the script's report aborts",
           lambda: G.assert_phase_transitions(doc(), promote, allowed=allowed, expected_count=2))
    raises("a dropped race aborts here too", lambda: G.assert_phase_transitions(
        doc(), edited(lambda d: d["races"].pop()), allowed=allowed))


def active_phase_cases():
    print("assert_active_phases_unchanged")
    passes("editing candidate content passes", lambda: G.assert_active_phases_unchanged(
        doc(), edited(lambda d: race(d, "r2")["phases"]["general"]["candidates"][0]
                      .update(name="Renamed"))))
    raises("a moved activePhase aborts", lambda: G.assert_active_phases_unchanged(
        doc(), edited(lambda d: race(d, "r1").update(activePhase="general"))))
    raises("a dropped activePhase aborts", lambda: G.assert_active_phases_unchanged(
        doc(), edited(lambda d: race(d, "r1").pop("activePhase"))))


def membership_cases():
    print("assert_membership_preserved")

    def general(d):
        return race(d, "r2")["phases"]["general"]["candidates"]

    passes("a field-level reconcile passes", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d)[0].update(name="D. Smith", website="https://x"))))
    passes("reordering candidates passes", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d).reverse())))
    raises("an added candidate aborts", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d).append(cand("c9", "Z")))))
    raises("a dropped candidate aborts", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d).pop())))
    raises("a re-slotted candidate id aborts", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d)[0].update(id="c9"))))
    raises("a changed candidate type aborts", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: general(d)[0].update(type="writeIn"))))
    raises("a dropped phase aborts", lambda: G.assert_membership_preserved(
        doc(), edited(lambda d: race(d, "r1")["phases"].pop("general"))))
    raises("emptying a phase's candidates aborts",
           lambda: G.assert_membership_preserved(doc(), edited(lambda d: (
               race(d, "r1")["phases"]["general"]["candidates"].clear()))))


def only_race_cases():
    print("assert_only_race_changed")
    passes("editing only the target race passes", lambda: G.assert_only_race_changed(
        doc(), edited(lambda d: race(d, "r3")["phases"]["general"]["candidates"]
                      .append(cand("c7", "G"))), "r3", require_populated_phase="general"))
    raises("touching another race aborts", lambda: G.assert_only_race_changed(
        doc(), edited(lambda d: (race(d, "r3").update(note="x"),
                                 race(d, "r2").update(note="x"))), "r3"))
    raises("a target race that is missing aborts", lambda: G.assert_only_race_changed(
        doc(), doc(), "r404"))
    raises("leaving the required phase empty aborts", lambda: G.assert_only_race_changed(
        doc(), edited(lambda d: race(d, "r3").update(note="x")), "r3",
        require_populated_phase="general"))


def equal_except_cases():
    print("assert_equal_except")
    passes("a timestamp-only change passes", lambda: G.assert_equal_except(
        doc(), edited(lambda d: d.update(updatedAt="2026-11-26T00:00:00Z")), "updatedAt"))
    raises("any race change aborts", lambda: G.assert_equal_except(
        doc(), edited(lambda d: race(d, "r1").update(activePhase="general")), "updatedAt"))
    raises("another top-level change aborts", lambda: G.assert_equal_except(
        doc(), edited(lambda d: d.update(_note="changed")), "updatedAt"))
    raises("a new top-level key aborts", lambda: G.assert_equal_except(
        doc(), edited(lambda d: d.update(extra=1)), "updatedAt"))


def main():
    race_set_cases()
    phase_transition_cases()
    active_phase_cases()
    membership_cases()
    only_race_cases()
    equal_except_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
