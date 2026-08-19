#!/usr/bin/env python3
"""
Exit 0 if a staged JSON file differs from HEAD ONLY in the given keys.

Used by commit steps to avoid committing a near-full copy of a large data file
when the only thing that moved is a timestamp. ga-member-votes.json is ~15 MB
and update-ga-votes runs on a schedule; every run bumps metadata.generatedAt, so
without this guard the repo grew by a full revision each run even when no vote
changed (CODEBASE-REVIEW-2026-08-18.md finding 5.6).

Usage:
  python scripts/only_keys_changed.py <path> <dotted.key> [<dotted.key> ...]

Semantics (fail safe — when in doubt, treat it as a real change so nothing is
silently dropped):
  exit 0  -> the file and its HEAD version are equal once the named keys are
             blanked, i.e. ONLY those keys changed. The caller should skip the
             commit.
  exit 1  -> a material change (or the file is new, unreadable, or not JSON, or
             git has no HEAD version). The caller should commit.
"""
import json
import subprocess
import sys


def blank_keys(obj, dotted_keys):
    """Set each dotted key path to a constant sentinel, in place. Missing paths
    are ignored — a key that isn't there can't be the thing that changed."""
    for dotted in dotted_keys:
        parts = dotted.split('.')
        node = obj
        ok = True
        for p in parts[:-1]:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                ok = False
                break
        if ok and isinstance(node, dict):
            node[parts[-1]] = '__IGNORED__'
    return obj


def main():
    if len(sys.argv) < 3:
        sys.exit('Usage: only_keys_changed.py <path> <dotted.key> [...]')
    path = sys.argv[1]
    keys = sys.argv[2:]

    # HEAD version — absent for a brand-new file, which is always a real change.
    try:
        head_raw = subprocess.run(
            ['git', 'show', f'HEAD:{path}'],
            capture_output=True, check=True).stdout
        head = json.loads(head_raw)
        work = json.loads(open(path, 'rb').read())
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        sys.exit(1)  # material — commit it

    if blank_keys(head, keys) == blank_keys(work, keys):
        sys.exit(0)  # only the named keys moved — skip
    sys.exit(1)      # something real changed — commit


if __name__ == '__main__':
    main()
