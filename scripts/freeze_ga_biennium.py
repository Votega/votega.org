#!/usr/bin/env python3
"""Freeze a GA biennium's per-member data and record it in the legislator ledger.

Usage: python scripts/freeze_ga_biennium.py <tag> (--members GID,GID | --departed | --all)
           [--overwrite] [--no-votes-ok GID,...]

--departed: roster members whose status is in DEPARTED_STATUSES.
--all: every voting-chamber member with a legisGaGovId (also copies curated key votes).
Writes nothing at all if freeze() raises; the ledger is saved once, at the end.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.ga_biennium_freeze import FROZEN_ROOT, FreezeError, freeze  # noqa: E402
from lib.ga_ledger import LedgerError, add_biennium, load_ledger, save_ledger  # noqa: E402
from lib.ga_legislator_pages import DEPARTED_STATUSES  # noqa: E402
from lib.ga_voters import VOTING_CHAMBERS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _split(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tag")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--members")
    g.add_argument("--departed", action="store_true")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--no-votes-ok", default="")
    a = ap.parse_args(argv)

    data_dir = os.path.join(ROOT, "assets", "data")
    out_root = os.path.join(ROOT, FROZEN_ROOT)
    with open(os.path.join(data_dir, "ga-members.json"), encoding="utf-8") as f:
        members = json.load(f)["members"]
    if a.members:
        gids = _split(a.members)
    elif a.departed:
        gids = [str(m["legisGaGovId"]) for m in members
                if m.get("legisGaGovId") is not None and m.get("status") in DEPARTED_STATUSES]
    else:
        gids = [str(m["legisGaGovId"]) for m in members
                if m.get("legisGaGovId") is not None and m.get("chamber") in VOTING_CHAMBERS]

    ledger_path = os.path.join(data_dir, "ga-legislator-ledger.json")
    try:
        ledger = load_ledger(ledger_path)
        # Fail on a ledger gap before freeze writes anything.
        absent = [g for g in gids if g not in ledger["people"]]
        if absent:
            raise LedgerError(f"no ledger entry for legisGaGovId: {', '.join(absent)}")
        report = freeze(a.tag, gids, data_dir, out_root, overwrite=a.overwrite,
                        no_votes_ok=_split(a.no_votes_ok), include_curated=a.all)
        for gid in gids:
            add_biennium(ledger, gid, a.tag)
        save_ledger(ledger, ledger_path)
    except (FreezeError, LedgerError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
