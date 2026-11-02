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
import html
import re
from urllib.parse import quote, urljoin

from lib.http import fetch_bytes, fetch_json


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


# The Web API leaves EventMinutesFile / EventVideoPath null for some clients even
# when the meeting-detail page links them (Fulton: minutes "Final" in the API,
# the file only on the page; video only via a JS popup). `detail_links: true` in
# the registry reads those two links off EventInSiteURL.
_DETAIL_MINUTES_RE = re.compile(
    r'<a id="[^"]*hypMinutes"[^>]*\shref="([^"#][^"]*)"', re.I)
_DETAIL_VIDEO_RE = re.compile(
    r'<a id="[^"]*hypVideo"[^>]*onclick="[^"]*?window\.open\(&#39;'
    r'(Video\.aspx\?.*?)&#39;', re.I)
DETAIL_RECHECK_DAYS = 90   # minutes get approved weeks later; older meetings are checked once


def parse_detail_links(page_html, page_url):
    """(minutesUrl, videoUrl) off a Legistar MeetingDetail page; None where the
    page shows the link greyed out / absent."""
    m = _DETAIL_MINUTES_RE.search(page_html)
    v = _DETAIL_VIDEO_RE.search(page_html)
    minutes = urljoin(page_url, html.unescape(m.group(1))) if m else None
    video = urljoin(page_url, html.unescape(v.group(1))) if v else None
    return minutes, video


def _fetch_detail_links(url, timeout=40):
    body = fetch_bytes(url, timeout=timeout, label='legistar detail')
    if not body:
        return None
    return parse_detail_links(body.decode('utf-8', 'replace'), url)


def apply_detail_links(meetings, site_urls, previous=None, today=None,
                       fetch=_fetch_detail_links):
    """Fill missing minutesUrl/videoUrl from detail pages, in place.

    Incremental: a meeting older than DETAIL_RECHECK_DAYS that `previous` marks
    `detailChecked` was checked on an earlier run and is carried forward untouched, so
    a steady-state run fetches only recent and brand-new meetings. A failed page
    leaves the record as the API gave it (never overwrites with nothing).
    Returns the number of pages fetched."""
    today = today or dt.date.today()
    prev = {str(m.get('id')): m for m in (previous or [])}
    cutoff = (today - dt.timedelta(days=DETAIL_RECHECK_DAYS)).isoformat()
    fetched = 0
    for m in meetings:
        if m['date'] > today.isoformat():
            continue
        old = prev.get(m['id'])
        if old and old.get('detailChecked') and m['date'] < cutoff:
            for k in ('minutesUrl', 'videoUrl'):
                m[k] = m[k] or old.get(k)
            m['detailChecked'] = True
            continue
        url = site_urls.get(m['id'])
        if not url or (m['minutesUrl'] and m['videoUrl']):
            continue
        got = fetch(url)
        fetched += 1
        if not got:
            continue
        m['detailChecked'] = True
        m['minutesUrl'] = m['minutesUrl'] or got[0]
        m['videoUrl'] = m['videoUrl'] or got[1]
    return fetched


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


def fetch_legistar_meetings(client, years=4, timeout=40, page_size=1000, max_pages=20,
                            detail_links=False, previous=None):
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
    site_urls = {}
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
            if e.get('EventInSiteURL'):
                site_urls[m['id']] = e['EventInSiteURL']
            bodies.add(m['body'])

        if len(data) < page_size:
            break
        skip += page_size

    if detail_links:
        n = apply_detail_links(meetings, site_urls, previous)
        print('  legistar %s: read %d meeting-detail page(s) for minutes/video' % (client, n))

    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings, sorted(bodies)
