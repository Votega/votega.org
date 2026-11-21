#!/usr/bin/env python3
"""Tests for validate_ga_legislator_ledger.py, against a throwaway git repo.

Usage: python scripts/test_validate_ga_legislator_ledger.py   (exit 0 ok, 1 on failure)
"""
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_legislator_ledger as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


U = "https://www.votega.org"
LEDGER = {"metadata": {"generatedAt": "x", "count": 2}, "people": {
    "1": {"rosterId": "ocd-person/1", "urls": [{"path": "/ga-legislators/a-house-1/", "biennium": "2025_26"}],
          "bienniums": ["2023_24"]},
    "2": {"rosterId": "ocd-person/2", "urls": [{"path": "/ga-legislators/b-senate-2/", "biennium": "2025_26"}],
          "bienniums": []}}}
ROSTER = {"members": [
    {"legisGaGovId": 1, "votegaUrl": U + "/ga-legislators/a-house-1/", "status": None},
    {"legisGaGovId": 2, "votegaUrl": U + "/ga-legislators/b-senate-2/", "status": "Resigned"}]}
FROZEN = {"2023_24": {"members": [{"legisGaGovId": 1, "chamber": "House of Representatives", "district": 1}]}}


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def git(d, *args):
    subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def setup(tmp, ledger=LEDGER, roster=ROSTER, frozen=FROZEN):
    """Commit `LEDGER` at HEAD, then write the working-tree `ledger`."""
    write(os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json"), LEDGER)
    git(tmp, "init", "-q")
    git(tmp, "add", "-A")
    git(tmp, "commit", "-q", "-m", "base")
    write(os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json"), ledger)
    write(os.path.join(tmp, "assets", "data", "ga-members.json"), roster)
    for tag, doc in frozen.items():
        write(os.path.join(tmp, "assets", "data", "ga-bienniums", tag, "ga-members.json"), doc)


def run(tmp, *extra):
    return V.main(["--ledger", os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json"),
                   "--roster", os.path.join(tmp, "assets", "data", "ga-members.json"),
                   "--frozen-root", os.path.join(tmp, "assets", "data", "ga-bienniums"), *extra])


def scenario(label, want, **kw):
    mutate = kw.pop("mutate", None)
    msg = kw.pop("msg", None)
    with tempfile.TemporaryDirectory() as tmp:
        led = copy.deepcopy(LEDGER)
        if mutate:
            mutate(led)
        setup(tmp, ledger=led, **kw)
        # The base read must really have worked, or every "pass" below is vacuous.
        base = V.read_base_ledger(os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json"), "HEAD")
        check(label + ": base read succeeded", len(base["people"]), 2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(tmp)
        check(label, rc, want)
        if msg:
            check(label + ": message", msg in buf.getvalue(), True)


def test_clean_passes():
    scenario("clean", 0)


def test_rename_is_a_note_not_a_failure():
    def m(led):
        led["people"]["1"]["urls"].insert(0, {"path": "/ga-legislators/a-senate-9/", "biennium": "2027_28"})
    roster = copy.deepcopy(ROSTER)
    roster["members"][0]["votegaUrl"] = U + "/ga-legislators/a-senate-9/"
    scenario("rename", 0, mutate=m, roster=roster)


def test_removed_url_fails():
    scenario("removed url", 1, mutate=lambda led: led["people"]["2"].update(urls=[]),
             msg="person 2: path /ga-legislators/b-senate-2/ removed")


def test_removed_person_fails():
    scenario("removed person", 1, mutate=lambda led: led["people"].pop("2"), msg="person 2 removed")


def test_person_in_neither_roster_nor_frozen_fails():
    def m(led):
        led["people"]["3"] = {"rosterId": "ocd-person/3", "bienniums": [],
                              "urls": [{"path": "/ga-legislators/c-house-3/", "biennium": "2025_26"}]}
    with tempfile.TemporaryDirectory() as tmp:
        led = copy.deepcopy(LEDGER)
        m(led)
        setup(tmp, ledger=led)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(tmp)
        check("unbuildable person fails", rc, 1)
        check("names person 3", "person 3: in neither the live roster nor any frozen" in buf.getvalue(), True)


def test_shared_url_fails():
    def m(led):
        led["people"]["2"]["urls"].append({"path": "/ga-legislators/a-house-1/", "biennium": "2025_26"})
    scenario("shared url", 1, mutate=m)


def test_votegaurl_mismatch_fails():
    roster = copy.deepcopy(ROSTER)
    roster["members"][0]["votegaUrl"] = U + "/ga-legislators/other/"
    scenario("votegaUrl mismatch", 1, roster=roster)


def test_foreign_votegaurl_fails():
    roster = copy.deepcopy(ROSTER)
    roster["members"][0]["votegaUrl"] = "https://example.com/ga-legislators/a-house-1/"
    scenario("foreign votegaUrl", 1, roster=roster)


def test_biennium_without_frozen_record_fails():
    scenario("biennium without frozen record", 1, frozen={})


def test_two_records_in_one_frozen_biennium_fails():
    frozen = {"2023_24": {"members": [
        {"legisGaGovId": 1, "chamber": "House of Representatives", "district": 1},
        {"legisGaGovId": 1, "chamber": "Senate", "district": 5}]}}
    scenario("mid-biennium move", 1, frozen=frozen)


def test_missing_file_at_base_is_empty_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        write(os.path.join(tmp, "README"), {})
        git(tmp, "init", "-q")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base")
        p = os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json")
        write(p, LEDGER)
        check("missing at base", V.read_base_ledger(p, "HEAD")["people"], {})


def test_base_read_failure_is_an_error_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        setup(tmp, ledger=LEDGER)
        check("bad ref exits 1", run(tmp, "--base-ref", "no-such-ref"), 1)
    with tempfile.TemporaryDirectory() as tmp:  # not a git repo at all
        write(os.path.join(tmp, "assets", "data", "ga-legislator-ledger.json"), LEDGER)
        write(os.path.join(tmp, "assets", "data", "ga-members.json"), ROSTER)
        check("not a repo exits 1", run(tmp), 1)


for t in [test_clean_passes, test_rename_is_a_note_not_a_failure, test_removed_url_fails,
          test_removed_person_fails, test_shared_url_fails, test_votegaurl_mismatch_fails,
          test_foreign_votegaurl_fails, test_biennium_without_frozen_record_fails,
          test_two_records_in_one_frozen_biennium_fails, test_missing_file_at_base_is_empty_ledger,
          test_base_read_failure_is_an_error_not_a_pass]:
    print(t.__name__)
    t()

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nAll checks passed.")
