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
import re
from datetime import datetime, timezone

# ── Subject taxonomy ──────────────────────────────────────────────────────────
# Keyword rules over the meeting/agenda-item text. Matched case-insensitively as
# plain substrings (see classify). Data-center / land-use is the killer app —
# rezonings, special-use permits and comprehensive-plan amendments are where data
# centers, warehouses and quarries get approved, so those subjects drive the card
# flags. Add a keyword here and BOTH enrichers pick it up.
#
# The 'alpr' rule (automated license plate readers / mass-surveillance cameras)
# was tuned against real agendas with scripts/probe_alpr_keywords.py: the generic
# capability terms alone under-matched (recall 1/3) because governments name the
# dominant vendor plainly — "Flock", "Flock cameras", "safer city" — not "license
# plate reader". So the net is two layers: generic phrases (catch any vendor,
# even unknown ones) plus a vendor lexicon (Flock and its competitors). The
# probe measured recall 3/3 with zero false positives across 46 control docs.
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
    'alpr':               ['license plate reader', 'license plate recognition',
                           'automated license plate', 'automatic license plate',
                           'plate reader', 'lpr camera', 'alpr', 'safer city',
                           # Vendors beyond Flock (Flock itself is a word-rule below).
                           # Keyed on ALPR-SPECIFIC brands: 'vigilant solutions' is
                           # Motorola's ALPR line, but the bare 'motorola solutions'
                           # parent brand (radios/CAD/body cams) and 'mobile-vision'
                           # (in-car video) over-matched non-ALPR contracts, so they
                           # are omitted. 'fusus' (Axon real-time crime center) is a
                           # camera aggregator, not an ALPR vendor — omitted too.
                           'vigilant solutions', 'genetec', 'autovu', 'sharpv',
                           'rekor', 'openalpr', 'elsag', 'neology', 'jenoptik',
                           'perceptics', 'verra mobility', 'platesmart'],
}

# Keywords that must match as WHOLE WORDS, not substrings — same tag semantics as
# TOPIC_RULES but matched with a word boundary. 'flock' is how agendas name Flock
# Safety, but a bare substring would also fire on "flocking"/"flocked"; \bflock\b
# skips those while still catching "flock", "flock cameras", "flock/axon". (The
# substring rules above deliberately keep prefix behaviour like 'rezon'/'annex'.)
TOPIC_WORD_RULES = {
    'alpr': ['flock'],
}
_WORD_RE = {kw: re.compile(r'\b' + re.escape(kw) + r'\b')
            for kws in TOPIC_WORD_RULES.values() for kw in kws}

# Every keyword (substring + word-rule) that counts as ALPR evidence — used to
# filter a meeting's matchedTerms down to the vendor/capability phrases that
# actually fired, for the sourced alprItems citations.
ALPR_TERMS = set(TOPIC_RULES['alpr']) | set(TOPIC_WORD_RULES['alpr'])

# Display labels for the ALPR vendor keywords, so a matched term can be shown as a
# vendor NAME on the topic index pages (assets/scripts/topic-index.js reads the
# vendor list the generator derives from these). Kept here, beside the lexicon it
# maps from, so the vendor identity stays single-source with the keywords — a new
# ALPR vendor keyword added above gets a label here in the same edit. Only the
# vendor/brand keywords appear; the generic capability phrases ("plate reader",
# "alpr", "flock") are evidence terms, not vendor names, and are intentionally
# absent. 'flock' is the one brand that is also its plain agenda spelling, so it
# maps to the Flock Safety label.
ALPR_VENDOR_LABELS = {
    'flock':              'Flock Safety',
    'vigilant solutions': 'Vigilant (Motorola)',
    'genetec':            'Genetec',
    'autovu':             'Genetec AutoVu',
    'sharpv':             'Genetec SharpV',
    'rekor':              'Rekor',
    'openalpr':           'OpenALPR (Rekor)',
    'elsag':              'Elsag (Leonardo)',
    'neology':            'Neology',
    'jenoptik':           'Jenoptik',
    'perceptics':         'Perceptics',
    'verra mobility':     'Verra Mobility',
    'platesmart':         'PlateSmart',
}

# The spelled-out capability phrases that, on their own, are unambiguous enough to
# mark a mention "high" confidence even without a named vendor (mirrors the
# handoff scanner's high tier). Everything else that trips the alpr rule is
# "medium" — real, badgeable, but keyword-only.
ALPR_HIGH_TERMS = {
    'automated license plate', 'automatic license plate',
    'license plate recognition', 'license plate reader',
}


def alpr_vendors(terms):
    """Distinct vendor display names implied by a meeting's matched ALPR terms."""
    return sorted({ALPR_VENDOR_LABELS[t] for t in terms if t in ALPR_VENDOR_LABELS})


# ── Per-mention excerpts (Phase A) ─────────────────────────────────────────────
# The badges/citations only need to know a tag FIRED; an excerpt needs the match
# POSITION, so this re-scans the text for offsets (classify/matched_terms answer
# "which", this answers "where"). Kept here so the one taxonomy owns both. Callers
# gate on the extraction method — excerpts are captured from the poppler text layer
# only, never OCR, because OCR text is non-deterministic (noisy git diffs) and
# often garbled (a misquote in public). See the topic-index rollout notes.

EXCERPT_CHARS = 240  # window of context captured around a matched term


def _snip(text, start, end):
    """A whitespace-collapsed excerpt around [start:end), with … where trimmed.

    Drops U+FFFD replacement chars first: pdftotext decodes with errors='replace',
    so a byte it can't map as UTF-8 becomes U+FFFD, which we must not quote
    verbatim in public. Removing it (rather than leaving a stray box glyph) keeps
    the quote clean; the whitespace collapse tidies the gap it leaves."""
    lo = max(0, start - EXCERPT_CHARS // 2)
    hi = min(len(text), end + EXCERPT_CHARS // 2)
    body = " ".join(text[lo:hi].replace(chr(0xFFFD), " ").split())
    return ("… " if lo > 0 else "") + body + (" …" if hi < len(text) else "")


def _tag_matches(low, tag):
    """All (start, end, keyword) hits for a tag's keywords, over lowercased text.
    Offsets are valid in the original text too (lower() preserves length here)."""
    hits = []
    for kw in TOPIC_RULES.get(tag, []):
        i = low.find(kw)
        if i != -1:
            hits.append((i, i + len(kw), kw))
    for kw in TOPIC_WORD_RULES.get(tag, []):
        m = _WORD_RE[kw].search(low)
        if m:
            hits.append((m.start(), m.end(), kw))
    return hits


def _best_hit(hits, tag):
    """Pick the hit to quote. For ALPR, prefer a vendor / spelled-out capability
    term (the high-confidence evidence) over a bare acronym; else earliest."""
    if tag == "alpr":
        strong = [h for h in hits
                  if h[2] in ALPR_VENDOR_LABELS or h[2] in ALPR_HIGH_TERMS]
        if strong:
            return min(strong, key=lambda h: h[0])
    return min(hits, key=lambda h: h[0])


def topic_excerpts(text, tags):
    """{tag: {term, excerpt}} for each tag in `tags` that yields a locatable hit.

    `text` is the raw extracted page text; `tags` is that meeting's classify()
    result. Returns only tags whose keyword can actually be located (so a tag that
    fired on a keyword the finder can't re-locate is simply omitted, never faked).
    """
    if not text:
        return {}
    low = text.lower()
    out = {}
    for tag in tags:
        hits = _tag_matches(low, tag)
        if not hits:
            continue
        start, end, term = _best_hit(hits, tag)
        out[tag] = {"term": term, "excerpt": _snip(text, start, end)}
    return out

# Subjects that make a meeting "land use" — drives the land-use card flag.
LAND_USE = {'data-center', 'rezoning', 'special-land-use', 'variance',
            'annexation', 'development', 'comprehensive-plan'}


def classify(text):
    """Return the sorted list of subject tags whose keywords appear in `text`."""
    t = (text or '').lower()
    tags = {tag for tag, kws in TOPIC_RULES.items() if any(k in t for k in kws)}
    tags |= {tag for tag, kws in TOPIC_WORD_RULES.items()
             if any(_WORD_RE[k].search(t) for k in kws)}
    return sorted(tags)


def matched_terms(text):
    """Return the concrete keywords that matched — the *evidence* behind the tags.

    OCR/agenda text has no per-item structure, so the sourced flag points at the
    whole meeting; recording which phrases tripped a tag lets the pipeline (and a
    human auditor) see *why* a place is flagged without re-reading the PDF.
    """
    t = (text or '').lower()
    terms = {k for kws in TOPIC_RULES.values() for k in kws if k in t}
    terms |= {k for k, rx in _WORD_RE.items() if rx.search(t)}
    return sorted(terms)


def topic_flags(topics):
    """Per-meeting/-place flags from a {tag: count} (or tag-iterable) of topics.

    Identical rule for both enrichers: any land-use subject → 'land-use';
    'data-center', 'millage-budget' and 'alpr' surface as their own flags.
    """
    present = set(topics)
    flags = []
    if present & LAND_USE:
        flags.append('land-use')
    if 'data-center' in present:
        flags.append('data-center')
    if 'millage-budget' in present:
        flags.append('millage-budget')
    if 'alpr' in present:
        flags.append('alpr')
    return flags


# ── Place-level rollup ────────────────────────────────────────────────────────

def build_summary(enriched):
    """Roll per-meeting enrichment up into the place-level `summary` the UI reads.

    Each `enriched` meeting must carry:
        date            'YYYY-MM-DD'
        flags           list[str]      (from topic_flags)
        topics          {tag: count}
        matchedTerms    list[str]      (from matched_terms; may be empty)
        dataCenterItems list[{title, date, sourceUrl}]  (may be empty)

    The Legistar enricher fills dataCenterItems from the structured land-use
    *items*; the OCR enricher fills it at the *meeting* level (one entry per
    flagged meeting) — either way every entry links a source. `landUseItems` and
    `alprItems` are DERIVED here uniformly from each meeting's `topics` (the
    meeting's title/date/sourceUrl + which subjects/vendor terms it hit), so a
    Legistar and an OCR place get the same sourced lists; data-center meetings are
    excluded from landUseItems because they already surface in dataCenterItems.
    """
    lu_tags = LAND_USE - {'data-center'}
    topic_totals = {}
    dc_items = {}
    lu_items = {}
    alpr_items = {}
    flags = set()
    last = None
    land_use_meetings = 0
    alpr_meetings = 0
    for m in enriched:
        flags.update(m.get('flags') or [])
        if 'land-use' in (m.get('flags') or []):
            land_use_meetings += 1
        d = m.get('date')
        if d and (last is None or d > last):
            last = d
        mtopics = m.get('topics') or {}
        for tag, n in mtopics.items():
            topic_totals[tag] = topic_totals.get(tag, 0) + n
        for it in (m.get('dataCenterItems') or []):
            # De-dupe by title so the same recurring item across meetings lists once.
            dc_items.setdefault(it['title'], it)
        # Land-use citations: a meeting that hit a land-use subject OTHER than
        # data-center (which has its own list). One entry per distinct meeting.
        present_lu = sorted(set(mtopics) & lu_tags)
        if present_lu and 'data-center' not in mtopics:
            title = m.get('title') or m.get('body') or 'Meeting'
            key = (m.get('date'), title)
            lu_items.setdefault(key, {
                'title': title, 'date': m.get('date'),
                'sourceUrl': m.get('sourceUrl'), 'tags': present_lu})
        # ALPR citations: one entry per distinct meeting that hit the alpr subject,
        # carrying the concrete vendor/capability terms that fired (from the
        # meeting's matchedTerms) as the evidence — the same sourced-list shape as
        # land use, derived uniformly so Legistar and OCR places match.
        if 'alpr' in mtopics:
            alpr_meetings += 1
            title = m.get('title') or m.get('body') or 'Meeting'
            terms = sorted(set(m.get('matchedTerms') or []) & ALPR_TERMS)
            key = (m.get('date'), title)
            alpr_items.setdefault(key, {
                'title': title, 'date': m.get('date'),
                'sourceUrl': m.get('sourceUrl'), 'terms': terms})
    # Newest first, capped so the committed sidecar stays small.
    lu_sorted = sorted(lu_items.values(), key=lambda x: x.get('date') or '', reverse=True)
    alpr_sorted = sorted(alpr_items.values(), key=lambda x: x.get('date') or '', reverse=True)
    return {
        'flags': sorted(flags),
        'lastActivity': last,
        'topicTotals': topic_totals,
        'dataCenterItems': list(dc_items.values()),
        'landUseItems': lu_sorted[:20],
        'landUseMeetings': land_use_meetings,
        'alprItems': alpr_sorted[:20],
        'alprMeetings': alpr_meetings,
    }


def flag_entry(summary):
    """The compact per-place record written into the hub file local-flags.json."""
    return {
        'flags': summary['flags'],
        'dataCenterCount': len(summary['dataCenterItems']),
        'landUseCount': len(summary.get('landUseItems') or []),
        'alprCount': len(summary.get('alprItems') or []),
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
