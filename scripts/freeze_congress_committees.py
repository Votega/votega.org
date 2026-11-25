#!/usr/bin/env python3
"""Save a Congress's committee rosters: assets/data/federal-congresses/<slug>/committees/.

Usage: python scripts/freeze_congress_committees.py <slug> [--final] [--overwrite]
           [--data-dir PATH] [--out-root PATH]

unitedstates/congress-legislators replaces its membership files in place when committees are
reorganized for a new Congress, and current-members.json keeps only full-committee names. This
keeps the whole record -- roles, rank, subcommittees -- for every committee, nationwide. Run it
BEFORE 3 January of the turnover year, next to freeze_federal_congress.py: provisional any time,
`--final` by 2 January.

What it writes:
  committee-membership.json, committees.json   the upstream YAML as JSON, nothing dropped (CC0)
  members.json       {bioguideId: name, party, state, district, chamber} for everyone listed;
                     upstream's own `party` is majority/minority, and the live roster is replaced
  freeze-committees.json   manifest, with sources, hashes, upstream dates and counts

The upstream files do not name their Congress. So <slug> must be the Congress seated today AND
the one the live roster describes; a late run exits before writing. All checks run before any write.

It reads the YAML on upstream's main branch, at one commit, as the daily roster does. The JSON mirror
at unitedstates.github.io was two months behind it in November 2026 (it lacked two sitting members).
Needs PyYAML.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.congress_session import congress_for_date, congress_ordinal  # noqa: E402
from lib.federal_pages import FROZEN_ROOT, MEMBERS  # noqa: E402
from lib.http import fetch_bytes, fetch_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = "https://raw.githubusercontent.com/unitedstates/congress-legislators/"
API = "https://api.github.com/repos/unitedstates/congress-legislators/commits"
HEAD = API + "?per_page=1&sha=main"
LAST_CHANGE = API + "?per_page=1&sha=main&path=committee-membership-current.yaml"
SOURCES = {"committee-membership.json": "committee-membership-current.yaml",
           "committees.json": "committees-current.yaml"}
MANIFEST = "freeze-committees.json"
SUBDIR = "committees"
MIN_COMMITTEES = 30      # 49 in November 2026; a partial file has far fewer
MAX_UNMATCHED = 10       # people upstream still lists after they left the live roster
MIN_KEEP = 0.9           # a re-freeze may not lose more than a tenth of the last one


class FreezeError(Exception):
    pass


def parse_yaml(text):
    import yaml  # lazily: the offline test job installs no packages
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(str(e))


def _parse(raw, label, parse):
    try:
        return parse(raw.decode("utf-8"))
    except ValueError as e:
        raise FreezeError(f"{label}: cannot be parsed ({e})")


def check_congress(slug, roster, now):
    seated = congress_ordinal(congress_for_date(now.date()))
    if slug != seated:
        raise FreezeError(f"{slug} is not the Congress seated on {now.date()} ({seated})")
    live = (roster.get("metadata") or {}).get("congress")
    if not isinstance(live, int) or congress_ordinal(live) != slug:
        raise FreezeError(f"the live roster describes Congress {live!r}, not {slug}")


def member_record(m):
    terms = (m.get("terms") or {}).get("item") or []
    return {"name": m.get("name"), "party": m.get("partyName"), "state": m.get("state"),
            "district": m.get("district"), "chamber": terms[-1].get("chamber") if terms else None}


def plan(membership, committees, roster):
    """Check the upstream files against each other and the roster; return (members, counts)."""
    if not isinstance(membership, dict) or not isinstance(committees, list):
        raise FreezeError("the upstream files are not in the expected shape")
    full, subs = set(), set()
    for c in committees:
        full.add(c["thomas_id"])
        subs |= {c["thomas_id"] + s["thomas_id"] for s in c.get("subcommittees") or []}
    if len(full) < MIN_COMMITTEES:
        raise FreezeError(f"only {len(full)} committees (expected at least {MIN_COMMITTEES})")
    empty = sorted(c for c in full if not membership.get(c))
    if empty:
        raise FreezeError(f"full committees with no members: {empty}")
    orphans = sorted(set(membership) - full - subs)
    if orphans:
        raise FreezeError(f"membership for committees not in the committee list: {orphans}")
    by_id = {m["bioguideId"]: m for m in roster.get("members") or [] if m.get("bioguideId")}
    names = {m["bioguide"]: m.get("name") for ms in membership.values() for m in ms}
    ids = sorted(names)
    missing = [b for b in ids if b not in by_id]
    # The roster's committees came from these same files: a copy without someone it has is older.
    stale = sorted(b for b, m in by_id.items() if m.get("committees") and b not in names)
    if stale:
        raise FreezeError(f"the live roster lists committees for members these files lack: {stale}")
    # Upstream lags the roster, so someone who just resigned is expected; many is a wrong file.
    if len(missing) > MAX_UNMATCHED:
        raise FreezeError(f"{len(missing)} committee members not in the live roster: {missing}")
    counts = {"committees": len(full), "subcommittees": len(subs), "members": len(ids),
              "assignments": sum(len(ms) for ms in membership.values()),
              "notInLiveRoster": missing,
              "subcommitteesWithNoMembersListed": sorted(s for s in subs if not membership.get(s))}
    return {b: member_record(by_id[b] if b in by_id else {"name": names[b]}) for b in ids}, counts


def freeze(slug, data_dir, out_root, *, kind="provisional", overwrite=False, now=None,
           fetch=fetch_bytes, fetch_meta=fetch_json, parse=parse_yaml):
    """Write out_root/<slug>/committees/. Returns the manifest."""
    now = now or datetime.now(timezone.utc)
    try:
        with open(os.path.join(data_dir, MEMBERS), encoding="utf-8") as f:
            roster = json.load(f)
    except (OSError, ValueError) as e:
        raise FreezeError(f"cannot read the live roster: {e}")
    check_congress(slug, roster, now)
    dest = os.path.join(out_root, slug, SUBDIR)
    mpath = os.path.join(dest, MANIFEST)
    previous = None
    if os.path.isfile(mpath):
        with open(mpath, encoding="utf-8") as f:
            previous = json.load(f)
        if previous.get("kind") == "final" and not overwrite:
            raise FreezeError(f"{slug} already has a FINAL committee freeze; "
                              "--overwrite replaces it deliberately")

    # One commit for both files, so they cannot describe two moments.
    try:
        sha = fetch_meta(HEAD)[0]["sha"]
    except (TypeError, KeyError, IndexError):
        raise FreezeError("could not read upstream's current commit")
    raws, parsed, urls = {}, {}, {}
    for name, remote in SOURCES.items():
        urls[name] = f"{RAW}{sha}/{remote}"
        raws[name] = fetch(urls[name])
        if raws[name] is None:
            raise FreezeError(f"could not fetch {urls[name]}")
        parsed[name] = _parse(raws[name], remote, parse)
    members, counts = plan(parsed["committee-membership.json"], parsed["committees.json"], roster)
    if previous and not overwrite:
        lost = [k for k in ("committees", "subcommittees", "members", "assignments")
                if counts[k] < MIN_KEEP * previous["counts"][k]]
        if lost:
            raise FreezeError(f"far fewer {', '.join(lost)} than the last freeze: "
                              f"{counts} vs {previous['counts']}")

    # Best effort: how fresh upstream's membership was. Never blocks the freeze.
    try:
        upstream = fetch_meta(LAST_CHANGE)[0]
        upstream = {"commit": upstream["sha"], "committedAt": upstream["commit"]["committer"]["date"]}
    except (TypeError, KeyError, IndexError):
        upstream = None
    manifest = {
        "congress": int("".join(ch for ch in slug if ch.isdigit())), "slug": slug, "kind": kind,
        "frozenAt": now.isoformat(), "schemaVersion": 1, "license": "CC0-1.0",
        "sources": {n: {"url": urls[n], "sha256": hashlib.sha256(raws[n]).hexdigest()} for n in SOURCES},
        "membershipLastUpdated": upstream,
        "rosterGeneratedAt": (roster.get("metadata") or {}).get("generatedAt"),
        "counts": counts,
        "note": "Upstream lags reorganizations. `party` in committee-membership.json is "
                "majority/minority; a person's own party and state are in members.json.",
    }
    for name, doc in parsed.items():
        write_json_atomic(os.path.join(dest, name), doc, separators=(",", ":"))
    write_json_atomic(os.path.join(dest, "members.json"), members, separators=(",", ":"))
    write_json_atomic(mpath, manifest, indent=2)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug", help="e.g. 119th")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "assets", "data"))
    ap.add_argument("--out-root", default=os.path.join(ROOT, FROZEN_ROOT))
    a = ap.parse_args(argv)
    try:
        m = freeze(a.slug, a.data_dir, a.out_root, kind="final" if a.final else "provisional",
                   overwrite=a.overwrite)
    except FreezeError as e:
        print(f"freeze_congress_committees: {e}", file=sys.stderr)
        return 1
    print(f"froze {m['slug']} committees ({m['kind']}): {m['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
