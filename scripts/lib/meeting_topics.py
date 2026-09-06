#!/usr/bin/env python3
"""Shared subject taxonomy for local-government meeting enrichment.

ONE source of truth for the keyword taxonomy and the place-level rollup shared by
both meeting enrichers:

    enrich_legistar_meetings.py   Fulton / DeKalb — STRUCTURED Legistar API
                                  (EventItems / Matters / RollCalls), no OCR.
    enrich_ocr_meetings.py        Newton (CivicPlus) / Covington (CoreCode) /
                                  Douglas / Cobb / Henry (CivicClerk) — agenda &
                                  minutes PDFs, poppler text-layer + tesseract OCR.

Both classify meeting text with the same `TOPIC_RULES`, derive the same per-place
`flags`, and emit the same enriched-sidecar `summary` shape, so the UI
(assets/scripts/local-subjects.js "On recent agendas" + the local.html hub badges
via local-flags.json) lights up identically no matter which platform a place is
on. Keeping the taxonomy here — not copied into each enricher — is the same
single-source discipline as scripts/lib/votes_schema.py and lib/ga_match.py: a new
watch keyword is added once and every place inherits it.
"""

import json
import os
from datetime import datetime, timezone

# ── Subject taxonomy ──────────────────────────────────────────────────────────
# Keyword rules over the meeting/agenda-item text. Matched case-insensitively as
# plain substrings (see classify). Data-center / land-use is the killer app —
# rezonings, special-use permits and comprehensive-plan amendments are where data
# centers, warehouses and quarries get approved, so those subjects drive the card
# flags. Add a keyword here and BOTH enrichers pick it up.
TOPIC_RULES = {
    'data-center':        ['data center', 'data centre', 'hyperscale', 'data-center'],
    'rezoning':           ['rezon'],
    'special-land-use':   ['special land use', 'special-use', 'slup', 'conditional use',
                           'land use permit'],
    'variance':           ['variance'],
    'annexation':         ['annex'],
    'development':        ['apartment', 'subdivision', 'warehouse', 'mixed use',
                           'mixed-use', 'townhome', 'multifamily', 'multi-family'],
    'comprehensive-plan': ['comprehensive plan', 'future land use', 'land use plan'],
    'millage-budget':     ['millage', 'ad valorem', 'tax rate', 'budget', 'fiscal year'],
    'contract':           ['contract', 'procurement', 'task order', 'award of', 'purchase order'],
    'appointment':        ['appoint', 'reappoint'],
}

# Subjects that make a meeting "land use" — drives the land-use card flag.
LAND_USE = {'data-center', 'rezoning', 'special-land-use', 'variance',
            'annexation', 'development', 'comprehensive-plan'}


def classify(text):
    """Return the sorted list of subject tags whose keywords appear in `text`."""
    t = (text or '').lower()
    return [tag for tag, kws in TOPIC_RULES.items() if any(k in t for k in kws)]


def matched_terms(text):
    """Return the concrete keywords that matched — the *evidence* behind the tags.

    OCR/agenda text has no per-item structure, so the sourced flag points at the
    whole meeting; recording which phrases tripped a tag lets the pipeline (and a
    human auditor) see *why* a place is flagged without re-reading the PDF.
    """
    t = (text or '').lower()
    return sorted({k for kws in TOPIC_RULES.values() for k in kws if k in t})


def topic_flags(topics):
    """Per-meeting/-place flags from a {tag: count} (or tag-iterable) of topics.

    Identical rule for both enrichers: any land-use subject → 'land-use';
    'data-center' and 'millage-budget' surface as their own flags.
    """
    present = set(topics)
    flags = []
    if present & LAND_USE:
        flags.append('land-use')
    if 'data-center' in present:
        flags.append('data-center')
    if 'millage-budget' in present:
        flags.append('millage-budget')
    return flags


# ── Place-level rollup ────────────────────────────────────────────────────────

def build_summary(enriched):
    """Roll per-meeting enrichment up into the place-level `summary` the UI reads.

    Each `enriched` meeting must carry:
        date            'YYYY-MM-DD'
        flags           list[str]      (from topic_flags)
        topics          {tag: count}
        dataCenterItems list[{title, date, sourceUrl}]  (may be empty)

    The Legistar enricher fills dataCenterItems from the structured land-use
    *items*; the OCR enricher fills it at the *meeting* level (one entry per
    flagged meeting) — either way every entry links a source.
    """
    topic_totals = {}
    dc_items = {}
    flags = set()
    last = None
    land_use_meetings = 0
    for m in enriched:
        flags.update(m.get('flags') or [])
        if 'land-use' in (m.get('flags') or []):
            land_use_meetings += 1
        d = m.get('date')
        if d and (last is None or d > last):
            last = d
        for tag, n in (m.get('topics') or {}).items():
            topic_totals[tag] = topic_totals.get(tag, 0) + n
        for it in (m.get('dataCenterItems') or []):
            # De-dupe by title so the same recurring item across meetings lists once.
            dc_items.setdefault(it['title'], it)
    return {
        'flags': sorted(flags),
        'lastActivity': last,
        'topicTotals': topic_totals,
        'dataCenterItems': list(dc_items.values()),
        'landUseMeetings': land_use_meetings,
    }


def flag_entry(summary):
    """The compact per-place record written into the hub file local-flags.json."""
    return {
        'flags': summary['flags'],
        'dataCenterCount': len(summary['dataCenterItems']),
        'lastActivity': summary['lastActivity'],
    }


def write_flags_file(out_dir, updates):
    """Merge per-place flag summaries into the single hub file local-flags.json.

    Merge, never replace: each enricher owns only its own places, so a Legistar
    run and an OCR run each update their slugs and leave the other's alone.
    """
    path = os.path.join(out_dir, 'local-flags.json')
    doc = {'metadata': {}, 'places': {}}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except (ValueError, OSError):
            pass
    doc.setdefault('places', {}).update(updates)
    doc['metadata'] = {'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path
