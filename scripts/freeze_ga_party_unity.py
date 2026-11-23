#!/usr/bin/env python3
"""Freeze the outgoing GA biennium's party-unity scorecard into a static file.

Usage: python scripts/freeze_ga_party_unity.py <tag> [--overwrite] [--data-dir PATH] [--out-root PATH]
       e.g. python scripts/freeze_ga_party_unity.py 2025_26

Writes assets/data/ga-bienniums/<tag>/ga-party-unity.json: the live ga-party-unity.json
verbatim plus `metadata.frozen`, `frozenAt` and `frozenTag`. Same per-biennium tree
freeze_ga_biennium.py and freeze_ga_bills.py fill, with the live file's own name.

RUN IT BEFORE the lib/ga_sessions.py bump (docs/RECURRING-TASKS.md section 3, step 2d),
and after the last update-ga-votes run of the outgoing biennium. After the bump the live
file is the new biennium's and these scores survive nowhere on the site.

Scorecards are per biennium and are never averaged across bienniums (decision D10):
chamber, colleagues and votes differ, so the frozen file is a separate record.

Refuses, writing nothing, when: the live file's biennium is not <tag> (the bump already
happened, or the wrong tag); it has no members; a member id repeats; counts disagree
with the members list; or the destination exists with different members and --overwrite
was not given.
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN_ROOT = os.path.join("assets", "data", "ga-bienniums")
LIVE_NAME = "ga-party-unity.json"
TAG_RE = re.compile(r"^(\d{4})_(\d{2})$")


class FreezeScorecardError(Exception):
    pass


def tag_to_biennium(tag):
    """'2025_26' -> '2025-2026' (the form ga-party-unity.json's metadata.biennium uses)."""
    m = TAG_RE.match(tag or "")
    if not m:
        raise FreezeScorecardError(f"tag must look like 2025_26, got {tag!r}")
    start, yy = int(m.group(1)), int(m.group(2))
    end = start + 1
    if end % 100 != yy:
        raise FreezeScorecardError(f"tag {tag!r} is not two consecutive years")
    return f"{start}-{end}"


def check_live(doc, tag):
    meta = doc.get("metadata") or {}
    members = doc.get("members") or []
    want = tag_to_biennium(tag)
    if meta.get("biennium") != want:
        raise FreezeScorecardError(
            f"live file is biennium {meta.get('biennium')!r}, not {want!r}: "
            f"freeze BEFORE the lib/ga_sessions.py bump")
    if not members:
        raise FreezeScorecardError("live file has no members")
    ids = set()
    for m in members:
        mid = m.get("id")
        if not mid:
            raise FreezeScorecardError(f"member {m.get('name')!r} has no id")
        if mid in ids:
            raise FreezeScorecardError(f"member id {mid} appears twice")
        ids.add(mid)
    if meta.get("count") is not None and meta["count"] != len(members):
        raise FreezeScorecardError(f"metadata.count is {meta['count']}, file has {len(members)} members")
    scored = sum(1 for m in members if m.get("partyUnity") is not None)
    if meta.get("scoredForUnity") is not None and meta["scoredForUnity"] != scored:
        raise FreezeScorecardError(f"metadata.scoredForUnity is {meta['scoredForUnity']}, file has {scored}")


def build_frozen(doc, tag, now=None):
    out = dict(doc)
    meta = dict(doc["metadata"])
    meta["frozen"] = True
    meta["frozenTag"] = tag
    meta["frozenAt"] = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    out["metadata"] = meta
    return out


def freeze_party_unity(tag, data_dir, out_root, *, overwrite=False, now=None):
    """Returns ('written'|'unchanged', path). Raises FreezeScorecardError before any write."""
    with open(os.path.join(data_dir, LIVE_NAME), encoding="utf-8") as f:
        doc = json.load(f)
    check_live(doc, tag)
    dest = os.path.join(out_root, tag, LIVE_NAME)
    if os.path.exists(dest):
        with open(dest, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("members") == doc["members"]:
            return "unchanged", dest
        if not overwrite:
            raise FreezeScorecardError(f"{dest} exists and differs from the live file; "
                                       f"pass --overwrite to replace it")
    write_json_atomic(dest, build_frozen(doc, tag, now), separators=(",", ":"))
    return "written", dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tag")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "assets", "data"))
    ap.add_argument("--out-root", default=os.path.join(ROOT, FROZEN_ROOT))
    a = ap.parse_args(argv)
    try:
        state, path = freeze_party_unity(a.tag, a.data_dir, a.out_root, overwrite=a.overwrite)
    except (FreezeScorecardError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{state}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
