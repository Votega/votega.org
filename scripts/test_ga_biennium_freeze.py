#!/usr/bin/env python3
"""Tests for lib/ga_biennium_freeze.py. No network; builds a temp data_dir.

Usage: python scripts/test_ga_biennium_freeze.py   (exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_biennium_freeze as F  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def raises(label, fn, *needles):
    try:
        fn()
    except F.FreezeError as e:
        ok = all(n in str(e) for n in needles)
        check(label, ok, True)
        return
    check(label, "no FreezeError", "FreezeError")


def wj(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rb(path):
    with open(path, "rb") as f:
        return f.read()


def make_data(d, vote_ids=("a", "b"), sponsor_members=("123",), with_votes=True):
    wj(os.path.join(d, "ga-members.json"), {
        "metadata": {"session": "2025_26"},
        "members": [{"id": "ocd-person/abc", "legisGaGovId": 123, "name": "A B",
                     "chamber": "Senate", "status": "Resigned"}]})
    wj(os.path.join(d, "ga-votes-index.json"), {"voteIds": list(vote_ids)})
    if with_votes:
        wj(os.path.join(d, "ga-votes", "ocd-person-abc.json"), {"v": 1})
    wj(os.path.join(d, "ga-sponsorship-index.json"), {"members": {m: [1, 2] for m in sponsor_members}})
    wj(os.path.join(d, "ga-sponsorship", "123.json"), {"s": 1})
    wj(os.path.join(d, "curated-ga-bill-votes.json"), {"c": 1})


def fresh(**kw):
    root = tempfile.mkdtemp()
    d, out = os.path.join(root, "data"), os.path.join(root, "out")
    make_data(d, **kw)
    return d, out


def frozen(out, name):
    return os.path.join(out, "2025_26", name)


def test_freeze_copies_member_record_and_slices():
    d, out = fresh()
    rep = F.freeze("2025_26", ["123"], d, out)
    check("report frozen", rep["frozen"], ["123"])
    for name in ("ga-votes-index.json", "ga-votes/ocd-person-abc.json",
                 "ga-sponsorship-index.json", "ga-sponsorship/123.json"):
        check(f"exists {name}", os.path.exists(frozen(out, name)), True)
    m = rj(frozen(out, "ga-members.json"))
    check("one member", len(m["members"]), 1)
    check("biennium", m["metadata"]["biennium"], "2025_26")
    check("session", m["metadata"]["session"], "2025_26")
    check("count", m["metadata"]["count"], 1)
    check("curated not copied by default", os.path.exists(frozen(out, "curated-ga-bill-votes.json")), False)


def test_curated_copied_when_asked():
    d, out = fresh()
    F.freeze("2025_26", ["123"], d, out, include_curated=True)
    check("curated copied", rj(frozen(out, "curated-ga-bill-votes.json")), {"c": 1})


def test_missing_vote_slice_refused():
    d, out = fresh(with_votes=False)
    raises("missing slice", lambda: F.freeze("2025_26", ["123"], d, out), "123")
    check("nothing written", os.path.exists(out), False)


def test_missing_sponsorship_slice_refused_when_indexed():
    d, out = fresh()
    os.remove(os.path.join(d, "ga-sponsorship", "123.json"))
    raises("indexed but slice missing", lambda: F.freeze("2025_26", ["123"], d, out),
           "123", "sponsorship")
    check("nothing written", os.path.exists(out), False)


def test_missing_sponsorship_slice_skipped_when_not_indexed():
    d, out = fresh(sponsor_members=())
    os.remove(os.path.join(d, "ga-sponsorship", "123.json"))
    F.freeze("2025_26", ["123"], d, out)
    check("frozen without sponsorship slice", os.path.exists(frozen(out, "ga-sponsorship/123.json")), False)
    check("member frozen", len(rj(frozen(out, "ga-members.json"))["members"]), 1)


def test_no_votes_ok_records_note():
    d, out = fresh(with_votes=False)
    F.freeze("2025_26", ["123"], d, out, no_votes_ok=("123",))
    check("noVotes", rj(frozen(out, "ga-members.json"))["metadata"]["noVotes"], ["123"])
    check("no vote slice", os.path.exists(frozen(out, "ga-votes/ocd-person-abc.json")), False)


def test_rerun_is_idempotent():
    d, out = fresh()
    F.freeze("2025_26", ["123"], d, out)
    before = {n: rb(frozen(out, n)) for n in ("ga-members.json", "ga-votes/ocd-person-abc.json",
                                              "ga-votes-index.json")}
    rep = F.freeze("2025_26", ["123"], d, out)
    check("unchanged", rep["unchanged"], ["123"])
    check("frozen empty", rep["frozen"], [])
    check("bytes identical", {n: rb(frozen(out, n)) for n in before}, before)


def test_changed_slice_refused_without_overwrite():
    d, out = fresh()
    F.freeze("2025_26", ["123"], d, out)
    wj(os.path.join(d, "ga-votes", "ocd-person-abc.json"), {"v": 2})
    raises("changed slice", lambda: F.freeze("2025_26", ["123"], d, out), "123")
    rep = F.freeze("2025_26", ["123"], d, out, overwrite=True)
    check("overwrite frozen", rep["frozen"], ["123"])
    check("slice replaced", rj(frozen(out, "ga-votes/ocd-person-abc.json")), {"v": 2})


def test_changed_member_record_refused_without_overwrite():
    d, out = fresh()
    F.freeze("2025_26", ["123"], d, out)
    doc = rj(os.path.join(d, "ga-members.json"))
    doc["members"][0]["name"] = "Other"
    wj(os.path.join(d, "ga-members.json"), doc)
    raises("changed record", lambda: F.freeze("2025_26", ["123"], d, out), "123")


def test_index_superset_accepted():
    d, out = fresh(vote_ids=("a", "b"))
    F.freeze("2025_26", ["123"], d, out)
    wj(os.path.join(d, "ga-votes-index.json"), {"voteIds": ["a", "b", "c"]})
    rep = F.freeze("2025_26", ["123"], d, out)
    check("replaced", "ga-votes-index.json" in rep["replacedIndexes"], True)
    check("new index", rj(frozen(out, "ga-votes-index.json"))["voteIds"], ["a", "b", "c"])


def test_index_reorder_refused():
    d, out = fresh(vote_ids=("a", "b"))
    F.freeze("2025_26", ["123"], d, out)
    wj(os.path.join(d, "ga-votes-index.json"), {"voteIds": ["b", "a", "c"]})
    raises("reorder", lambda: F.freeze("2025_26", ["123"], d, out), "voteIds")


def test_sponsorship_index_dropping_member_refused():
    d, out = fresh(sponsor_members=("123", "456"))
    F.freeze("2025_26", ["123"], d, out)
    wj(os.path.join(d, "ga-sponsorship-index.json"), {"members": {"123": [1, 2]}})
    raises("drop member", lambda: F.freeze("2025_26", ["123"], d, out), "456")


def test_unknown_gid_refused():
    d, out = fresh()
    raises("unknown gid", lambda: F.freeze("2025_26", ["999"], d, out), "999")


def add_second_member(d, with_votes=True):
    doc = rj(os.path.join(d, "ga-members.json"))
    doc["members"].append({"id": "ocd-person/def", "legisGaGovId": 456, "name": "C D",
                           "chamber": "House of Representatives", "status": "Resigned"})
    wj(os.path.join(d, "ga-members.json"), doc)
    if with_votes:
        wj(os.path.join(d, "ga-votes", "ocd-person-def.json"), {"v": 9})
    wj(os.path.join(d, "ga-sponsorship", "456.json"), {"s": 9})


def tree(root):
    out = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = rb(p)
    return out


def test_refusal_writes_nothing_fresh_root():
    d, out = fresh()
    add_second_member(d, with_votes=False)
    raises("second gid missing slice", lambda: F.freeze("2025_26", ["123", "456"], d, out), "456")
    check("fresh root untouched", os.path.exists(out) and tree(out), False)


def test_refusal_writes_nothing_fresh_root_changed_slice_path():
    # fresh root, second gid refused by a missing slice listed first
    d, out = fresh()
    add_second_member(d, with_votes=False)
    raises("refused when refusable gid is first", lambda: F.freeze("2025_26", ["456", "123"], d, out), "456")
    check("fresh root untouched", os.path.exists(out) and tree(out), False)


def test_refusal_writes_nothing_existing_root():
    d, out = fresh()
    F.freeze("2025_26", ["123"], d, out)
    add_second_member(d)
    before = tree(out)
    # 123's slice changed (refused) while 456 is new and the index grew: nothing may be written
    wj(os.path.join(d, "ga-votes", "ocd-person-abc.json"), {"v": 2})
    wj(os.path.join(d, "ga-votes-index.json"), {"voteIds": ["a", "b", "c"]})
    raises("changed slice among several", lambda: F.freeze("2025_26", ["456", "123"], d, out), "123")
    check("existing root byte-identical (changed slice)", tree(out), before)
    # restore 123; now 456 lacks a vote slice
    wj(os.path.join(d, "ga-votes", "ocd-person-abc.json"), {"v": 1})
    os.remove(os.path.join(d, "ga-votes", "ocd-person-def.json"))
    raises("missing slice among several", lambda: F.freeze("2025_26", ["123", "456"], d, out), "456")
    check("existing root byte-identical (missing slice)", tree(out), before)


for name, fn in sorted(globals().items()):
    if name.startswith("test_") and callable(fn):
        print(name)
        fn()

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nAll checks passed.")
