#!/usr/bin/env python3
"""Invariants for the per-topic citation counts in lib.meeting_topics.flag_entry().

The /local/ hub cards RANK a place's topics by these counts instead of listing
every topic present, because presence does not discriminate: local-taxes was on
56 of 59 flagged places and land-use-or-data-center on 56, so two of the three
pills a card showed were on nearly every card.

What is pinned here:
  1. Every pill-bearing topic has a count, so a card can rank them.
  2. A count is the number of distinct citing meetings and is NOT clipped by the
     20-item slice on the `*Items` lists.
  3. A sidecar written before the counts existed still reads (capped fallback).
  4. millage-budget gets a count for consistency but is NOT comparable with the
     narrow subjects — 'budget' and 'fiscal year' are in its lexicon, so it
     outscores them nearly everywhere. The card must not rank on it.

Stdlib only: CI installs no pip packages.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import (  # noqa: E402
    MILLAGE_TERMS, TOPIC_RULES, build_summary, flag_entry)

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def meeting(i, topics, terms, flags):
    return {
        'date': '2026-%02d-%02d' % ((i % 12) + 1, (i % 28) + 1),
        'title': 'Meeting %d' % i,
        'sourceUrl': 'https://example.gov/m/%d' % i,
        'flags': flags, 'topics': topics, 'matchedTerms': terms,
        'dataCenterItems': [],
    }


# ---------------------------------------------------------------------------
print("Every pill-bearing topic carries a count")

entry = flag_entry(build_summary([
    meeting(0, {'rezoning': 1}, ['rezoning'], ['land-use']),
    meeting(1, {'data-center': 1}, ['data center'], ['land-use', 'data-center']),
    meeting(2, {'alpr': 1}, ['flock'], ['alpr']),
    meeting(3, {'local-taxes': 1}, ['splost'], ['local-taxes']),
    meeting(4, {'millage-budget': 1}, ['millage'], ['millage-budget']),
]))
for key in ('landUseCount', 'dataCenterCount', 'alprCount',
            'localTaxesCount', 'millageCount'):
    check("%s present" % key, key in entry, True)

# ---------------------------------------------------------------------------
print("A count is distinct citing meetings, not the capped item list")

# 25 land-use meetings: the committed sidecar keeps 20 items, the count keeps 25.
many = [meeting(i, {'rezoning': 1}, ['rezoning'], ['land-use']) for i in range(25)]
summary = build_summary(many)
check("landUseItems is capped at 20", len(summary['landUseItems']), 20)
check("landUseCount is not capped", flag_entry(summary)['landUseCount'], 25)

# Same for the two narrow subjects that gained counts in this change.
taxes = [meeting(i, {'local-taxes': 1}, ['splost'], ['local-taxes'])
         for i in range(23)]
summary = build_summary(taxes)
check("localTaxItems is capped at 20", len(summary['localTaxItems']), 20)
check("localTaxesCount is not capped", flag_entry(summary)['localTaxesCount'], 23)

millage = [meeting(i, {'millage-budget': 1}, ['millage'], ['millage-budget'])
           for i in range(22)]
summary = build_summary(millage)
check("millageCount is not capped", flag_entry(summary)['millageCount'], 22)
# Counted, never listed: this tag has no page and no pill, so a sourced list would
# be ~197 KB across the committed sidecars that nothing reads, rewritten twice
# weekly. Its real millage content still reaches the Local taxes page, because
# 'millage' and 'ad valorem' are in the local-taxes lexicon too.
check("millage carries no items list", 'millageItems' in summary, False)

# ---------------------------------------------------------------------------
print("A meeting cited twice for one subject counts once")

repeat = build_summary([
    meeting(7, {'local-taxes': 4}, ['splost', 'millage'], ['local-taxes']),
])
check("four keyword hits in one meeting is one citation",
      flag_entry(repeat)['localTaxesCount'], 1)

# ---------------------------------------------------------------------------
print("Land use excludes the data-center meetings, which have their own count")

# dataCenterItems is supplied by the enricher (Legistar from structured items,
# OCR one per flagged meeting), not derived from `topics` here, so a realistic
# data-center meeting carries one.
dc_meeting = meeting(1, {'data-center': 1, 'rezoning': 1}, ['data center'],
                     ['land-use', 'data-center'])
dc_meeting['dataCenterItems'] = [{
    'title': 'Rezoning for a data center campus', 'date': dc_meeting['date'],
    'sourceUrl': dc_meeting['sourceUrl']}]
split = build_summary([
    meeting(0, {'rezoning': 1}, ['rezoning'], ['land-use']),
    dc_meeting,
])
entry = flag_entry(split)
check("a data-center meeting is not also a land-use citation",
      entry['landUseCount'], 1)
check("it is a data-center citation", entry['dataCenterCount'], 1)

# ---------------------------------------------------------------------------
print("A sidecar written before the counts existed still reads")

legacy = {
    'flags': ['land-use', 'local-taxes'], 'lastActivity': '2026-01-01',
    'dataCenterItems': [], 'landUseItems': [1, 2, 3], 'alprItems': [],
    'localTaxItems': [1, 2],
}
entry = flag_entry(legacy)
check("landUseCount falls back to the item count", entry['landUseCount'], 3)
check("localTaxesCount falls back to the item count", entry['localTaxesCount'], 2)
check("a sidecar with no millage count reads zero", entry['millageCount'], 0)

# ---------------------------------------------------------------------------
print("millage-budget is a broad tag and must not be ranked with the others")

# This is the reason the card ranks only the four pill-bearing subjects. If these
# two terms ever leave the lexicon, the card's exclusion of millage can be
# revisited — so the test names them rather than leaving it to a comment.
for term in ('budget', 'fiscal year'):
    check("%r is in the millage-budget lexicon" % term,
          term in TOPIC_RULES['millage-budget'], True)
    check("%r is a millage evidence term" % term, term in MILLAGE_TERMS, True)

# A place whose agendas merely say "budget" every month outscores a real
# land-use fight, which is why millage carries a count but never a pill.
broad = build_summary(
    [meeting(i, {'millage-budget': 1}, ['budget'], ['millage-budget'])
     for i in range(12)]
    + [meeting(50 + i, {'rezoning': 1}, ['rezoning'], ['land-use'])
       for i in range(3)])
entry = flag_entry(broad)
check("millage outscores land use on an ordinary place",
      entry['millageCount'] > entry['landUseCount'], True)

# ---------------------------------------------------------------------------
if failures:
    print("\n%d FAILED: %s" % (len(failures), ', '.join(failures)))
    sys.exit(1)
print("\nAll flag-entry count invariants hold.")
