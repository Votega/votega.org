#!/usr/bin/env python3
"""Adapter for county sites whose agendas live on a nimbleCMS event calendar.

Thomas County's "Public Meetings & Events" page is a FullCalendar widget over a JSON
feed. There is no document list anywhere on the site: each meeting is a calendar event
and the agenda is a PDF button inside the event's `full_details` HTML.

    GET <calendar page>/?start=2026-01-01&end=2027-01-01        (X-Requested-With: XMLHttpRequest)
    -> [{"id", "start", "title", "calendar_name", "full_details": "<p>...<a href=...pdf>Tentative Agenda</a>"}, ...]

Facts that shape this adapter:

  * One event is one meeting; `calendar_name` is the body ("County Commission",
    "Public Works Committee", ...). A day can hold several events, so the meeting id
    carries the body.
  * **Only agendas.** The site publishes no minutes at all; every record's minutesUrl
    is None, which is the truth, not a scraping gap.
  * **Future events carry a placeholder** (`.../Agenda/Pending.pdf`, the same file for
    every unposted meeting). It is not an agenda, so an event whose only PDF is a
    placeholder is skipped, never published as one.
  * Events with no PDF (an election-office hours entry, a called meeting not yet
    noticed) are skipped; a place page that lists a meeting with nothing to open adds
    noise, and the schedule block already says when the board meets.
  * The feed answers any date range, so history is fetched one calendar year at a time
    from `from_year`; a year that fails is an error for the whole run, because a hole
    in the middle of a record is indistinguishable from a quiet year once published.
  * **Minutes live elsewhere**: a separate file browser (`minutes_url`) of
    `MMDDYYYY Minutes.pdf` files, read through lib.pdflinks and merged onto the board's
    meeting of the same date (a date with minutes but no calendar agenda stands alone).
    Only the board keeps minutes there, so committees never receive any. Nothing older
    than `from_year` is kept from either source.

`parse_events` is pure (feed rows in, meetings out) so it is tested offline.

Import from a generator in scripts/:
    from lib.nimblecal import fetch_nimblecal_meetings
"""

import re
import sys
from datetime import date
from urllib.parse import urljoin

from lib.http import fetch_json

_PDF = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+?\.pdf)(?:\?[^"\']*)?["\'][^>]*>(.*?)</a>',
                  re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_PLACEHOLDER = re.compile(r'pending|placeholder|tbd', re.I)


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def _clean(s):
    return re.sub(r'\s+', ' ', _TAG.sub('', s or '')).strip()


def agenda_url(full_details, base_url):
    """The event's real agenda PDF, or None. A button labelled like an agenda wins;
    otherwise the first PDF. A placeholder file name never counts."""
    found = []
    html = (full_details or '').replace('\\/', '/')
    for href, label in _PDF.findall(html):
        if _PLACEHOLDER.search(href.rsplit('/', 1)[-1]):
            continue
        found.append((urljoin(base_url, href), _clean(label)))
    for url, label in found:
        if re.search(r'agenda', label, re.I):
            return url
    return found[0][0] if found else None


def parse_events(events, base_url, body_labels=None, include=None, exclude=None):
    """Feed rows -> (meetings, report). `body_labels` renames a calendar
    ({"County Commission": "Board of Commissioners"}); `include` / `exclude` filter by
    the calendar's own name."""
    body_labels = body_labels or {}
    meetings, seen = [], {}
    report = {'events': 0, 'noAgenda': 0, 'filtered': 0}
    for e in events:
        report['events'] += 1
        cal = (e.get('calendar_name') or '').strip()
        if (include and cal not in include) or (exclude and cal in exclude):
            report['filtered'] += 1
            continue
        iso = (e.get('start') or '')[:10]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso):
            continue
        url = agenda_url(e.get('full_details'), base_url)
        if not url:
            report['noAgenda'] += 1
            continue
        body = body_labels.get(cal, cal) or 'Board of Commissioners'
        mid = '%s-%s' % (iso, _slug(body) or 'meeting')
        n = seen[mid] = seen.get(mid, 0) + 1
        meetings.append({
            'body': body,
            'date': iso,
            'id': mid if n == 1 else '%s-%d' % (mid, n),
            'title': _clean(e.get('title')) or '%s %s' % (body, iso),
            'agendaUrl': url,
            'minutesUrl': None,
            'videoUrl': None,
            'hasPreviousVersions': False,
        })
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    return meetings, report


def merge_minutes(meetings, minutes, body):
    """Attach each minutes record to the `body` meeting of the same date; a date the
    calendar has no agenda for becomes its own minutes-only meeting. Returns the merged
    list, newest first."""
    by_key = {(m['date'], m['body']): m for m in meetings}
    for mm in minutes:
        url = mm.get('minutesUrl')
        if not url:
            continue
        hit = by_key.get((mm['date'], body))
        if hit is not None:
            hit['minutesUrl'] = hit['minutesUrl'] or url
            continue
        rec = dict(mm, body=body, id='%s-%s' % (mm['date'], _slug(body) or 'meeting'),
                   agendaUrl=None, videoUrl=None)
        by_key[(mm['date'], body)] = rec
        meetings.append(rec)
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    return meetings


def fetch_nimblecal_meetings(calendar_url, base_url=None, from_year=2026, body_labels=None,
                             include=None, exclude=None, minutes_url=None,
                             minutes_body='Board of Commissioners', fetcher=None,
                             minutes_fetcher=None):
    """Returns (meetings, bodies_seen), or (None, None) when any year cannot be read.
    `fetcher(url) -> list | None` and `minutes_fetcher(url, body) -> (meetings, bodies)`
    are injectable so tests need no network."""
    base_url = base_url or calendar_url
    cal = calendar_url.rstrip('/') + '/'
    fetch = fetcher or (lambda u: fetch_json(
        u, headers={'User-Agent': 'Mozilla/5.0 (votega.org meeting-list)',
                    'X-Requested-With': 'XMLHttpRequest'}))
    events = []
    for year in range(int(from_year), date.today().year + 2):
        rows = fetch('%s?start=%d-01-01&end=%d-01-01' % (cal, year, year + 1))
        if not isinstance(rows, list):
            print('  nimblecal: %d could not be read - giving up' % year, file=sys.stderr)
            return None, None
        events.extend(rows)
    meetings, report = parse_events(events, base_url, body_labels, include, exclude)
    if minutes_url:
        if minutes_fetcher is None:
            from lib.pdflinks import fetch_pdflinks_meetings
            minutes_fetcher = lambda u, b: fetch_pdflinks_meetings(u, body=b)  # noqa: E731
        got, _ = minutes_fetcher(minutes_url, minutes_body)
        if got is None:
            print('  nimblecal: the minutes page could not be read - giving up', file=sys.stderr)
            return None, None
        recent = [m for m in got if int(m['date'][:4]) >= int(from_year)]
        meetings = merge_minutes(meetings, recent, minutes_body)
    if not meetings:
        print('  nimblecal: %d events but none carried an agenda PDF' % report['events'],
              file=sys.stderr)
        return None, None
    print('  nimblecal: %d events -> %d with an agenda (%d without one, %d filtered out)'
          % (report['events'], len(meetings), report['noAgenda'], report['filtered']))
    return meetings, sorted({m['body'] for m in meetings})
