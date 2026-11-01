#!/usr/bin/env python3
"""validate_races.py: every check fires on the damage it exists for, and a clean
edit passes. Synthetic documents only, so a data commit can never break this suite.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_races as v


def cand(cid, name="X"):
    return {"id": cid, "name": name, "party": "Democrat"}


def race(rid, active="general", **extra):
    r = {
        "id": rid,
        "activePhase": active,
        "phases": {
            "primary": {"ballots": {"Democrat": [cand(f"{rid}-p1"), cand(f"{rid}-p2")]}},
            "general": {"ballots": {"Democrat": [cand(f"{rid}-g1")], "Republican": [cand(f"{rid}-g2")]}},
        },
    }
    r.update(extra)
    return r


def doc(*races):
    return {"_note": "n", "_incumbentIds": [], "updatedAt": "2026-11-01", "races": list(races)}


BASE = doc(*[race(f"r{i}") for i in range(40)])


def has(errs, text):
    assert any(text in e for e in errs), f"expected {text!r} in {errs}"


# ---- absolute -------------------------------------------------------------- #
def test_clean_document_passes():
    assert v.check_document(BASE) == []


def test_empty_or_malformed():
    has(v.check_document({"races": []}), "no 'races' list")
    has(v.check_document([]), "not a JSON object")


def test_duplicate_race_id():
    d = copy.deepcopy(BASE)
    d["races"].append(copy.deepcopy(d["races"][0]))
    has(v.check_document(d), "duplicate race id")


def test_active_phase_must_exist_and_be_populated():
    d = copy.deepcopy(BASE)
    d["races"][0]["activePhase"] = "runoff"
    has(v.check_document(d), "is not one of its phases")
    d = copy.deepcopy(BASE)
    d["races"][1]["phases"]["general"]["ballots"] = {}
    has(v.check_document(d), "has no candidates")


def test_duplicate_candidate_id_in_a_phase():
    d = copy.deepcopy(BASE)
    d["races"][0]["phases"]["general"]["ballots"]["Republican"].append(cand("r0-g1"))
    has(v.check_document(d), "duplicate candidate id")


def test_winner_rules():
    d = copy.deepcopy(BASE)
    d["races"][0].update(status="certified", winner={"candidateId": "r0-g1", "name": "X"})
    assert v.check_document(d) == []
    d["races"][0]["winner"] = {"candidateId": "nobody"}
    has(v.check_document(d), "not on any ballot")
    d["races"][0]["winner"] = {"name": "X"}
    has(v.check_document(d), "neither a candidateId nor a memberId")
    d["races"][0]["winner"] = {"memberId": "bioguide-1"}  # incumbent: memberId only
    assert v.check_document(d) == []
    d["races"][0].pop("winner")
    has(v.check_document(d), "no winner is recorded")
    d["races"][0].update(winner={"candidateId": "r0-g1"}, status=None)
    has(v.check_document(d), "not 'certified'")


# ---- change ---------------------------------------------------------------- #
def test_clean_edit_passes():
    after = copy.deepcopy(BASE)
    after["races"][3]["phases"]["general"]["ballots"]["Democrat"][0]["name"] = "Renamed"
    after["updatedAt"] = "2026-11-02"
    assert v.check_change(BASE, after) == []


def test_race_dropped_or_added():
    after = copy.deepcopy(BASE)
    after["races"].pop()
    has(v.check_change(BASE, after), "race set changed")
    after = copy.deepcopy(BASE)
    after["races"].append(race("brand-new"))
    has(v.check_change(BASE, after), "race set changed")


def test_phase_may_only_move_forward():
    before = copy.deepcopy(BASE)
    before["races"][0]["activePhase"] = "primary"
    after = copy.deepcopy(BASE)  # r0 now general: primary -> general is allowed
    assert v.check_change(before, after) == []
    has(v.check_change(BASE, before), "unexpected phase transition")  # general -> primary


def test_candidate_total_cliff():
    after = copy.deepcopy(BASE)
    for r in after["races"][:20]:
        r["phases"]["general"]["ballots"]["Republican"] = []
    has(v.check_change(BASE, after), "active-ballot candidates fell")


def test_a_few_candidates_leaving_is_fine():
    after = copy.deepcopy(BASE)
    after["races"][0]["phases"]["general"]["ballots"]["Republican"] = []
    assert v.check_change(BASE, after) == []


def test_recorded_winner_cannot_be_changed_or_removed():
    before = copy.deepcopy(BASE)
    before["races"][0].update(status="certified", winner={"candidateId": "r0-g1"})
    replaced = copy.deepcopy(before)
    replaced["races"][0]["winner"] = {"candidateId": "r0-g2"}
    has(v.check_change(before, replaced), "replaced")
    removed = copy.deepcopy(before)
    removed["races"][0].pop("winner")
    removed["races"][0].pop("status")
    has(v.check_change(before, removed), "removed")
    recorded = copy.deepcopy(BASE)
    recorded["races"][0].update(status="certified", winner={"candidateId": "r0-g1"})
    assert v.check_change(BASE, recorded) == []  # recording a first winner is the normal path


def test_marker_relaxes_change_checks_only():
    after = copy.deepcopy(BASE)
    after["races"].pop()
    assert v.check_change(BASE, after, allow_structure_change=True) == []
    after["races"][0]["activePhase"] = "nope"
    assert v.check_document(after), "absolute checks must still apply with the marker"


def test_missing_baseline_skips_change_checks():
    assert v.load_base(None)[0] is None
    assert v.load_base(v.ZERO_SHA)[0] is None
    assert v.load_base("deadbeef" * 5)[0] is None


if __name__ == "__main__":
    fns = [f for k, f in sorted(globals().items()) if k.startswith("test_") and callable(f)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
