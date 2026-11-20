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
    check("ambiguous queue surfaced", [h for h, _ in sec], ["Ambiguous matches awaiting review"])
    ppl = [{"vgId": "v", "name": {"full": "J"}, "ids": {"rosterId": "r"},
            "provenance": {"ballotpediaId": {"confidence": "ambiguous", "candidates": ["A", "B"]}}}]
    check("ambiguity with people is labelled by kind, never as a filing",
          [h for h, _ in V.tier2(cov(), cov(), people=ppl)], ["Ambiguous Ballotpedia page matches awaiting review (1)"])
    check("render with no sections says no material change",
          "No material change" in V.render([]), True)


def ledger_merge_cases():
    """Ledger.merge: two already-assigned vgIds for one person, joined by a forward."""
    print("ledger merge (retire an assigned vgId, forward it to the survivor)")
    import json
    import tempfile
    import build_id_crosswalk as B
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.json")
        led = B.Ledger(path)
        legislator = led.id_for("ocd-person/rep")       # vg-ga-p-000001
        candidate = led.id_for("peachfile:2")           # vg-ga-p-000002, minted separately
        check("alias alone cannot join two assigned ids (the old trap)",
              led.alias("peachfile:2", legislator), candidate)
        check("merge retires the candidate id onto the legislator's",
              led.merge("peachfile:2", legislator), legislator)
        check("the assignment itself is never rewritten",
              led.assign["peachfile:2"], candidate)
        check("every lookup follows the forward",
              (led.id_for("peachfile:2"), led.id_for_any(["peachfile:2"]),
               led.alias("peachfile:2", "x")), (legislator,) * 3)
        check("merging again is a no-op", (led.merge("peachfile:2", legislator), led.merged),
              (legislator, {candidate: legislator}))
        check("a merge never mints", led.next_seq, 3)
        led.save()
        saved = json.load(open(path, encoding="utf-8"))
        check("merged is persisted", saved.get("merged"), {candidate: legislator})
        check("and reloads", B.Ledger(path).canonical(candidate), legislator)
        third = led.id_for("fec:3")
        led.merge("ocd-person/rep", third)
        check("retiring a survivor re-points earlier forwards (one hop, no chains)",
              led.merged, {candidate: third, legislator: third})
    with tempfile.TemporaryDirectory() as d:
        led = B.Ledger(os.path.join(d, "ledger.json"))
        led.merged = {"a": "b", "b": "a"}
        try:
            led.canonical("a")
            got = "no error"
        except SystemExit:
            got = "stopped"
        check("a forward cycle stops the build", got, "stopped")


def merge_validation_cases():
    print("merge forwards (tier 1)")
    assign = {"ocd-person/rep": "vg1", "peachfile:2": "vg2", "peachfile:9": "vg9"}
    ok_ov = {"peachfile:2": {"sameAs": "ocd-person/rep", "_note": "same human: ..."}}
    good = {"vg2": "vg1"}
    check("an explicit, noted, one-hop forward passes",
          V.merge_errors(assign, good, ok_ov, published=good), [])
    check("no forwards, nothing to check", V.merge_errors(assign, {}, {}), [])
    check("a forward with no sameAs behind it fails",
          len(V.merge_errors(assign, good, {})), 1)
    check("a sameAs with no _note fails",
          len(V.merge_errors(assign, good, {"peachfile:2": {"sameAs": "ocd-person/rep"}})), 1)
    check("a forward from an id the ledger never issued fails",
          len(V.merge_errors(assign, {"vg7": "vg1"}, ok_ov)) >= 1, True)
    chain = {"vg2": "vg1", "vg1": "vg9"}
    check("a chain fails", any("chain" in e for e in V.merge_errors(assign, chain, ok_ov)), True)
    check("a dropped forward fails (append-only)",
          len(V.merge_errors(assign, {}, ok_ov, old_merged=good)), 1)
    check("a changed forward fails",
          any("changed" in e for e in V.merge_errors(
              assign, {"vg2": "vg9"},
              {"peachfile:2": {"sameAs": "peachfile:9", "_note": "n"}}, old_merged=good)), True)
    check("a record still carrying the retired id fails",
          len(V.merge_errors(assign, good, ok_ov, people=[{"vgId": "vg2", "name": {"full": "X"}}])), 1)
    check("the published map must match the ledger",
          len(V.merge_errors(assign, good, ok_ov, published={})), 1)
    check("resolve follows a forward and leaves others alone",
          (V.resolve(good, "vg2"), V.resolve(good, "vg9")), ("vg1", "vg9"))


def main():
    tier1_cases()
    tier2_cases()
    ledger_merge_cases()
    merge_validation_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
