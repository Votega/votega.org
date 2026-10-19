#!/usr/bin/env python3
"""Adapter for AgendaPlus (agendaplus.org) "publishing" sites (City of Savannah).

AgendaPlus publishes a council's agendas as static HTML under `/publishing/`. It
is NOT CivicPlus AgendaCenter, Granicus, or IQM2 — no API, no JSON, no JS
rendering. The whole archive is one list page:

    https://agenda.<city>.gov/publishing/ap-agendas.html

  * One `<tr ID="1593" class="flRow October2026">` per meeting (Savannah: ~470
    rows back to 2017, newest first). The `ID` is the platform's stable numeric
    meeting id; the class carries the month group the page's `#lstMonths`
    dropdown filters on client-side, so there is no pagination.
  * Cells are identified by CLASS, not position: `td.meetingdate` ("October 22,
    2026"), `td.title` ("October 22, 2026 City Council Regular Meeting"),
    `td.agendalink`, `td.minutelink`.
  * Hrefs are RELATIVE to the list page (`<slug>/agenda.html`), and the slug is
    the date plus the body. Older rows link a direct PDF instead of
    `minutes.html`; both are kept as-is. Attachments live on the detail page,
    which we deliberately do not fetch: the agenda page itself is the link.

⚠ `td.minutelink` is emitted SELF-CLOSING (`<td class="minutelink" />`) when
there are no minutes yet. That is not valid HTML (a td cannot self-close), so a
tolerant parser reads it as an OPEN cell that swallows the next row. This module
therefore parses with regexes over the rendered text and treats `<td ... />` as
an empty cell — it must not be swapped for an HTML parser without keeping that.

⚠ The title restates the meeting date and the body ("October 22, 2026 City
Council Regular Meeting"). `body` is the title with the leading date removed —
still the meeting TYPE (Regular Meeting vs Workshop), so a place scopes and
relabels it with a body_map, exactly as with CivicClerk.

Video is not exposed (videoUrl null).

Import from a generator in scripts/:
    from lib.agendaplus import fetch_agendaplus_meetings
"""

import datetime as dt
import re
from urllib.parse import urljoin

from lib.http import fetch_bytes

_ROW_RE = re.compile(r'<tr\b([^>]*\bclass="[^"]*\bflRow\b[^"]*"[^>]*)>(.*?)</tr>',
                     re.S | re.I)
_ID_RE = re.compile(r'\bID="([^"]+)"', re.I)
# A cell is `<td class="x">…</td>` or the self-closing `<td class="x" />` (see ⚠).
_CELL_RE = re.compile(
    r'<td\b[^>]*\bclass="([^"]*)"[^>]*?(?:/>|>(.*?)</td>)', re.S | re.I)
_HREF_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"', re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_LEAD_DATE_RE = re.compile(r'^\s*[A-Za-z]+\.?\s+\d{1,2},\s*\d{4}\s*[-–:]?\s*')


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _parse_date(text):
    """'October 22, 2026' -> '2026-10-22', or None."""
    t = _clean(text).replace('.', '')
    for fmt in ('%B %d, %Y', '%b %d, %Y'):
        try:
            return dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _first_href(cell_html, base):
    m = _HREF_RE.search(cell_html or '')
    return urljoin(base, m.group(1).strip()) if m else None


def parse_agendaplus_list(html, page_url):
    """Parse an `ap-agendas.html` page into meeting dicts (unsorted, unscoped).

    A row with no date, or with neither an agenda nor minutes link, is dropped
    (an unpublished placeholder has nothing to link to)."""
    meetings, seen = [], set()
    for attrs, inner in _ROW_RE.findall(html):
        idm = _ID_RE.search(attrs)
        cells = {}
        for cls, content in _CELL_RE.findall(inner):
            for c in cls.split():
                cells.setdefault(c.lower(), content or '')
        date = _parse_date(cells.get('meetingdate', ''))
        title = _clean(cells.get('title', ''))
        if not date:
            continue
        agenda_url = _first_href(cells.get('agendalink'), page_url)
        minutes_url = _first_href(cells.get('minutelink'), page_url)
        if not (agenda_url or minutes_url):
            continue

        mid = idm.group(1) if idm else (agenda_url or minutes_url)
        if mid in seen:
            continue
        seen.add(mid)

        body = _LEAD_DATE_RE.sub('', title).strip() or title or 'Meeting'
        meetings.append({
            'body': body,
            'date': date,
            'id': mid,
            'title': title or body,
            'agendaUrl': agenda_url,
            'minutesUrl': minutes_url,
            'videoUrl': None,
            'hasPreviousVersions': False,
        })
    return meetings


def _sort_key(m):
    mid = m['id']
    return (m['date'], int(mid) if str(mid).isdigit() else -1, str(mid))


def fetch_agendaplus_meetings(agendas_url, timeout=30, fetcher=fetch_bytes):
    """Fetch and parse an AgendaPlus list page. `agendas_url` is the full URL of
    `ap-agendas.html`. Returns (meetings, bodies_seen), or (None, None) if the
    page cannot be fetched. `fetcher` is injectable so tests need no network."""
    raw = fetcher(agendas_url, timeout=timeout, label='agendaplus list')
    if raw is None:
        return None, None
    meetings = parse_agendaplus_list(raw.decode('utf-8', errors='replace'),
                                     agendas_url)
    meetings.sort(key=_sort_key, reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
