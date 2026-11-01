#!/usr/bin/env python3
"""Adapter for a Drupal "Upcoming Meetings" view (CivicPlus's Drupal CMS, e.g. Palmetto).

The page is a server-rendered table. Columns are read by their HEADER text, never by
position, so a city that reorders or drops one still parses:

    Date | Meeting | Agendas | Agenda Packets | [Minutes] | View

  * Date      "Nov 4, 2026 | 5pm"  -> ISO date (the time is used to merge duplicates)
  * Meeting   the title
  * Agendas   PDF link(s) - Drupal media entities, `/media/<id>`; ids are not
              per-meeting-sequential, so they can only be read off the row
  * Packets   PDF link(s) -> `agendaPacketUrl`
  * Minutes   (if the view has one) -> `minutesUrl`
  * View      the meeting's detail page; its path names the body
              (`/citycouncil/meeting/<slug>` -> `body_paths["citycouncil"]`) and its slug is
              the meeting id

⚠ Two rows can describe ONE meeting. Palmetto lists "work-session-49" and
"city-council-work-session-meeting-november-4-2026-530-pm" for the same 5:30 p.m.
work session. Rows with the same date AND time are merged (links unioned, the
longer title kept), so a voter does not see the meeting twice.

TWO WAYS TO FEED IT
  live        `pages` omitted: the view's `agendas_url` (+ optional `recent_url`) is fetched.
              Palmetto's origin challenges every non-browser client (Cloudflare), so this
              returns (None, None) there until the city allowlists us.
  saved page  `pages=[(url, html)]`: HTML a person saved from a real browser. A saved page
              is a SNAPSHOT, so previous records the pages no longer show are carried
              forward (a meeting that rolled off "Upcoming" is not forgotten); the live
              path rebuilds from the source like every other adapter.

Import from a generator in scripts/:
    from lib.drupalviews import fetch_drupalviews_meetings
"""

import html as htmllib
import re
import sys
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

from lib.http import fetch_bytes

_ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r'<t([dh])\b[^>]*>(.*?)</t[dh]>', re.S | re.I)
_HREF = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.I)
_TAG = re.compile(r'<[^>]+>')
_DATE = re.compile(r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})(?:\s*\|\s*(.+))?')
UA = 'Mozilla/5.0 (votega.org meeting-list)'


def _text(cell):
    t = re.sub(r'<strong class="tablesaw-cell-label".*?</strong>', '', cell, flags=re.S)
    return re.sub(r'\s+', ' ', htmllib.unescape(_TAG.sub(' ', t))).strip()


def _links(cell, base):
    out = []
    for h in _HREF.findall(cell):
        u = urljoin(base, htmllib.unescape(h))
        if u not in out:
            out.append(u)
    return out


def parse_date(text):
    """(ISO date, normalized time or None) from 'Nov 4, 2026 | 5pm', else (None, None)."""
    m = _DATE.search(text or '')
    if not m:
        return None, None
    try:
        d = datetime.strptime('%s %s %s' % (m.group(1)[:3], m.group(2), m.group(3)), '%b %d %Y').date()
    except ValueError:
        return None, None
    t = re.sub(r'\s+', '', (m.group(4) or '').lower()) or None
    return d.isoformat(), t


def parse_rows(page_html, page_url):
    """Header-driven table rows -> [dict]. A page with no recognisable table gives []."""
    rows, headers = [], None
    for tr in _ROW.findall(page_html or ''):
        cells = _CELL.findall(tr)
        if not cells:
            continue
        if all(k.lower() == 'h' for k, _ in cells):
            headers = [_text(c).lower() for _, c in cells]
            continue
        if not headers or len(cells) != len(headers):
            continue
        by = dict(zip(headers, (c for _, c in cells)))

        def col(*names):
            for n in names:
                for h, c in by.items():
                    if n in h:
                        return c
            return ''
        iso, tm = parse_date(_text(col('date')))
        if not iso:
            continue
        detail = _links(col('view', 'details'), page_url)
        rows.append({
            'date': iso, 'time': tm, 'title': _text(col('meeting', 'title')),
            'agenda': _links(col('agendas'), page_url),
            'packet': _links(col('packet'), page_url),
            'minutes': _links(col('minute'), page_url),
            'video': _links(col('video', 'audio'), page_url),
            'detail': detail[0] if detail else None,
        })
    return rows


def _segment(detail):
    parts = [p for p in urlsplit(detail or '').path.split('/') if p]
    return parts[0] if parts else None


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def merge_same_meeting(rows):
    """Rows with the same date AND time are one meeting listed twice."""
    out, idx = [], {}
    for r in rows:
        key = (r['date'], r['time']) if r['time'] else None
        if key is not None and key in idx:
            k = out[idx[key]]
            for f in ('agenda', 'packet', 'minutes', 'video'):
                k[f] = k[f] + [u for u in r[f] if u not in k[f]]
            if len(r['title']) > len(k['title']):
                k['title'] = r['title']
            continue
        if key is not None:
            idx[key] = len(out)
        out.append(dict(r))
    return out


def to_meetings(rows, body_paths, default_body, today=None):
    """A PAST meeting with nothing to open (no agenda, packet, minutes or video) is
    dropped: a row with no link adds noise. A FUTURE one stays, since files are
    posted close to the date."""
    today = today or date.today().isoformat()
    meetings, seen, unmapped = [], {}, set()
    for r in merge_same_meeting(rows):
        if r['date'] < today and not (r['agenda'] or r['packet'] or r['minutes'] or r['video']):
            continue
        seg = _segment(r['detail'])
        body = (body_paths or {}).get(seg)
        if body is None:
            body = default_body
            if seg:
                unmapped.add(seg)
        slug = _slug(r['detail'].rstrip('/').rsplit('/', 1)[-1]) if r['detail'] else _slug(r['title'])
        mid = '%s-%s' % (r['date'], slug or 'meeting')
        n = seen[mid] = seen.get(mid, 0) + 1
        m = {
            'body': body, 'date': r['date'], 'id': mid if n == 1 else '%s-%d' % (mid, n),
            'title': r['title'] or '%s %s' % (body, r['date']),
            'agendaUrl': r['agenda'][0] if r['agenda'] else None,
            'minutesUrl': r['minutes'][0] if r['minutes'] else None,
            'videoUrl': r['video'][0] if r['video'] else None, 'hasPreviousVersions': False,
        }
        if r['packet']:
            m['agendaPacketUrl'] = r['packet'][0]
        if r['detail']:
            m['detailUrl'] = r['detail']
        meetings.append(m)
    return meetings, unmapped


def fetch_drupalviews_meetings(agendas_url, recent_url=None, body_paths=None,
                               body='City Council', pages=None, previous=None, fetcher=None,
                               today=None):
    """Returns (meetings, bodies_seen) or (None, None).

    `pages` = [(url, html)] switches to saved-page mode (see the module docstring)."""
    if pages is None:
        get = fetcher or (lambda u: fetch_bytes(u, headers={'User-Agent': UA}))
        pages = []
        for u in [agendas_url] + ([recent_url] if recent_url else []):
            raw = get(u)
            if not raw:
                print('  drupalviews: %s could not be read - giving up' % u, file=sys.stderr)
                return None, None
            pages.append((u, raw.decode('utf-8', 'replace')))
        saved = False
    else:
        saved = True

    rows = []
    for url, page in pages:
        rows += parse_rows(page, url)
    if not rows:
        print('  drupalviews: no meeting rows found (markup changed, or a challenge page)',
              file=sys.stderr)
        return None, None
    meetings, unmapped = to_meetings(rows, body_paths, body, today)
    if unmapped:
        print('  drupalviews: unmapped body path(s) %s - shown as %r; add to body_paths'
              % (sorted(unmapped), body))
    if saved and previous:
        have = {m['id'] for m in meetings}
        today_iso = today or date.today().isoformat()
        meetings += [dict(p) for p in previous if p.get('id') not in have
                     and not (p.get('date', '') < today_iso and not (
                         p.get('agendaUrl') or p.get('agendaPacketUrl')
                         or p.get('minutesUrl') or p.get('videoUrl')))]
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    print('  drupalviews: %d meeting(s) from %d page(s)%s'
          % (len(meetings), len(pages), ' (saved pages, earlier records kept)' if saved else ''))
    return meetings, sorted({m['body'] for m in meetings})
