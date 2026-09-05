#!/usr/bin/env python3
"""Adapter for CivicPlus / CivicEngage county websites.

Today this covers one thing: the **Agenda Center** (public meeting agendas,
minutes, and linked video). CivicPlus exposes two access paths and this module
deliberately prefers the second:

  RSS   /RSSFeed.aspx?ModID=65&CID=<Body>-<catId>
        Clean XML, but *recent-only* (a "latest agendas" feed, a handful of
        items), the <link> points at PreviousVersions rather than the file, and
        it carries no agenda-vs-minutes distinction or reliable body field. Some
        bodies return an empty feed even when the Agenda Center HTML lists their
        meetings (observed on Newton's Board of Commissioners). Insufficient on
        its own.

  HTML  /AgendaCenter
        Fully server-rendered and complete: every body is a collapsible panel
        headed by an <h2 data-cp-toggle>, and every meeting is a
        <tr class="catAgendaRow"> carrying explicit
        /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-<id> and .../Minutes/... links.
        This is the authoritative source, so it is what we parse.

The markup is stable CivicPlus boilerplate, so regex parsing (as in
generate_ga_executive_orders.py) is appropriate and keeps this dependency-free.
If CivicPlus reskins, scripts/validate_county_meetings.py is what catches it.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`, so the `lib` package resolves):

    from lib.civicplus import fetch_agenda_center
"""

import re

from lib.http import fetch_bytes

AGENDA_MODULE_ID = 65

# A meeting row: <tr ... class="catAgendaRow"> ... </tr>. Rows are flat (no
# nested <tr>), so a non-greedy match to the first </tr> is exact.
_ROW_RE = re.compile(r'<tr[^>]*class="catAgendaRow".*?</tr>', re.S | re.I)
# Collapsible body headers, in document order. Rows belong to the header above them.
_HEADER_RE = re.compile(r'<h2[^>]*data-cp-toggle[^>]*>(.*?)</h2>', re.S | re.I)
# A ViewFile link classifies the file (Agenda|Minutes) and carries _MMDDYYYY-<id>.
_VIEWFILE_RE = re.compile(
    r'/AgendaCenter/ViewFile/(Agenda|Minutes)/(_(\d{2})(\d{2})(\d{4})-(\d+))', re.I)
_PREVVERS_RE = re.compile(r'/AgendaCenter/PreviousVersions/\d+', re.I)
_VIDEO_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/[^"\'<> ]+', re.I)
# Text of the agenda link, used as a human label ("BOC Agenda").
_AGENDA_LINK_TEXT_RE = re.compile(
    r'<a[^>]*ViewFile/Agenda[^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')


def _clean(text):
    """Strip tags and collapse whitespace to a single line."""
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _abs(base_url, path):
    return base_url.rstrip('/') + path


def _header_positions(html):
    """[(char_offset, body_name), ...] in document order."""
    return [(m.start(), _clean(m.group(1))) for m in _HEADER_RE.finditer(html)]


def _body_for(offset, headers):
    body = None
    for pos, name in headers:
        if pos < offset:
            body = name
        else:
            break
    return body


def _parse_row(row, base_url, body):
    files = _VIEWFILE_RE.findall(row)
    if not files:
        return None  # a row with no downloadable file is not a usable record

    agenda_url = minutes_url = None
    meeting_id = iso_date = None
    for kind, token, mm, dd, yyyy, num in files:
        url = _abs(base_url, '/AgendaCenter/ViewFile/%s/%s' % (kind, token))
        if kind.lower() == 'agenda' and agenda_url is None:
            agenda_url = url
        elif kind.lower() == 'minutes' and minutes_url is None:
            minutes_url = url
        # date + id come from the token; agenda and minutes of one meeting share it
        if iso_date is None:
            iso_date, meeting_id = '%s-%s-%s' % (yyyy, mm, dd), num

    link_text = _AGENDA_LINK_TEXT_RE.search(row)
    label = _clean(link_text.group(1)) if link_text else None
    video = _VIDEO_RE.search(row)

    return {
        'body': body,
        'date': iso_date,
        'id': meeting_id,
        'title': label,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video.group(0) if video else None,
        'hasPreviousVersions': bool(_PREVVERS_RE.search(row)),
    }


def parse_agenda_center(html, base_url):
    """Parse Agenda Center HTML into a list of normalized meeting dicts.

    Meetings are sorted newest-first (date desc, then id desc). Bodies come from
    the panel header each row sits under.
    """
    headers = _header_positions(html)
    meetings = []
    seen = set()
    for m in _ROW_RE.finditer(html):
        meeting = _parse_row(m.group(0), base_url, _body_for(m.start(), headers))
        if not meeting or not meeting['date']:
            continue
        key = (meeting['body'], meeting['date'], meeting['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(meeting)

    meetings.sort(key=lambda x: (x['date'], int(x['id'])), reverse=True)
    return meetings


def fetch_agenda_center(base_url, module_id=AGENDA_MODULE_ID, timeout=30):
    """Fetch and parse a county's Agenda Center. Returns (meetings, bodies_seen).

    Returns (None, None) if the page could not be fetched — the caller decides
    whether a fetch failure should abort (it should: never overwrite good data
    with nothing).
    """
    url = _abs(base_url, '/AgendaCenter')
    raw = fetch_bytes(url, label='%s Agenda Center' % base_url, timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')
    meetings = parse_agenda_center(html, base_url)
    bodies_seen = [name for _, name in _header_positions(html)]
    return meetings, bodies_seen
