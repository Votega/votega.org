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


# The cycles races.json holds today. Nothing below names a year: the file moves to a new
# cycle (and may hold two at once) without any edit here, and a data commit can never
# fail this suite.
CYCLE_FILES = ["RACES.md", "candidates.csv", "races.csv", "races.json", "races.schema.json"]


def live_races():
    return json.load(open(pr.SRC_RACES, encoding="utf-8"))


def live_cycles():
    return sorted(pr.group_by_cycle(live_races()["races"]))


def test_everything_is_published_under_the_cycle_folder_and_nothing_at_the_root():
    arts = pr.build_artifacts()
    # The DATA files, which is what this test is about. data/<dataset>/manifest.json
    # is excluded on purpose: it is the repo-wide dataset-discovery convention
    # (lib.sibling_publish.add_dataset_manifest), it is not cycle-scoped, and it is
    # not a race file. Scoping here rather than widening the lists below keeps the
    # original intent — no data file may drift back to the repo root — intact.
    data = sorted(p for p in arts if p.startswith("races/"))
    assert data == sorted(f"races/{c}/{n}" for c in live_cycles() for n in CYCLE_FILES)
    assert not any("/" not in p for p in arts), "a data file at the repo root would resurrect the old layout"
    assert set(pr.LEGACY_ROOT_FILES) == set(CYCLE_FILES), "the cleanup list must name exactly the moved files"
    assert "data/races/manifest.json" in arts, "the dataset manifest must still be published"


def test_schema_id_is_the_path_it_is_published_at_and_covers_every_level():
    arts = pr.build_artifacts()
    for c in live_cycles():
        sch = json.loads(arts[f"races/{c}/races.schema.json"])
        assert sch["$id"] == f"https://raw.githubusercontent.com/Votega/ga-races-elections/main/races/{c}/races.schema.json"
        levels = set(sch["properties"]["races"]["items"]["properties"]["level"]["enum"])
        doc = json.loads(arts[f"races/{c}/races.json"])
        unseen = {r["level"] for r in doc["races"]} - levels
        assert not unseen, f"the published schema would reject levels in the data: {unseen}"


def test_racesmd_links_stay_relative_so_they_work_inside_the_folder():
    arts = pr.build_artifacts()
    for c in live_cycles():
        md = arts[f"races/{c}/RACES.md"].decode()
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
    doc = live_races()
    cycles = live_cycles()
    nxt = cycles[-1] + 2
    later = [dict(copy.deepcopy(r), cycle=nxt, id=f"{r['id']}-c{nxt}") for r in doc["races"][:5]]
    doc2 = dict(doc, races=doc["races"] + later)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "races.json")
        json.dump(doc2, open(path, "w", encoding="utf-8"))
        saved, pr.SRC_RACES = pr.SRC_RACES, path
        try:
            arts = pr.build_artifacts()
        finally:
            pr.SRC_RACES = saved
    # Cycle folders only — the dataset manifest lives at data/races/manifest.json
    # and is deliberately not partitioned by cycle (it describes the dataset).
    assert sorted({int(p.split("/")[1]) for p in arts if p.startswith("races/")}) == cycles + [nxt]
    by_cycle = pr.group_by_cycle(doc["races"])
    for c in cycles:
        rc = json.loads(arts[f"races/{c}/races.json"])["races"]
        assert len(rc) == len(by_cycle[c]) and {r["cycle"] for r in rc} == {c}
    rn = json.loads(arts[f"races/{nxt}/races.json"])["races"]
    assert len(rn) == 5 and {r["cycle"] for r in rn} == {nxt}
    assert json.loads(arts[f"races/{nxt}/races.schema.json"])["$id"].endswith(f"/races/{nxt}/races.schema.json")
    assert "5 races" in arts[f"races/{nxt}/RACES.md"].decode()
    pr.validate(arts)


def test_one_cycle_is_published_byte_for_byte_from_the_source_file():
    import tempfile
    doc = live_races()
    c = live_cycles()[-1]
    one = dict(doc, races=[r for r in doc["races"] if r["cycle"] == c])
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "races.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(one, fh, indent=2)
        saved, pr.SRC_RACES = pr.SRC_RACES, path
        try:
            assert pr.build_artifacts()[f"races/{c}/races.json"] == open(path, "rb").read()
        finally:
            pr.SRC_RACES = saved


def test_validate_finds_the_races_in_every_folder():
    arts = pr.build_artifacts()
    pr.validate(arts)
    empty = dict(arts)
    empty[f"races/{live_cycles()[0]}/races.json"] = json.dumps({"races": []}).encode()
    for bad in (empty, {k: v for k, v in arts.items() if not k.endswith("races.json")}):
        try:
            pr.validate(bad)
        except ValueError:
            continue
        raise AssertionError("validate must fail on an empty or missing races.json")


def test_active_phase_follows_phase_dates_for_a_general_runoff():
    cand = {"id": "c", "name": "A", "party": "Republican"}
    def race(phases):
        return {"phases": {k: {"electionDate": d, "candidates": [cand]} for k, d in phases.items()}}
    # a general runoff (HD 151, Dec 1) comes AFTER the general ...
    assert pr.derive_active_phase(race({"primary": "2026-05-19", "general": "2026-11-03",
                                        "runoff": "2026-12-01"})) == "runoff"
    # ... a primary runoff comes BEFORE it
    assert pr.derive_active_phase(race({"primary": "2026-05-19", "runoff": "2026-06-16",
                                        "general": "2026-11-03"})) == "general"
    # undated phases keep the canonical name order
    assert pr.derive_active_phase({"phases": {"runoff": {"candidates": [cand]},
                                              "general": {"candidates": [cand]}}}) == "general"


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
