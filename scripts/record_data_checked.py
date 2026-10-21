#!/usr/bin/env python3
"""Record the day an update workflow last checked a dataset's source.

Several generators keep an unchanged ``generatedAt`` (or skip the commit when only that
moved) so a quiet week commits nothing. That is right for the repo and wrong for the
stale-stamp rule: a healthy dataset whose content simply has not changed would look
neglected. This writes ``_data/freshness/<dataset>.json`` = {"checkedAt": "YYYY-MM-DD"}
so assets/scripts/freshness.js (and data-freshness.html) can measure from the newer of
the stamp and the last check.

Date granularity on purpose: a daily date moves the file at most once a day, so the
workflows' tiny follow-up commit (scripts/commit_freshness.sh) is at most one per
dataset per day, and a re-run on the same day changes nothing.

Usage:  python scripts/record_data_checked.py <dataset> [<dataset> ...] [--date YYYY-MM-DD]

A dataset must have a ``window_days`` entry in _data/data_freshness.yml; names marked
``never`` or not listed are refused, so a typo cannot silently record into the void.
"""
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "_data", "data_freshness.yml")
OUT_DIR = os.path.join(ROOT, "_data", "freshness")


def windowed_datasets(table_path=TABLE):
    """Names with a window_days entry. A line-level read: the table is one flat map per
    line, and the workflows that call this install no PyYAML."""
    names = set()
    with open(table_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*\{(.*)\}", line)
            if m and "window_days" in m.group(2):
                names.add(m.group(1))
    return names


def record(dataset, day, out_dir=OUT_DIR, table_path=TABLE):
    """Write the check day. Returns True if the file changed."""
    if dataset not in windowed_datasets(table_path):
        raise SystemExit(f"error: {dataset!r} has no window_days entry in _data/data_freshness.yml")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise SystemExit(f"error: bad date {day!r} (want YYYY-MM-DD)")
    path = os.path.join(out_dir, dataset + ".json")
    try:
        import json
        with open(path, encoding="utf-8") as f:
            if json.load(f).get("checkedAt") == day:
                return False
    except (OSError, ValueError):
        pass
    os.makedirs(out_dir, exist_ok=True)
    write_json_atomic(path, {"checkedAt": day}, indent=2)
    return True


def main(argv):
    args = list(argv)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "--date" in args:
        i = args.index("--date")
        day = args[i + 1]
        del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    for name in args:
        changed = record(name, day)
        print(f"{name}: checkedAt {day}" + ("" if changed else " (unchanged)"))


if __name__ == "__main__":
    main(sys.argv[1:])
