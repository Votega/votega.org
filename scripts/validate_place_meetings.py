#!/usr/bin/env python3
"""Validate generated local-government meeting JSON before it is committed.

The source is scraped, so the real failure mode is silent: a place reskins its
site, the adapter matches nothing (or garbage), and a valid-but-empty/wrong file
gets committed. This guard makes that loud. It runs in update-local-government.yml
and can be run locally after the generator.

Checks per place file (assets/data/local-<slug>-meetings.json):
  - structural: metadata / bodies / meetings present, metadata.count == len(meetings)
  - non-empty, and count >= --min-meetings (default 1)
  - each meeting: body set, date is YYYY-MM-DD, has an agenda or minutes URL
  - link liveness: a small sample of file URLs return HTTP 200
  - coverage: warn (not fail) on a registry body absent from the file

Usage:
    python scripts/validate_place_meetings.py [--slug newton] [--min-meetings N]
                                              [--sample N] [--no-network]

Exits 1 on any hard failure.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date

import yaml

sys.path.insert(0, os.path.dirname(__file__))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
DATA_DIR = os.path.join(ROOT, 'assets', 'data')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TODAY = date.today().isoformat()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return the 3xx response instead of following it."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def link_alive(url, timeout=25, retries=2):
    """Redirect-AWARE liveness check: judge a link by its first response (and,
    for a 3xx, its Location) rather than following the redirect.

    This matters for Granicus ViewPublisher agenda/minutes links, which 302 to a
    document on `granicus_production_attachments.s3.amazonaws.com` — a bucket name
    with underscores, so the host fails TLS hostname verification in Python's
    urllib (browsers/curl accept it). Following the redirect would spuriously mark
    a perfectly good link dead. A missing meeting instead 302s to
    /core/error/NotFound.aspx, so the redirect *target* is the real signal.

    Alive = a 2xx, or a 3xx whose Location is not an error page. Direct-file
    platforms (Legistar/CivicClerk PDFs) are unaffected: they return 200.
    Retries on 5xx / network error per the repo's HTTP policy; 4xx is dead.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={'User-Agent': 'votega.org/1.0'})
    for attempt in range(retries + 1):
        try:
            resp = opener.open(req, timeout=timeout)
            code, loc = resp.getcode(), resp.headers.get('Location')
        except urllib.error.HTTPError as e:
            code, loc = e.code, e.headers.get('Location')
        except Exception:
            code, loc = None, None
        if code is not None:
            if 200 <= code < 300:
                return True
            if 300 <= code < 400:
                return not (loc and '/core/error/' in loc.lower())
            if code < 500:
                return False  # 4xx: non-retryable, dead
        if attempt < retries:  # None (network) or 5xx: retry
            time.sleep(3)
    return False
# Kept in sync with generate_place_meetings.py. Platforms with a scraper adapter…
ADAPTER_PLATFORMS = {'civicplus', 'corecode', 'civicclerk', 'legistar', 'teammunicode',
                     'primegov', 'granicus', 'gwinnett', 'iqm2'}
# …and recognized platforms/markers we have NO scraper for (unknown + bespoke CMSs
# like Revize/Wix/WordPress): they produce no JSON, so there is nothing to validate
# and they are skipped silently. A value in neither set is a likely typo → warned.
# (`granicus` is a scraped adapter — the ViewPublisher portal — so it lives above.)
NO_SCRAPER_PLATFORMS = {'unknown', 'custom', 'revize', 'wix', 'wordpress',
                        'governmentwindow'}


def _norm(name):
    return ' '.join((name or '').lower().split())


def check_place(place, min_meetings, sample, network):
    slug = place['slug']
    cfg = (place.get('domains') or {}).get('meetings')
    if not cfg:
        return [], []  # no meetings domain — nothing to validate
    platform = cfg.get('platform')
    if not platform or platform in NO_SCRAPER_PLATFORMS:
        # schedule / agendas_url-only, or a recognized no-scraper platform
        # (`unknown`, Revize, Wix, …) — nothing scraped, skip silently.
        return [], []
    if platform not in ADAPTER_PLATFORMS:
        # Not an adapter platform AND not a recognized no-scraper one — likely a
        # typo; nudge so it gets fixed (or registered in NO_SCRAPER_PLATFORMS).
        return [], ['%s: unrecognized meetings platform %r — no scraper, skipping'
                    % (slug, platform)]

    path = os.path.join(DATA_DIR, 'local-%s-meetings.json' % slug)
    errors, warnings = [], []

    if not os.path.exists(path):
        # A missing file means the scrape never produced output (a newly-added or
        # mis-configured place). generate_place_meetings.py already warns loudly on
        # that, so keep it a WARNING here rather than hard-failing the whole run —
        # a broken *existing* file (stale / dead links / schema) still errors below.
        return [], ['%s: no meetings file yet (%s) — scrape has not produced output'
                    % (slug, os.path.basename(path))]

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    meta = data.get('metadata') or {}
    meetings = data.get('meetings')
    bodies = data.get('bodies')

    if not isinstance(meetings, list):
        return ['%s: "meetings" missing or not a list' % slug], []
    if not isinstance(bodies, list):
        errors.append('%s: "bodies" missing or not a list' % slug)

    if len(meetings) < min_meetings:
        errors.append('%s: %d meeting(s) < minimum %d'
                      % (slug, len(meetings), min_meetings))
    if meta.get('count') != len(meetings):
        errors.append('%s: metadata.count %r != %d meetings'
                      % (slug, meta.get('count'), len(meetings)))
    for field in ('generatedAt', 'source', 'sourceUrl', 'place'):
        if not meta.get(field):
            errors.append('%s: metadata.%s missing' % (slug, field))

    for i, m in enumerate(meetings):
        where = '%s meeting[%d]' % (slug, i)
        if not m.get('body'):
            errors.append('%s: body missing' % where)
        if not DATE_RE.match(m.get('date') or ''):
            errors.append('%s: bad date %r' % (where, m.get('date')))
        # A meeting is a usable record if it links ANY artifact. Most platforms
        # publish agendas/minutes; CoreCode (Covington) publishes minutes + video
        # only, and the newest meetings may have just the video until minutes post.
        # EXCEPTION: an UPCOMING meeting (date today or later) legitimately has no
        # documents yet — it is surfaced as a scheduled meeting, not an error.
        date = m.get('date') or ''
        is_upcoming = DATE_RE.match(date) and date >= _TODAY
        if not (m.get('agendaUrl') or m.get('minutesUrl') or m.get('videoUrl')) \
                and not is_upcoming:
            errors.append('%s: no agenda, minutes, or video URL' % where)

    present = {_norm(b) for b in (bodies or [])}
    for b in (cfg.get('bodies') or {}):
        if _norm(b) not in present:
            warnings.append('%s: registry body absent from output: %s' % (slug, b))

    if network and meetings:
        urls = []
        for m in meetings:
            urls += [u for u in (m.get('agendaUrl'), m.get('minutesUrl')) if u]
            if len(urls) >= sample:
                break
        for url in urls[:sample]:
            if link_alive(url):
                print('  ok: %s' % url)
            else:
                errors.append('%s: dead link %s' % (slug, url))

    print('%s: %d meetings, %d bodies%s'
          % (slug, len(meetings), len(bodies or []),
             '' if not warnings else ' (%d warning(s))' % len(warnings)))
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='only validate this place')
    ap.add_argument('--min-meetings', type=int, default=1)
    ap.add_argument('--sample', type=int, default=3,
                    help='file links to liveness-check per place')
    ap.add_argument('--no-network', action='store_true',
                    help='skip link-liveness checks (offline/CI-lite)')
    args = ap.parse_args()

    with open(REGISTRY, encoding='utf-8') as f:
        places = (yaml.safe_load(f) or {}).get('places', [])
    if args.slug:
        places = [p for p in places if p['slug'] == args.slug]
        if not places:
            sys.exit('No place with slug %r' % args.slug)

    all_errors, all_warnings = [], []
    for place in places:
        errors, warnings = check_place(
            place, args.min_meetings, args.sample, not args.no_network)
        all_errors += errors
        all_warnings += warnings

    for w in all_warnings:
        print('WARNING: %s' % w)
    if all_errors:
        print('\n%d error(s):' % len(all_errors))
        for e in all_errors:
            print('  - %s' % e)
        sys.exit(1)
    print('\nAll place meeting files valid.')


if __name__ == '__main__':
    main()
