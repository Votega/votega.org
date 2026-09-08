#!/usr/bin/env python3
"""Adapter for the Municode **PublishPage** meetings portal (meetings.municode.com).

This is a DIFFERENT front-end from `lib/teammunicode.py`: some Municode clients
run the classic Drupal "/meetings" table (that adapter), while others use the
newer PublishPage portal at
    https://meetings.municode.com/PublishPage/index?cid=<CID>&ppid=<PPID>&p=<page>
Same Azure-blob document backend (mccmeetings.blob.core.usgovcloudapi.net), but a
paginated `div-table` of document links instead. Each link is
    /d/f?u=<direct blob PDF URL>&n=<Type>-<Body>-<Month D, YYYY H.MM AM>.pdf
so the filename (`n=`) carries the document type (Agenda/Minutes/…), the body, and
the meeting date, and `u=` is the direct PDF. Agenda + Minutes for one meeting
share the same `MEET-<hash>` blob id, so the hash is a stable meeting id.

Paginate `p=1,2,…` until a page yields no document links (Paulding: ~10 pages).
`body` is the full "<Board> <Meeting type>" string — scope with body_label/body_map.
Video isn't exposed here (videoUrl null). Regex parsing keeps this dependency-free.

Import from a generator in scripts/:
    from lib.municode import fetch_municode_meetings
"""

import datetime as dt
import re
import urllib.parse

from lib.http import fetch_bytes

_DOC_RE = re.compile(r'/d/f\?u=([^&"\']+)&n=([^"\'&]+)', re.I)
_HASH_RE = re.compile(r'MEET-[A-Za-z ]+-([0-9a-f]+)\.pdf', re.I)
_DATE_RE = re.compile(r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})')
_AGENDA_TYPES = ('agenda',)          # prefer the standalone agenda
_AGENDA_FALLBACK = ('agenda packet',)
_MINUTES_TYPES = ('minutes',)
_MINUTES_FALLBACK = ('minutes packet',)

_MONTHS = {dt.date(2000, i, 1).strftime('%B').lower(): i for i in range(1, 13)}
_MONTHS.update({dt.date(2000, i, 1).strftime('%b').lower(): i for i in range(1, 13)})


def _parse_name(name):
    """`<Type>-<Body>-<Month D, YYYY …>.pdf` → (type_lower, body, iso_date)."""
    name = urllib.parse.unquote(name)
    if name.lower().endswith('.pdf'):
        name = name[:-4]
    dm = _DATE_RE.search(name)
    iso = None
    if dm:
        mon = _MONTHS.get(dm.group(1).lower())
        if mon:
            iso = '%04d-%02d-%02d' % (int(dm.group(3)), mon, int(dm.group(2)))
    head = name[:dm.start()].rstrip(' -') if dm else name
    typ, _, body = head.partition('-')
    return typ.strip().lower(), body.strip(), iso


def parse_page(html):
    """Group a page's document links into {hash: meeting-fields-so-far}."""
    meetings = {}
    for u, n in _DOC_RE.findall(html):
        blob = urllib.parse.unquote(u)
        h = _HASH_RE.search(blob)
        typ, body, iso = _parse_name(n)
        if not iso:
            continue
        key = h.group(1) if h else '%s|%s' % (body.lower(), iso)
        m = meetings.setdefault(key, {
            'body': body or 'Meeting', 'date': iso, 'id': key,
            'agendaUrl': None, 'minutesUrl': None, 'videoUrl': None,
            'hasPreviousVersions': False, '_agenda_pref': False, '_minutes_pref': False})
        if typ in _AGENDA_TYPES:
            m['agendaUrl'] = blob; m['_agenda_pref'] = True
        elif typ in _AGENDA_FALLBACK and not m['_agenda_pref']:
            m['agendaUrl'] = m['agendaUrl'] or blob
        elif typ in _MINUTES_TYPES:
            m['minutesUrl'] = blob; m['_minutes_pref'] = True
        elif typ in _MINUTES_FALLBACK and not m['_minutes_pref']:
            m['minutesUrl'] = m['minutesUrl'] or blob
    return meetings


def _page_url(publish_url, page):
    parts = urllib.parse.urlparse(publish_url)
    q = urllib.parse.parse_qs(parts.query)
    q['p'] = [str(page)]
    new_q = urllib.parse.urlencode({k: v[0] for k, v in q.items()})
    return urllib.parse.urlunparse(parts._replace(query=new_q))


def fetch_municode_meetings(publish_url, max_pages=20, timeout=30):
    """Fetch and parse a Municode PublishPage portal. `publish_url` is the
    ?cid=&ppid= portal URL; pages are walked until one yields no documents.
    Returns (meetings, bodies_seen), or (None, None) if the first page fails."""
    merged = {}
    for page in range(1, max_pages + 1):
        raw = fetch_bytes(_page_url(publish_url, page),
                          label='Municode PublishPage p%d' % page, timeout=timeout)
        if raw is None:
            if page == 1:
                return None, None
            break
        found = parse_page(raw.decode('utf-8', errors='replace'))
        if not found:
            break  # past the last page of results
        for k, v in found.items():
            if k not in merged:
                merged[k] = v

    meetings = []
    for m in merged.values():
        for junk in ('_agenda_pref', '_minutes_pref'):
            m.pop(junk, None)
        if m['agendaUrl'] or m['minutesUrl']:
            meetings.append(m)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
