#!/usr/bin/env python3
"""Print `true` if the staged federal roster opens a new Congress over HEAD, else `false`.

Used by update-current-members.yml, between `git add` and `git commit`, to decide whether to
dispatch update-federal-votes.yml (see lib.federal_turnover.opened_congress). Reads the
committed copies with `git show HEAD:<path>` and the working copies from disk. Any problem
reading either side prints `false`: the dispatch is a convenience, and the weekly votes run
still covers the new members a week later.

Usage: python scripts/federal_turnover_committed.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.federal_turnover import opened_congress  # noqa: E402

ROSTER = "assets/data/current-members.json"
INDEX = "assets/data/federal-sponsorship-index.json"


def at_head(path):
    try:
        out = subprocess.run(["git", "show", f"HEAD:{path}"], check=True, capture_output=True).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def on_disk(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main():
    opened = opened_congress(at_head(ROSTER), at_head(INDEX), on_disk(ROSTER), on_disk(INDEX))
    print("true" if opened else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
