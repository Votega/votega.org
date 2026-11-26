#!/usr/bin/env python3
"""Tests for the certified election results publish_results.py builds for Votega/ga-races-elections.

    python scripts/test_publish_results.py
"""
import csv
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import publish_results as pr  # noqa: E402
import validate_sibling_pointers as vsp  # noqa: E402

# The nine columns the dataset was specified with; later ones are only ever appended.
ORIGINAL = ["election", "office", "district", "party", "candidate", "votes", "totalVotes",
            "incumbent", "winner"]


def contest(*votes, party="np", total=None, names=None, **extra):
    names = names or [f"Person {i}" for i in range(len(votes))]
    return {"party": party, "totalVotes": sum(votes) if total is None else total,
            "candidates": [{"name": n, "votes": v, "incumbent": False} for n, v in zip(names, votes)],
            **extra}


def sections(**by_section):
    """sections(courts=[("Office", contest, ...)]) in the shape build_results_json.py writes."""
    return [{"id": sid.replace("_", "-"), "label": sid,
             "races": [{"office": o[0], "contests": list(o[1:])} for o in offices]}
            for sid, offices in by_section.items()]


def page(key="ga-general-2026-results", folder="2026-general", status="certified",
         date="2026-11-03", mode="round", **extra):
    fm = {"layout": "election_results", "results_data": key, "results_folder": folder,
          "status": status, "election_date": date, "results_mode": mode,
          "heading": "A Heading", "permalink": f"/{key}/", **extra}
    return {k: v for k, v in fm.items() if v is not None}


def make_root(tmp, pages, data, stamps=None):
    """A minimal site tree: results page stubs, their data files and the build stamps."""
    os.makedirs(os.path.join(tmp, "_data", "election_results"))
    for fm in pages:
        body = "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n"
        with open(os.path.join(tmp, fm["results_data"] + ".html"), "w", encoding="utf-8") as f:
            f.write(body)
    for key, secs in data.items():
        with open(os.path.join(tmp, "_data", "election_results", key + ".json"), "w", encoding="utf-8") as f:
            json.dump(secs, f)
    if stamps is None:
        stamps = {key: {"iso": "2026-11-20T15:51:29+00:00"} for key in data}
    with open(os.path.join(tmp, "_data", "results_updated.json"), "w", encoding="utf-8") as f:
        json.dump(stamps, f)
    return tmp


def build(pages, data, stamps=None, published=None):
    with tempfile.TemporaryDirectory() as tmp:
        return pr.build_artifacts(make_root(tmp, pages, data, stamps), published)


def contests_of(secs, mode="round", **pg):
    out = build([page(mode=mode, **pg)], {"ga-general-2026-results": secs})
    return json.loads(out["results/2026-general/results.json"])["contests"]


def raises(fn, *fragments):
    try:
        fn()
    except ValueError as e:
        for f in fragments:
            assert f in str(e), f"{f!r} not in {e}"
        return
    raise AssertionError("expected a ValueError")


ONE = sections(statewide=[("Governor", contest(60, 40))])


# --- what gets published -----------------------------------------------------

def test_only_certified_elections_are_published():
    out = build([page(), page("ga-general-2026-runoff-results", "2026-general-runoff", "unofficial", "2026-12-01")],
                {"ga-general-2026-results": ONE, "ga-general-2026-runoff-results": ONE})
    assert sorted(out) == ["data/results/manifest.json", "results/2026-general/results.csv",
                           "results/2026-general/results.json", "results/2026-general/results.schema.json"]


def test_a_page_with_no_status_is_not_certified():
    raises(lambda: build([page(status=None)], {"ga-general-2026-results": ONE}), "no certified")


def test_certified_page_with_no_votes_is_refused():
    empty = sections(statewide=[("Governor", contest(0, 0))])
    raises(lambda: build([page()], {"ga-general-2026-results": empty}), "no votes")


def test_certified_contest_with_several_candidates_and_no_votes_is_refused():
    secs = sections(statewide=[("Governor", contest(60, 40)), ("Attorney General", contest(0, 0))])
    raises(lambda: build([page()], {"ga-general-2026-results": secs}), "Attorney General", "no votes")


def test_single_candidate_contest_with_no_votes_is_marked_not_reported_never_zero():
    secs = sections(statewide=[("Governor", contest(60, 40))], courts=[("District Attorney - X", contest(0))])
    c = contests_of(secs)[1]
    assert c["outcome"] == "not-reported" and c["totalVotes"] is None
    assert c["candidates"][0]["votes"] is None and c["candidates"][0]["winner"] is None


def test_candidate_votes_exceeding_the_contest_total_are_refused():
    secs = sections(statewide=[("Governor", contest(60, 40, total=90))])
    raises(lambda: build([page()], {"ga-general-2026-results": secs}), "Governor", "exceed")


def test_certified_page_needs_a_folder_named_for_its_year_and_not_shared():
    raises(lambda: build([page(folder=None)], {"ga-general-2026-results": ONE}), "results_folder")
    raises(lambda: build([page(folder="2028-general")], {"ga-general-2026-results": ONE}), "2026-")
    raises(lambda: build([page(folder="2026-Gen/x")], {"ga-general-2026-results": ONE}), "results_folder")
    raises(lambda: build([page(), page("ga-primary-results")],
                         {"ga-general-2026-results": ONE, "ga-primary-results": ONE}), "2026-general")


def test_missing_build_stamp_is_refused():
    raises(lambda: build([page()], {"ga-general-2026-results": ONE}, stamps={}), "results_updated.json")


# --- how a contest is read (the rules of assets/scripts/results-contest.js) ---

def flags(c, key):
    return [x[key] for x in c["candidates"]]


def test_round_mode_majority_wins_and_plurality_goes_to_a_runoff():
    secs = sections(statewide=[("Governor", contest(60, 40)), ("Attorney General", contest(45, 40, 15)),
                               ("Secretary of State", contest(50, 30, 20))])
    won, runoff, half = contests_of(secs)
    assert won["outcome"] == "decided" and flags(won, "winner") == [True, False]
    assert runoff["outcome"] == "runoff" and flags(runoff, "winner") == [False, False, False]
    assert flags(runoff, "advancedToRunoff") == [True, True, False]
    assert half["outcome"] == "runoff", "exactly half is not a majority"


def test_final_mode_leader_wins_without_a_majority():
    c = contests_of(sections(statewide=[("Governor", contest(45, 40, 15))]), mode="final")[0]
    assert c["outcome"] == "decided" and flags(c, "winner") == [True, False, False]


def test_a_tie_for_first_in_a_decided_contest_is_refused():
    secs = sections(statewide=[("Governor", contest(50, 50))])
    raises(lambda: contests_of(secs, mode="final"), "Governor", "tie")


def test_unopposed_candidate_wins():
    c = contests_of(sections(statewide=[("Governor", contest(12))]))[0]
    assert c["outcome"] == "uncontested" and flags(c, "winner") == [True]


# --- names, offices, ids ------------------------------------------------------

def test_party_comes_from_the_name_suffix_else_the_contest_and_the_suffix_is_removed():
    assert pr.candidate_party("Jon Ossoff (Dem)", "np") == ("Jon Ossoff", "Democrat")
    assert pr.candidate_party("Natalie Paine (Rep)", "rep") == ("Natalie Paine", "Republican")
    assert pr.candidate_party("Al Third (Ind)", "np") == ("Al Third", "Independent")
    assert pr.candidate_party("Mike Collins", "rep") == ("Mike Collins", "Republican")
    assert pr.candidate_party('Richard "Richy" Braun', "np") == ('Richard "Richy" Braun', None)


def test_office_and_district():
    assert pr.office_and_district("state-house", "District 151") == ("Georgia House of Representatives", 151)
    assert pr.office_and_district("state-senate", "Special State Senate - District 7") == (
        "Georgia State Senate (special election)", 7)
    assert pr.office_and_district("us-house", "District 13") == ("U.S. House", 13)
    assert pr.office_and_district("statewide", "PSC - District 3") == ("PSC - District 3", 3)
    assert pr.office_and_district("courts", "District Attorney - Waycross Judicial Circuit") == (
        "District Attorney - Waycross Judicial Circuit", None)


def test_contest_ids_separate_party_ballots_and_same_named_seats():
    secs = sections(statewide=[("Governor", contest(6, 4, party="rep"), contest(6, 4, party="dem"))],
                    courts=[("Superior Court - G", contest(3), contest(4))])
    assert [c["contestId"] for c in contests_of(secs)] == [
        "statewide-governor-rep", "statewide-governor-dem",
        "courts-superior-court-g-1", "courts-superior-court-g-2"]


# --- the files -----------------------------------------------------------------

def test_columns_and_one_row_per_contest_candidate():
    assert pr.RESULTS_COLUMNS[:9] == ORIGINAL
    secs = sections(state_house=[("District 5", contest(60, 40, names=["A (Rep)", "B (Dem)"]))],
                    courts=[("District Attorney - X", contest(0))])
    out = build([page()], {"ga-general-2026-results": secs})
    body = out["results/2026-general/results.csv"].decode("utf-8")
    assert body.splitlines()[0].split(",") == pr.RESULTS_COLUMNS
    rows = list(csv.DictReader(io.StringIO(body)))
    assert len(rows) == 3
    first = rows[0]
    assert [first[k] for k in ORIGINAL] == [
        "2026-general", "Georgia House of Representatives", "5", "Republican", "A", "60", "100", "False", "True"]
    assert first["status"] == "certified" and first["electionDate"] == "2026-11-03"
    assert (rows[2]["votes"], rows[2]["totalVotes"], rows[2]["winner"]) == ("", "", "")


def test_metadata_says_certified_and_which_election():
    meta = json.loads(build([page()], {"ga-general-2026-results": ONE})
                      ["results/2026-general/results.json"])["metadata"]
    assert meta["status"] == "certified" and meta["election"] == "2026-general"
    assert meta["electionDate"] == "2026-11-03" and meta["generatedAt"] == "2026-11-20T15:51:29+00:00"
    assert meta["resultsPage"] == "https://www.votega.org/ga-general-2026-results/"
    assert meta["schemaVersion"] == pr.SCHEMA_VERSION


def test_schema_declares_its_own_path_and_describes_every_field_published():
    out = build([page()], {"ga-general-2026-results": ONE})
    schema = json.loads(out["results/2026-general/results.schema.json"])
    assert schema["$id"] == pr.RAW_BASE + "/results/2026-general/results.schema.json"
    assert schema["schemaVersion"] == pr.SCHEMA_VERSION and schema["schemaStability"]
    doc = json.loads(out["results/2026-general/results.json"])
    item = schema["properties"]["contests"]["items"]
    cand = item["properties"]["candidates"]["items"]
    assert set(doc["metadata"]) == set(schema["properties"]["metadata"]["properties"])
    assert set(doc["contests"][0]) == set(item["properties"]) == set(item["required"])
    assert set(doc["contests"][0]["candidates"][0]) == set(cand["properties"]) == set(cand["required"])


def test_manifest_names_only_files_that_are_published():
    out = build([page()], {"ga-general-2026-results": ONE})
    man = json.loads(out["data/results/manifest.json"])
    assert man["dataset"] == "results" and man["generatedAt"] == "2026-11-20T15:51:29+00:00"
    assert man["rowCount"] == 2
    assert man["coverage"]["elections"] == [
        {"election": "2026-general", "electionDate": "2026-11-03", "status": "certified"}]
    assert vsp.dangling(man, set(out), "data/results/manifest.json") == []
    assert {f["path"] for f in man["files"]} == {p for p in out if p.startswith("results/")}


def test_two_builds_are_byte_identical():
    args = ([page()], {"ga-general-2026-results": ONE})
    assert build(*args) == build(*args)


# --- per-election folders are permanent ---------------------------------------

def write_tree(root, artifacts):
    for path, data in artifacts.items():
        dest = os.path.join(root, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)


def test_an_earlier_published_election_stays_in_the_manifest_unchanged():
    old = build([page()], {"ga-general-2026-results": ONE})
    with tempfile.TemporaryDirectory() as published:
        write_tree(published, old)
        # next cycle: the same page and data key now describe 2028
        new = build([page(folder="2028-general", date="2028-11-07")], {"ga-general-2026-results": ONE},
                    stamps={"ga-general-2026-results": {"iso": "2028-11-20T00:00:00+00:00"}},
                    published=published)
    for path in (p for p in old if p.startswith("results/")):
        assert new[path] == old[path]
    man = json.loads(new["data/results/manifest.json"])
    assert [e["election"] for e in man["coverage"]["elections"]] == ["2026-general", "2028-general"]
    assert man["rowCount"] == 4 and man["generatedAt"] == "2028-11-20T00:00:00+00:00"


def test_a_published_folder_is_never_rewritten_for_a_different_election_date():
    old = build([page()], {"ga-general-2026-results": ONE})
    with tempfile.TemporaryDirectory() as published:
        write_tree(published, old)
        raises(lambda: build([page(date="2026-12-01")], {"ga-general-2026-results": ONE}, published=published),
               "2026-general", "2026-11-03")


# --- the real data -------------------------------------------------------------

def test_real_repo_publishes_every_certified_page_and_loses_no_vote():
    certified = {p["results_data"]: p for p in pr.results_pages(ROOT) if p.get("status") == "certified"}
    assert certified, "no certified results page found"
    out = pr.build_artifacts(ROOT, None)
    folders = {p.split("/")[1] for p in out if p.startswith("results/")}
    assert folders == {p["results_folder"] for p in certified.values()}
    for key, fm in certified.items():
        src = json.load(open(os.path.join(ROOT, "_data", "election_results", key + ".json"), encoding="utf-8"))
        want = [c["votes"] if k["totalVotes"] else None
                for s in src for r in s["races"] for k in r["contests"] for c in k["candidates"]]
        doc = json.loads(out[f"results/{fm['results_folder']}/results.json"])
        got = [c["votes"] for k in doc["contests"] for c in k["candidates"]]
        assert sorted(got, key=str) == sorted(want, key=str), key
        ids = [k["contestId"] for k in doc["contests"]]
        assert len(ids) == len(set(ids)), f"{key}: contestId is not unique"
        left = [c["candidate"] for k in doc["contests"] for c in k["candidates"]
                if c["candidate"].endswith((")",)) and c["candidate"][-5:] in ("(Dem)", "(Rep)", "(Ind)")]
        assert not left, f"{key}: party suffix left on {left[:3]}"


def test_results_layout_links_the_published_folder_on_certified_pages():
    layout = open(os.path.join(ROOT, "_layouts", "election_results.html"), encoding="utf-8").read()
    assert "github.com/Votega/ga-races-elections/tree/main/results/{{ page.results_folder }}" in layout
    assert "result_status == 'certified' and page.results_folder" in layout


def test_publish_workflow_follows_the_results_workflow_by_its_current_name():
    def read(name):
        with open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8") as f:
            return f.read()
    name = next(line[len("name: "):].strip() for line in read("publish-results.yml").splitlines()
                if line.startswith("name: "))
    assert f"workflows: [{name}]" in read("publish-results-to-ga-races-elections.yml")


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
    print("All publish_results tests passed.")
