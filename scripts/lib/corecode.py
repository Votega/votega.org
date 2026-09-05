#!/usr/bin/env python3
"""Adapter for CoreCode CMS city sites (e.g. the City of Covington).

CoreCode is a proprietary PHP CMS (pages are `index.php?section=...`). It has no
feed or API — the second local-government platform, and the one that proves the
adapter boundary: it shares nothing with CivicPlus but normalizes to the SAME
meetings schema, so /local/<slug>/ renders it identically (see
LOCAL-GOVERNMENT-IA.md).

The council-meetings page is a flat HTML table, one <tr> per meeting:
  col 1  the minutes PDF link, or plain "MM/DD/YYYY Meeting COMING SOON" text
  col 2  the Vimeo recording link
No agendas are published, so `agendaUrl` is always None for this platform, and a
meeting is kept when it has minutes OR video. The date is read from the
MM/DD/YYYY cell text — the PDF filenames are inconsistent
(`2026_CityCouncil_0706_Minutes.pdf`, `2024_0903_CouncilMinutes.pdf`, …) and are
not a reliable key.

robots.txt disallows /corecode/*, /conf/*, /albumupload/*, /fckimages/* — but NOT
/ckeditorfiles/ (the minutes PDFs) or the index.php section pages, so this scrape
stays within the site's stated rules.

Import from a generator in scripts/ (the `lib` package resolves when run as
`python scripts/generate_x.py`):

    from lib.corecode import fetch_council_meetings
"""

import re

from lib.http import fetch_bytes

DEFAULT_MEETINGS_PATH = '/index.php?section=Council-Meetings'
BODY = 'City Council'

_ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
_DATE_RE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')
_PDF_RE = re.compile(r'https?://[^"\'> ]*?/ckeditorfiles/files/[^"\'> ]+\.pdf', re.I)
_VIMEO_RE = re.compile(r'https?://(?:www\.)?vimeo\.com/\d+', re.I)


def _https(url):
    return re.sub(r'^http://', 'https://', url or '')


def parse_council_meetings(html):
    """Parse the council-meetings table into normalized meeting dicts.

    One meeting per date (newest first). Rows with no MM/DD/YYYY date (headers)
    and rows with neither a minutes PDF nor a video are skipped.
    """
    meetings = []
    seen = set()
    for m in _ROW_RE.finditer(html):
        row = m.group(1)
        d = _DATE_RE.search(row)
        if not d:
            continue
        mm, dd, yyyy = d.groups()
        iso = '%s-%s-%s' % (yyyy, mm, dd)
        if iso in seen:
            continue

        pdf = _PDF_RE.search(row)
        vid = _VIMEO_RE.search(row)
        minutes_url = _https(pdf.group(0)) if pdf else None
        video_url = _https(vid.group(0)) if vid else None
        if not (minutes_url or video_url):
            continue  # an announced-but-empty row is not a usable record yet

        seen.add(iso)
        meetings.append({
            'body': BODY,
            'date': iso,
            'id': '%s%s%s' % (yyyy, mm, dd),
            'title': 'City Council Meeting',
            'agendaUrl': None,        # CoreCode/Covington publishes no agendas
            'minutesUrl': minutes_url,
            'videoUrl': video_url,
            'hasPreviousVersions': False,
        })

    meetings.sort(key=lambda x: x['date'], reverse=True)
    return meetings


def fetch_council_meetings(base_url, path=DEFAULT_MEETINGS_PATH, timeout=30):
    """Fetch and parse a CoreCode council-meetings page.

    Returns (meetings, bodies_seen). bodies_seen is always [BODY] on success —
    CoreCode sites surface a single council. Returns (None, None) on fetch
    failure so the caller can refuse to overwrite good data with nothing.
    """
    url = base_url.rstrip('/') + path
    raw = fetch_bytes(url, label='%s council meetings' % base_url, timeout=timeout)
    if raw is None:
        return None, None
    meetings = parse_council_meetings(raw.decode('utf-8', errors='replace'))
    return meetings, [BODY]
