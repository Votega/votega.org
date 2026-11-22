#!/usr/bin/env python3
"""Gate the freeze-ga-roster workflow: refuse to publish a roster that is not whole.

The freeze writes the outgoing General Assembly into
Votega/ga-legislators sessions/<slug>/ and cannot be repeated -- once the incoming
class is seated the source roster is gone (RECURRING-TASKS.md section 3). Until now the
workflow ran `publish_ga_legislators.py freeze-roster` with no check at all, so a
short, doubled or mislabelled roster would have been archived as the permanent record.

This runs BEFORE the publish step and exits 1 with `::error` annotations on any
failure. It reuses validate_ga_members.tier1 (the checks update-ga-members already
gates on: metadata.count, required fields, duplicate districts, a chamber over its
size) and adds what only a freeze can demand:

  * EXACTLY 56 Senate and 180 House seats accounted for. The daily validator lets a
    chamber sit below full strength (a vacancy is a fact worth publishing); a frozen
    record has to be complete, so every seat is held by one current member or a Vacant
    placeholder. Resigned/Removed/Deceased are departed people, kept as extra records
    (the 2026-11-21 roster had 247 for 236 seats) and never count toward a seat.
    Suspended members still hold the seat, and Vacant placeholders stand in for one.
  * Every district 1..N present, so 56 seats cannot be 55 districts plus a duplicate.
  * The roster describes the biennium being frozen (metadata.session vs the slug), so
    a run after the rollover cannot file the 2027-28 class under 2025-2026.

Usage:
    python scripts/validate_ga_roster_freeze.py [session-slug]
        [--members assets/data/ga-members.json]

Blank slug means the current biennium, exactly as the publisher resolves it.
Exit codes: 0 whole, 1 refuse to freeze.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_members as V  # noqa: E402
from lib.ga_sessions import BIENNIUM  # noqa: E402

DEFAULT_MEMBERS = "assets/data/ga-members.json"


def session_tag(slug):
    """'2025-2026' -> '2025_26' (the form metadata.session uses); None if not a biennium."""
    m = re.fullmatch(r"(\d{4})-(\d{4})", slug or "")
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        return None
    return f"{m.group(1)}_{m.group(2)[2:]}"


def check(doc, slug=None):
    """Every reason this roster must not be frozen. Empty list means safe to freeze."""
    errors = list(V.tier1(doc))
    members = doc.get("members") or []
    if not members:
        return errors

    for chamber, size in V.CHAMBER_MAX.items():
        here = V.seated(members, chamber)
        if len(here) != size:
            errors.append(f"{chamber}: {len(here)} seats accounted for, a freeze needs "
                          f"exactly {size} (one current member or Vacant placeholder "
                          f"per seat; Resigned/Removed/Deceased do not count)")
        held = {m.get("district") for m in here}
        gaps = [n for n in range(1, size + 1) if n not in held]
        if gaps:
            errors.append(f"{chamber}: no entry for district(s) "
                          f"{', '.join(map(str, gaps[:12]))}{' ...' if len(gaps) > 12 else ''}")
        stray = sorted((d for d in held if d is not None and d not in range(1, size + 1)),
                       key=str)
        if stray:
            errors.append(f"{chamber}: district(s) outside 1-{size}: {stray}")

    want = session_tag(slug or BIENNIUM)
    have = (doc.get("metadata") or {}).get("session")
    if want and have != want:
        errors.append(f"metadata.session is {have!r} but the freeze slug "
                      f"{slug or BIENNIUM!r} is {want!r} -- the live roster is not "
                      f"the one being frozen")
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?", default="")
    ap.add_argument("--members", default=DEFAULT_MEMBERS)
    args = ap.parse_args(argv)

    try:
        with open(args.members, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::freeze refused: cannot read {args.members}: {exc}")
        return 1

    errors = check(doc, args.slug or None)
    if errors:
        for e in errors:
            print(f"::error::freeze refused: {e}")
        print("Nothing was published. Fix the roster (or the slug) and re-run; the "
              "freeze is only safe while ga-members.json still holds the outgoing class.")
        return 1
    n = len(doc["members"])
    print(f"Roster whole: {n} records, 56 Senate + 180 House seats accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
