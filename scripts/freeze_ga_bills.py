#!/usr/bin/env python3
"""Freeze the outgoing GA biennium's bills into a static file nothing regenerates.

Usage: python scripts/freeze_ga_bills.py <tag> [--overwrite] [--data-dir PATH] [--out-root PATH]
       e.g. python scripts/freeze_ga_bills.py 2025_26

Writes assets/data/ga-bienniums/<tag>/ga-bills.json: the live ga-bills.json verbatim
(bills untouched, party tallies already baked in) plus `metadata.frozen`, `frozenAt`
and `frozenTag`. It is the same per-biennium tree freeze_ga_biennium.py fills, with
the live file's own name, so a frozen biennium needs only a different root on the client.

RUN IT BEFORE the lib/ga_sessions.py bump (docs/RECURRING-TASKS.md section 3, step 2b).
After the bump the live file is the new biennium and the old bills survive nowhere on
the site. Bill numbers restart each General Assembly (HB 943 in 2027 is a different
bill), which is why ga-bills.html qualifies anchors by session and finds a frozen bill
by legislationId.

Refuses, writing nothing, when: the live file's biennium is not <tag> (the bump already
happened, or the wrong tag); a bill carries a session the metadata does not list, or no
legislationId; legislationIds repeat; the per-session counts disagree with the bills;
or the destination exists with different bytes and --overwrite was not given.

Never run enrich_bills_with_party_votes.py on the result: it tallies with the LIVE
roster and would undercount departed members. The frozen file's tallies are the record.
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
LIVE_NAME = "ga-bills.json"
TAG_RE = re.compile(r"^(\d{4})_(\d{2})$")


class FreezeBillsError(Exception):
    pass


def tag_to_biennium(tag):
    """'2025_26' -> '2025-2026' (the form ga-bills.json's metadata.biennium uses)."""
    m = TAG_RE.match(tag or "")
    if not m:
        raise FreezeBillsError(f"tag must look like 2025_26, got {tag!r}")
    start, yy = int(m.group(1)), int(m.group(2))
    end = start + 1
    if end % 100 != yy:
        raise FreezeBillsError(f"tag {tag!r} is not two consecutive years")
    return f"{start}-{end}"


def check_live(doc, tag):
    """Raise FreezeBillsError unless `doc` is a complete, whole biennium `tag`."""
    meta = doc.get("metadata") or {}
    bills = doc.get("bills") or []
    want = tag_to_biennium(tag)
    if meta.get("biennium") != want:
        raise FreezeBillsError(
            f"live file is biennium {meta.get('biennium')!r}, not {want!r}: "
            f"freeze BEFORE the lib/ga_sessions.py bump")
    if not bills:
        raise FreezeBillsError("live file has no bills")
    listed = {s.get("id"): s.get("billCount") for s in (meta.get("sessions") or [])}
    seen, ids, counts = set(), set(), {}
    for b in bills:
        sess = b.get("session")
        if sess not in listed:
            raise FreezeBillsError(f"bill {b.get('identifier')!r} has session {sess!r}, "
                                   f"which metadata.sessions does not list")
        lid = b.get("legislationId")
        if lid in (None, ""):
            raise FreezeBillsError(f"bill {b.get('identifier')!r} ({sess}) has no legislationId")
        if lid in ids:
            raise FreezeBillsError(f"legislationId {lid} appears twice")
        ids.add(lid)
        key = (sess, b.get("identifier"))
        if key in seen:
            raise FreezeBillsError(f"{key[1]} appears twice in session {sess}")
        seen.add(key)
        counts[sess] = counts.get(sess, 0) + 1
    for sid, claimed in listed.items():
        if claimed is not None and counts.get(sid, 0) != claimed:
            raise FreezeBillsError(f"metadata claims {claimed} bills for {sid}, file has {counts.get(sid, 0)}")


def build_frozen(doc, tag, now=None):
    out = dict(doc)
    meta = dict(doc["metadata"])
    meta["frozen"] = True
    meta["frozenTag"] = tag
    meta["frozenAt"] = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    out["metadata"] = meta
    return out


def freeze_bills(tag, data_dir, out_root, *, overwrite=False, now=None):
    """Returns ('written'|'unchanged', path). Raises FreezeBillsError before any write."""
    with open(os.path.join(data_dir, LIVE_NAME), encoding="utf-8") as f:
        doc = json.load(f)
    check_live(doc, tag)
    dest = os.path.join(out_root, tag, LIVE_NAME)
    if os.path.exists(dest):
        with open(dest, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("bills") == doc["bills"]:
            return "unchanged", dest
        if not overwrite:
            raise FreezeBillsError(f"{dest} exists and differs from the live file; "
                                   f"pass --overwrite to replace it")
    frozen = build_frozen(doc, tag, now)
    write_json_atomic(dest, frozen, separators=(",", ":"))
    return "written", dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tag")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "assets", "data"))
    ap.add_argument("--out-root", default=os.path.join(ROOT, FROZEN_ROOT))
    a = ap.parse_args(argv)
    try:
        state, path = freeze_bills(a.tag, a.data_dir, a.out_root, overwrite=a.overwrite)
    except (FreezeBillsError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{state}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
