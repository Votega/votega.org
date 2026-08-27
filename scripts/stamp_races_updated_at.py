#!/usr/bin/env python3
"""Keep assets/data/races.json's `updatedAt` honest.

races.json is edited by many hands and scripts (build_legislative_races.py, the
set_general_* / update_general_* helpers, apply_overrides.py, the race-candidate
editor tool, and plain manual edits). Most bump `updatedAt`, some don't — so the
field silently drifts older than the data it stamps. That field is not cosmetic:
it drives the "Data last updated" stamp on race.html / elections.html /
candidate.html and the "Last updated" line in the published RACES.md, so a stale
value makes the site under-report freshness (drifted 3 days before this script
existed — see the CD-13 profile-reconcile edit, commit 9e7605b).

This reconciles `updatedAt` against a BASE revision of the file: if the content
changed (anything but `updatedAt` itself) and `updatedAt` did not advance past
the base's value, the stamp is stale.

Modes:
  --check            Report only; exit 1 if stale. A CI guard / pre-push check.
  (default = fix)    Rewrite `updatedAt` in place to --time (default: now, UTC).

Options:
  --base <ref>       Git revision to compare against (default: HEAD). In CI on a
                     push, pass the pre-push SHA so the whole pushed range is
                     judged as one change.
  --time <iso>       Value to stamp in fix mode (default: current UTC time in the
                     same YYYY-MM-DDTHH:MM:SSZ shape the writers use).

The rewrite is a targeted string replacement of the timestamp only, so the
file's byte formatting (CRLF, 2-space indent, key order) is preserved and the
diff is a single line. A fix run changes only `updatedAt`, which is not itself a
content change, so re-running is a no-op — the workflow can't loop.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

RACES_PATH = "assets/data/races.json"
# Matches the one `updatedAt` string value; group 1 is everything up to and
# including the opening quote, group 2 the closing quote.
_STAMP_RE = re.compile(r'("updatedAt"\s*:\s*")[^"]*(")')


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_without_stamp(text):
    """Parse the file and drop `updatedAt` so two revisions can be compared on
    content alone. Returns None if the text isn't valid JSON (e.g. a deleted or
    half-written base)."""
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(doc, dict):
        doc = dict(doc)
        doc.pop("updatedAt", None)
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def _stamp_of(text):
    try:
        return json.loads(text).get("updatedAt")
    except (ValueError, TypeError):
        return None


def _read_working():
    with open(RACES_PATH, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _read_base(ref):
    try:
        return subprocess.check_output(
            ["git", "show", f"{ref}:{RACES_PATH}"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
    except subprocess.CalledProcessError:
        return None  # base doesn't exist (new file / unknown ref) — nothing to compare


def is_stale(working_text, base_text):
    """True when content changed vs base but `updatedAt` did not advance."""
    if base_text is None:
        return False
    base_content = _content_without_stamp(base_text)
    work_content = _content_without_stamp(working_text)
    if base_content is None or work_content is None:
        return False
    if base_content == work_content:
        return False  # only the stamp (or nothing) changed — fine
    return _stamp_of(working_text) == _stamp_of(base_text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="HEAD", help="revision to compare against (default: HEAD)")
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if stale")
    ap.add_argument("--time", default=None, help="ISO stamp to write in fix mode (default: now)")
    args = ap.parse_args(argv)

    working = _read_working()
    base = _read_base(args.base)

    if not is_stale(working, base):
        print(f"races.json updatedAt is current ({_stamp_of(working)}); nothing to do.")
        return 0

    old = _stamp_of(working)
    if args.check:
        print(f"::error::races.json content changed but updatedAt was not bumped "
              f"(still {old}). Run: python scripts/stamp_races_updated_at.py", file=sys.stderr)
        return 1

    new = args.time or _now_iso()
    updated, n = _STAMP_RE.subn(lambda m: m.group(1) + new + m.group(2), working, count=1)
    if n != 1:
        print("::error::could not locate a single updatedAt field to rewrite", file=sys.stderr)
        return 2
    with open(RACES_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    print(f"races.json updatedAt bumped {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
