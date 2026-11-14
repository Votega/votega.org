#!/usr/bin/env python3
"""CLI tests for freeze_ga_biennium.py. Temp data dir, out root and ledger; no network.

Usage: python scripts/test_freeze_ga_biennium_cli.py   (exit 0 ok, 1 on failure)
"""
import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freeze_ga_biennium as C  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def wj(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


MEMBERS = [
    {"id": "ocd-person/aaa", "legisGaGovId": 1, "chamber": "Senate", "status": "Resigned"},
    {"id": "ocd-person/bbb", "legisGaGovId": 2, "chamber": "House of Representatives", "status": None},
    {"id": "ga-senate-7-vacant", "legisGaGovId": None, "chamber": "Senate", "status": "Vacant"},
    {"id": "exec-1", "legisGaGovId": 3, "chamber": "executive", "status": None},
]


def setup(ledger_gids=("1", "2"), votes=("aaa", "bbb")):
    root = tempfile.mkdtemp()
    d, out, led = os.path.join(root, "data"), os.path.join(root, "out"), os.path.join(root, "ledger.json")
    wj(os.path.join(d, "ga-members.json"), {"metadata": {"session": "2025_26"}, "members": MEMBERS})
    wj(os.path.join(d, "ga-votes-index.json"), {"voteIds": ["a"]})
    wj(os.path.join(d, "ga-sponsorship-index.json"), {"members": {}})
    wj(os.path.join(d, "curated-ga-bill-votes.json"), {"c": 1})
    for v in votes:
        wj(os.path.join(d, "ga-votes", f"ocd-person-{v}.json"), {"v": 1})
    wj(led, {"metadata": {"generatedAt": None, "count": 0}, "people": {
        g: {"rosterId": "x", "urls": [{"path": f"/ga-legislators/p{g}/", "biennium": "2025_26"}],
            "bienniums": []} for g in ledger_gids}})
    return d, out, led


def run(args, d, out, led):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = C.main(args + ["--data-dir", d, "--out-root", out, "--ledger", led])
    return code, err.getvalue()


def frozen_gids(out):
    return sorted(m["legisGaGovId"] for m in rj(os.path.join(out, "2025_26", "ga-members.json"))["members"])


def test_departed_selects_only_departed():
    d, out, led = setup()
    code, _ = run(["2025_26", "--departed"], d, out, led)
    check("exit 0", code, 0)
    check("only departed member frozen", frozen_gids(out), [1])
    people = rj(led)["people"]
    check("ledger updated for 1", people["1"]["bienniums"], ["2025_26"])
    check("ledger untouched for 2", people["2"]["bienniums"], [])


def test_all_selects_voting_chambers_and_copies_curated():
    d, out, led = setup()
    code, _ = run(["2025_26", "--all"], d, out, led)
    check("exit 0", code, 0)
    check("voting chambers with a gid (no executive, no vacant)", frozen_gids(out), [1, 2])
    check("curated copied", os.path.exists(os.path.join(out, "2025_26", "curated-ga-bill-votes.json")), True)


def test_members_flag_does_not_copy_curated():
    d, out, led = setup()
    code, _ = run(["2025_26", "--members", "2"], d, out, led)
    check("exit 0", code, 0)
    check("curated not copied", os.path.exists(os.path.join(out, "2025_26", "curated-ga-bill-votes.json")), False)


def test_ledger_gap_refused_no_files():
    d, out, led = setup(ledger_gids=("1",))
    before = rj(led)
    code, err = run(["2025_26", "--all"], d, out, led)
    check("exit 1", code, 1)
    check("names the gid", "2" in err, True)
    check("no frozen tree", os.path.exists(out), False)
    check("ledger unchanged", rj(led), before)


def test_freeze_refusal_exits_1_no_files():
    d, out, led = setup(votes=("aaa",))  # member 2 has no vote slice
    before = rj(led)
    code, err = run(["2025_26", "--all"], d, out, led)
    check("exit 1", code, 1)
    check("message names gid", "2" in err, True)
    check("no frozen tree", os.path.exists(out), False)
    check("ledger unchanged", rj(led), before)


def test_no_votes_ok_flag():
    d, out, led = setup(votes=("aaa",))
    code, _ = run(["2025_26", "--all", "--no-votes-ok", "2"], d, out, led)
    check("exit 0", code, 0)
    check("noVotes", rj(os.path.join(out, "2025_26", "ga-members.json"))["metadata"]["noVotes"], ["2"])


for name, fn in sorted(globals().items()):
    if name.startswith("test_") and callable(fn):
        print(name)
        fn()

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nAll checks passed.")
