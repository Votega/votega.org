#!/usr/bin/env python3
"""Adapter for counties that publish meetings as a plain server-rendered HTML table
with Date | Agenda | Minutes (| Video) columns.

Houston County's Meeting Minutes page is the first: a table whose rows are present in
the static HTML (the page's DataTables script only sorts and pages them), one row per
meeting, each cell either empty or holding a link. No JavaScript is needed, so this is
a plain fetch.

Rules, because a table like this changes without notice:
  * Columns are found by HEADER TEXT (date / agenda / minutes / video), never by
    position, so a reordered or added column does not shift documents under the wrong
    heading.
  * The date comes from the first cell. Houston puts a hidden sortable `YYYYMMDD` in a
    span ahead of the visible `M/D/YYYY`; either is accepted, the hidden one first.
    A row with no parseable date is skipped and reported, never guessed.
  * Hrefs are made absolute and percent-encoded (the county's file names hold spaces
    and double spaces, e.g. `2026-10-20  Minutes.pdf`), without double-encoding a
    name that is already encoded.
  * A table with rows but no document links anywhere is treated as a layout change
    and fails, rather than publishing meetings stripped of their links.

`parse_table` is pure (HTML in, meetings out) so it is tested offline against a real
page; `fetch_htmltable_meetings` is the thin fetching wrapper.

Import from a generator in scripts/:
    from lib.htmltable import fetch_htmltable_meetings
"""

import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from lib.http import fetch_bytes

_HIDDEN_DATE = re.compile(r'^\d{8}$')
_SLASH_DATE = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})')


def _clean(s):
    return re.sub(r'\s+', ' ', (s or '').replace('\xa0', ' ')).strip()


class _Tables(HTMLParser):
    """Collect every <table> as {'headers': [text], 'rows': [[cell]]}, a cell being
    {'text': str, 'links': [(href, text)]}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._t = None
        self._row = None
        self._cell = None
        self._in_th = False
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            self._t = {'headers': [], 'rows': []}
            self.tables.append(self._t)
        elif self._t is None:
            return
        elif tag == 'tr':
            self._row = {'cells': [], 'th': []}
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = {'text': '', 'links': [], 'th': tag == 'th'}
        elif tag == 'a' and self._cell is not None and a.get('href'):
            self._a = {'href': a['href'], 'text': ''}

    def handle_data(self, data):
        if self._cell is not None:
            self._cell['text'] += data
            if self._a is not None:
                self._a['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self._a is not None and self._cell is not None:
            self._cell['links'].append((self._a['href'], _clean(self._a['text'])))
            self._a = None
        elif tag in ('td', 'th') and self._cell is not None and self._row is not None:
            self._cell['text'] = _clean(self._cell['text'])
            (self._row['th'] if self._cell['th'] else self._row['cells']).append(self._cell)
            self._cell = None
        elif tag == 'tr' and self._row is not None and self._t is not None:
            if self._cell is not None:
                # Houston never closes the Video </td>; flush it at the row end.
                if self._a is not None:
                    self._cell['links'].append((self._a['href'], _clean(self._a['text'])))
                    self._a = None
                self._cell['text'] = _clean(self._cell['text'])
                (self._row['th'] if self._cell['th'] else self._row['cells']).append(self._cell)
                self._cell = None
            if self._row['th'] and not self._row['cells']:
                self._t['headers'] = [c['text'] for c in self._row['th']]
            elif self._row['cells']:
                self._t['rows'].append(self._row['cells'])
            self._row = None
        elif tag == 'table':
            self._t = None


def _encode(base_url, href):
    """Absolute, percent-encoded URL; an already-encoded name is left alone."""
    parts = urlsplit(urljoin(base_url, href.strip()))
    path = quote(parts.path, safe="/%:@&=+$,;~()'!*")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ''))


def _iso(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def _row_date(cell):
    """ISO date for a row. Houston prints a hidden sortable `YYYYMMDD` immediately
    before the visible `M/D/YYYY`, so the cell text reads `202609229/22/2026` with no
    separator - a slash-date search on that string finds `29/22/2026`. The visible date
    is therefore taken from the link text (or the text after the 8 digits), and when
    both are present they must agree, or the row is skipped rather than guessed."""
    text = cell['text']
    hidden = None
    m = re.match(r'(\d{4})(\d{2})(\d{2})', text)
    if m and (len(text) == 8 or _SLASH_DATE.match(text[8:].lstrip())):
        hidden = _iso(*m.groups())
        text = text[8:].lstrip()
    visible = None
    for src in [t for _, t in cell['links']] + [text]:
        v = _SLASH_DATE.fullmatch(src.strip()) or (_SLASH_DATE.match(src.strip()) if src == text else None)
        if v:
            visible = _iso(v.group(3), v.group(1), v.group(2))
            break
    if hidden and visible and hidden != visible:
        return None
    return visible or hidden


def _long_date(iso):
    d = datetime.strptime(iso, '%Y-%m-%d')
    return '%s %d, %d' % (d.strftime('%B'), d.day, d.year)


def _col(headers, word):
    for i, h in enumerate(headers):
        if word in h.lower():
            return i
    return None


def parse_table(html, base_url, body='Board of Commissioners'):
    """HTML -> (meetings, report). report: {'rows', 'skippedRows', 'documents'}.
    Raises ValueError when the page cannot be trusted (see module docstring)."""
    p = _Tables()
    p.feed(html)
    table = None
    for t in p.tables:
        ci = {k: _col(t['headers'], k) for k in ('date', 'agenda', 'minutes', 'video')}
        if ci['date'] is not None and (ci['agenda'] is not None or ci['minutes'] is not None):
            table, cols = t, ci
            break
    if table is None or not table['rows']:
        raise ValueError('no meetings table with Date and Agenda/Minutes headers found')

    def link(cells, idx):
        if idx is None or idx >= len(cells):
            return None
        links = {_encode(base_url, h) for h, _ in cells[idx]['links']}
        if len(links) != 1:      # none, or two different documents: never pick one
            return None
        return links.pop()

    meetings, skipped, seen = [], [], {}
    for cells in table['rows']:
        date = _row_date(cells[cols['date']]) if cols['date'] < len(cells) else None
        if not date:
            skipped.append(_clean(' | '.join(c['text'] for c in cells[:2])))
            continue
        urls = {'agendaUrl': link(cells, cols['agenda']),
                'minutesUrl': link(cells, cols['minutes']),
                'videoUrl': link(cells, cols['video'])}
        # Older years list one meeting as two rows (agenda in one, minutes in the
        # other). Fold a same-date row into an earlier one only when it adds fields
        # and contradicts none; otherwise it is a second meeting that day.
        host = next((m for m in seen.get(date, [])
                     if all(not (urls[k] and m[k] and urls[k] != m[k]) for k in urls)), None)
        if host:
            for k, v in urls.items():
                host[k] = host[k] or v
            continue
        n = len(seen.setdefault(date, [])) + 1
        m = {'body': body, 'date': date,
             'id': date + '-meeting' + ('' if n == 1 else '-%d' % n),
             'title': '%s Meeting' % _long_date(date)}
        m.update(urls)
        m['hasPreviousVersions'] = False
        seen[date].append(m)
        meetings.append(m)

    docs = sum(1 for m in meetings for k in ('agendaUrl', 'minutesUrl') if m[k])
    report = {'rows': len(table['rows']), 'skippedRows': skipped, 'documents': docs}
    if not meetings:
        raise ValueError('table found but no row had a parseable date')
    if not docs:
        raise ValueError('%d meetings but no document links - the page layout has changed'
                         % len(meetings))
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    return meetings, report


def fetch_htmltable_meetings(agendas_url, body='Board of Commissioners', timeout=40):
    """Returns (meetings, bodies_seen), or (None, None) if the page cannot be read or
    cannot be trusted."""
    raw = fetch_bytes(agendas_url, timeout=timeout, label='htmltable')
    if not raw:
        return None, None
    try:
        meetings, report = parse_table(raw.decode('utf-8', 'replace'), agendas_url, body=body)
    except ValueError as e:
        print('  htmltable: %s (%s)' % (e, agendas_url), file=sys.stderr)
        return None, None
    print('  htmltable: %d meetings, %d documents; skipped rows %s'
          % (len(meetings), report['documents'], report['skippedRows'] or 'none'))
    return meetings, [body]
