#!/usr/bin/env python3
"""Tests for publish_early_vote.py. Runs against the committed source files, plus tampered copies to prove each gate fires.

    python scripts/test_publish_early_vote.py
"""
import copy
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import publish_early_vote as pub  # noqa: E402

os.chdir(ROOT)  # the publisher reads its sources relative to the repo root


def sources():
    return copy.deepcopy(pub.load_sources())


def build(totals=None, daily=None):
    t, d, f, dic = sources()
    return pub.build_artifacts(totals or t, daily or d, f, dic)


def rows_of(artifacts, name):
    return list(csv.DictReader(io.StringIO(artifacts[f"early-vote/2026-general/{name}"].decode("utf-8"))))


def raises(fn, *needles):
    try:
        fn()
    except ValueError as e:
        assert all(n in str(e) for n in needles), (needles, str(e))
        return
    raise AssertionError(f"expected ValueError containing {needles}")


def test_suppress_withholds_one_to_nine_only():
    assert [pub.suppress(n) for n in (0, 1, 9, 10, 250, None)] == [0, None, None, 10, 250, None]


def test_every_published_column_is_declared_and_none_is_personal():
    a = build()
    schema = json.loads(a["early-vote/2026-general/county-totals.schema.json"])
    declared = list(schema["properties"]["counties"]["items"]["properties"])
    header = list(rows_of(a, "county-totals.csv")[0])
    assert header == declared, "the CSV, the JSON rows and the schema must carry exactly the same columns"
    js = json.loads(a["early-vote/2026-general/county-totals.json"])["counties"]
    assert all(set(r) == set(declared) for r in js)
    by_day = list(rows_of(a, "county-by-day.csv")[0])
    personal = ("name_", "first", "last", "address", "street", "zip", "voter_", "birth", "phone", "email", "precinct", "district")
    for col in header + by_day:
        assert not any(p in col for p in personal), f"column {col!r} looks personal"
    assert len(header) == len(set(header))


def test_small_sensitive_mail_counts_never_leave():
    a = build()
    for r in rows_of(a, "county-totals.csv"):
        for col in pub.SENSITIVE:
            assert r[col] == "" or int(r[col]) == 0 or int(r[col]) >= pub.SUPPRESS_BELOW, (r["county"], col, r[col])
    for r in json.loads(a["early-vote/2026-general/county-totals.json"])["counties"]:
        for col in pub.SENSITIVE:
            assert r[col] is None or r[col] == 0 or r[col] >= pub.SUPPRESS_BELOW


def test_totals_and_by_day_describe_the_same_ballots():
    a = build()
    totals = {r["county_fips"]: r for r in rows_of(a, "county-totals.csv")}
    assert len(totals) == 159
    sums = {}
    for r in rows_of(a, "county-by-day.csv"):
        if r["election_year"] == "2026":
            s = sums.setdefault(r["county_fips"], [0, 0])
            s[0] += int(r["in_person"]); s[1] += int(r["mail"])
    assert {f: s for f, s in sums.items()} == {f: [int(r["in_person"]), int(r["mail"])] for f, r in totals.items()}


def test_by_day_is_a_complete_zero_filled_grid_with_only_complete_years():
    rows = rows_of(build(), "county-by-day.csv")
    assert {r["election_year"] for r in rows} == {"2026", "2024"}, "2022's file is incomplete, so it is not published"
    for year in ("2026", "2024"):
        per_county = {}
        for r in rows:
            if r["election_year"] == year:
                per_county.setdefault(r["county_fips"], []).append(int(r["days_before"]))
        assert len(per_county) == 159
        days = {tuple(v) for v in per_county.values()}
        assert len(days) == 1, "every county carries the same days"
        d = list(days)[0]
        assert d[0] == 45 and list(d) == sorted(d, reverse=True) and len(d) == len(set(d))
    pooled = [r for r in rows if r["days_before"] == "45"]
    assert pooled and all(r["date"] == "" for r in pooled) and all(r["date"] for r in rows if r["days_before"] != "45")


def test_two_builds_are_byte_identical():
    assert build() == build(), "no wall-clock time may reach the artifacts, or every run would publish"


def test_fips_codes_are_five_digit_georgia():
    for r in rows_of(build(), "county-totals.csv"):
        assert len(r["county_fips"]) == 5 and r["county_fips"].startswith("13")


def test_refuses_when_the_two_files_run_through_different_days():
    t, d, f, dic = sources()
    d["years"]["2026"]["asOf"] = "2026-10-01"
    raises(lambda: pub.build_artifacts(t, d, f, dic), "county-by-day runs through")


def test_refuses_when_by_day_disagrees_with_totals():
    t, d, f, dic = sources()
    county = next(iter(d["years"]["2026"]["counties"]))
    d["years"]["2026"]["counties"][county][0][1] += 1
    raises(lambda: pub.build_artifacts(t, d, f, dic), "adds to")


def test_refuses_to_publish_a_withheld_value():
    a = build()
    totals_rows = json.loads(a["early-vote/2026-general/county-totals.json"])["counties"]
    by_day = json.loads(a["early-vote/2026-general/county-by-day.json"])["rows"]
    pub.check_consistency(totals_rows, by_day, "2026")  # the real tables pass
    totals_rows[0]["mail_rejected"] = 3
    raises(lambda: pub.check_consistency(totals_rows, by_day, "2026"), "must be withheld")


def test_validate_requires_all_counties():
    a = build()
    pub.validate(a)  # passes on the real build
    short = dict(a)
    doc = json.loads(short["early-vote/2026-general/county-totals.json"])
    doc["counties"] = doc["counties"][:100]
    short["early-vote/2026-general/county-totals.json"] = json.dumps(doc).encode()
    raises(lambda: pub.validate(short), "need >= 159")


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print("ok  ", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", name, "-", e)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
