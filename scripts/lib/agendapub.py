#!/usr/bin/env python3
"""Adapter for the "agendapub" meeting portal (Hall County).

Hall County's Board of Commissioners agendas run on a small agenda-publishing app
at `agendapub.<host>` (embedded via an iframe on the county's CivicPlus page). It
is NOT CivicPlus AgendaCenter, CivicClerk, or Granicus — its own thing:

  * `GET /api/calendar/?start=YYYY-MM-DD&end=YYYY-MM-DD` returns FullCalendar-style
    events: [{title, start, end, url: "/meeting/<id>"}]. `title` is the meeting
    type (all Board of Commissioners here), `start` the date.
  * `GET /meeting/<id>` is an HTML detail page linking the documents as direct PDFs
    on DigitalOcean Spaces (`…/media/pdfs/…`), labelled Agenda / Packet / Minutes.

So it's a calendar call plus one detail fetch per meeting — heavier than the
single-request adapters, hence a `months` window (default 15) to bound it. `body`
is the event title; a single-body county folds it with body_label. Video isn't
exposed (videoUrl null).

Import from a generator in scripts/:
    from lib.agendapub import fetch_agendapub_meetings
"""

import datetime as dt
import re
from urllib.parse import urlparse

from lib.http import fetch_bytes, fetch_json

DEFAULT_MONTHS = 15

_PDF_A_RE = re.compile(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_MEETING_ID_RE = re.compile(r'/meeting/(\d+)')


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _classify_docs(html):
    """(agenda_url, minutes_url) from a meeting-detail page. Prefers the standalone
    Agenda, falls back to the Packet; Minutes by label/filename."""
    agenda = packet = minutes = None
    for href, label in _PDF_A_RE.findall(html):
        t = (_clean(label) + ' ' + href).lower()
        if 'minute' in t:
            minutes = minutes or href
        elif 'packet' in t:
            packet = packet or href
        elif 'agenda' in t:
            agenda = agenda or href
    return (agenda or packet), minutes


def fetch_agendapub_meetings(portal_url, months=DEFAULT_MONTHS, timeout=30):
    """Fetch and parse an agendapub portal. `portal_url` is any URL on the
    agendapub host (its origin is reused). Windows the calendar to the last
    `months` months (through ~2 months out) and fetches each meeting's detail for
    its document links. Returns (meetings, bodies_seen), or (None, None) if the
    calendar call fails."""
    parsed = urlparse(portal_url)
    origin = '%s://%s' % (parsed.scheme or 'https', parsed.netloc)
    today = dt.date.today()
    start = (today - dt.timedelta(days=30 * months)).isoformat()
    end = (today + dt.timedelta(days=60)).isoformat()

    cal = fetch_json('%s/api/calendar/?start=%s&end=%s' % (origin, start, end),
                     timeout=timeout, label='agendapub calendar')
    if not isinstance(cal, list):
        return None, None

    meetings, seen = [], set()
    for ev in cal:
        url = ev.get('url') or ''
        m = _MEETING_ID_RE.search(url)
        date = (ev.get('start') or '')[:10]
        if not m or len(date) != 10:
            continue
        mid = m.group(1)
        if mid in seen:
            continue
        seen.add(mid)
        body = _clean(ev.get('title')) or 'Meeting'

        raw = fetch_bytes(origin + url, label='agendapub meeting %s' % mid, timeout=timeout)
        agenda_url = minutes_url = None
        if raw is not None:
            agenda_url, minutes_url = _classify_docs(raw.decode('utf-8', errors='replace'))

        upcoming = date >= today.isoformat()
        if not (agenda_url or minutes_url) and not upcoming:
            continue  # past meeting with nothing to link to

        meetings.append({
            'body': body,
            'date': date,
            'id': mid,
            'title': body,
            'agendaUrl': agenda_url,
            'minutesUrl': minutes_url,
            'videoUrl': None,
            'hasPreviousVersions': False,
        })

    meetings.sort(key=lambda x: (x['date'], int(x['id'])), reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
