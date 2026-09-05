#!/usr/bin/env python3
"""Adapter for CivicClerk meeting portals (a CivicPlus product).

The *newer* CivicPlus platform renders its Agenda Center in JavaScript, so the
classic HTML scrape (lib/civicplus.py) gets nothing. Those counties run meetings
on CivicClerk instead — `<sub>.portal.civicclerk.com`, backed by an OPEN OData
JSON API at `<sub>.api.civicclerk.com/v1/Events`. No HTML scraping, no key. One
adapter covers every CivicClerk jurisdiction (Douglas, Cobb, Henry, … and many
GA counties statewide) — see LOCAL-GOVERNMENT-IA.md.

API shape (confirmed against douglascountyga):
  GET /v1/Events?$orderby=startDateTime desc&$filter=startDateTime lt <cap>
    → paged (~15/page) via `@odata.nextLink`. Each event has:
        categoryName    the governing body ("Board Of Commissioners")
        startDateTime   ISO-8601 UTC
        eventName       human title
        youtubeVideoId  recording (may be "")
        publishedFiles  [ {fileId, type: "Agenda"|"Minutes"|"Agenda Packet"|…,
                           name, url, sort} ]
  A file downloads from:
        /v1/Meetings/GetMeetingFileStream(fileId=<id>,plainText=false)   (application/pdf)

Normalized to the shared meetings schema. Only events carrying an agenda,
minutes, or video are kept — CivicClerk pre-creates future placeholder events
with no files, which are not usable records yet (same rule as lib/corecode.py).

Import from a generator in scripts/:
    from lib.civicclerk import fetch_civicclerk_meetings
"""

import datetime as dt
from urllib.parse import quote

from lib.http import fetch_json


def api_base(subdomain):
    return 'https://%s.api.civicclerk.com' % subdomain


def portal_url(subdomain):
    return 'https://%s.portal.civicclerk.com/' % subdomain


def _file_url(subdomain, file_id):
    return ('%s/v1/Meetings/GetMeetingFileStream(fileId=%s,plainText=false)'
            % (api_base(subdomain), file_id))


def _video_url(youtube_id):
    yt = (youtube_id or '').strip()
    return 'https://www.youtube.com/watch?v=%s' % yt if yt else None


def _event_to_meeting(subdomain, e):
    body = (e.get('categoryName') or '').strip() or 'Meeting'
    sdt = e.get('startDateTime') or ''
    date = sdt[:10] if len(sdt) >= 10 else None
    if not date:
        return None

    files = e.get('publishedFiles') or []
    agenda_url = minutes_url = None
    for f in files:
        t = (f.get('type') or '').strip().lower()
        fid = f.get('fileId')
        if not fid:
            continue
        if t == 'agenda' and agenda_url is None:
            agenda_url = _file_url(subdomain, fid)
        elif t == 'minutes' and minutes_url is None:
            minutes_url = _file_url(subdomain, fid)
    # Fall back to an "Agenda Packet" when no plain Agenda was published.
    if agenda_url is None:
        for f in files:
            if (f.get('type') or '').strip().lower().startswith('agenda') and f.get('fileId'):
                agenda_url = _file_url(subdomain, f['fileId'])
                break

    video_url = _video_url(e.get('youtubeVideoId'))
    if not (agenda_url or minutes_url or video_url):
        return None

    return {
        'body': body,
        'date': date,
        'id': str(e.get('id')),
        'title': (e.get('eventName') or body).strip(),
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video_url,
        'hasPreviousVersions': False,
    }


def fetch_civicclerk_meetings(subdomain, years=4, timeout=30, max_pages=80):
    """Fetch and normalize a CivicClerk portal's meetings.

    Pulls recent-first, bounded to the last `years` years (CivicClerk archives
    run back a decade) and dropping far-future placeholder events. Returns
    (meetings, bodies_seen); (None, None) only if the very first request fails —
    a later page failure returns what was gathered so a transient blip near the
    tail of the archive does not wipe the recent, important data.
    """
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=365 * years)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cap = (now + dt.timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # NB: do NOT send $top — CivicClerk treats it as a cap on the TOTAL result
    # set (the nextLink counts it down), so any $top silently truncates the
    # archive. Omitting it lets the server page the full set via @odata.nextLink
    # at its own page size (~15).
    order = quote('startDateTime desc')
    filt = quote('startDateTime lt %s' % cap)
    url = '%s/v1/Events?%%24orderby=%s&%%24filter=%s' % (
        api_base(subdomain), order, filt)

    meetings, seen, bodies = [], set(), set()
    pages = 0
    while url and pages < max_pages:
        data = fetch_json(url, timeout=timeout,
                          label='%s civicclerk events' % subdomain)
        if data is None:
            if pages == 0:
                return None, None
            break  # keep what we have from earlier pages
        pages += 1

        stop = False
        for e in data.get('value', []):
            sdt = e.get('startDateTime') or ''
            if sdt and sdt < cutoff:
                stop = True  # desc order: everything after this is older too
                continue
            m = _event_to_meeting(subdomain, e)
            if not m:
                continue
            key = (m['body'], m['date'], m['id'])
            if key in seen:
                continue
            seen.add(key)
            meetings.append(m)
            bodies.add(m['body'])
        if stop:
            break
        url = data.get('@odata.nextLink')

    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings, sorted(bodies)
