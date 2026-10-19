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
    Clayton     PrimeGov   (agenda PDFs via CompiledDocument?compileOutputType=1)
    Baldwin/Banks/Walton  TeamMunicode (agenda PDFs on mccmeetings.blob…usgovcloudapi.net)

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

sys.path.insert(0, os.path.dirname(__file__))
from lib.http import fetch_bytes  # noqa: E402
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.pdf_text import extract_text, has_ocr  # noqa: E402
from lib.meeting_topics import (  # noqa: E402
    classify, matched_terms, topic_flags, build_summary, flag_entry,
    topic_excerpts, agenda_head,
)
from lib.enrich_runner import (  # noqa: E402
    run_places, run_meetings, report, too_lossy, PlaceOutcome,
)
from lib.gdrive import drive_download_url  # noqa: E402
from lib.text_cache import open_cache  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA_DIR = os.path.join(ROOT, 'assets', 'data')

# Platforms this enricher handles — everything whose agenda/minutes links are
# direct PDFs. Legistar is structured (enrich_legistar_meetings.py) and Granicus
# ViewPublisher serves HTML (enrich_granicus_meetings.py), so both are excluded.
# PrimeGov (Clayton) exposes agendas as CompiledDocument PDFs with a text layer,
# TeamMunicode (Baldwin/Banks/Walton) serves direct agenda PDFs on Azure blob
# storage, Gwinnett serves agenda PDFs from its own host, and Revize (Bartow/
# Fayette) harvests direct agenda/minutes PDF links — all ride the same poppler
# path.
# Google Drive (Carrollton) stores agenda/minutes as PDFs in a public folder; the
# meeting URL is the Drive /file/d/<id>/view page, which drive_download_url() rewrites
# to the direct-download endpoint before fetching (the view page is HTML, not the PDF).
OCR_PLATFORMS = {'civicplus', 'corecode', 'civicclerk', 'primegov', 'teammunicode',
                 'gwinnett', 'iqm2', 'municode', 'agendapub', 'revize', 'gdrive'}

_PDF_HEADERS = {
    'User-Agent': 'votega.org/1.0 (meeting-topic-enricher)',
    'Accept':     'application/pdf',
}


def ocr_places(slug=None):
    """(place, cfg) for every visible PDF-platform place with a meetings domain.

    `yaml` is imported HERE, not at module scope, and that placement is load-
    bearing: it is this module's only third-party dependency and the only place
    that needs it. scripts/test_enrich_*.py import this module, and
    run-script-tests.yml deliberately installs no pip packages — so a module-level
    `import yaml` made those suites fail with ModuleNotFoundError while the
    invariants they check were fine (see c01efecc for the same fix). Keep it local.
    """
    import yaml  # noqa: PLC0415 - see the docstring above
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


def enrich_meeting(meeting, cache, reclassify=False, agenda_packet=False,
                   slug=None, text_cache=None, from_text_cache=False):
    """Classify one meeting's PDF. Returns an enriched record, or None to skip.

    Reuses the cached record when the agenda/minutes URL is unchanged (no
    re-download); otherwise downloads the PDF, extracts text, classifies, and
    discards the text. Never stores raw text in the COMMITTED sidecar.

    `reclassify=True` bypasses that cache reuse and re-fetches every meeting, so a
    taxonomy change (a new subject keyword in lib/meeting_topics.py) re-tags
    already-cached meetings that a normal incremental run would leave untouched.

    `text_cache` (a lib.text_cache.TextCache, opt-in via --text-cache) stores the
    extracted text OUTSIDE git so it can be scored and re-classified later; with
    `from_text_cache=True` that stored text STANDS IN FOR THE FETCH, which is what
    makes a full `--reclassify` re-tag of the history free and offline instead of
    ~800 downloads. A from-cache run never falls back to the network: a gap is
    reported and the meeting keeps its prior tags, so the run stays reproducible
    and its cost stays predictable.

    `agenda_packet=True` (a per-place setting) marks a source whose AGENDA file is a
    full packet with the prior meetings' minutes bundled in after the agenda; the
    agenda text is trimmed to its head (agenda_head) so those embedded minutes don't
    tag THIS meeting with topics discussed at earlier ones. Minutes sources are left
    whole — they are already single-meeting.
    """
    mid = meeting.get('id')
    url, kind = text_source(meeting)
    if not url:
        return None  # video-only / nothing to read

    cached = cache.get(mid)
    if not reclassify and cached and cached.get('textSourceUrl') == url and 'tags' in cached:
        return cached  # unchanged agenda — keep derived tags, skip the fetch

    # Combined agenda packet: classify only the agenda proper, not the prior-meeting
    # minutes bundled in after it (which belong to — and are enriched as — those
    # earlier meetings). Minutes sources are already single-meeting, so leave them.
    trimmed = agenda_packet and kind == 'agenda'

    # Offline re-tag path: cached text replaces the download entirely.
    text = None
    if from_text_cache and text_cache is not None:
        text = text_cache.text_for(slug, mid)
    if text is not None:
        ent = text_cache.entry(slug, mid) or {}
        # The cache holds RAW extracted text, so apply this place's trim policy here
        # exactly as the fetching path below does.
        if trimmed:
            text = agenda_head(text)
        method = ent.get('method') or 'pdftotext'
        pdf_sha = ent.get('pdfSha256') or (cached or {}).get('pdfSha256')
    else:
        if from_text_cache:
            print('    %s: no cached text — keeping prior tags (no fetch)' % mid)
            return cached

        # A Google Drive view URL (Carrollton) is an HTML page, not the PDF — rewrite
        # it to the direct-download endpoint. Non-Drive URLs pass through unchanged.
        pdf = fetch_bytes(drive_download_url(url), headers=_PDF_HEADERS,
                          retries=3, backoff=5, label=url)
        if pdf is None:
            print('    %s: PDF fetch failed (%s) — skipping' % (mid, kind))
            return cached  # keep prior derived data rather than dropping the meeting

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, 'meeting.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(pdf)
            text, method = extract_text(pdf_path)
        pdf_sha = hashlib.sha256(pdf).hexdigest()

        # Store the RAW text (pre-trim) for later scoring / offline re-tagging, and
        # record whether production trims it so a scorer can reproduce this run.
        if text_cache is not None and method != 'none':
            text_cache.record(slug, mid, text, method=method, pdf_sha=pdf_sha,
                              source_url=url, date=meeting.get('date'),
                              body=meeting.get('body'), title=meeting.get('title'),
                              trimmed=trimmed)

        if trimmed:
            text = agenda_head(text)

    # If no text could be extracted now (image-only PDF and OCR unavailable, e.g. a
    # local run without tesseract), keep any prior derived tags rather than wiping
    # them to empty — same "never overwrite good data with nothing" discipline as
    # the batch-level guard. A genuine reclassify still re-tags every readable PDF.
    if method == 'none' and cached and cached.get('tags'):
        return cached

    tags = classify(text)
    terms = matched_terms(text)
    # Phase A per-mention excerpts: capture only from the poppler text layer, never
    # OCR (OCR text is non-deterministic → noisy diffs, and garbled → misquotes).
    excerpts = topic_excerpts(text, tags) if method == 'pdftotext' else {}
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
        'pdfSha256': pdf_sha,
        'topics': topics,
        'tags': tags,
        'matchedTerms': terms,
        'topicExcerpts': excerpts,
        'flags': topic_flags(topics),
        'dataCenterItems': dc_items,
        # Present only when the agenda packet was trimmed to its head — a signal that
        # textChars reflects the agenda proper, not the (much larger) full packet.
        **({'agendaPacketTrimmed': True} if trimmed else {}),
    }


def recent_meetings(meetings, since, limit):
    """Newest-first meetings on/after `since`, capped at `limit`."""
    dated = [m for m in meetings if (m.get('date') or '') >= since]
    dated.sort(key=lambda m: m.get('date') or '', reverse=True)
    return dated[:limit]


def enrich_place(place, cfg, since, limit, reclassify=False, text_cache=None,
                 from_text_cache=False):
    """Enrich one PDF-platform place: write its sidecar, return its flag entry.

    Returns None to leave the place's committed data untouched — no meetings file
    yet, or nothing classified (the "never overwrite good data with nothing"
    guard) — or a PlaceOutcome when meetings inside the window were lost, so the
    run still fails even though the sidecar was written. Raising is reserved for
    the unexpected, which lib.enrich_runner contains to this one place.
    """
    slug = place['slug']
    data = load_meetings(slug)
    if not data or not data.get('meetings'):
        print('%s: no meetings file yet — run generate_place_meetings.py first' % slug)
        return None

    cache = load_cache(slug)
    window = recent_meetings(data['meetings'], since, limit)
    print('Enriching %s (%s): %d of %d meeting(s) since %s ...'
          % (place['name'], cfg.get('platform'), len(window), len(data['meetings']), since))

    agenda_packet = bool(cfg.get('agenda_packet'))
    # Per-MEETING boundary: one malformed PDF (or a poppler/OCR surprise) costs
    # one meeting, not this place's whole window, and a meeting that raises keeps
    # its cached tags.
    enriched, lost = run_meetings(
        slug, window,
        lambda m: enrich_meeting(m, cache, reclassify=reclassify,
                                 agenda_packet=agenda_packet, slug=slug,
                                 text_cache=text_cache,
                                 from_text_cache=from_text_cache),
        cache=cache)

    # Guard like generate/validate: never overwrite a good sidecar / good flags
    # with nothing. Empty means every fetch failed and there was no prior cache.
    if not enriched:
        print('  WARNING: 0 classified meetings for %s — leaving existing data intact' % slug)
        return PlaceOutcome(None, lost)
    # ... nor with a window short of meetings we simply could not read.
    if too_lossy(slug, lost, len(window)):
        return PlaceOutcome(None, lost)

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
    write_json_atomic(os.path.join(DATA_DIR, 'local-%s-meetings-enriched.json' % slug),
                      out, indent=1)
    print('  %s: flags=%s, %d data-center meeting(s)'
          % (slug, ','.join(summary['flags']) or '-', len(summary['dataCenterItems'])))
    return PlaceOutcome(flag_entry(summary), lost)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='one place (default: all PDF-platform places)')
    ap.add_argument('--months', type=int, default=12, help='look-back window')
    ap.add_argument('--limit', type=int, default=40, help='recent meetings per place')
    ap.add_argument('--reclassify', action='store_true',
                    help='ignore the incremental cache and re-fetch every meeting '
                         'in the window — use once after a taxonomy change so already-'
                         'cached meetings pick up new subject keywords')
    ap.add_argument('--text-cache', metavar='DIR',
                    help='also store each document\'s extracted text under DIR '
                         '(gitignored, never committed) to build the offline corpus '
                         'that scripts/score_topic_lexicon.py measures against')
    ap.add_argument('--from-text-cache', action='store_true',
                    help='classify from --text-cache instead of downloading. With '
                         '--reclassify this re-tags the whole history offline after '
                         'a taxonomy change, with no fetches; meetings absent from '
                         'the cache keep their prior tags')
    args = ap.parse_args()

    if args.from_text_cache and not args.text_cache:
        ap.error('--from-text-cache needs --text-cache DIR to read from')

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')
    if not has_ocr():
        print('note: pdftoppm/tesseract not found — text-layer PDFs still classify '
              'via pdftotext; scanned/image-only PDFs will be skipped.')

    # One place's failure is contained to that place, and local-flags.json is
    # written as each place finishes — see lib/enrich_runner.py for the run this
    # cost us.
    # Writable only when we are the ones fetching: a --from-text-cache run reads the
    # corpus and must not half-populate it.
    text_cache = open_cache(args.text_cache, writable=not args.from_text_cache)
    done, failed = run_places(
        ocr_places(args.slug), DATA_DIR,
        lambda place, cfg: enrich_place(place, cfg, since, args.limit,
                                        reclassify=args.reclassify,
                                        text_cache=text_cache,
                                        from_text_cache=args.from_text_cache))
    if text_cache is not None and text_cache.flush():
        print('text cache: %s' % text_cache.stats())
    sys.exit(report(done, failed, DATA_DIR))


if __name__ == '__main__':
    main()
