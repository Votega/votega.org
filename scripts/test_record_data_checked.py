#!/usr/bin/env python3
"""Invariants of the stale-stamp plumbing: scripts/record_data_checked.py and the window
table it reads (_data/data_freshness.yml).

Run: python scripts/test_record_data_checked.py   (no network; writes only to a temp dir)

What matters here is that the recorder cannot silently record into the void, and that every
dataset a workflow records is one the rule actually knows about.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_data_checked as rdc  # noqa: E402

ROOT = rdc.ROOT


def _table(tmp, text):
    p = os.path.join(tmp, "t.yml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def test_writes_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        t = _table(tmp, 'datasets:\n  ga-bills: { window_days: 10 }\n')
        out = os.path.join(tmp, "f")
        assert rdc.record("ga-bills", "2026-10-21", out, t) is True
        with open(os.path.join(out, "ga-bills.json"), encoding="utf-8") as f:
            assert json.load(f) == {"checkedAt": "2026-10-21"}
        # same day again: no rewrite, so the follow-up commit has nothing to commit
        assert rdc.record("ga-bills", "2026-10-21", out, t) is False
        assert rdc.record("ga-bills", "2026-10-22", out, t) is True


def test_refuses_never_flag_and_unknown_datasets():
    with tempfile.TemporaryDirectory() as tmp:
        t = _table(tmp, 'datasets:\n  ga-bills: { window_days: 10 }\n  supreme-court: { never: true, note: "x" }\n')
        for name in ("supreme-court", "typo-name"):
            try:
                rdc.record(name, "2026-10-21", os.path.join(tmp, "f"), t)
            except SystemExit as e:
                assert "no window_days" in str(e)
            else:
                raise AssertionError(f"{name} should have been refused")


def test_refuses_a_bad_date():
    with tempfile.TemporaryDirectory() as tmp:
        t = _table(tmp, 'datasets:\n  ga-bills: { window_days: 10 }\n')
        for bad in ("2026-1-5", "yesterday", ""):
            try:
                rdc.record("ga-bills", bad, os.path.join(tmp, "f"), t)
            except SystemExit:
                continue
            raise AssertionError(f"{bad!r} should have been refused")


def test_real_table_parses_and_never_entries_have_no_window():
    names = rdc.windowed_datasets()
    for expected in ("current-members", "ga-members", "ga-bills", "ga-member-votes",
                     "federal-member-votes", "ga-campaign-finance", "ga-fec-data",
                     "ga-executive-orders", "curated-ga-bill-votes", "local-government"):
        assert expected in names, expected
    for never in ("ga-executive", "supreme-court", "executive", "ga-legislative-candidates",
                  "ga-election-calendar", "ga-campaign-finance-history"):
        assert never not in names, never


def test_every_workflow_recorder_targets_a_windowed_dataset():
    names = rdc.windowed_datasets()
    wf_dir = os.path.join(ROOT, ".github", "workflows")
    found = 0
    for fn in sorted(os.listdir(wf_dir)):
        with open(os.path.join(wf_dir, fn), encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r"record_data_checked\.py\s+([A-Za-z0-9_.-]+)", text):
            found += 1
            assert m.group(1) in names, f"{fn} records {m.group(1)!r}, which has no window"
            # success() only: a failed run must not refresh the check date
            assert re.search(r"Record data check date\s*\n\s*if: success\(\)", text), fn
    assert found >= 7, f"expected the seven update workflows to record, found {found}"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", e)
    sys.exit(1 if fails else 0)
