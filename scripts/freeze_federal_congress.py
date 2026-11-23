#!/usr/bin/env python3
"""Freeze a Congress's Georgia-delegation record on this site: assets/data/federal-congresses/<slug>/.

Usage: python scripts/freeze_federal_congress.py <slug> [--final] [--overwrite]
           [--data-dir PATH] [--out-root PATH]

`publish_federal_delegation.py freeze` keeps the record in the sibling repo; this keeps the
copy the PAGE BUILDER reads at deploy, so a member who does not return keeps their
`/us-congress/<slug>/` page after the next Congress is seated (rollover decision D12, option
B). The live files are replaced or deleted at the turnover, so run this BEFORE it (RECURRING-
TASKS.md section 3b): provisional any time, `--final` by 2 January 2027, after the last roster,
votes and sponsorship runs have committed.

What it writes (file names mirror the live files, so the page needs only a different root):
  freeze.json                      manifest, incl. `urls`: the page URL each member has (never changes)
  current-members.json             the Georgia delegation, as published
  federal-votes-index.json, federal-votes-keyvotes.json, federal-votes/<bioguideId>.json
  federal-sponsorship-index.json, federal-sponsorship/<bioguideId>.json
  federal-party-unity.json, curated-federal-bills.json

It reuses the publisher's refusal to file one Congress's data under another's name
(`assert_same_congress`): after 3 January the live files describe the 120th, so a late run of
`freeze_federal_congress.py 119th` exits before writing anything. All checks run before any write.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.federal_pages import (CURATED, FROZEN_ROOT, MANIFEST, MEMBERS, SPONSOR_DIR,  # noqa: E402
                               SPONSOR_INDEX, UNITY, VOTES_DIR, VOTES_INDEX, VOTES_KEYVOTES,
                               congress_slug_years, federal_permalink)
from publish_federal_delegation import SLUG_RE, assert_same_congress  # noqa: E402  (one implementation)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = ("provisional", "final")
SCHEMA_VERSION = 1


class FreezeError(Exception):
    pass


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise FreezeError(f"cannot read {path}: {e}")


def _meta(doc, key):
    return (doc.get("metadata") or {}).get(key) if isinstance(doc, dict) else None


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _congress_number(slug):
    return int("".join(ch for ch in slug if ch.isdigit()))


def plan(slug, data_dir):
    """Read and check everything; return what to write. Raises FreezeError or SystemExit
    (the publisher's same-Congress refusal) before anything is written."""
    if not SLUG_RE.match(slug):
        raise FreezeError(f"slug must look like '119th', got {slug!r}")
    path = lambda name: os.path.join(data_dir, name)  # noqa: E731
    roster = _load(path(MEMBERS))
    votes_index = _load(path(VOTES_INDEX))
    keyvotes = _load(path(VOTES_KEYVOTES))
    unity = _load(path(UNITY))
    sp_index = _load(path(SPONSOR_INDEX))
    curated = _load(path(CURATED))

    sources = {VOTES_INDEX: _meta(votes_index, "congress"), VOTES_KEYVOTES: _meta(keyvotes, "congress"),
               UNITY: _meta(unity, "congress"), SPONSOR_INDEX: _meta(sp_index, "congress")}
    # The roster carries its Congress only since the turnover guard; absent on an older file.
    if _meta(roster, "congress") is not None:
        sources[MEMBERS] = _meta(roster, "congress")
    assert_same_congress(slug, sources)  # exits, writing nothing, on a different Congress

    ga = [m for m in roster.get("members") or []
          if m.get("state") == "Georgia" and m.get("currentMember") is not False]
    if not ga:
        raise FreezeError("no sitting Georgia members in the roster: refusing to freeze an empty delegation")
    ids = sorted(m["bioguideId"] for m in ga)
    if len(set(ids)) != len(ids):
        raise FreezeError("duplicate bioguideId in the Georgia roster")
    in_index = set((sp_index.get("members") or {}))
    if set(ids) != in_index:
        raise FreezeError(f"sponsorship index and Georgia roster disagree: "
                          f"only in roster {sorted(set(ids) - in_index)}, only in index {sorted(in_index - set(ids))}")

    files = [(path(f"{VOTES_DIR}/{b}.json"), f"{VOTES_DIR}/{b}.json") for b in ids]
    files += [(path(f"{SPONSOR_DIR}/{b}.json"), f"{SPONSOR_DIR}/{b}.json") for b in ids]
    missing = [rel for src, rel in files if not os.path.isfile(src)]
    if missing:
        raise FreezeError(f"missing per-member slices (refusing to freeze a record without them): {missing}")
    for name in (VOTES_INDEX, VOTES_KEYVOTES, UNITY, SPONSOR_INDEX, CURATED):
        files.append((path(name), name))

    urls = {m["bioguideId"]: federal_permalink(m) for m in ga}
    dupes = sorted(u for u in set(urls.values()) if list(urls.values()).count(u) > 1)
    if dupes:
        raise FreezeError(f"two members would share a page URL: {dupes}")
    return {"roster": roster, "ga": ga, "ids": ids, "files": files, "urls": urls,
            "sources": {"members": _meta(roster, "generatedAt"), "votes": _meta(votes_index, "generatedAt"),
                        "scorecard": _meta(unity, "generatedAt"), "sponsorship": _meta(sp_index, "generatedAt")},
            "counts": {"members": len(ga), "votes": _meta(votes_index, "totalVotes"),
                       "sponsored": _meta(sp_index, "totalSponsored"),
                       "cosponsored": _meta(sp_index, "totalCosponsored")}}


def freeze(slug, data_dir, out_root, *, kind="provisional", overwrite=False, now=None):
    """Write out_root/<slug>/. Returns the manifest."""
    if kind not in KINDS:
        raise FreezeError(f"kind must be one of {KINDS}, got {kind!r}")
    p = plan(slug, data_dir)
    dest = os.path.join(out_root, slug)
    mpath = os.path.join(dest, MANIFEST)
    if os.path.isfile(mpath):
        existing = _load(mpath)
        if existing.get("kind") == "final" and not overwrite:
            raise FreezeError(f"{slug} already has a FINAL freeze; re-run with --overwrite to replace it deliberately")
        # A URL, once frozen, is a promise: replacing the freeze may not drop or move one.
        old, new = existing.get("urls") or {}, p["urls"]
        broken = sorted(b for b in old if new.get(b) != old[b])
        if broken and not overwrite:
            raise FreezeError(f"the new freeze would drop or change the page URL of {broken}; "
                              f"pass --overwrite only if that is intended")
    frozen_at = (now or datetime.now(timezone.utc)).isoformat()
    first, end = congress_slug_years(slug)
    manifest = {
        "congress": _congress_number(slug), "slug": slug, "kind": kind, "frozenAt": frozen_at,
        "congressYears": [first, end], "termEnds": f"{end}-01-03", "schemaVersion": SCHEMA_VERSION,
        "members": p["ids"], "urls": p["urls"], "sources": p["sources"], "counts": p["counts"],
        "note": "On-site copy for the page builder; the published record is sessions/"
                f"{slug}/ in Votega/ga-federal-legislators. `urls` is append-only in spirit: a URL "
                "listed here must keep resolving.",
    }
    roster = dict(p["roster"])
    roster["members"] = p["ga"]
    roster["metadata"] = dict(p["roster"].get("metadata") or {}, congress=manifest["congress"],
                              count=len(p["ga"]), freeze={"kind": kind, "frozenAt": frozen_at, "slug": slug})
    for src, rel in p["files"]:
        _copy(src, os.path.join(dest, rel))
    write_json_atomic(os.path.join(dest, MEMBERS), roster, separators=(",", ":"))
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
        print(f"freeze_federal_congress: {e}", file=sys.stderr)
        return 1
    print(f"froze {m['counts']['members']} members of the {a.slug} Congress ({m['kind']}) "
          f"under {os.path.join(a.out_root, a.slug)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
