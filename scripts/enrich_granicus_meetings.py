#!/usr/bin/env python3
"""Extend the data-center / land-use topic watch to Granicus ViewPublisher places.

The other enrichers cover the other platforms:

    enrich_legistar_meetings.py   Fulton / DeKalb   — structured Legistar API
    enrich_ocr_meetings.py        Newton / Covington / Douglas / Cobb / Henry
                                  — agenda/minutes PDFs, poppler + tesseract OCR

Granicus ViewPublisher places (Barrow, Cherokee) are neither: their agenda/minutes
links (AgendaViewer.php / MinutesViewer.php, produced by lib.granicus) are not
direct PDFs — each 302-redirects to an *HTML* agenda hosted on Granicus's S3
bucket. So this enricher reads the already-generated, already-scoped links file
assets/data/local-<slug>-meetings.json, resolves each meeting's agenda (falling
back to minutes) to that HTML, strips it to text, and runs the SAME keyword
taxonomy as the other two (lib.meeting_topics: TOPIC_RULES → data-center,
rezoning, …). It emits the SAME enriched sidecar + local-flags.json shape, so the
place page's "On recent agendas" section and the /local/ hub's data-center badge
light up with no UI change.

Most Granicus ViewPublisher places (Barrow, Cherokee) serve the agenda as HTML, so
the default path just strips it to text. Some instances (Spalding) instead have
`AgendaViewer.php` return a native **PDF** with a direct 2xx — no HTML at all. That
is detected here by the `%PDF-` magic bytes and routed through the shared poppler /
Tesseract path (lib.pdf_text.extract_text), exactly like enrich_ocr_meetings.py;
without that check the PDF bytes were fed to the HTML stripper and classified as
binary garbage, tagging zero topics.

Four Granicus quirks handled here:

  * The AgendaViewer redirect points at
    `https://<bucket>.s3.amazonaws.com/...` where the bucket name contains
    underscores (`granicus_production_attachments`). That is an invalid TLS
    hostname, so following the redirect the normal way fails cert verification in
    Python (browsers/curl tolerate it). We rewrite the virtual-hosted URL to the
    **path-style** endpoint `https://s3.amazonaws.com/<bucket>/...`, whose cert
    (`s3.amazonaws.com`) verifies cleanly — no TLS downgrade needed.
  * A missing/unpublished agenda 302s to `/core/error/NotFound.aspx` instead of a
    document; that is detected and skipped (the meeting keeps any prior tags).
  * ⚠ The Location header is sometimes RELATIVE. Catoosa answers 11 of its
    first 35 documents with `/DocumentViewer.php?file=<hash>.pdf&view=1`,
    which RFC 7231 §7.1.2 permits and urllib rejects outright ("unknown url
    type"). Every Location is resolved against the viewer URL before use.
    DocumentViewer.php serves the PDF itself, so it lands on the `%PDF-`
    path below. Barrow/Cherokee/Spalding only ever send absolute S3 URLs,
    which is why this stayed invisible until a fourth portal was added.

Git-bloat rule (same as the OCR enricher): only DERIVED data — tags, flags,
matched keywords, the HTML's sha256 — is committed to the sidecar. Raw agenda text
is classified in memory and discarded. The sidecar doubles as the incremental
cache: a meeting whose viewer URL is unchanged keeps its cached tags and is not
re-fetched, so steady-state runs only classify newly-scraped meetings.

Usage:
    python scripts/enrich_granicus_meetings.py [--slug cherokee] [--months 12] [--limit 40]
"""

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from lib.meeting_topics import (  # noqa: E402
    classify, matched_terms, topic_flags, build_summary, flag_entry,
    topic_excerpts,
)
from lib.enrich_runner import (  # noqa: E402
    run_places, run_meetings, report, too_lossy, PlaceOutcome,
)
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.pdf_text import extract_text  # noqa: E402
from lib.text_cache import open_cache  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA_DIR = os.path.join(ROOT, 'assets', 'data')

# Platforms this enricher handles. Legistar and the PDF platforms have their own.
GRANICUS_PLATFORMS = {'granicus'}

_HEADERS = {'User-Agent': 'votega.org/1.0 (meeting-topic-enricher)'}
# Virtual-hosted S3 URL -> (bucket, region-or-'', key), so we can rewrite to the
# path-style endpoint whose cert verifies (the bucket name has underscores).
_S3_VHOST_RE = re.compile(
    r'https?://([^/]+)\.s3([.-][^./]+)?\.amazonaws\.com/(.*)', re.I)
_SCRIPT_STYLE_RE = re.compile(r'<(script|style)\b.*?</\1>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return the 3xx response instead of following it — we resolve redirects by
    hand so we can rewrite the S3 target to a path-style URL that verifies."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _path_style(url):
    """Rewrite a virtual-hosted S3 URL to the path-style endpoint. A path-style
    URL (or any non-S3 URL) is returned unchanged."""
    m = _S3_VHOST_RE.match(url)
    if not m:
        return url
    bucket, region, key = m.group(1), m.group(2) or '', m.group(3)
    return 'https://s3%s.amazonaws.com/%s/%s' % (region, bucket, key)


def _get(url, timeout=30):
    """GET without following redirects. Returns (code, location, body_or_None)."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        # Request() is built INSIDE the try on purpose: it raises
        # ValueError on a URL urllib will not accept, and one unreadable
        # document must never abort a multi-county run (it did — see
        # scripts/test_enrich_granicus.py).
        req = urllib.request.Request(url, headers=_HEADERS)
        resp = opener.open(req, timeout=timeout)
        return resp.getcode(), resp.headers.get('Location'), resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = None
        return e.code, e.headers.get('Location'), body
    except Exception:
        return None, None, None


def fetch_agenda_html(viewer_url, timeout=30, retries=3, backoff=5):
    """Resolve a Granicus AgendaViewer/MinutesViewer link to its agenda HTML bytes.

    Returns the raw HTML bytes, or None (missing document, error page, or a
    network/5xx failure after retries). Follows the one Granicus 302 by hand and
    rewrites an S3 virtual-host target to path-style so TLS verifies.
    """
    for attempt in range(retries):
        code, loc, body = _get(viewer_url, timeout=timeout)
        # Direct 2xx (no indirection) — take the body as-is.
        if code and 200 <= code < 300 and body:
            return body
        if code and 300 <= code < 400 and loc:
            if '/core/error/' in loc.lower():
                return None  # missing / unpublished agenda
            # ⚠ A Location may be RELATIVE (RFC 7231 §7.1.2). Catoosa
            # answers with `/DocumentViewer.php?file=<hash>.pdf&view=1`;
            # handing that to urllib raises "unknown url type". Resolve
            # against the viewer URL before the S3 rewrite, which is a
            # no-op for anything that is not an S3 virtual host.
            target = _path_style(urljoin(viewer_url, loc))
            code2, _, body2 = _get(target, timeout=timeout)
            if code2 and 200 <= code2 < 300 and body2:
                return body2
            if code2 and code2 < 500:
                return None  # 4xx on the document — nothing to read
        elif code and 400 <= code < 500:
            return None  # non-retryable
        if attempt < retries - 1:
            time.sleep(backoff)
    return None


def html_to_text(raw):
    """Strip HTML bytes to classifiable plain text (scripts/styles removed,
    entities decoded, whitespace collapsed)."""
    if not raw:
        return ''
    text = raw.decode('utf-8', errors='replace')
    text = _SCRIPT_STYLE_RE.sub(' ', text)
    text = _TAG_RE.sub(' ', text)
    text = htmllib.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def granicus_places(slug=None):
    """(place, cfg) for every visible Granicus ViewPublisher place.

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
        if cfg.get('platform') not in GRANICUS_PLATFORMS:
            continue
        if slug and p['slug'] != slug:
            continue
        out.append((p, cfg))
    if slug and not out:
        sys.exit('%r is not a (visible) Granicus place' % slug)
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
    """(url, kind) to classify: agenda first, else minutes. Video-only meetings
    yield (None, None) and are skipped."""
    if meeting.get('agendaUrl'):
        return meeting['agendaUrl'], 'agenda'
    if meeting.get('minutesUrl'):
        return meeting['minutesUrl'], 'minutes'
    return None, None


def enrich_meeting(meeting, cache, reclassify=False, slug=None, text_cache=None,
                   from_text_cache=False):
    """Classify one meeting's agenda HTML. Returns an enriched record, or None.

    Reuses the cached record when the viewer URL is unchanged (no re-fetch);
    otherwise resolves + downloads the HTML, classifies, and discards the text.

    `reclassify=True` bypasses that cache reuse so a taxonomy change re-tags
    already-cached meetings.

    `text_cache` / `from_text_cache` mirror enrich_ocr_meetings.py: the extracted
    text is stored outside git (opt-in, --text-cache) so a lexicon change can be
    scored offline, and a from-cache run classifies that stored text instead of
    re-fetching. A from-cache run never falls back to the network.
    """
    mid = meeting.get('id')
    url, kind = text_source(meeting)
    if not url:
        return None

    cached = cache.get(mid)
    if not reclassify and cached and cached.get('textSourceUrl') == url and 'tags' in cached:
        return cached  # unchanged agenda — keep derived tags, skip the fetch

    # Offline re-tag path: cached text replaces the fetch entirely.
    text = None
    if from_text_cache and text_cache is not None:
        text = text_cache.text_for(slug, mid)
    if text is not None:
        method = (text_cache.entry(slug, mid) or {}).get('method') or 'html'
        # No bytes were fetched on this path, so the document hash cannot be
        # recomputed — carry the one the last networked run recorded. It still
        # identifies the document this record was derived from; it is simply not
        # re-verified by an offline re-tag.
        content_sha = (cached or {}).get('contentSha256')
    else:
        if from_text_cache:
            print('    %s: no cached text — keeping prior tags (no fetch)' % mid)
            return cached

        raw = fetch_agenda_html(url)
        if raw is None:
            print('    %s: agenda fetch failed/unpublished (%s) — skipping' % (mid, kind))
            return cached  # keep prior derived data rather than dropping the meeting

        # Most instances serve HTML; some (Spalding) return a native PDF from the same
        # AgendaViewer.php. Detect the PDF and extract its text with poppler/OCR rather
        # than feeding binary bytes to the HTML stripper (which yields unclassifiable
        # garbage — the original Spalding "0 topics" bug).
        if raw[:5] == b'%PDF-':
            with tempfile.TemporaryDirectory() as tmp:
                pdf_path = os.path.join(tmp, 'meeting.pdf')
                with open(pdf_path, 'wb') as f:
                    f.write(raw)
                text, method = extract_text(pdf_path)
            # Image-only PDF with OCR unavailable (e.g. a dev run without tesseract):
            # keep prior tags rather than wiping them to empty. A reclassify still
            # re-tags every readable PDF.
            if method == 'none' and cached and cached.get('tags'):
                return cached
            if method == 'none':
                print('    %s: no text extracted (image-only PDF, OCR unavailable)' % mid)
        else:
            text, method = html_to_text(raw), 'html'
        content_sha = hashlib.sha256(raw).hexdigest()

        # Granicus agendas are never combined packets, so nothing is trimmed here.
        if text_cache is not None and method != 'none':
            text_cache.record(slug, mid, text, method=method, source_url=url,
                              date=meeting.get('date'), body=meeting.get('body'),
                              title=meeting.get('title'))

    tags = classify(text)
    terms = matched_terms(text)
    # Per-mention excerpts: safe to quote from HTML-stripped text or the poppler text
    # layer, but never from OCR (non-deterministic → noisy diffs, garbled → misquotes).
    excerpts = topic_excerpts(text, tags) if method in ('html', 'pdftotext') else {}
    topics = {tag: 1 for tag in tags}          # presence-per-meeting (one blob/meeting)
    date = meeting.get('date')
    title = (meeting.get('title') or meeting.get('body') or '').strip()
    # Link the item at the stable, user-facing viewer URL (not the raw S3 file).
    dc_items = ([{'title': title or 'Meeting %s' % mid, 'date': date, 'sourceUrl': url}]
                if 'data-center' in tags else [])

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
        'contentSha256': content_sha,
        'topics': topics,
        'tags': tags,
        'matchedTerms': terms,
        'topicExcerpts': excerpts,
        'flags': topic_flags(topics),
        'dataCenterItems': dc_items,
    }


def recent_meetings(meetings, since, limit):
    """Newest-first meetings on/after `since`, capped at `limit`."""
    dated = [m for m in meetings if (m.get('date') or '') >= since]
    dated.sort(key=lambda m: m.get('date') or '', reverse=True)
    return dated[:limit]


def enrich_place(place, cfg, since, limit, reclassify=False, text_cache=None,
                 from_text_cache=False):
    """Enrich one Granicus place: write its sidecar, return its flag entry.

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

    # Per-MEETING boundary: one unreadable document costs one meeting, not this
    # place's whole window, and a meeting that raises keeps its cached tags.
    enriched, lost = run_meetings(
        slug, window,
        lambda m: enrich_meeting(m, cache, reclassify=reclassify, slug=slug,
                                 text_cache=text_cache,
                                 from_text_cache=from_text_cache),
        cache=cache)

    # Guard like generate/validate: never overwrite a good sidecar with nothing.
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
            'source': '%s (%s agenda HTML)' % (place['name'], cfg.get('platform')),
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
    ap.add_argument('--slug', help='one place (default: all Granicus places)')
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
                    help='classify from --text-cache instead of fetching. With '
                         '--reclassify this re-tags the whole history offline after '
                         'a taxonomy change, with no fetches; meetings absent from '
                         'the cache keep their prior tags')
    args = ap.parse_args()

    if args.from_text_cache and not args.text_cache:
        ap.error('--from-text-cache needs --text-cache DIR to read from')

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')

    # One place's failure is contained to that place, and local-flags.json is
    # written as each place finishes — see lib/enrich_runner.py for the run this
    # cost us.
    # Writable only when we are the ones fetching: a --from-text-cache run reads
    # the corpus and must not half-populate it.
    text_cache = open_cache(args.text_cache, writable=not args.from_text_cache)
    done, failed = run_places(
        granicus_places(args.slug), DATA_DIR,
        lambda place, cfg: enrich_place(place, cfg, since, args.limit,
                                        reclassify=args.reclassify,
                                        text_cache=text_cache,
                                        from_text_cache=args.from_text_cache))
    if text_cache is not None and text_cache.flush():
        print('text cache: %s' % text_cache.stats())
    sys.exit(report(done, failed, DATA_DIR))


if __name__ == '__main__':
    main()
