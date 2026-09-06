#!/usr/bin/env python3
"""Adapter for Legistar (Granicus) meeting portals.

Legistar — a Granicus product — powers large jurisdictions. In metro Atlanta it
backs Fulton and DeKalb; statewide/nationally it also runs the City of Atlanta,
MARTA, and many others, so this one adapter has broad reach (see
LOCAL-GOVERNMENT-IA.md).

Its Web API is open JSON, no key (confirmed against fulton + dekalbcountyga):
  GET https://webapi.legistar.com/v1/<client>/Events
      ?$orderby=EventDate desc&$filter=EventDate ge datetime'YYYY-MM-DD'
  Returns a FLAT array (OData v3; page with $top/$skip — no @odata.nextLink).
  Each event carries clean fields:
    EventBodyName    the governing body ("Board of Commissioners","Planning Commission")
    EventDate        ISO date at midnight; EventTime is separate ("10:00 AM")
    EventAgendaFile  direct agenda PDF URL (or null)   <- no download indirection
    EventMinutesFile direct minutes PDF URL (or null)
    EventVideoPath   recording (usually null on these clients)
    EventInSiteURL   the meeting detail page

Normalized to the shared meetings schema; agenda/minutes are already downloadable
URLs. Only events with an agenda, minutes, or video are kept (future placeholder
meetings with none are skipped, as with the other adapters).

Import from a generator in scripts/:
    from lib.legistar import fetch_legistar_meetings
"""

import datetime as dt
from urllib.parse import quote

from lib.http import fetch_json


def api_base(client):
    return 'https://webapi.legistar.com/v1/%s' % client


def portal_url(client):
    return 'https://%s.legistar.com/Calendar.aspx' % client


def _event_to_meeting(e):
    body = (e.get('EventBodyName') or '').strip() or 'Meeting'
    sdt = e.get('EventDate') or ''
    date = sdt[:10] if len(sdt) >= 10 else None
    if not date:
        return None

    agenda = e.get('EventAgendaFile') or None
    minutes = e.get('EventMinutesFile') or None
    video = e.get('EventVideoPath') or None
    if not (agenda or minutes or video):
        return None

    return {
        'body': body,
        'date': date,
        # EventBodyName doubles as the title so a relabeled body (via body_map)
        # still shows its original meeting type (e.g. "Committee of the Whole").
        'title': body,
        'id': str(e.get('EventId')),
        'agendaUrl': agenda,
        'minutesUrl': minutes,
        'videoUrl': video,
        'hasPreviousVersions': False,
    }


def fetch_events(client, since, timeout=40):
    """Raw Event rows (dicts) since `since` (YYYY-MM-DD), newest first — includes
    EventInSiteURL for sourcing. Used by the enrichment prototype."""
    order = quote('EventDate desc')
    filt = quote("EventDate ge datetime'%s'" % since)
    url = '%s/Events?%%24orderby=%s&%%24filter=%s' % (api_base(client), order, filt)
    data = fetch_json(url, timeout=timeout, label='%s events' % client)
    return data if isinstance(data, list) else []


def fetch_event_items(client, event_id, timeout=40):
    """Structured agenda items for a meeting (topics, matter type, pass/fail)."""
    url = '%s/Events/%s/EventItems' % (api_base(client), event_id)
    data = fetch_json(url, timeout=timeout, label='%s event %s items' % (client, event_id))
    return data if isinstance(data, list) else []


def fetch_rollcalls(client, event_item_id, timeout=40):
    """Per-member roll-call votes for one agenda item: [{RollCallPersonName,
    RollCallValueName}, ...]."""
    url = '%s/EventItems/%s/RollCalls' % (api_base(client), event_item_id)
    data = fetch_json(url, timeout=timeout,
                      label='%s item %s rollcalls' % (client, event_item_id))
    return data if isinstance(data, list) else []


def fetch_legistar_meetings(client, years=4, timeout=40, page_size=1000, max_pages=20):
    """Fetch and normalize a Legistar client's meetings.

    Windowed to the last `years` years and paged with $top/$skip (Legistar caps a
    response at ~1000 rows). Returns (meetings, bodies_seen); (None, None) only if
    the first request fails.
    """
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=365 * years)).strftime('%Y-%m-%d')
    order = quote('EventDate desc')
    filt = quote("EventDate ge datetime'%s'" % cutoff)
    base = api_base(client)

    meetings, seen, bodies = [], set(), set()
    skip = 0
    for _ in range(max_pages):
        url = ('%s/Events?%%24orderby=%s&%%24filter=%s&%%24top=%d&%%24skip=%d'
               % (base, order, filt, page_size, skip))
        data = fetch_json(url, timeout=timeout, label='%s legistar events' % client)
        if data is None or not isinstance(data, list):
            if not meetings:
                return None, None
            break

        for e in data:
            m = _event_to_meeting(e)
            if not m:
                continue
            key = (m['body'], m['date'], m['id'])
            if key in seen:
                continue
            seen.add(key)
            meetings.append(m)
            bodies.add(m['body'])

        if len(data) < page_size:
            break
        skip += page_size

    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings, sorted(bodies)
