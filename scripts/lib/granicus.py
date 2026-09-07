#!/usr/bin/env python3
"""Adapter for Granicus **ViewPublisher** meeting portals.

Granicus (the company) sells several products. `lib.legistar` already covers the
Legistar legislative API (Fulton, DeKalb). This module covers the *other* common
Granicus surface in Georgia counties: the **ViewPublisher** media/agenda portal
at `https://<client>.granicus.com/ViewPublisher.php?view_id=<N>` (Barrow,
Cherokee). It is a plain server-rendered HTML page — no open JSON API — so, like
`lib.civicplus`, we regex the stable boilerplate and keep this dependency-free.

Page structure (confirmed against cherokeega + barrowga):

  * One "Upcoming Events" table plus year-tabbed "archive" tables. The year tabs
    are CSS show/hide, so *every* year's rows are present in the one HTML payload
    — no per-year fetch needed.
  * Every meeting is a `<tr class="listingRow">` with `<td class="listItem">`
    cells. The **Name** cell (`headers="Name"`) carries the body *and* meeting
    type in one string ("Board of Commissioners Regular Meeting", "Planning
    Commission", "Board of Elections and Registration ..."). Like the CivicClerk
    adapter, we put that whole string in `body`; the registry's `body_map` /
    `include_bodies` (see scope_bodies in generate_place_meetings.py) narrows and
    relabels it to the bodies we publish.
  * Links are protocol-relative (`//host/...`): AgendaViewer.php (agenda),
    MinutesViewer.php (minutes), MediaPlayer.php (video, in an onClick).
  * The stable meeting id is `clip_id` (archived rows); upcoming rows use
    `event_id` instead. A row with neither an id nor any file/video link is a
    placeholder (a future meeting with nothing published yet) and is dropped, as
    the other adapters drop link-less rows.

Import from a generator in scripts/:
    from lib.granicus import fetch_granicus_meetings
"""

import datetime as dt
import re
from urllib.parse import urlparse, parse_qs

from lib.http import fetch_bytes

_ROW_RE = re.compile(r'<tr class="listingRow">.*?</tr>', re.S | re.I)
_NAME_RE = re.compile(r'headers="Name"[^>]*>(.*?)</td>', re.S | re.I)
# Date lives in a cell like: July 21, 2026 - 6:00 PM  (month may be abbreviated).
_DATE_RE = re.compile(r'([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})')
_AGENDA_RE = re.compile(r'(//[^"\']*AgendaViewer\.php\?[^"\']+)', re.I)
_MINUTES_RE = re.compile(r'(//[^"\']*MinutesViewer\.php\?[^"\']+)', re.I)
_VIDEO_RE = re.compile(r'(//[^"\']*MediaPlayer\.php\?[^"\']+)', re.I)
_CLIP_RE = re.compile(r'clip_id=(\d+)', re.I)
_EVENT_RE = re.compile(r'event_id=(\d+)', re.I)
_TAG_RE = re.compile(r'<[^>]+>')

_MONTHS = {}
for _i in range(1, 13):
    _dt = dt.date(2000, _i, 1)
    _MONTHS[_dt.strftime('%B').lower()] = _i   # full name
    _MONTHS[_dt.strftime('%b').lower()] = _i   # 3-letter abbreviation


def _clean(text):
    """Strip tags, decode the non-breaking spaces Granicus litters, collapse ws."""
    text = (text or '').replace('&nbsp;', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text)).strip()


def _abs(scheme, url):
    """Protocol-relative //host/... -> absolute; leave already-absolute alone."""
    if url.startswith('//'):
        return '%s:%s' % (scheme, url)
    return url


def _parse_date(text):
    m = _DATE_RE.search(text or '')
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    try:
        return '%04d-%02d-%02d' % (int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def _parse_row(row, scheme):
    name = _NAME_RE.search(row)
    body = _clean(name.group(1)) if name else None
    if not body:
        return None

    date = _parse_date(_clean(row))
    if not date:
        return None

    agenda = _AGENDA_RE.search(row)
    minutes = _MINUTES_RE.search(row)
    video = _VIDEO_RE.search(row)
    agenda_url = _abs(scheme, agenda.group(1)) if agenda else None
    minutes_url = _abs(scheme, minutes.group(1)) if minutes else None
    video_url = _abs(scheme, video.group(1)) if video else None

    clip = _CLIP_RE.search(row)
    event = _EVENT_RE.search(row)
    meeting_id = (clip.group(1) if clip else
                  (event.group(1) if event else None))

    # A row with no id and nothing to link to is a bare placeholder — drop it,
    # matching the other adapters (never publish a meeting with no artifacts).
    if not meeting_id and not (agenda_url or minutes_url or video_url):
        return None

    return {
        'body': body,
        'date': date,
        'id': meeting_id or ('%s-%s' % (date, re.sub(r'\W+', '-', body.lower())[:40])),
        'title': body,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video_url,
        'hasPreviousVersions': False,
    }


def parse_view(html, scheme):
    """Parse one ViewPublisher HTML page into normalized meeting dicts."""
    meetings, seen = [], set()
    for m in _ROW_RE.finditer(html):
        meeting = _parse_row(m.group(0), scheme)
        if not meeting:
            continue
        key = (meeting['body'], meeting['date'], meeting['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(meeting)
    return meetings


def _view_ids_from_url(agendas_url):
    q = parse_qs(urlparse(agendas_url).query)
    vids = q.get('view_id')
    return [int(v) for v in vids if v.isdigit()] if vids else [1]


def fetch_granicus_meetings(agendas_url, view_ids=None, timeout=40):
    """Fetch and normalize a Granicus ViewPublisher portal's meetings.

    `agendas_url` is the ViewPublisher URL from the registry
    (https://<client>.granicus.com/ViewPublisher.php?view_id=<N>); its host and
    view_id are reused. A place that splits bodies across several views can list
    them in `view_ids` (registry key) — each is fetched and merged.

    Returns (meetings, bodies_seen); (None, None) only if the first request
    fails (so the caller never overwrites good data with nothing). Meetings are
    sorted newest-first.
    """
    parsed = urlparse(agendas_url)
    scheme = parsed.scheme or 'https'
    host = '%s://%s' % (scheme, parsed.netloc)
    if not view_ids:
        view_ids = _view_ids_from_url(agendas_url)

    meetings, seen, first = [], set(), True
    for vid in view_ids:
        url = '%s/ViewPublisher.php?view_id=%d' % (host, vid)
        raw = fetch_bytes(url, label='%s ViewPublisher view %d' % (parsed.netloc, vid),
                          timeout=timeout)
        if raw is None:
            if first and not meetings:
                return None, None
            continue  # a later view failing shouldn't discard views already parsed
        first = False
        html = raw.decode('utf-8', errors='replace')
        for meeting in parse_view(html, scheme):
            key = (meeting['body'], meeting['date'], meeting['id'])
            if key in seen:
                continue
            seen.add(key)
            meetings.append(meeting)

    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
