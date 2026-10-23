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


ABS_HDR = ["County", "Voter Registration #", "Ballot Status", "Ballot Return Date", "Ballot Style"]


def test_current_dedupes_picks_best_record_and_derives_as_of():
    import datetime as dt
    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            ["FULTON", "1", "A", "10/20/2026", "EARLY IN-PERSON"],
            ["FULTON", "2", "C", "", "ABSENTEE BY MAIL"],           # mailed ballot surrendered ...
            ["FULTON", "2", "A", "10/21/2026", "EARLY IN-PERSON"],  # ... to vote in person: counts once, in person
            ["FULTON", "3", "A", "10/19/2026", "ABSENTEE BY MAIL"],
            ["FULTON", "4", "I", "", "ABSENTEE BY MAIL"],           # outstanding
            ["FULTON", "5", "R", "10/19/2026", "ELECTRONIC BALLOT DELIVERY"],
            ["FULTON", "6", "A", "10/26/2029", "ABSENTEE BY MAIL"],  # stray date after as-of: not counted
        ]
        _write(os.path.join(tmp, "FULTON.csv"), ABS_HDR, rows)
        _write(os.path.join(tmp, "STATEWIDE.csv"), ABS_HDR, rows)   # repeats every county
        out = g.read_current(tmp, dt.date(2026, 11, 3))
        assert out["as_of"] == dt.date(2026, 10, 21)
        c = out["counties"]["FULTON"]
        assert (c["inPerson"], c["mail"]) == (2, 1), c
        # records, not voters: voter 2's cancelled mail ballot still counts as cancelled
        assert c["pipeline"] == {"accepted": 1, "rejected": 1, "outstanding": 1, "other": 0, "cancelled": 1}, c
        # daily is days before election day: Oct 21 -> 13 (one in person), Oct 20 -> 14, Oct 19 -> 15 (one mail)
        assert out["daily"] == {13: [1, 0], 14: [1, 0], 15: [0, 1]}, out["daily"]
        assert set(out["voters"]) == {"1", "2", "3"}


def test_days_before_folds_early_ballots_into_the_window_edge():
    import datetime as dt
    e = dt.date(2026, 11, 3)
    assert g._days_before(dt.date(2026, 10, 21), e) == 13
    assert g._days_before(dt.date(2026, 8, 1), e) == g.DAILY_WINDOW  # earlier than the window: kept, not dropped
    assert g._days_before(dt.date(2026, 11, 4), e) is None            # after election day


def test_current_missing_directory_is_fatal():
    import datetime as dt
    with tempfile.TemporaryDirectory() as tmp:
        try:
            g.read_current(os.path.join(tmp, "nope"), dt.date(2026, 11, 3))
        except SystemExit:
            return
        raise AssertionError("an empty current directory must not yield zero counts")


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
        out, mail, voted, daily = g.count_prior(tmp, dt.date(2022, 10, 26), dt.date(2022, 11, 8))
        assert out == {"COBB": 1}, out
        assert voted == {"1", "2"}, voted  # repeat match ignores the cutoff, still only accepted ballots with a return date


def test_prior_missing_directory_is_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            g.count_prior(os.path.join(tmp, "nope"), dt.date(2022, 10, 26), dt.date(2022, 11, 8))
        except SystemExit:
            return
        raise AssertionError("an empty prior directory must not yield zero counts")


def test_match_repeat_counts_by_county():
    cur = {"1": "A", "2": "A", "3": "B"}
    assert g.match_repeat(cur, {"1", "3", "99"}) == {"A": 1, "B": 1}


def test_validate_flags_ballots_above_active():
    cur = {"X": {"inPerson": 5, "mail": 0, "pipeline": {k: 0 for k in g.PIPELINE_ORDER}}}
    reg = {"X": {"name": "X", "active": 3, "total": 3}}
    counties = g.build(cur, reg, {})
    errs = g.validate(counties, cur, reg)
    assert any("exceed active" in e for e in errs)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
