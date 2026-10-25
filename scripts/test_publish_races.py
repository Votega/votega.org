#!/usr/bin/env python3
"""Tests for the candidates.csv that publish_races.py builds for Votega/ga-races-elections.

    python scripts/test_publish_races.py
"""
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import publish_races as pr  # noqa: E402

os.chdir(ROOT)

# The first twelve columns are what consumers reading by position already rely on.
ORIGINAL = ["raceId", "level", "chamber", "district", "cycle", "phase", "electionDate",
            "party", "name", "type", "isIncumbent", "candidateId"]

FED = {"O000174": "Ossoff, Jon", "M001218": "Mike Collins"}
STATE = {"ocd-person/aaaa": "Pat Legislator"}


def race(rid, candidates, phase="general"):
    return {"id": rid, "level": "federal", "chamber": "U.S. House", "district": 1, "cycle": 2026,
            "phases": {phase: {"electionDate": "2026-11-03", "candidates": candidates}}}


def rows(races):
    return list(csv.DictReader(io.StringIO(pr.candidates_csv(races, FED, STATE).decode("utf-8"))))


def test_original_columns_keep_their_positions_and_new_ones_are_appended():
    assert pr.CANDIDATE_COLUMNS[:12] == ORIGINAL
    assert pr.CANDIDATE_COLUMNS[12:] == ["memberId", "memberSource", "candidateKey"]
    header = pr.candidates_csv([race("r", [])], FED, STATE).decode().splitlines()[0].split(",")
    assert header == pr.CANDIDATE_COLUMNS


def test_incumbent_listed_by_reference_carries_member_id_and_a_join_key():
    r = rows([race("senate-2026", [{"type": "incumbent", "memberId": "O000174", "memberSource": "congress", "party": "Democrat"}])])[0]
    assert r["candidateId"] == "" and r["memberId"] == "O000174" and r["memberSource"] == "congress"
    assert r["candidateKey"] == "O000174" and r["name"] == "Ossoff, Jon" and r["isIncumbent"] == "True"


def test_candidate_with_their_own_id_who_is_also_a_member_keeps_both():
    r = rows([race("ga-agri", [{"type": "incumbent", "id": "challenger-pat-1", "name": "Pat Legislator", "party": "Republican",
                                "existingMemberId": "ocd-person/aaaa", "existingMemberSource": "state", "isIncumbent": True}])])[0]
    assert r["candidateId"] == "challenger-pat-1" and r["memberId"] == "ocd-person/aaaa" and r["memberSource"] == "state"
    assert r["candidateKey"] == "challenger-pat-1", "candidateId wins when there is one"


def test_plain_challenger_has_no_member_columns():
    r = rows([race("r", [{"type": "challenger", "id": "challenger-jane-1", "name": "Jane Roe", "party": "Democrat"}])])[0]
    assert (r["memberId"], r["memberSource"], r["candidateKey"]) == ("", "", "challenger-jane-1")


def test_member_reference_precedence_matches_name_resolution():
    # a candidate with both: the id the name was looked up with is the id published
    c = {"existingMemberId": "M001218", "memberId": "O000174", "existingMemberSource": "congress", "memberSource": "congress"}
    assert pr.member_ref(c) == ("M001218", "congress")
    assert pr.resolve_name(c, FED, STATE) == "Mike Collins"
    assert pr.member_ref({"memberId": "X"}) == ("X", "")  # no source recorded: blank, not invented
    assert pr.member_ref({"id": "challenger-a"}) == ("", "")


def test_withdrawn_candidates_are_still_left_out():
    assert rows([race("r", [{"type": "challenger", "id": "c1", "name": "Out", "withdrawn": True}])]) == []


def test_every_row_of_the_real_dataset_has_a_join_key():
    doc = json.load(open("assets/data/races.json", encoding="utf-8"))
    fed, state = pr.load_name_maps()
    out = list(csv.DictReader(io.StringIO(pr.candidates_csv(doc["races"], fed, state).decode("utf-8"))))
    assert out, "no candidates built"
    missing = [(r["raceId"], r["phase"], r["name"]) for r in out if not r["candidateKey"]]
    assert not missing, f"rows with no candidateId and no memberId: {missing[:5]}"
    # an incumbent without a candidateId must be reachable through its member
    assert all(r["memberId"] for r in out if not r["candidateId"])


def test_everything_is_published_under_the_cycle_folder_and_nothing_at_the_root():
    arts = pr.build_artifacts()
    assert sorted(arts) == ["races/2026/RACES.md", "races/2026/candidates.csv", "races/2026/races.csv",
                            "races/2026/races.json", "races/2026/races.schema.json"]
    assert not any("/" not in p for p in arts), "a data file at the repo root would resurrect the old layout"
    assert set(pr.LEGACY_ROOT_FILES) == {p.rsplit("/", 1)[1] for p in arts}, "the cleanup list must name exactly the moved files"


def test_schema_id_is_the_path_it_is_published_at_and_covers_every_level():
    arts = pr.build_artifacts()
    sch = json.loads(arts["races/2026/races.schema.json"])
    assert sch["$id"] == "https://raw.githubusercontent.com/Votega/ga-races-elections/main/races/2026/races.schema.json"
    levels = set(sch["properties"]["races"]["items"]["properties"]["level"]["enum"])
    doc = json.loads(arts["races/2026/races.json"])
    unseen = {r["level"] for r in doc["races"]} - levels
    assert not unseen, f"the published schema would reject levels in the data: {unseen}"


def test_racesmd_links_stay_relative_so_they_work_inside_the_folder():
    md = pr.build_artifacts()["races/2026/RACES.md"].decode()
    for name in ("races.json", "races.csv", "candidates.csv"):
        assert f"]({name})" in md


def test_a_race_without_an_integer_cycle_is_refused():
    assert list(pr.group_by_cycle([{"cycle": 2026}, {"cycle": 2026}, {"cycle": 2028}])) == [2026, 2028]
    for bad in ([{"cycle": None}], [{"cycle": "2026"}], [{"id": "x"}], [{"cycle": True}], []):
        try:
            pr.group_by_cycle(bad)
        except ValueError as e:
            assert "refusing to publish" in str(e)
        else:
            raise AssertionError(f"{bad} must be refused")


def test_a_file_with_two_cycles_gets_a_folder_per_cycle_holding_only_that_cycle():
    import copy
    import tempfile
    doc = json.load(open(pr.SRC_RACES, encoding="utf-8"))
    later = [dict(copy.deepcopy(r), cycle=2028, id=r["id"].replace("2026", "2028")) for r in doc["races"][:5]]
    doc2 = dict(doc, races=doc["races"] + later)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "races.json")
        json.dump(doc2, open(path, "w", encoding="utf-8"))
        saved, pr.SRC_RACES = pr.SRC_RACES, path
        try:
            arts = pr.build_artifacts()
        finally:
            pr.SRC_RACES = saved
    assert sorted({p.split("/")[1] for p in arts}) == ["2026", "2028"]
    r26 = json.loads(arts["races/2026/races.json"])["races"]
    r28 = json.loads(arts["races/2028/races.json"])["races"]
    assert len(r26) == len(doc["races"]) and {r["cycle"] for r in r26} == {2026}
    assert len(r28) == 5 and {r["cycle"] for r in r28} == {2028}
    assert json.loads(arts["races/2028/races.schema.json"])["$id"].endswith("/races/2028/races.schema.json")
    assert "5 races" in arts["races/2028/RACES.md"].decode()
    pr.validate(arts)


def test_one_cycle_is_published_byte_for_byte_from_the_source_file():
    assert pr.build_artifacts()["races/2026/races.json"] == open(pr.SRC_RACES, "rb").read()


def test_validate_finds_the_races_in_every_folder():
    arts = pr.build_artifacts()
    pr.validate(arts)
    empty = dict(arts)
    empty["races/2026/races.json"] = json.dumps({"races": []}).encode()
    for bad in (empty, {k: v for k, v in arts.items() if not k.endswith("races.json")}):
        try:
            pr.validate(bad)
        except ValueError:
            continue
        raise AssertionError("validate must fail on an empty or missing races.json")


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
