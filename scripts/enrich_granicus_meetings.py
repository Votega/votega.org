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
light up with no UI change. No poppler/OCR — the source is already text.

Two Granicus quirks handled here:

  * The AgendaViewer redirect points at
    `https://<bucket>.s3.amazonaws.com/...` where the bucket name contains
    underscores (`granicus_production_attachments`). That is an invalid TLS
    hostname, so following the redirect the normal way fails cert verification in
    Python (browsers/curl tolerate it). We rewrite the virtual-hosted URL to the
    **path-style** endpoint `https://s3.amazonaws.com/<bucket>/...`, whose cert
    (`s3.amazonaws.com`) verifies cleanly — no TLS downgrade needed.
  * A missing/unpublished agenda 302s to `/core/error/NotFound.aspx` instead of a
    document; that is detected and skipped (the meeting keeps any prior tags).

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
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.meeting_topics import (  # noqa: E402
    classify, matched_terms, topic_flags, build_summary, flag_entry, write_flags_file,
)

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
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
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
            code2, _, body2 = _get(_path_style(loc), timeout=timeout)
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
    """(place, cfg) for every visible Granicus ViewPublisher place."""
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


def enrich_meeting(meeting, cache, reclassify=False):
    """Classify one meeting's agenda HTML. Returns an enriched record, or None.

    Reuses the cached record when the viewer URL is unchanged (no re-fetch);
    otherwise resolves + downloads the HTML, classifies, and discards the text.

    `reclassify=True` bypasses that cache reuse so a taxonomy change re-tags
    already-cached meetings (the text is not stored, so re-classifying re-fetches).
    """
    mid = meeting.get('id')
    url, kind = text_source(meeting)
    if not url:
        return None

    cached = cache.get(mid)
    if not reclassify and cached and cached.get('textSourceUrl') == url and 'tags' in cached:
        return cached  # unchanged agenda — keep derived tags, skip the fetch

    raw = fetch_agenda_html(url)
    if raw is None:
        print('    %s: agenda fetch failed/unpublished (%s) — skipping' % (mid, kind))
        return cached  # keep any prior derived data rather than dropping the meeting

    text = html_to_text(raw)
    tags = classify(text)
    terms = matched_terms(text)
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
        'textMethod': 'html',
        'textChars': len(text),
        'contentSha256': hashlib.sha256(raw).hexdigest(),
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
    ap.add_argument('--slug', help='one place (default: all Granicus places)')
    ap.add_argument('--months', type=int, default=12, help='look-back window')
    ap.add_argument('--limit', type=int, default=40, help='recent meetings per place')
    ap.add_argument('--reclassify', action='store_true',
                    help='ignore the incremental cache and re-fetch every meeting '
                         'in the window — use once after a taxonomy change so already-'
                         'cached meetings pick up new subject keywords')
    args = ap.parse_args()

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')

    flag_updates = {}
    for place, cfg in granicus_places(args.slug):
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
            rec = enrich_meeting(m, cache, reclassify=args.reclassify)
            if rec:
                enriched.append(rec)

        # Guard like generate/validate: never overwrite a good sidecar with nothing.
        if not enriched:
            print('  WARNING: 0 classified meetings for %s — leaving existing data intact' % slug)
            continue

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
