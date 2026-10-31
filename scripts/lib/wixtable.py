#!/usr/bin/env python3
"""Adapter for Wix counties that publish meetings as a table with hand-placed link icons.

Baker County's Minutes and Agendas page is a Wix table (Date | Meeting | Agenda |
Minutes). Two things make it unreadable to a plain HTTP scrape:

  * Wix fills the table from JavaScript. The server HTML carries the first 15 rows;
    the browser shows 23. Everything after row 15 exists only after hydration.
  * The Agenda / Minutes cells are EMPTY. The documents are separate icon
    components (`<a href=".../_files/ugd/<hash>.pdf">` wrapping an image), absolutely
    positioned over the table by whoever edited the page. Their only label is the
    scanner's filename (`doc00721720260728100514.pdf`), so nothing in the markup
    says which meeting a document belongs to.

The one place the row/column of a document is stated is the RENDERED PAGE: a person
sees the icon sitting in the Minutes cell of the July 7 row. So this adapter reads
that, in headless Chrome: for every table row and every `_files/ugd` link it records
the bounding box, and a link belongs to the row whose vertical band contains its
centre and the column whose horizontal band contains it. That is the same inference a
reader makes, and it is the only one available.

`parse_snapshot` is pure (geometry in, meetings out) so it is tested offline against
a snapshot of the real page; `snapshot_page` is the only part that needs a browser.

Never guess: a row whose date is not a clean `Month d, yyyy` is skipped and counted
(the county typed "July 16, 206" on one row), a cell holding two DIFFERENT documents
gets neither, and a run that finds rows but no documents at all, or many icons that
land in no cell, is treated as a layout change and fails rather than publish
meetings that silently lost their links.

Import from a generator in scripts/:
    from lib.wixtable import fetch_wixtable_meetings
"""

import os
import re
import sys
import time
from datetime import datetime

DOC_PATH = '/_files/ugd/'
VIEWPORT = {'width': 1280, 'height': 1000}
# Fail the run when this share of in-table icons land in no cell: the layout moved.
MAX_ORPHAN_SHARE = 0.25

_DATE_RE = re.compile(r'^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$')

# Runs in the page. Plain geometry only: every rule lives in Python where it is tested.
COLLECT_JS = r"""
() => {
  const tb = document.querySelector('table');
  if (!tb) return null;
  const box = el => { const r = el.getBoundingClientRect();
    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; };
  const columns = [...tb.querySelectorAll('thead th')].map(th =>
    Object.assign({label: th.textContent.trim()}, box(th)));
  const rows = [...tb.querySelectorAll('tbody tr')].map(tr =>
    Object.assign({cells: [...tr.cells].map(c => c.textContent)}, box(tr)));
  const icons = [...document.querySelectorAll('a[href*="/_files/ugd/"]')]
    .filter(a => !tb.contains(a))
    .map(a => { const r = a.getBoundingClientRect();
      return {href: a.href, x: r.left + r.width / 2, y: r.top + r.height / 2,
              w: r.width, h: r.height}; });
  return {columns, rows, icons, table: box(tb)};
}
"""


def _clean(s):
    return re.sub(r'\s+', ' ', (s or '').replace('​', '')).strip()


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def parse_date(text):
    """'January  6, 2026' -> '2026-01-06'; None for anything that is not a clean
    `Month d, yyyy` (so 'July 16, 206' is skipped, never repaired)."""
    m = _DATE_RE.match(_clean(text))
    if not m:
        return None
    mon, day, year = m.groups()
    for fmt in ('%B %d %Y', '%b %d %Y'):
        try:
            return datetime.strptime('%s %s %s' % (mon, day, year), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _long_date(iso):
    """'2026-07-07' -> 'July 7, 2026' (no zero padding, same on every platform)."""
    d = datetime.strptime(iso, '%Y-%m-%d')
    return '%s %d, %d' % (d.strftime('%B'), d.day, d.year)


def _col_index(columns, word):
    for i, c in enumerate(columns):
        if word in _clean(c.get('label')).lower():
            return i
    return None


def _inside(v, lo, hi):
    return lo <= v < hi


def parse_snapshot(snap, body='Board of Commissioners'):
    """Geometry snapshot -> (meetings, report).

    report: {'rows', 'skippedRows': [text], 'icons', 'orphans', 'ambiguousCells':
    [(date, 'agenda'|'minutes')], 'documents', 'reusedDocuments': [href]}.
    Raises ValueError when the snapshot cannot be trusted (see module docstring)."""
    if not snap or not snap.get('rows'):
        raise ValueError('no table rows in the rendered page')
    cols = snap['columns']
    ci = {k: _col_index(cols, k) for k in ('date', 'meeting', 'agenda', 'minutes')}
    if None in ci.values():
        raise ValueError('table headers not recognised: %r' % [c.get('label') for c in cols])

    rows = snap['rows']
    table = snap.get('table') or {}
    t_top = min(r['top'] for r in rows)
    t_bot = max(r['bottom'] for r in rows)
    kinds = {ci['agenda']: 'agenda', ci['minutes']: 'minutes'}

    # icon -> (row index, kind), or an orphan when it lands in no document cell
    cell_docs = {}
    in_table = orphans = 0
    for ic in snap.get('icons', []):
        # Only icons overlapping the table's vertical extent are candidates; the page's
        # own notices (tax digest) sit above it and are not meeting documents.
        if not _inside(ic['y'], t_top, t_bot):
            continue
        in_table += 1
        row = next((i for i, r in enumerate(rows) if _inside(ic['y'], r['top'], r['bottom'])), None)
        col = next((i for i in kinds if _inside(ic['x'], cols[i]['left'], cols[i]['right'])), None)
        if row is None or col is None:
            orphans += 1
            continue
        cell_docs.setdefault((row, kinds[col]), [])
        if ic['href'] not in cell_docs[(row, kinds[col])]:
            cell_docs[(row, kinds[col])].append(ic['href'])

    meetings, skipped, ambiguous = [], [], []
    for i, r in enumerate(rows):
        cells = r['cells']
        date = parse_date(cells[ci['date']])
        mtype = _clean(cells[ci['meeting']])
        if not date or not mtype:
            skipped.append(_clean(' | '.join(cells[:2])))
            continue
        urls = {}
        for kind in ('agenda', 'minutes'):
            found = cell_docs.get((i, kind), [])
            if len(found) > 1:
                ambiguous.append((date, kind))
                found = []
            urls[kind] = found[0] if found else None
        meetings.append({
            'body': body,
            'date': date,
            'id': '%s-%s' % (date, _slug(mtype)),
            'title': '%s %s' % (_long_date(date), mtype),
            'agendaUrl': urls['agenda'],
            'minutesUrl': urls['minutes'],
            'videoUrl': None,
            'hasPreviousVersions': False,
        })

    docs = [u for m in meetings for u in (m['agendaUrl'], m['minutesUrl']) if u]
    reused = sorted({u for u in docs if docs.count(u) > 1})
    report = {'rows': len(rows), 'skippedRows': skipped, 'icons': in_table,
              'orphans': orphans, 'ambiguousCells': ambiguous,
              'documents': len(docs), 'reusedDocuments': reused}

    if not meetings:
        raise ValueError('table found but no row had a clean date')
    if not docs:
        raise ValueError('%d meetings but no document landed in an Agenda/Minutes cell '
                         '- the page layout has changed' % len(meetings))
    if in_table and orphans / in_table > MAX_ORPHAN_SHARE:
        raise ValueError('%d of %d icons landed in no cell - the page layout has changed'
                         % (orphans, in_table))

    # Same newest-first order as the other adapters (ties: later row first).
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    return meetings, report


def snapshot_page(url, timeout=60, settle=3):
    """Render `url` in headless Chrome and return the geometry snapshot (or None).

    Waits for hydration to FINISH, not just start: the server HTML has 15 rows and the
    browser 23, so a snapshot taken at first paint silently loses the newest meetings.
    The row count must hold steady across `settle` consecutive polls."""
    from playwright.sync_api import sync_playwright  # lazy: parser tests need no browser

    launch = {'channel': os.environ['CHROME_CHANNEL']} if os.environ.get('CHROME_CHANNEL') else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        try:
            page = browser.new_page(viewport=VIEWPORT)
            # Not 'networkidle': Wix polls analytics forever, so it never fires. The
            # table wait plus the stable-row-count loop below is the real readiness test.
            page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
            page.wait_for_selector('table tbody tr', timeout=timeout * 1000)
            last, steady = -1, 0
            deadline = time.time() + timeout
            while steady < settle and time.time() < deadline:
                n = page.evaluate("document.querySelectorAll('table tbody tr').length")
                steady = steady + 1 if n == last else 0
                last = n
                time.sleep(1)
            # Icons are positioned after layout settles.
            return page.evaluate(COLLECT_JS)
        finally:
            browser.close()


def fetch_wixtable_meetings(agendas_url, body='Board of Commissioners', timeout=60,
                            snapshotter=snapshot_page):
    """Returns (meetings, bodies_seen), or (None, None) if the page cannot be read or
    cannot be trusted. `snapshotter` is injectable so tests need no browser."""
    last_err = None
    for attempt in range(2):
        try:
            snap = snapshotter(agendas_url, timeout=timeout)
            meetings, report = parse_snapshot(snap, body=body)
            break
        except Exception as e:  # noqa: BLE001 - one place's failure must not stop the run
            last_err = e
            print('  wixtable: attempt %d failed for %s: %s' % (attempt + 1, agendas_url, e),
                  file=sys.stderr)
    else:
        print('  wixtable: giving up on %s (%s)' % (agendas_url, last_err), file=sys.stderr)
        return None, None
    print('  wixtable: %d meetings, %d documents; skipped rows %s; ambiguous cells %s; '
          'documents linked from two rows %d; icons outside any cell %d'
          % (len(meetings), report['documents'], report['skippedRows'] or 'none',
             report['ambiguousCells'] or 'none', len(report['reusedDocuments']),
             report['orphans']))
    return meetings, [body]
