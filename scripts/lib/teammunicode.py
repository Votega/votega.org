#!/usr/bin/env python3
"""Adapter for Municode "Meetings" (teammunicode.com).

Some GA counties (Banks) run their public meetings on Municode's meetings portal —
a Drupal 7 site, often embedded via an iframe on the county's CivicPlus page, so
the CivicPlus Agenda Center itself is a near-empty stub and this is the real
source. The `/meetings` page is a server-rendered table (a Drupal view); each
<tr> carries:

  * an ISO calendar date  (<span class="date-display-single" content="…">)
  * a Meeting title       (<td class="views-field-title">) — which names the body
  * Agenda / Packet / Minutes / Video document links, one per column, as direct
    PDF URLs (hosted on an Azure blob store). One row already carries every
    document type, so — unlike CivicPlus — there is nothing to de-duplicate.

Markup is stable Drupal-view boilerplate, so regex parsing keeps this dependency-
free (same approach as lib/civicplus.py). Output is the shared normalized schema:
  {body, date, id, title, agendaUrl, minutesUrl, videoUrl, hasPreviousVersions}
`body` is set to the meeting title (the body name lives in it), so a place scopes
with body_map / include_bodies exactly like the CivicClerk places (Cobb, Douglas).

Import from a generator in scripts/ (sys.path[0] is scripts/):
    from lib.teammunicode import fetch_teammunicode_meetings
"""

import re
from datetime import date, timezone, datetime

from lib.http import fetch_bytes

_TAG_RE = re.compile(r'<[^>]+>')
# Flat table rows; a meeting row is one that carries a calendar date.
_ROW_RE = re.compile(r'<tr[^>]*>.*?</tr>', re.S | re.I)
_DATE_RE = re.compile(r'date-display-single[^>]*content="([^"]+)"', re.I)
_TITLE_RE = re.compile(r'views-field-title[^>]*>(.*?)</td>', re.S | re.I)
_DETAIL_RE = re.compile(r'/([a-z0-9][a-z0-9-]*)/page/([a-z0-9-]+)', re.I)
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
_VIDEO_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/[^"\'<> ]+', re.I)


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _cell(row, field):
    """First href inside the <td class="views-field-<field>"> cell, or None."""
    m = re.search(r'views-field-%s[^>]*>(.*?)</td>' % re.escape(field), row, re.S | re.I)
    if not m:
        return None
    h = _HREF_RE.search(m.group(1))
    return h.group(1) if h else None


def _parse_row(row):
    date_m = _DATE_RE.search(row)
    title_m = _TITLE_RE.search(row)
    if not date_m or not title_m:
        return None  # not a meeting row (e.g. an alerts/other view)
    title = _clean(title_m.group(1))
    if not title:
        return None
    iso_date = date_m.group(1)[:10]  # YYYY-MM-DD from the ISO datetime
    detail = _DETAIL_RE.search(row)
    slug = detail.group(2) if detail else None
    num = re.search(r'-(\d+)$', slug or '')
    meeting_id = num.group(1) if num else (slug or iso_date)

    # Prefer the standalone Agenda; fall back to the Agenda Packet.
    agenda_url = _cell(row, 'field-agendas') or _cell(row, 'field-packets')
    minutes_url = _cell(row, 'field-minutes')
    video = _VIDEO_RE.search(_cell(row, 'field-video-link') or '') \
        or _VIDEO_RE.search(row)
    # Keep a document-less row only if it is UPCOMING (a scheduled meeting whose
    # agenda isn't posted yet — useful to surface); drop a PAST doc-less row, which
    # is just noise (nothing to link to). The UI derives "upcoming" from the date.
    upcoming = iso_date >= date.today().isoformat()
    if not (agenda_url or minutes_url or video) and not upcoming:
        return None
    return {
        'body': title,          # names the body; a place scopes via body_map
        'date': iso_date,
        'id': str(meeting_id),
        'title': title,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video.group(0) if video else None,
        'hasPreviousVersions': False,
    }


def parse_meetings(html):
    """Parse the /meetings table into normalized meeting dicts, newest-first."""
    meetings = []
    seen = set()
    for m in _ROW_RE.finditer(html):
        rec = _parse_row(m.group(0))
        if not rec:
            continue
        key = (rec['body'], rec['date'], rec['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings


def fetch_teammunicode_meetings(base_url, timeout=30):
    """Fetch and parse a county's Municode meetings table.

    Returns (meetings, bodies_seen), or (None, None) if the page could not be
    fetched — the caller decides whether a fetch failure should abort (it should:
    never overwrite good data with nothing)."""
    url = base_url.rstrip('/') + '/meetings'
    raw = fetch_bytes(url, label='%s meetings' % base_url, timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')
    meetings = parse_meetings(html)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
