#!/usr/bin/env python3
"""Fingerprint a county/city meeting platform from its website, en masse.

Onboarding a place to the local-government registry means answering two questions
by hand: which meeting platform does it run, and what config does that adapter
need (a Municode cid/ppid, a CivicClerk subdomain, a Granicus view URL, ...).
Doing that in a browser per county is slow, and it has a trap: many counties run
a CivicPlus/Revize CMS whose "Agendas & Minutes" page merely *iframes* the real
portal (e.g. Dawson's CivicPlus site embeds meetings.municode.com). A naive "is
there an /AgendaCenter?" check mislabels those.

This script does the fingerprint in one pass. Given a county URL — its homepage
or its Agendas page — it fetches the page, follows an obvious agenda link and any
iframes, then matches the combined markup against every platform's host/path
signature. Third-party portals are checked BEFORE the CMS platforms, so an
embedded Municode/CivicClerk/Granicus wins over the CivicPlus shell that hosts it.
For each hit it extracts the exact config key the adapter reads (see
generate_place_meetings.fetch_meetings) and prints a ready-to-paste places.yml
stub. With --validate it then runs the matching adapter and prints the meeting
count and body distribution — the table you write `body_map` from.

Usage:
    python scripts/detect_meeting_platform.py URL [URL ...]
    python scripts/detect_meeting_platform.py --file urls.txt        # one URL per line
    python scripts/detect_meeting_platform.py --validate URL         # also run the adapter
    echo https://www.dawsoncountyga.gov/129/Agendas-Minutes | python scripts/detect_meeting_platform.py -

Read-only: it fetches public pages and (with --validate) the adapter's normal
source. It writes nothing — you review each stub before adding it to the registry.
"""

import argparse
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.http import fetch_bytes  # noqa: E402

# ---------------------------------------------------------------------------
# Platform signatures. Order matters: embedded third-party portals first, so a
# CMS page that iframes one of them resolves to the portal, not the CMS shell.
# Each entry: (platform, compiled host/path regex, extractor(match, page_url) -> cfg).
# The extractor returns the domains.meetings config dict (minus schedule/body_map),
# or None to reject a false match.
# ---------------------------------------------------------------------------

def _origin(u):
    p = urllib.parse.urlparse(u if '//' in u else 'https://' + u)
    return '%s://%s' % (p.scheme or 'https', p.netloc)


def _municode(m, page):
    # Keep the whole PublishPage URL — it carries cid + ppid, which the adapter needs.
    url = m.group(0)
    if url.startswith('//'):
        url = 'https:' + url
    # Trim trailing junk / entity-encoded params, normalise &amp;
    url = url.replace('&amp;', '&').rstrip('"\'\\ )')
    if 'cid=' not in url:
        return None
    return {'platform': 'municode', 'agendas_url': url}


def _civicclerk(m, page):
    return {'platform': 'civicclerk', 'subdomain': m.group(1)}


def _legistar(m, page):
    sub = m.group(1)
    if sub in ('webapi', 'www'):
        return None
    return {'platform': 'legistar', 'client': sub}


def _granicus(m, page):
    url = m.group(0).replace('&amp;', '&').rstrip('"\'\\ )')
    if not url.startswith('http'):
        url = 'https://' + url.lstrip('/')
    return {'platform': 'granicus', 'agendas_url': url}


def _iqm2(m, page):
    url = m.group(0).replace('&amp;', '&').rstrip('"\'\\ )')
    if not url.startswith('http'):
        url = 'https://' + url.lstrip('/')
    return {'platform': 'iqm2', 'agendas_url': url}


def _primegov(m, page):
    return {'platform': 'primegov', 'base_url': _origin(m.group(0))}


def _agendapub(m, page):
    return {'platform': 'agendapub', 'agendas_url': _origin(m.group(0))}


def _teammunicode(m, page):
    origin = _origin(m.group(0))
    # teammunicode.com serves the view at /meetings; municodemeetings.com at root.
    path = '/meetings' if 'teammunicode.com' in origin else '/'
    cfg = {'platform': 'teammunicode', 'base_url': origin}
    if path != '/meetings':
        cfg['meetings_path'] = path
    return cfg


SIGNATURES = [
    ('municode', re.compile(r'https?:\\?/\\?/meetings\.municode\.com/PublishPage/[^"\'\s<>]+', re.I), _municode),
    ('civicclerk', re.compile(r'([a-z0-9][a-z0-9-]*)\.(?:portal|api)\.civicclerk\.com', re.I), _civicclerk),
    ('legistar', re.compile(r'([a-z0-9][a-z0-9-]*)\.legistar\.com', re.I), _legistar),
    ('granicus', re.compile(r'https?://[a-z0-9-]+\.granicus\.com/ViewPublisher\.php[^"\'\s<>]*', re.I), _granicus),
    ('iqm2', re.compile(r'https?://[a-z0-9-]+\.iqm2\.com/Citizens/[^"\'\s<>]*', re.I), _iqm2),
    ('primegov', re.compile(r'https?://[a-z0-9-]+\.primegov\.com[^"\'\s<>]*', re.I), _primegov),
    ('agendapub', re.compile(r'https?://agendapub\.[a-z0-9.-]+', re.I), _agendapub),
    ('teammunicode', re.compile(r'https?://[a-z0-9-]+\.(?:teammunicode\.com|municodemeetings\.com)[^"\'\s<>]*', re.I), _teammunicode),
]

# CivicPlus (real Agenda Center, not an empty shell) — only if no portal above hit.
_CIVICPLUS_HINT = re.compile(r'/AgendaCenter|cpTextResizeOn|connect\.civicplus\.com|CivicEngage', re.I)
# Adapter-less CMSs we recognise but can't scrape — flag so time isn't wasted.
_NO_SCRAPER = [
    ('revize', re.compile(r'revize\.com|Revize', re.I)),
    ('governmentwindow', re.compile(r'governmentwindow\.com', re.I)),
    ('boarddocs', re.compile(r'boarddocs\.com|go\.boarddocs', re.I)),
    ('escribe', re.compile(r'escribemeetings\.com|pub-[a-z0-9-]+\.escribe', re.I)),
    ('novusagenda', re.compile(r'novusagenda\.com', re.I)),
    ('wix', re.compile(r'wix\.com|wixsite\.com|_wixCssStates', re.I)),
    ('wordpress', re.compile(r'wp-content|wp-json', re.I)),
]

_IFRAME_RE = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:(?!</a>).){0,120}?'
    r'(?:agenda|minute|meeting)', re.I | re.S)


def _fetch(url, timeout):
    raw = fetch_bytes(url, label='detect %s' % url, timeout=timeout)
    return raw.decode('utf-8', errors='replace') if raw else None


def _candidate_pages(url, html, timeout, max_follow=3):
    """Yield (source_url, html) to scan: the page itself, then its iframes and an
    obvious agenda link (one level deep). Portals are usually iframed, so iframes
    matter most."""
    yield url, html
    followed = 0
    seen = {url}
    # iframes first — the embedded portal lives here.
    targets = _IFRAME_RE.findall(html)
    # then agenda-ish links, in case the input was a homepage.
    targets += [h for h in _LINK_RE.findall(html)]
    for raw_href in targets:
        if followed >= max_follow:
            break
        href = raw_href.replace('&amp;', '&')
        full = urllib.parse.urljoin(url, href)
        if full in seen or full.startswith(('mailto:', 'javascript:', 'tel:')):
            continue
        seen.add(full)
        # A portal host in the iframe src alone is enough — but fetching lets us
        # extract view_ids / confirm. Skip fetching cross-origin portals we can
        # already fingerprint from the src; still yield the src as pseudo-html.
        yield full, href  # href scanned as text (cheap: catches host in src)
        sub = _fetch(full, timeout)
        if sub:
            yield full, sub
        followed += 1


def detect(url, timeout=30):
    """Return a result dict for one URL: platform, config, confidence, evidence."""
    html = _fetch(url, timeout)
    if html is None:
        return {'url': url, 'platform': None, 'error': 'could not fetch'}

    civicplus_seen = None
    for src_url, blob in _candidate_pages(url, html, timeout):
        # Scan the source URL itself alongside its markup: the host of the page
        # you're on is a signal too (an iQM2 / agendapub / primegov portal serves
        # its own list at that host with relative links, so the absolute portal
        # URL never appears in the body).
        hay = (src_url or '') + '\n' + blob
        for platform, rx, extract in SIGNATURES:
            m = rx.search(hay)
            if not m:
                continue
            cfg = extract(m, src_url)
            if cfg:
                return {'url': url, 'platform': platform, 'config': cfg,
                        'confidence': 'high', 'evidence': src_url,
                        'matched': m.group(0)[:100]}
        if civicplus_seen is None and _CIVICPLUS_HINT.search(hay):
            civicplus_seen = src_url

    # No third-party portal. CivicPlus Agenda Center, if it's real.
    if civicplus_seen is not None:
        base = _origin(url)
        return {'url': url, 'platform': 'civicplus',
                'config': {'platform': 'civicplus', 'base_url': base},
                'confidence': 'medium',
                'evidence': civicplus_seen,
                'note': 'CivicPlus AgendaCenter — VALIDATE: confirm it is populated, '
                        'not an empty shell iframing another portal.'}

    for name, rx in _NO_SCRAPER:
        if rx.search(html):
            return {'url': url, 'platform': None, 'recognized': name,
                    'confidence': 'n/a',
                    'note': 'Recognized %s — no adapter. Lists PDFs; would need a '
                            'bespoke adapter or manual handling.' % name}
    return {'url': url, 'platform': None, 'note': 'No known platform fingerprint found.'}


# ---------------------------------------------------------------------------
# Optional validation: run the matching adapter, print counts + body table.
# ---------------------------------------------------------------------------

def validate(cfg, timeout=40):
    from generate_place_meetings import fetch_meetings  # reuse the real dispatch
    meetings, bodies = fetch_meetings(cfg)
    return meetings, bodies


def _print_bodies(meetings):
    import collections
    import datetime
    recent_cut = (datetime.date.today() - datetime.timedelta(days=548)).isoformat()
    allc = collections.Counter(m['body'] for m in meetings)
    rec = collections.Counter(m['body'] for m in meetings if m['date'] >= recent_cut)
    print('    %-46s %5s %10s' % ('BODY', 'all', 'last~18mo'))
    for b, n in allc.most_common():
        print('    %-46s %5d %10d' % (b[:46], n, rec.get(b, 0)))


def _emit_stub(res):
    cfg = res['config']
    print('  # platform: %s   confidence: %s   evidence: %s'
          % (res['platform'], res.get('confidence'), res.get('evidence')))
    print('      meetings:')
    for k in ('platform', 'base_url', 'subdomain', 'client', 'agendas_url', 'meetings_path'):
        if k in cfg:
            print('        %s: %s' % (k, ('"%s"' % cfg[k]) if k != 'platform' else cfg[k]))
    if res.get('note'):
        print('        # NOTE: %s' % res['note'])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('urls', nargs='*', help='county URLs (homepage or Agendas page)')
    ap.add_argument('--file', help='read URLs from a file, one per line')
    ap.add_argument('--validate', action='store_true',
                    help='run the matched adapter and print meeting count + body table')
    ap.add_argument('--timeout', type=int, default=30)
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding='utf-8') as fh:
            urls += [ln.strip() for ln in fh if ln.strip() and not ln.startswith('#')]
    if urls == ['-'] or (not urls and not sys.stdin.isatty()):
        urls = [ln.strip() for ln in sys.stdin if ln.strip() and not ln.startswith('#')]
    if not urls:
        ap.error('no URLs given (pass URLs, --file, or pipe them on stdin)')

    summary = []
    for url in urls:
        print('\n=== %s ===' % url)
        res = detect(url, timeout=args.timeout)
        if not res.get('platform'):
            tag = res.get('recognized') or res.get('error') or 'unknown'
            print('  NO ADAPTER: %s' % (res.get('note') or tag))
            summary.append((url, 'none/%s' % tag, ''))
            continue
        _emit_stub(res)
        counts = ''
        if args.validate:
            try:
                meetings, _ = validate(res['config'], timeout=max(args.timeout, 40))
            except Exception as e:  # noqa: BLE001 — a bad guess shouldn't kill the batch
                print('  VALIDATE ERROR: %s' % e)
                meetings = None
            if meetings:
                print('  VALIDATED: %d meetings' % len(meetings))
                _print_bodies(meetings)
                counts = '%d mtgs' % len(meetings)
            elif meetings is not None:
                print('  VALIDATE: adapter returned 0 meetings — likely wrong guess '
                      'or client-rendered; check manually.')
                counts = '0 mtgs'
        summary.append((url, res['platform'], counts))

    print('\n\n===== SUMMARY =====')
    for url, plat, counts in summary:
        print('  %-55s %-14s %s' % (url[:55], plat, counts))


if __name__ == '__main__':
    main()
