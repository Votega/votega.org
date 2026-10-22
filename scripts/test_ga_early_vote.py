#!/usr/bin/env python3
"""Invariants of scripts/generate_ga_early_vote.py (no network, temp dirs only).

Run: python scripts/test_ga_early_vote.py
"""
import csv
import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_early_vote as g  # noqa: E402


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_key_joins_spacing_variants():
    assert g.key("BEN HILL") == g.key("BENHILL") == "BENHILL"
    assert g.key("JEFFDAVIS") == g.key("Jeff Davis")


def test_current_dedupes_and_splits_styles():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "c.csv")
        _write(p, ["County Name", "Voter Registration Number", "Ballot Style"], [
            ["FULTON", "1", "EARLY IN-PERSON"],
            ["FULTON", "1", "EARLY IN-PERSON"],  # duplicate voter
            ["FULTON", "2", "ABSENTEE BY MAIL"],
        ])
        out, ids = g.count_current(p)
        assert ids == {"1": "FULTON", "2": "FULTON"}
        assert out["FULTON"] == {"total": 2, "inPerson": 1, "mail": 1, "electronic": 0}


def test_prior_cutoff_status_and_statewide_skip():
    hdr = ["County", "Voter Registration #", "Ballot Status", "Ballot Return Date"]
    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            ["COBB", "1", "A", "10/26/2022"],   # on cutoff: counted
            ["COBB", "2", "A", "10/27/2022"],   # after cutoff: not counted
            ["COBB", "3", "C", "10/20/2022"],   # cancelled: not counted
            ["COBB", "4", "A", ""],             # never returned: not counted
        ]
        _write(os.path.join(tmp, "COBB.csv"), hdr, rows)
        _write(os.path.join(tmp, "STATEWIDE.csv"), hdr, rows)  # repeats every county
        out, mail, voted = g.count_prior(tmp, dt.date(2022, 10, 26))
        assert out == {"COBB": 1}, out
        assert voted == {"1", "2"}, voted  # repeat match ignores the cutoff, still only accepted ballots with a return date


def test_prior_missing_directory_is_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            g.count_prior(os.path.join(tmp, "nope"), dt.date(2022, 10, 26))
        except SystemExit:
            return
        raise AssertionError("an empty prior directory must not yield zero counts")


def test_match_repeat_counts_by_county():
    cur = {"1": "A", "2": "A", "3": "B"}
    assert g.match_repeat(cur, {"1", "3", "99"}) == {"A": 1, "B": 1}


def test_validate_flags_ballots_above_active():
    cur = {"X": {"total": 5, "inPerson": 5, "mail": 0, "electronic": 0}}
    reg = {"X": {"name": "X", "active": 3, "total": 3}}
    counties = g.build(cur, reg, {}, None, None)
    errs = g.validate(counties, cur, reg)
    assert any("exceed active" in e for e in errs)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
