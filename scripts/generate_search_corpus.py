#!/usr/bin/env python3
"""Build a slim client-side search index of site *entities*.

The Jekyll-rendered ``assets/data/searchcorpus.json`` only knows about blog
posts and static HTML pages. The site's actual content -- legislators, races,
candidates, executives, justices -- lives in separately-generated JSON files
that Jekyll never sees, so none of it is searchable.

This script reads those already-generated data files and emits a compact
``assets/data/search-entities.json`` using the same record shape the search
widget expects (``title``, ``desc``, ``category``, ``url``). ``_includes/
search.html`` lazy-loads this file and merges it with the posts/pages corpus.

Scope note: this is a Georgia voter site, so the federal Congress file is
filtered to the Georgia delegation only. Everything indexed here points at a
detail page that already accepts the corresponding deep-link query param.

Run from the repo root (or anywhere -- paths are resolved relative to this
file). Exits non-zero on fatal errors so CI catches failures.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

# The two chambers of the General Assembly. Shared so the definition of "is a
# legislator" lives in one place -- ga-members.json also carries statewide
# executives, and every consumer has to exclude them the same way.
from lib.ga_voters import VOTING_CHAMBERS

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "assets" / "data"
JEKYLL_DATA_DIR = REPO_ROOT / "_data"
OUTPUT_PATH = DATA_DIR / "search-entities.json"

# Minimum record count below which we assume something went wrong and refuse
# to overwrite a good index with a broken one.
MIN_RECORDS = 200


def load(name, base=DATA_DIR):
    """Load a data file, returning None if it's missing (non-fatal)."""
    path = base / name
    if not path.exists():
        print(f"  ! {name} not found -- skipping", file=sys.stderr)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def clean(value):
    """Collapse a value to a trimmed string, or '' for None/blank."""
    if value is None:
        return ""
    return str(value).strip()


def add(records, seen, title, desc, category, url):
    """Append a record, skipping blanks and duplicate title+url pairs.

    Deduping on (title, url) rather than url alone lets several people share a
    single overview page (e.g. the GA executives all point at
    ga-executive.html) while still collapsing the same candidate listed in both
    the primary and general phase of one race.
    """
    title = clean(title)
    url = clean(url)
    if not title or not url:
        return
    key = (title, url)
    if key in seen:
        return
    seen.add(key)
    records.append(
        {
            "title": title,
            "desc": clean(desc),
            "category": category,
            "url": url,
        }
    )


def build_ga_legislators(records, seen):
    data = load("ga-members.json")
    if not data:
        return
    for m in data.get("members", []):
        oid = clean(m.get("id"))
        if not oid or not oid.startswith("ocd-person/"):
            # Synthetic/vacant IDs have no detail page to link to.
            continue
        if m.get("status") in ("Resigned", "Removed", "Deceased"):
            # Same filter as ga.js and ga-majority-tracker.html -- don't index
            # former members as if they were sitting legislators.
            continue
        chamber = clean(m.get("chamber"))
        if chamber not in VOTING_CHAMBERS:
            # ga-members.json also carries the four statewide executives under a
            # fifth chamber, "executive" (Governor, Lt. Governor, AG, SoS). They
            # have no ga-member.html page worth linking, they are already indexed
            # from ga-executive.json under "GA Executive", and their `title` is a
            # raw enum -- Burt Jones surfaced in search as a "GA Legislator"
            # described as "Lt_Governor". ga.js and ga-majority-tracker.html
            # filter on the exact chamber string, so only this index leaked them.
            # See CODEBASE-REVIEW-2026-08-18.md finding 3.2.
            continue
        district = m.get("district")
        title_word = clean(m.get("title")) or (
            "Senator" if chamber == "Senate" else "Representative"
        )
        party = clean(m.get("party"))
        bits = [b for b in [title_word] if b]
        if district is not None:
            bits.append(f"District {district}")
        if party:
            bits.append(party)
        add(
            records,
            seen,
            title=m.get("name"),
            desc=", ".join(bits),
            category="GA Legislator",
            url=f"ga-member.html?id={quote(oid, safe='')}",
        )


def build_ga_federal_delegation(records, seen):
    data = load("current-members.json")
    if not data:
        return
    for m in data.get("members", []):
        if clean(m.get("state")) != "Georgia":
            continue  # GA voter site: index only the Georgia delegation.
        bid = clean(m.get("bioguideId"))
        if not bid:
            continue
        terms = ((m.get("terms") or {}).get("item")) or []
        chamber = clean(terms[-1].get("chamber")) if terms else ""
        party = clean(m.get("partyName"))
        district = m.get("district")
        bits = []
        if chamber:
            bits.append(chamber)
        if district is not None and "House" in chamber:
            bits.append(f"District {district}")
        if party:
            bits.append(party)
        add(
            records,
            seen,
            title=m.get("name"),
            desc=", ".join(bits),
            category="U.S. Congress",
            url=f"member.html?bioguideId={quote(bid, safe='')}",
        )


def build_races_and_candidates(records, seen):
    data = load("races.json")
    if not data:
        return

    # Name lookups so incumbent candidates (referenced by member id, no name
    # of their own) resolve to a human-readable name -- mirroring race.html.
    fed = load("current-members.json") or {}
    ga = load("ga-members.json") or {}
    by_bioguide = {
        clean(m.get("bioguideId")): clean(m.get("name"))
        for m in fed.get("members", [])
        if m.get("bioguideId")
    }
    by_ocd = {
        clean(m.get("id")): clean(m.get("name"))
        for m in ga.get("members", [])
        if m.get("id")
    }

    def resolve_name(cand):
        name = clean(cand.get("name"))
        if name:
            return name
        mid = clean(cand.get("existingMemberId") or cand.get("memberId"))
        src = clean(cand.get("existingMemberSource") or cand.get("memberSource"))
        if src == "congress":
            return by_bioguide.get(mid, "")
        return by_ocd.get(mid, "")

    for race in data.get("races", []):
        rid = clean(race.get("id"))
        if not rid:
            continue
        chamber = clean(race.get("chamber"))
        district = race.get("district")
        title = clean(race.get("displayTitle"))
        if not title:
            title = chamber or "Race"
            if district is not None:
                title += f" District {district}"
            title += f" {race.get('cycle', '')}".rstrip()
        add(
            records,
            seen,
            title=title,
            desc=clean(race.get("level")).title(),
            category="Race",
            url=f"race.html?id={quote(rid, safe='')}",
        )

        for phase in (race.get("phases") or {}).values():
            for party, ballot in (phase.get("ballots") or {}).items():
                for cand in ballot:
                    if cand.get("withdrawn") or cand.get("disqualified"):
                        continue
                    name = resolve_name(cand)
                    if not name:
                        continue
                    cid = clean(cand.get("id"))
                    if cid:
                        url = f"candidate.html?id={quote(cid, safe='')}"
                    else:
                        mid = clean(
                            cand.get("existingMemberId") or cand.get("memberId")
                        )
                        src = clean(
                            cand.get("existingMemberSource")
                            or cand.get("memberSource")
                        )
                        if not mid:
                            continue
                        url = (
                            f"candidate.html?raceId={quote(rid, safe='')}"
                            f"&memberId={quote(mid, safe='')}"
                            f"&memberSource={quote(src, safe='')}"
                        )
                    desc_bits = [b for b in [clean(cand.get("party")) or party, title] if b]
                    add(
                        records,
                        seen,
                        title=name,
                        desc=" — ".join(desc_bits),
                        category="Candidate",
                        url=url,
                    )


def build_ga_executive(records, seen):
    data = load("ga-executive.json")
    if not data:
        return
    for o in data.get("officials", []):
        # GA executive officials have null ids and no per-person detail page;
        # link to the executive overview page.
        add(
            records,
            seen,
            title=o.get("name"),
            desc=clean(o.get("title")) or clean(o.get("office")) or "GA Executive Branch",
            category="GA Executive",
            url="ga-executive.html",
        )


def build_federal_executive(records, seen):
    # Source of truth lives in _data/ (Jekyll build-time data); the served
    # assets/data/executive.json is a generated passthrough, not raw JSON.
    data = load("executive.json", base=JEKYLL_DATA_DIR)
    if not data:
        return
    for o in data.get("officials", []):
        oid = clean(o.get("id"))
        url = f"executive-member.html?id={quote(oid, safe='')}" if oid else "executive-branch.html"
        add(
            records,
            seen,
            title=o.get("name"),
            desc=clean(o.get("role")) or clean(o.get("title")) or "Federal Executive Branch",
            category="Federal Executive",
            url=url,
        )


def build_scotus(records, seen):
    data = load("supreme-court.json")
    if not data:
        return
    for j in data.get("justices", []):
        jid = clean(j.get("id"))
        url = f"justice.html?id={quote(jid, safe='')}" if jid else "supreme-court.html"
        add(
            records,
            seen,
            title=j.get("name"),
            desc=clean(j.get("title")) or "U.S. Supreme Court",
            category="U.S. Supreme Court",
            url=url,
        )


def main():
    records = []
    seen = set()

    print("Building search entity index...")
    build_ga_legislators(records, seen)
    build_ga_federal_delegation(records, seen)
    build_races_and_candidates(records, seen)
    build_ga_executive(records, seen)
    build_federal_executive(records, seen)
    build_scotus(records, seen)

    # Tally by category for the run log / sanity check.
    by_cat = {}
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat}: {n}")
    print(f"  TOTAL: {len(records)}")

    if len(records) < MIN_RECORDS:
        print(
            f"FATAL: only {len(records)} records (expected >= {MIN_RECORDS}); "
            "refusing to write a likely-broken index.",
            file=sys.stderr,
        )
        sys.exit(1)

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "votega.org entity data files",
            "count": len(records),
            "categories": by_cat,
        },
        "records": records,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=1)
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
