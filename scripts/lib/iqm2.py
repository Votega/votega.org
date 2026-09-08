#!/usr/bin/env python3
"""Adapter for IQM2 (Accela / Granicus "Meeting Manager") Citizens portals.

Distinct from Granicus ViewPublisher (`lib/granicus.py`) and Legistar
(`lib/legistar.py`): IQM2 is the older Accela product Granicus acquired, served at
`<sub>.iqm2.com/Citizens/`. The **Calendar** page is a server-rendered list — one
`<div class="Row MeetingRow">` per meeting — and a single fetch with an explicit
`?From=&To=` range returns the whole window, so no per-meeting detail fetch is
needed:

  * the `RowLink`/icon `title` tooltip carries the full date ("TUESDAY, JANUARY 27,
    2026 6:00 PM") and Board/Type/Status;
  * `<div class="RowDetails">` holds "<Board> - <Meeting type>" (e.g. "Mayor and
    Council - Regular Meeting") — the Board names the body;
  * `<div class="RowRight MeetingLinks">` lists document links as
    `FileOpen.aspx?Type=<t>&ID=<fileId>&Inline=True`, with the type codes:
        14 = Agenda        1  = Agenda Packet   (agenda; prefer 14, fall back to 1)
        15 = Minutes       12 = Minutes Packet  (minutes; prefer 15, fall back to 12)
    Video links are a JS-driven `HiddenDocumentLink` (`href="#"`) — no static URL,
    so videoUrl is left null.

`body` is the Board name (scope/relabel with body_map/body_label). Agenda/minutes
are direct PDFs on the county host, so IQM2 rides the OCR enricher. Regex parsing
keeps this dependency-free, as with the other HTML adapters.

Import from a generator in scripts/:
    from lib.iqm2 import fetch_iqm2_meetings
"""

import datetime as dt
import re
from urllib.parse import urlparse

from lib.http import fetch_bytes

# Each meeting starts at a "Row MeetingRow" div; split on it (rows nest divs, so a
# to-next-marker chunk is exact enough for field extraction).
_ROW_SPLIT = re.compile(r'<div class="Row MeetingRow"', re.I)
_DETAIL_RE = re.compile(r'/Citizens/Detail_Meeting\.aspx\?ID=(\d+)', re.I)
_TITLE_DATE_RE = re.compile(r'title="[A-Za-z]+,\s*([A-Za-z]+)\s+(\d+),\s+(\d{4})', re.I)
_DETAILS_RE = re.compile(r'RowDetails"[^>]*>(.*?)</div>', re.S | re.I)
_FILE_RE = re.compile(r'FileOpen\.aspx\?Type=(\d+)&ID=(\d+)[^"\']*', re.I)
_TAG_RE = re.compile(r'<[^>]+>')

_MONTHS = {}
for _i in range(1, 13):
    _MONTHS[dt.date(2000, _i, 1).strftime('%B').lower()] = _i

_AGENDA_TYPES = ('14', '1')    # Agenda, then Agenda Packet
_MINUTES_TYPES = ('15', '12')  # Minutes, then Minutes Packet


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _file_url(origin, chunk, wanted_types):
    """First FileOpen link in `chunk` whose type is in `wanted_types` (priority
    order). Returns an absolute /Citizens/FileOpen.aspx URL, or None."""
    found = {}
    for m in _FILE_RE.finditer(chunk):
        found.setdefault(m.group(1), m.group(0))
    for t in wanted_types:
        if t in found:
            return '%s/Citizens/%s' % (origin, found[t])
    return None


def _parse_chunk(chunk, origin):
    detail = _DETAIL_RE.search(chunk)
    if not detail:
        return None
    meeting_id = detail.group(1)

    dm = _TITLE_DATE_RE.search(chunk)
    if not dm:
        return None
    month = _MONTHS.get(dm.group(1).lower())
    if not month:
        return None
    iso_date = '%04d-%02d-%02d' % (int(dm.group(3)), month, int(dm.group(2)))

    details = _DETAILS_RE.search(chunk)
    full = _clean(details.group(1)) if details else ''
    body = full.split(' - ', 1)[0].strip() if full else 'Meeting'
    title = full or body

    agenda_url = _file_url(origin, chunk, _AGENDA_TYPES)
    minutes_url = _file_url(origin, chunk, _MINUTES_TYPES)

    # Drop a past meeting with nothing to link to; keep an upcoming one (agenda not
    # posted yet) so scheduled meetings still surface.
    upcoming = iso_date >= dt.date.today().isoformat()
    if not (agenda_url or minutes_url) and not upcoming:
        return None

    return {
        'body': body,
        'date': iso_date,
        'id': meeting_id,
        'title': title,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': None,   # IQM2 video is a JS-driven link, no static URL
        'hasPreviousVersions': False,
    }


def parse_calendar(html, origin):
    meetings, seen = [], set()
    parts = _ROW_SPLIT.split(html)[1:]  # drop the pre-first-row preamble
    for chunk in parts:
        rec = _parse_chunk(chunk, origin)
        if not rec:
            continue
        key = (rec['body'], rec['date'], rec['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings


def fetch_iqm2_meetings(portal_url, years=3, timeout=30):
    """Fetch and parse an IQM2 Citizens Calendar.

    `portal_url` is any URL on the county's IQM2 site (its origin is reused); the
    adapter queries `<origin>/Citizens/Calendar.aspx?From=&To=` over a window of the
    last `years` years through ~13 months out. Returns (meetings, bodies_seen), or
    (None, None) if the page could not be fetched."""
    parsed = urlparse(portal_url)
    origin = '%s://%s' % (parsed.scheme or 'https', parsed.netloc)
    today = dt.date.today()
    frm = (today - dt.timedelta(days=365 * years)).strftime('%m/%d/%Y')
    to = (today + dt.timedelta(days=400)).strftime('%m/%d/%Y')
    url = '%s/Citizens/Calendar.aspx?From=%s&To=%s' % (origin, frm, to)
    raw = fetch_bytes(url, label='IQM2 calendar', timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')
    meetings = parse_calendar(html, origin)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
