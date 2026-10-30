#!/usr/bin/env python3
"""The ballot name is what we SHOW; the legal name is what the URL is slugged from.

Candidates now display the name printed on their ballot ("Butch Parrish"), not
the qualifying name races.json used to carry ("Larry J Parrish"), so a voter
recognises them. But build_entity_pages.py slugs a candidate page from the
search record's title, and switching the title would have moved 66 live
candidate URLs days before an election.

So the two were separated: `title` is the ballot name, `slugName` pins the URL
to the name it was already slugged from, and the legal name also goes into
`desc` so searching it still finds the person. These pin that split, because
every part of it is silent when it breaks — a moved URL 404s for anyone holding
the old link, and a dropped legal name just stops matching in search.

Usage:
  python scripts/test_ballot_name_slugs.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_search_corpus as C  # noqa: E402
import build_entity_pages as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def record(**kw):
    recs, seen = [], set()
    C.add(recs, seen, category="Candidate", **kw)
    return recs[0] if recs else None


def permalink(rec, race_id="ga-house-158-2026"):
    """The permalink the real planner would give this record."""
    cid = B.qs_id(rec["url"])
    races = [{"id": race_id, "cycle": 2026, "chamber": "Georgia House of Representatives",
              "district": 158,
              "phases": {"general": {"ballots": {"Republican": [
                  {"id": cid, "name": rec["title"]}]}}}}]
    return B.plan_candidate_permalinks([rec], races).get(cid)


def cases():
    renamed = record(title="Butch Parrish", desc="Republican", url="candidate.html?id=ga-house-158-2026-r-1",
                     slug_name="Larry J Parrish")
    check("the record shows the ballot name", renamed["title"], "Butch Parrish")
    check("slugName carries the legal name", renamed.get("slugName"), "Larry J Parrish")
    check("the URL is slugged from the legal name, not the ballot name",
          permalink(renamed), "/candidates/larry-j-parrish-ga-house-158/")

    # The whole point: this URL is the one that already existed.
    unrenamed = record(title="Larry J Parrish", desc="Republican",
                       url="candidate.html?id=ga-house-158-2026-r-1")
    check("which is exactly the URL before the rename",
          permalink(unrenamed), permalink(renamed))

    # A candidate whose ballot name is already their only name must be untouched:
    # an unconditional slugName would be a no-op here but a liability later.
    plain = record(title="Melissa Stuckey", desc="Republican",
                   url="candidate.html?id=ga-house-70-2026-r-1")
    check("no slugName when there is nothing to pin", "slugName" in plain, False)
    check("and the slug comes from the displayed name",
          permalink(plain), "/candidates/melissa-stuckey-ga-house-158/")

    same = record(title="Jane Roe", desc="Democrat", url="candidate.html?id=x-1",
                  slug_name="Jane Roe")
    check("no slugName when the two names agree", "slugName" in same, False)

    # Search has to find the legal name, or renaming hides the person from
    # anyone who knows them by the name on the qualifying paperwork.
    from_builder = C.add
    recs, seen = [], set()
    from_builder(recs, seen, title="Butch Parrish",
                 desc="Republican — Georgia House of Representatives District 158 2026 — Larry J Parrish",
                 category="Candidate", url="candidate.html?id=ga-house-158-2026-r-1",
                 slug_name="Larry J Parrish")
    check("the legal name stays searchable through desc",
          "Larry J Parrish" in recs[0]["desc"], True)


if __name__ == "__main__":
    print("ballot name vs slug:")
    cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
