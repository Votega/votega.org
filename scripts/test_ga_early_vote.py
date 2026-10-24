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
        out, mail, voted, daily, final = g.count_prior(tmp, dt.date(2022, 10, 26), dt.date(2022, 11, 8))
        assert final == {"COBB": 2}, final  # every accepted ballot with a date, whatever the date
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


def test_history_ids_are_normalized_and_only_early_styles_count():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["County Name", "Voter Registration Number", "Election Date", "Election Type", "Party",
                        "Ballot Style", "Absentee", "Provisional", "Supplemental"])
            w.writerow(["FULTON", "00001234", "11/08/2022", "GENERAL", "", "EARLY IN-PERSON", "Y", "", "N"])
            w.writerow(["FULTON", "00001234", "11/08/2022", "GENERAL", "", "ABSENTEE BY MAIL", "Y", "", "N"])  # same voter twice
            w.writerow(["COBB", "00005678", "11/08/2022", "GENERAL", "", "REGULAR", "", "", "N"])  # election day
            w.writerow(["COBB", "00009999", "11/08/2022", "GENERAL", "", "ELECTRONIC BALLOT DELIVERY", "Y", "", "N"])
        voted, counts = g.read_history(p)
    assert voted == {"1234", "9999"} and counts == {g.key("Fulton"): 1, g.key("Cobb"): 1}
    # the absentee files carry the id without its zero padding
    assert g.match_repeat_history({"1234": "A", "5678": "B", "01234": "A"}, voted) == {"A": 2}


def test_history_missing_file_is_fatal():
    try:
        g.read_history(os.path.join(tempfile.gettempdir(), "no-such-history.csv"))
    except SystemExit:
        return
    raise AssertionError("a missing history file must stop the run")


def test_county_winners_use_share_of_all_votes_and_the_majority_line():
    import json
    def county(name, votes):
        return {"name": name, "ballotItems": [{"name": "Governor", "ballotOptions": [
            {"name": n, "voteCount": v, "politicalParty": party} for n, v, party in votes]}]}
    data = {"localResults": [
        county("Cobb County", [("A", 600, "REP"), ("B", 380, "DEM"), ("C", 20, "LIB")]),
        county("Dekalb County", [("A", 450, "REP"), ("B", 480, "DEM"), ("C", 70, "LIB")]),   # plurality, not a majority
        county("Clay County", [("A", 0, "REP"), ("B", 0, "DEM")]),                            # no votes: skipped
    ]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "r.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
        out = g.read_county_winners(p, "Governor")
    cobb, dekalb = out[g.key("Cobb")], out[g.key("Dekalb")]
    assert (cobb["party"], cobb["pct"], cobb["majority"]) == ("R", 60.0, True)
    assert (dekalb["party"], dekalb["pct"], dekalb["majority"]) == ("D", 48.0, False)
    assert g.key("Clay") not in out


def _out(**over):
    import copy
    d = {
        "metadata": {"electionDate": "2026-11-03", "asOf": "2026-10-21", "quality": {},
                     "comparisons": {"2022": {"electionDate": "2022-11-08", "cutoff": "2022-10-26"}}},
        "statewide": {"ballots": 10, "mail": 4, "mailPipeline": {"accepted": 4}, "prior": {"2022": 6}},
        "daily": {"2026": [[13, 6, 4]], "2022": [[13, 0, 6], [5, 0, 3]]},
        "counties": [{"name": "A", "ballots": 10}],
    }
    d = copy.deepcopy(d)
    for path, v in over.items():  # "metadata.asOf" -> d["metadata"]["asOf"]
        node = d
        *head, last = path.split(".")
        for h in head:
            node = node[h]
        node[last] = v
    return d


def _check(data, prev=None, today=None):
    import datetime as dt
    return g.check_output(data, prev, today or dt.date(2026, 10, 22))


def test_check_output_clean_passes_silently():
    errs, warns = _check(_out())
    assert errs == [] and warns == [], (errs, warns)


def test_check_output_gates_on_each_contradiction():
    import datetime as dt
    cases = {
        "daily does not add up": _out(**{"daily": {"2026": [[13, 5, 4]], "2022": [[13, 0, 6]]}}),
        "a past year counted zero": _out(**{"statewide.prior": {"2022": 0}}),
        "as-of after election day": _out(**{"metadata.asOf": "2026-11-04"}),
        "as-of in the future": _out(**{"metadata.asOf": "2026-10-30"}),
        "mail pipeline disagrees": _out(**{"statewide.mailPipeline": {"accepted": 99}}),
        "too many stray dates": _out(**{"metadata.quality": {"strayAccepted": 500}}),
    }
    for name, data in cases.items():
        errs, _ = _check(data)
        assert errs, f"no error for: {name}"


def test_check_output_refuses_to_replace_good_data_with_worse():
    prev_ok = _out()
    assert _check(_out(), prev_ok)[0] == []
    older = _out(**{"metadata.asOf": "2026-10-20"})
    assert any("OLDER" in e for e in _check(older, prev_ok)[0])
    smaller = _out(**{"statewide.ballots": 10})
    prev_big = _out(**{"statewide.ballots": 100})
    assert any("fell" in e for e in _check(smaller, prev_big)[0])
    other_election = _out(**{"metadata.electionDate": "2026-12-01"})
    assert not any("OLDER" in e or "fell" in e for e in _check(_out(), other_election)[0])


def test_check_output_warns_about_what_was_dropped_and_stale_files():
    import datetime as dt
    data = _out(**{"metadata.quality": {"strayAccepted": 2, "badDates": 3, "unknownStatuses": {"X": 4}, "duplicateRecords": 7}})
    errs, warns = _check(data, today=dt.date(2026, 10, 28))
    assert errs == []
    text = " ".join(warns)
    for needle in ("dropped", "could not be read", "unrecognized", "merged", "refresh"):
        assert needle in text, (needle, warns)


def test_emit_is_loud():
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        g.emit(["something broke"], ["be careful"])
    out = buf.getvalue()
    assert "CHECK FAILED" in out and "ERROR: something broke" in out and "WARNING: be careful" in out


def test_results_json_normalizes_method_labels_and_requires_159_counties():
    import json
    def county(i, labels):
        return {"name": f"{chr(65 + i // 26)}{chr(65 + i % 26)} County", "ballotItems": [{"name": "Governor", "ballotOptions": [
            {"groupResults": [{"groupName": labels[0], "voteCount": 6}, {"groupName": labels[1], "voteCount": 2},
                              {"groupName": labels[2], "voteCount": 4}, {"groupName": "Provisional", "voteCount": 1}]}]}]}
    for labels in (("Advanced Voting", "Absentee by Mail", "Election Day"),
                   ("Advance Voting Votes", "Absentee by Mail Votes", "Election Day Votes")):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "e.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"localResults": [county(i, labels) for i in range(159)]}, f)
            res, contest = g.read_results_json(path)
            assert contest == "Governor" and len(res) == 159
            assert res["AA"] == {"early": 6, "mail": 2, "eday": 4, "prov": 1, "total": 13}, res["AA"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "e.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"localResults": [county(i, labels) for i in range(158)]}, f)
        try:
            g.read_results_json(path)
        except SystemExit:
            return
        raise AssertionError("158 counties must not load")


def test_check_output_past_year_gap_gate():
    gap = [{"county": "Fulton", "file": 133278, "official": 305815}]
    undeclared = _out(**{"metadata.pastYearGaps": {"2022": gap}})
    errs, _ = _check(undeclared)
    assert any("3% short" in e and "Fulton" in e for e in errs), errs
    declared = _out(**{"metadata.pastYearGaps": {"2022": gap},
                       "metadata.comparisons": {"2022": {"electionDate": "2022-11-08", "cutoff": "2022-10-22",
                                                         "daysBefore": 17, "lastCompleteDate": "2022-10-22"}}})
    declared["statewide"]["prior"] = {"2022": 6}
    declared["daily"]["2022"] = [[17, 0, 6]]
    errs, warns = _check(declared)
    assert errs == [] and any("last complete day" in w for w in warns), (errs, warns)
    unneeded = dict(declared); unneeded["metadata"] = dict(declared["metadata"]); unneeded["metadata"]["pastYearGaps"] = {"2022": []}
    errs, warns = _check(unneeded)
    assert errs == [] and any("still needed" in w for w in warns), (errs, warns)
    # when the voter history supplies the repeat figure, the warning says so instead of "omitted"
    declared["metadata"]["comparisons"]["2022"]["repeatSource"] = "voter history"
    errs, warns = _check(declared)
    assert errs == [] and any("voter history" in w and "omitted" not in w for w in warns), (errs, warns)


def test_check_output_point_must_match_headline_when_same_day():
    bad = _out(**{"statewide.atPoint": {"2022": {"ballots": 9}}, "metadata.comparisons": {"2022": {
        "electionDate": "2022-11-08", "cutoff": "2022-10-26", "daysBefore": 13}}, "metadata.daysBeforeElection": 13})
    errs, _ = _check(bad)
    assert any("comparison point" in e for e in errs), errs


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
