#!/usr/bin/env python3
"""Tests for distill_results_breakdown.py: the county and vote-method figures kept from a
Secretary of State JSON export.

    python scripts/test_distill_results_breakdown.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import distill_results_breakdown as dr  # noqa: E402

GROUPS = ("Election Day", "Advance Voting", "Absentee by Mail", "Provisional")


def option(oid, name, votes, split=None, party="REP"):
    split = split or [None] * 4
    return {"id": oid, "name": name, "voteCount": votes, "politicalParty": party,
            "groupResults": [{"groupName": g, "voteCount": v} for g, v in zip(GROUPS, split)],
            "precinctResults": [{"id": "1", "name": "P", "voteCount": votes}]}


def item(cid, name, *options):
    return {"id": cid, "name": name, "ballotOptions": list(options)}


def feed(items, counties):
    return {"electionDate": "2026-05-19", "createdAt": "2026-06-05T16:30:33Z",
            "results": {"ballotItems": items},
            "localResults": [{"name": n, "ballotItems": i} for n, i in counties.items()]}


def simple():
    state = item("US2R", "US Senate - Rep", option("1", "Ann Able (I)", 30, [10, 15, 5, 0]),
                 option("2", "Bo Baker", 12, [4, 8, 0, 0]))
    return feed([state, item("L1", "City Council at Large", option("9", "Local Person", 3))], {
        "Ben Hill County": [item("US2R", "US Senate - Rep", option("2", "Bo Baker", 2, [1, 1, 0, 0]),
                                 option("1", "Ann Able (I)", 20, [5, 10, 5, 0]))],
        "Echols County": [item("US2R", "US Senate - Rep", option("1", "Ann Able (I)", 10),
                               option("2", "Bo Baker", 10)),
                          item("L1", "City Council at Large", option("9", "Local Person", 3))],
    })


def raises(payload, *fragments):
    try:
        dr.distill(payload)
    except ValueError as e:
        for f in fragments:
            assert f in str(e), f"{f!r} not in {e}"
        return
    raise AssertionError("expected a ValueError")


def test_keeps_totals_methods_and_counties_aligned_by_candidate():
    out = dr.distill(simple())
    assert out["electionDate"] == "2026-05-19" and out["createdAt"] == "2026-06-05T16:30:33Z"
    assert out["methods"] == ["electionDay", "advanceVoting", "absenteeByMail", "provisional"]
    (contest,) = out["contests"]  # the city council contest is not one the site publishes
    assert contest["section"] == "statewide" and contest["office"] == "US Senate - Rep"
    assert contest["candidates"] == [{"name": "Ann Able", "votes": 30, "methods": [10, 15, 5, 0]},
                                     {"name": "Bo Baker", "votes": 12, "methods": [4, 8, 0, 0]}]
    assert sorted(contest["counties"]) == ["Ben Hill", "Echols"]
    assert contest["counties"]["Ben Hill"] == [[20, [5, 10, 5, 0]], [2, [1, 1, 0, 0]]]


def test_a_county_that_reports_no_split_has_none_never_zeros():
    assert dr.distill(simple())["contests"][0]["counties"]["Echols"] == [[10, None], [10, None]]


def test_party_suffix_is_removed_from_names():
    p = feed([item("S1", "Governor", option("1", "Ann Able (I) (Dem)", 3, [1, 1, 1, 0]))], {
        "Echols County": [item("S1", "Governor", option("1", "Ann Able (I) (Dem)", 3, [1, 1, 1, 0]))]})
    assert dr.distill(p)["contests"][0]["candidates"][0]["name"] == "Ann Able"


def test_county_votes_that_do_not_add_up_are_refused():
    p = simple()
    p["localResults"][1]["ballotItems"][0]["ballotOptions"][1]["voteCount"] = 3
    raises(p, "US Senate - Rep", "Bo Baker", "counties")


def test_a_split_that_does_not_add_up_is_refused():
    p = simple()
    p["results"]["ballotItems"][0]["ballotOptions"][0]["groupResults"][0]["voteCount"] = 11
    raises(p, "Ann Able", "vote method")


def test_a_partly_blank_split_is_refused():
    p = simple()
    p["results"]["ballotItems"][0]["ballotOptions"][0]["groupResults"][3]["voteCount"] = None
    raises(p, "Ann Able", "vote method")


def test_an_unknown_vote_method_is_refused():
    p = simple()
    p["results"]["ballotItems"][0]["ballotOptions"][0]["groupResults"][0]["groupName"] = "Drop Box"
    raises(p, "Drop Box")


def test_a_county_missing_a_candidate_is_refused():
    p = simple()
    del p["localResults"][0]["ballotItems"][0]["ballotOptions"][0]
    raises(p, "Ben Hill", "candidates")


def test_a_file_that_is_not_the_results_export_is_refused():
    raises({"counties": {}}, "export")
    raises(feed([item("S1", "Governor", option("1", "A", 1))], {}), "county")


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except Exception as e:  # noqa: BLE001 -- report every failure, not just the first
                failed += 1
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print("All distill_results_breakdown tests passed.")
