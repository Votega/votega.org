"""Which GA roster members have a VoteGA entity page, and what its URL is.

`votegaUrl` on a roster record is the absolute URL of that member's page
(`https://www.votega.org/ga-legislators/deborah-silcox-house-53/`), or None when the member has no page. It
exists so an outside site (Georgia Commons) can link by `legisGaGovId` without parsing
our slugs. It is DERIVED, never hand-set.

Two files decide the answer, and this module mirrors both so the roster producer can
state it without running the page builder:
  * generate_search_corpus.build_ga_legislators -- who gets an entry (the page set is that
    index): an `ocd-person/` or `legis-` id, a voting chamber, not Resigned/Removed/Deceased.
  * build_entity_pages.build_ga_legislators -- the slug (name + chamber + district) and the
    collision rule (append the first 8 chars of the id's last segment).
scripts/test_ga_legislator_pages.py runs the real builder and fails if the two disagree.
"""
from __future__ import annotations

import re

from lib.ga_voters import VOTING_CHAMBERS

NO_PAGE_STATUSES = ("Resigned", "Removed", "Deceased")
SITE_URL = "https://www.votega.org"  # same as build_entity_pages.SITE_URL (test pins it)
PERMALINK = "/ga-legislators/{}/"


def slugify(*parts):
    """Same rule as build_entity_pages.slugify."""
    s = " ".join(str(p) for p in parts if p not in (None, ""))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)


def has_page(m):
    """True when the page builder will emit an entity page for this member."""
    mid = (m.get("id") or "").strip()
    return (mid.startswith(("ocd-person/", "legis-"))
            and m.get("chamber") in VOTING_CHAMBERS
            and m.get("status") not in NO_PAGE_STATUSES)


def base_slug(m):
    chamber = "senate" if "senate" in (m.get("chamber") or "").lower() else "house"
    return slugify(m.get("name") or "", chamber, m.get("district"))


def assign_votega_urls(members):
    """Set `votegaUrl` on every record, in roster order (the order the builder walks, so a
    slug collision resolves the same way). Returns the number of members with a page."""
    seen, n = set(), 0
    for m in members:
        if not has_page(m):
            m["votegaUrl"] = None
            continue
        slug = base_slug(m)
        if slug in seen:
            slug = slugify(slug, m["id"].split("/")[-1][:8])
        seen.add(slug)
        m["votegaUrl"] = SITE_URL + PERMALINK.format(slug)
        n += 1
    return n
