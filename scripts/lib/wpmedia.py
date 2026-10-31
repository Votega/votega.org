#!/usr/bin/env python3
"""Adapter for WordPress counties whose agenda/minutes PDFs live in the media library.

Some WordPress sites (Rockdale) publish no usable list of meetings: the agenda page
is a calendar, and the "minutes" page hands off to a document-library plugin that
loads its rows through a nonce-protected AJAX call. But every PDF the clerk uploads
is a public media item, and WordPress serves those, with a title and upload date, at
`/wp-json/wp/v2/media`. This adapter searches that endpoint for agenda/minutes/packet
files and turns them into meetings.

Dates and agenda/minutes kind are NOT re-derived here. Each media item is rewritten
as an `<a href=source_url>title</a>` link and handed to `lib.pdflinks.parse_page`, so a
wpmedia place gets exactly pdflinks' rules: many date spellings, the `/uploads/YYYY/MM/`
year inference, and SKIP-don't-guess for anything ambiguous (`Oct 25`, month + year
with no day). Titles that only say "Packet" are read as agendas.

The media library holds every committee's files, so `media_bodies` is required: an ordered
list of {match, label} (regex on the title, case-insensitive). The first match labels
the file; files matching none are dropped, which is what keeps SPLOST subcommittees,
water-authority and beautification-board files out of the commissioners' page. Each
body is grouped separately, so two bodies meeting the same day stay two records.

Import from a generator in scripts/:
    from lib.wpmedia import fetch_wpmedia_meetings
"""

import html
import json
import re
from urllib.parse import quote, urlsplit

from lib.http import fetch_bytes
from lib.pdflinks import build_meetings, parse_page

DEFAULT_TERMS = ('minutes', 'agenda', 'packet')
PER_PAGE = 100
MAX_PAGES = 10           # per search term; 1,000 files is far past any county's archive


def _link_html(items):
    """Media items -> a minimal anchor list for pdflinks.parse_page. A 'packet' title
    gets an 'Agenda' label so pdflinks classifies it (it keys off agenda/minute words);
    a title that already says minutes is left alone."""
    out = []
    for it in items:
        title = html.unescape((it.get('title') or {}).get('rendered') or '')
        text = title
        if re.search(r'(?i)packet', title) and not re.search(r'(?i)minute|agenda', title):
            text = title + ' Agenda'
        out.append('<a href="%s">%s</a>' % (html.escape(it['source_url'], quote=True),
                                            html.escape(text)))
    return '\n'.join(out)


def _body_for(title, filename, bodies):
    hay = '%s %s' % (title, filename)
    for rule in bodies:
        if re.search(rule['match'], hay, re.I):
            return rule['label']
    return None


def collect_media(api_base, terms, timeout=40):
    """All PDF media items matching any term, de-duplicated by id. Returns None when
    the first page of any term fails, so a half-read set never overwrites a good one;
    a failure on a LATER page just ends that term (WordPress answers 400 past the end)."""
    seen = {}
    for term in terms:
        for page in range(1, MAX_PAGES + 1):
            url = ('%s/wp-json/wp/v2/media?search=%s&mime_type=application/pdf'
                   '&per_page=%d&page=%d&_fields=id,title,source_url'
                   % (api_base, quote(term), PER_PAGE, page))
            raw = fetch_bytes(url, label='wpmedia %s p%d' % (term, page), timeout=timeout,
                              quiet_statuses=(400,) if page > 1 else ())
            if raw is None:
                if page == 1:
                    return None
                break
            try:
                batch = json.loads(raw.decode('utf-8', errors='replace'))
            except ValueError:
                return None if page == 1 else seen.values()
            for it in batch:
                if it.get('source_url'):
                    seen.setdefault(it['id'], it)
            if len(batch) < PER_PAGE:
                break
    return list(seen.values())


def fetch_wpmedia_meetings(base_url, bodies, terms=None, timeout=40):
    """Fetch and normalize a WordPress media library's agenda/minutes PDFs.

    Returns (meetings, bodies_seen); (None, None) if the API can't be read."""
    if not bodies:
        raise ValueError('wpmedia requires a non-empty `media_bodies` list of {match, label}')
    parts = urlsplit(base_url)
    api_base = '%s://%s' % (parts.scheme, parts.netloc)
    items = collect_media(api_base, list(terms or DEFAULT_TERMS), timeout=timeout)
    if items is None:
        return None, None

    by_body = {}
    dropped = 0
    for it in items:
        fn = it['source_url'].rsplit('/', 1)[-1]
        label = _body_for(html.unescape((it.get('title') or {}).get('rendered') or ''),
                          fn, bodies)
        if label is None:
            dropped += 1
            continue
        by_body.setdefault(label, []).append(it)

    meetings = []
    stats = {}
    for label, group in by_body.items():
        links = parse_page(_link_html(group), base_url + '/', body=label, stats=stats)
        recs = build_meetings(links, body=label)
        if len(by_body) > 1:
            for m in recs:
                m['id'] = '%s-%s' % (m['date'], re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-'))
        meetings.extend(recs)
    meetings.sort(key=lambda m: (m['date'], m['body']), reverse=True)
    print('  wpmedia: %d media PDF(s), %d outside the configured bodies, %d dated link(s) kept, '
          '%d skipped (no usable date), %d skipped (not agenda/minutes)'
          % (len(items), dropped, stats.get('kept', 0), stats.get('skipped_nodate', 0),
             stats.get('skipped_nokind', 0)))
    return meetings, sorted({m['body'] for m in meetings})
