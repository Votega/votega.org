#!/usr/bin/env python3
"""Extend the data-center / land-use topic watch to the non-Legistar places.

The Legistar counties (Fulton, DeKalb) expose fully structured agendas, so
enrich_legistar_meetings.py mines subjects and per-item votes straight from the
API. The rest of VoteGA's local governments publish agendas/minutes only as PDFs:

    Newton      CivicPlus  (agenda PDFs)
    Covington   CoreCode   (minutes PDFs — no agendas)
    Douglas     CivicClerk (agenda PDFs via GetMeetingFileStream)
    Cobb        CivicClerk
    Henry       CivicClerk

This enricher reads the already-generated, already-scoped links file
assets/data/local-<slug>-meetings.json, downloads each meeting's agenda (falling
back to minutes) PDF, extracts its text with poppler — Tesseract OCR only when a
PDF has no text layer (the GA executive-orders pattern, via lib/pdf_text.py) — and
runs the SAME keyword taxonomy as the Legistar enricher (lib/meeting_topics.py:
TOPIC_RULES → data-center, rezoning, special-land-use, …). It emits the SAME
enriched sidecar + local-flags.json shape, so the existing UI (the place page's
"On recent agendas" section and the /local/ hub's "Data centers on agenda" badge)
lights up for these places with no UI change.

Git-bloat rule (see the task / CLAUDE.md data-schema notes): only DERIVED data —
tags, flags, the matched keywords, the PDF's sha256 — is written to the committed
sidecar. Raw extracted text is NEVER committed (agenda packets are large and
churn); it is classified in memory and discarded. The sidecar doubles as the
incremental cache: a meeting whose agenda URL is unchanged from the last run keeps
its cached tags and is not re-downloaded, so steady-state runs only fetch new
meetings. Every flagged item links its source PDF.

Usage:
    python scripts/enrich_ocr_meetings.py [--slug douglas] [--months 12] [--limit 40]
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.http import fetch_bytes  # noqa: E402
from lib.pdf_text import extract_text, has_ocr  # noqa: E402
from lib.meeting_topics import (  # noqa: E402
    classify, matched_terms, topic_flags, build_summary, flag_entry, write_flags_file,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA_DIR = os.path.join(ROOT, 'assets', 'data')

# Platforms this enricher handles — everything PDF-based. Legistar is structured
# and handled by enrich_legistar_meetings.py, so it is deliberately excluded here.
OCR_PLATFORMS = {'civicplus', 'corecode', 'civicclerk'}

_PDF_HEADERS = {
    'User-Agent': 'votega.org/1.0 (meeting-topic-enricher)',
    'Accept':     'application/pdf',
}


def ocr_places(slug=None):
    """(place, cfg) for every visible PDF-platform place with a meetings domain."""
    with open(REGISTRY, encoding='utf-8') as f:
        places = (yaml.safe_load(f) or {}).get('places', [])
    out = []
    for p in places:
        if p.get('hidden'):
            continue
        cfg = (p.get('domains') or {}).get('meetings') or {}
        if cfg.get('platform') not in OCR_PLATFORMS:
            continue
        if slug and p['slug'] != slug:
            continue
        out.append((p, cfg))
    if slug and not out:
        sys.exit('%r is not a (visible) PDF-platform place' % slug)
    return out


def load_meetings(slug):
    path = os.path.join(DATA_DIR, 'local-%s-meetings.json' % slug)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_cache(slug):
    """Prior enriched sidecar indexed by meeting id — the incremental cache."""
    path = os.path.join(DATA_DIR, 'local-%s-meetings-enriched.json' % slug)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            prior = json.load(f)
    except (ValueError, OSError):
        return {}
    return {m['id']: m for m in prior.get('meetings', []) if m.get('id')}


def text_source(meeting):
    """(url, kind) for the PDF to classify: agenda first, else minutes. Video-only
    meetings (Covington's newest rows) yield (None, None) and are skipped."""
    if meeting.get('agendaUrl'):
        return meeting['agendaUrl'], 'agenda'
    if meeting.get('minutesUrl'):
        return meeting['minutesUrl'], 'minutes'
    return None, None


def enrich_meeting(meeting, cache):
    """Classify one meeting's PDF. Returns an enriched record, or None to skip.

    Reuses the cached record when the agenda/minutes URL is unchanged (no
    re-download); otherwise downloads the PDF, extracts text, classifies, and
    discards the text. Never stores raw text.
    """
    mid = meeting.get('id')
    url, kind = text_source(meeting)
    if not url:
        return None  # video-only / nothing to read

    cached = cache.get(mid)
    if cached and cached.get('textSourceUrl') == url and 'tags' in cached:
        return cached  # unchanged agenda — keep derived tags, skip the fetch

    pdf = fetch_bytes(url, headers=_PDF_HEADERS, retries=3, backoff=5, label=url)
    if pdf is None:
        print('    %s: PDF fetch failed (%s) — skipping' % (mid, kind))
        return cached  # keep any prior derived data rather than dropping the meeting

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, 'meeting.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf)
        text, method = extract_text(pdf_path)

    tags = classify(text)
    terms = matched_terms(text)
    topics = {tag: 1 for tag in tags}          # presence-per-meeting (one blob/meeting)
    date = meeting.get('date')
    title = (meeting.get('title') or meeting.get('body') or '').strip()
    dc_items = ([{'title': title or 'Meeting %s' % mid, 'date': date, 'sourceUrl': url}]
                if 'data-center' in tags else [])

    if method == 'none':
        print('    %s: no text extracted (image-only PDF, OCR unavailable)' % mid)

    return {
        'id': mid,
        'date': date,
        'body': meeting.get('body'),
        'title': title,
        'sourceUrl': url,
        'textSource': kind,
        'textSourceUrl': url,
        'textMethod': method,
        'textChars': len(text),
        'pdfSha256': hashlib.sha256(pdf).hexdigest(),
        'topics': topics,
        'tags': tags,
        'matchedTerms': terms,
        'flags': topic_flags(topics),
        'dataCenterItems': dc_items,
    }


def recent_meetings(meetings, since, limit):
    """Newest-first meetings on/after `since`, capped at `limit`."""
    dated = [m for m in meetings if (m.get('date') or '') >= since]
    dated.sort(key=lambda m: m.get('date') or '', reverse=True)
    return dated[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='one place (default: all PDF-platform places)')
    ap.add_argument('--months', type=int, default=12, help='look-back window')
    ap.add_argument('--limit', type=int, default=40, help='recent meetings per place')
    args = ap.parse_args()

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')
    if not has_ocr():
        print('note: pdftoppm/tesseract not found — text-layer PDFs still classify '
              'via pdftotext; scanned/image-only PDFs will be skipped.')

    flag_updates = {}
    for place, cfg in ocr_places(args.slug):
        slug = place['slug']
        data = load_meetings(slug)
        if not data or not data.get('meetings'):
            print('%s: no meetings file yet — run generate_place_meetings.py first' % slug)
            continue

        cache = load_cache(slug)
        window = recent_meetings(data['meetings'], since, args.limit)
        print('Enriching %s (%s): %d of %d meeting(s) since %s ...'
              % (place['name'], cfg.get('platform'), len(window), len(data['meetings']), since))

        enriched = []
        for m in window:
            rec = enrich_meeting(m, cache)
            if rec:
                enriched.append(rec)

        # Guard like generate/validate: never overwrite a good sidecar / good flags
        # with nothing. Empty means every fetch failed and there was no prior cache.
        if not enriched:
            print('  WARNING: 0 classified meetings for %s — leaving existing data intact' % slug)
            continue

        summary = build_summary(enriched)
        out = {
            'metadata': {
                'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'source': '%s (%s agenda/minutes PDFs, poppler+OCR)'
                          % (place['name'], cfg.get('platform')),
                'place': place['name'],
                'count': len(enriched),
            },
            'summary': summary,
            'meetings': enriched,
        }
        with open(os.path.join(DATA_DIR, 'local-%s-meetings-enriched.json' % slug),
                  'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        flag_updates[slug] = flag_entry(summary)
        print('  %s: flags=%s, %d data-center meeting(s)'
              % (slug, ','.join(summary['flags']) or '-', len(summary['dataCenterItems'])))

    if flag_updates:
        print('Wrote %s' % write_flags_file(DATA_DIR, flag_updates))


if __name__ == '__main__':
    main()
