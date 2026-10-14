#!/usr/bin/env python3
"""Georgia federal delegation sponsorship: paginated fetch + index/slice artifacts.

Two jobs, kept here rather than in generate_current_members_data.py so both are
testable without a live CONGRESS_API_KEY (the fetch half takes its fetcher as an
argument; the write half is a pure function of in-memory rows).

**Why this exists.** The members generator used to call
``/member/{bioguide}/sponsored-legislation?limit=20`` — ONE page — and only then
filter the 20 rows it got to the current Congress. Two bugs in one line:

  * it truncated at 20, so a prolific member's record was cut off, and
  * the endpoint is not ordered newest-Congress-first, so *which* of the 20
    survived the filter was effectively arbitrary. Measured against the
    committed file: Sen. Warnock showed 3 bills and Sen. Ossoff 14, from the
    same 20-row page size — Warnock has the larger career record of the two.

Cosponsorship was not fetched at all, which federally is the main alignment
signal: Georgia's delegation carries ~26k career cosponsorships against ~1.8k
sponsorships.

**Scope is deliberately the 16-member Georgia delegation.** Congress.gov has no
bulk per-Congress bill endpoint (the legis.ga.gov SOAP GetLegislationForSession
equivalent does not exist), so full-corpus federal parity with the GA panel would
mean ~16,600 detail fetches and ~20MB of churned JSON per refresh — straight into
the bandwidth and git-history ceilings CLAUDE.md flags. The delegation's own
record costs ~131 paginated requests against a documented 5,000/hour limit.

**Artifacts** mirror build_sponsorship_slices.py / build_member_votes_slices.py:

  assets/data/federal-sponsorship-index.json   provenance + a
                                               {bioguideId: [nPrimary, nCo]}
                                               count map.
  assets/data/federal-sponsorship/<bioguide>.json  one member's rows.

The full record does NOT go inline into current-members.json: that file is
fetched by federal-reps.html, find-my-reps.html, my-representatives.html and
every /us-congress/<slug>/ page, so ~27k sponsorship rows there would be paid for
by every visitor to read one member's panel. current-members.json keeps only the
20 most recent sponsored bills (``recentSponsored``, now a well-defined "most
recent" instead of an arbitrary 20 — the sibling ga-federal-legislators publish
documents and republishes it) plus a tiny ``sponsorship`` count object the entity
page reads to decide whether the tab appears, before any slice is fetched.
"""
from __future__ import annotations

import os
import time

from lib.atomic_io import write_json_atomic

#: Congress.gov bill type -> congress.gov/bill/<congress>th-congress/<slug>/<n>.
BILL_TYPE_SLUG = {
    'HR':      'house-bill',
    'S':       'senate-bill',
    'HRES':    'house-resolution',
    'SRES':    'senate-resolution',
    'HJRES':   'house-joint-resolution',
    'SJRES':   'senate-joint-resolution',
    'HCONRES': 'house-concurrent-resolution',
    'SCONRES': 'senate-concurrent-resolution',
}

#: Max the Congress.gov API accepts on a list endpoint. Using anything smaller
#: multiplies the request count for no benefit: the delegation's heaviest
#: cosponsor list (~6,400 career records) is 26 pages at 250 and 320 at 20.
PAGE_LIMIT = 250

#: Response envelope key and the record shape differ per endpoint.
KINDS = {
    'sponsored':   ('sponsored-legislation',   'sponsoredLegislation'),
    'cosponsored': ('cosponsored-legislation', 'cosponsoredLegislation'),
}


def bill_url(congress, bill_type, number):
    """Public congress.gov permalink for a bill. Derived, never stored per row."""
    slug = BILL_TYPE_SLUG.get(bill_type, str(bill_type or '').lower())
    return f"https://www.congress.gov/bill/{congress}th-congress/{slug}/{number}"


def normalize_bill(raw, congress):
    """One sponsorship record -> the fields the panel renders, or None if unusable.

    ``None`` (never '') for absent optional fields, per CLAUDE.md. A row missing
    type/number/title cannot be rendered or linked, so it is dropped rather than
    published as a blank line.
    """
    bill_type = (raw.get('type') or '').strip()
    number = str(raw.get('number') or '').strip()
    title = (raw.get('title') or '').strip()
    if not bill_type or not number or not title:
        return None
    action = raw.get('latestAction') or {}
    return {
        'type':           bill_type,
        'number':         number,
        'title':          title,
        'introducedDate': raw.get('introducedDate') or None,
        'actionDate':     action.get('actionDate') or None,
        'actionText':     action.get('text') or None,
        'policyArea':     (raw.get('policyArea') or {}).get('name') or None,
        'billUrl':        bill_url(congress, bill_type, number),
    }


def fetch_member_legislation(fetch, bioguide, kind, congress, *,
                             base_url="https://api.congress.gov/v3",
                             limit=PAGE_LIMIT, delay=0.0, log=print):
    """Every ``kind`` record for ``bioguide`` in ``congress``, or None on failure.

    ``fetch`` is injected (callable(url) -> parsed dict or None) so the caller owns
    the API key, the retry policy and the redaction, and so this is drivable from a
    fixture in a session with no key. ``fetch`` returning None is a hard failure
    (lib.http has already exhausted its 429/5xx retries, or hit a non-retryable
    4xx) — we return None rather than a short list, because a truncated list is
    indistinguishable from a real one once written and would publish as fact that
    a member sponsored less than they did.

    Pagination follows the ``pagination.next`` link the API supplies, exactly as
    get_current_members() does, with an offset fallback for the pages where it is
    absent. There is no congress= filter on these endpoints, so the whole career
    list is walked and filtered here; the career totals are what set the request
    count (~131 pages for the delegation).

    Early exit is deliberately NOT attempted on "we've passed the current
    Congress": ordering across Congresses is exactly the assumption the limit=20
    bug was built on, and it does not hold.
    """
    path, envelope = KINDS[kind]
    url = f"{base_url}/member/{bioguide}/{path}?limit={limit}&offset=0&format=json"
    rows, seen_pages, offset = [], 0, 0
    # A `next` link that repeats (or an offset fallback that fails to advance)
    # would page forever against a live API; the guard makes that a short-circuit
    # instead of a hung workflow.
    seen_urls = set()

    while url and url not in seen_urls:
        seen_urls.add(url)
        data = fetch(url)
        if data is None:
            log(f"  {bioguide} {kind}: fetch failed on page {seen_pages + 1} — "
                f"discarding partial list ({len(rows)} rows) rather than "
                f"publishing a truncated record")
            return None

        page = data.get(envelope)
        if isinstance(page, dict):          # {item: [...]} variant, as on /member
            page = page.get('item') or []
        if not isinstance(page, list):
            page = []

        for raw in page:
            if raw.get('congress') != congress:
                continue
            row = normalize_bill(raw, congress)
            if row:
                rows.append(row)

        seen_pages += 1
        # Tracked from what the API actually returned, not assumed to be
        # seen_pages * limit: the offset fallback below has to know the real
        # position after however many `next` links we followed.
        offset += len(page)
        pagination = data.get('pagination') or {}
        total = pagination.get('count')
        next_url = (pagination.get('next') or '').strip()
        if not next_url and len(page) == limit and (total is None or offset < total):
            # Some responses omit `next` on the last full page; step the offset
            # ourselves so a member whose count is an exact multiple of the page
            # size does not lose their final page. `count` is consulted first so
            # the common case costs no extra confirming request — without it, a
            # member whose record is an exact multiple of 250 pays one empty fetch.
            next_url = (f"{base_url}/member/{bioguide}/{path}"
                        f"?limit={limit}&offset={offset}&format=json")
        url = next_url or None
        if url and delay:
            time.sleep(delay)

    return rows


# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #
# Positions in a slice row. Rows are positional arrays, not objects, because the
# field names would otherwise repeat on every one of the delegation's thousands of
# cosponsorship records. Keep in step with the R_* constants in
# _includes/entity/federal-legislator.html.
#
#   [type, number, title, introducedDate, actionDate, actionIdx, policyIdx]
#
# actionIdx/policyIdx point into the slice's own intern tables: latest-action text
# ("Referred to the Subcommittee on Health.") and policy area ("Health") are long
# and recur across hundreds of a member's bills, so interning them per slice is
# free compression. billUrl is omitted and rebuilt client-side from congress +
# type + number — the same reasoning as legislationId in build_sponsorship_slices.py.
ROW_FIELDS = ('type', 'number', 'title', 'introducedDate', 'actionDate')


def compact_row(bill, actions, action_index, policies, policy_index):
    def intern(value, table, index):
        if not value:
            return -1
        if value not in index:
            index[value] = len(table)
            table.append(value)
        return index[value]

    return [bill.get(f) for f in ROW_FIELDS] + [
        intern(bill.get('actionText'), actions, action_index),
        intern(bill.get('policyArea'), policies, policy_index),
    ]


def _by_recency(bill):
    """Sort key: newest introduced first, bill identifier breaking the many ties.

    Returned as a value to be sorted DESCENDING on the date and ascending on the
    identifier, so the order is stable across refreshes instead of inheriting
    whatever order the API paged in — the ordering instability that made the old
    first-20-rows behaviour unreproducible in the first place.
    """
    return (bill.get('introducedDate') or '', bill.get('type') or '',
            int(bill.get('number') or 0))


def most_recent(bills, limit=20):
    """The ``limit`` most recently introduced bills, deterministically ordered."""
    return sorted(bills, key=_by_recency, reverse=True)[:limit]


def as_recent_sponsored(bill):
    """One normalized bill in the shape current-members.json has always published.

    The internal row is flat (actionDate/actionText) because that is what the
    slices encode; ``recentSponsored`` keeps the nested ``latestAction`` object,
    because Votega/ga-federal-legislators republishes this field and its README and
    JSON Schema document that shape. Changing it here would silently break every
    consumer of the sibling dataset for no gain on our side.
    """
    return {
        'type':           bill.get('type'),
        'number':         bill.get('number'),
        'title':          bill.get('title'),
        'introducedDate': bill.get('introducedDate'),
        'latestAction':   {'actionDate': bill.get('actionDate'),
                           'text':       bill.get('actionText')},
        'policyArea':     bill.get('policyArea'),
        'billUrl':        bill.get('billUrl'),
    }


def write_sponsorship_artifacts(data_dir, congress, records, *,
                                generated_at, source='Congress.gov API',
                                log=print):
    """Write the index + per-member slices. ``records`` is

        {bioguideId: {'name': str, 'primary': [bill], 'cosponsored': [bill]}}

    Members whose fetch failed must be left OUT by the caller: a member present
    here with empty lists is published as "sponsored nothing this Congress", which
    is a claim about the member, not about our pipeline.

    Returns a stats dict. Everything goes through lib.atomic_io, so an interrupted
    run leaves the previous artifacts intact rather than a truncated slice.
    """
    slices_dir = os.path.join(data_dir, 'federal-sponsorship')
    index_path = os.path.join(data_dir, 'federal-sponsorship-index.json')

    # Clear stale slices first, so a member who leaves the delegation does not keep
    # a dangling file that would render as a live sponsorship record.
    os.makedirs(slices_dir, exist_ok=True)
    for name in os.listdir(slices_dir):
        if name.endswith('.json'):
            os.remove(os.path.join(slices_dir, name))

    counts, sizes = {}, []
    total_primary = total_co = 0
    for bioguide, rec in sorted(records.items()):
        actions, action_index = [], {}
        policies, policy_index = [], {}
        out = {}
        for key, src in (('primary', rec.get('primary') or []),
                         ('cosponsored', rec.get('cosponsored') or [])):
            ordered = sorted(src, key=_by_recency, reverse=True)
            out[key] = [compact_row(b, actions, action_index, policies, policy_index)
                        for b in ordered]
        path = os.path.join(slices_dir, f"{bioguide}.json")
        write_json_atomic(path, {
            'bioguideId':  bioguide,
            'congress':    congress,
            'actions':     actions,
            'policyAreas': policies,
            'primary':     out['primary'],
            'cosponsored': out['cosponsored'],
        }, separators=(',', ':'))
        counts[bioguide] = [len(out['primary']), len(out['cosponsored'])]
        total_primary += len(out['primary'])
        total_co += len(out['cosponsored'])
        sizes.append(os.path.getsize(path))

    # The index is deliberately thin: the provenance the panel prints from this
    # dataset's OWN generatedAt (not the roster stamp at the foot of the page — see
    # CLAUDE.md on per-dataset provenance), and the counts that decide tab
    # visibility before any slice is fetched.
    write_json_atomic(index_path, {
        'metadata': {
            'generatedAt':      generated_at,
            'source':           source,
            'congress':         congress,
            'scope':            'Georgia congressional delegation',
            'memberCount':      len(counts),
            'totalSponsored':   total_primary,
            'totalCosponsored': total_co,
        },
        'members': counts,
    }, separators=(',', ':'))

    sizes.sort()
    stats = {
        'members': len(counts),
        'sponsored': total_primary,
        'cosponsored': total_co,
        'indexBytes': os.path.getsize(index_path),
        'medianSliceBytes': sizes[len(sizes) // 2] if sizes else 0,
        'maxSliceBytes': sizes[-1] if sizes else 0,
    }
    log(f"federal sponsorship: index {stats['indexBytes'] / 1024:.0f}KB, "
        f"{stats['members']} member slices (median "
        f"{stats['medianSliceBytes'] / 1024:.1f}KB, max "
        f"{stats['maxSliceBytes'] / 1024:.1f}KB) from {total_primary} sponsored "
        f"+ {total_co} cosponsored records in the {congress}th Congress.")
    return stats
