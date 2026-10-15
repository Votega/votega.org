#!/usr/bin/env python3
"""Invariants of the wpDataTables meeting adapter (lib/wpdatatables.py).

The adapter's source is a WordPress plugin reached by POST, so none of this can
be exercised without the network — fetch_wpdatatables_meetings() takes its
fetcher as an argument and the fake below reproduces the real endpoint's shape,
including the two behaviours that make it dangerous to parse casually:

  * a POST without the `wdtNonce` field returns HTTP 200 with a ZERO-BYTE body
    rather than an error, so "forgot the nonce" looks exactly like "no meetings";
  * the first column is a POSTING date, it is dirty on the live site, and a
    second column named "Date of Meeting" is blank on every older row.

Pinned here: column roles follow the HEADER TEXT and not the column order, a
posting date is never published as a meeting date, the title carries the date
when the meeting-date cell is empty, link-less and date-less rows are dropped,
pagination is complete, and ids are namespaced per table.

Run: python scripts/test_wpdatatables.py       (no network, no repo writes)
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.wpdatatables import fetch_wpdatatables_meetings, _column_roles

PAGE_URL = 'https://example.gov/mayor-council/'
failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def anchor(href, text='Agenda'):
    return "<a href='%s' rel='' target='_blank'>%s</a>" % (href, text)


EMPTY_ANCHOR = "<a href='' rel='' target='_blank'></a>"


def build_page(tables):
    """Render the fragments of a wpDataTables page the adapter actually reads:
    the table tag (dom id + plugin id), its <thead>, the descriptor input that
    carries the ordered column slugs, and the nonce input."""
    out = []
    for dom_n, (table_id, headers, slugs, nonce) in enumerate(tables, start=1):
        dom_id = 'table_%d' % dom_n
        desc = json.dumps({'tableId': dom_id,
                           'columnsDecimalPlaces': dict((s, -1) for s in slugs)})
        if nonce is not None:
            out.append("<input type='hidden' id='wdtNonceFrontendEdit_%s' "
                       "name='wdtNonceFrontendEdit_%s' value='%s' />"
                       % (table_id, table_id, nonce))
        out.append("<input type=\"hidden\" id=\"%s_desc\" value='%s' />" % (dom_id, desc))
        out.append('<table id="%s" class="wpDataTable wpDataTableID-%s" '
                   'data-wpdatatable_id="%s" data-described-by=\'%s_desc\'>'
                   % (dom_id, table_id, table_id, dom_id))
        out.append('<thead><tr>%s</tr></thead>'
                   % ''.join('<th class="wdtheader">%s</th>' % h for h in headers))
        out.append('<tbody></tbody></table>')
    return ('<html><body>%s</body></html>' % '\n'.join(out)).encode('utf-8')


def make_fetch(page_bytes, rows_by_table, page_length=500, require_nonce=True):
    """Fake lib.http.fetch_bytes. Serves the page on GET; on POST serves the
    table's rows, or b'' when the nonce is missing — the live failure mode."""
    calls = {'posts': 0}

    def fetch(url, headers=None, data=None, timeout=None, label=None, **kw):
        if data is None:
            return page_bytes
        calls['posts'] += 1
        params = dict(urllib.parse.parse_qsl(data.decode('utf-8')))
        if require_nonce and not params.get('wdtNonce'):
            return b''          # HTTP 200, zero bytes. Not an error.
        table_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['table_id'][0]
        rows = rows_by_table.get(table_id, [])
        start = int(params.get('start', 0))
        window = rows[start:start + page_length]
        return json.dumps({'draw': 1, 'recordsTotal': str(len(rows)),
                           'recordsFiltered': str(len(rows)),
                           'data': window}).encode('utf-8')

    fetch.calls = calls
    return fetch


# ---------------------------------------------------------------------------
print("Column roles are read from the header text, not the position")

# The live site's two layouts. Note both call a column "Date", and in the first
# the one named plainly "Date Posted" is NOT the meeting date.
roles_a = _column_roles(['Date Posted', 'Organization', 'Date of Meeting',
                         'wdt_ID', 'Title of Meeting', 'Agenda', 'Video'])
check('"Date of Meeting" wins over "Date Posted"', roles_a.get('date'), 2)
check('"Date Posted" is tagged posted, not date', roles_a.get('posted'), 0)
check('organization is the body column', roles_a.get('body'), 1)
check('agenda/video found by name', (roles_a.get('agenda'), roles_a.get('video')), (5, 6))

roles_b = _column_roles(['wdt_ID', 'Date', 'Title', 'Agenda', 'Minutes', 'Video'])
check('a bare "Date" is the meeting date when there is no explicit one',
      roles_b.get('date'), 1)
check('no posted column is invented', roles_b.get('posted'), None)
check('minutes column found', roles_b.get('minutes'), 4)

# ---------------------------------------------------------------------------
print("\nRows: dates, links and drops")

HEADERS = ['Date Posted', 'Organization', 'Date of Meeting', 'wdt_ID',
           'Title of Meeting', 'Agenda', 'Video']
SLUGS = ['date', 'organization', 'dateofmeeting', 'wdt_ID', 'title', 'agenda', 'video1']

ROWS = [
    # Normal row: meeting-date column present and trustworthy.
    ['09-25-26', 'City Council', '09-28-26', '115',
     'September 28, 2026 ~ Council Meeting',
     anchor('https://example.gov/a/20260928.pdf'),
     anchor('https://youtu.be/abc', 'View Video')],
    # ⚠ Posting date is a typo for 2026 AND the meeting-date cell disagrees with
    # it. The meeting-date column must win; 2020 must never appear.
    ['07-15-20', 'City Council', '07-16-26', '109', 'Joint Work Session',
     anchor('https://example.gov/a/notice-0716.pdf'), EMPTY_ANCHOR],
    # Meeting-date cell blank: the date survives only in the title, and the
    # month there carries a stray comma ("February, 24, 2025").
    ['02-22-25', '', '', '71', 'February, 24, 2025 ~ City Council Meeting',
     anchor('https://example.gov/a/20250224.pdf'),
     anchor('https://youtu.be/def', 'View Video')],
    # Nothing published yet -> dropped.
    ['03-01-26', 'City Council', '03-10-26', '99', 'March 10, 2026 ~ Council Meeting',
     EMPTY_ANCHOR, EMPTY_ANCHOR],
    # No resolvable date anywhere (only a posting date) -> dropped, NOT posted.
    ['04-02-26', 'City Council', '', '98', 'Called Meeting',
     anchor('https://example.gov/a/called.pdf'), EMPTY_ANCHOR],
]

page = build_page([('22', HEADERS, SLUGS, 'n0nce')])
meetings, bodies = fetch_wpdatatables_meetings(
    PAGE_URL, body_label='City Council', fetch=make_fetch(page, {'22': ROWS}))

check('link-less and date-less rows are dropped', len(meetings), 3)
by_id = dict((m['id'], m) for m in meetings)
check('ids are namespaced by table', sorted(by_id), ['22-109', '22-115', '22-71'])
check('meeting-date column is used', by_id['22-115']['date'], '2026-09-28')
check('posting-date typo never becomes the meeting date',
      by_id['22-109']['date'], '2026-07-16')
check('no 2020 date anywhere', [m for m in meetings if m['date'] < '2024-01-01'], [])
check('title date is used when the meeting-date cell is blank',
      by_id['22-71']['date'], '2025-02-24')
check('empty anchors become null, not an empty string',
      by_id['22-109']['videoUrl'], None)
check('agenda url is kept absolute',
      by_id['22-115']['agendaUrl'], 'https://example.gov/a/20260928.pdf')
check('body falls back to the registry label when the cell is blank',
      by_id['22-71']['body'], 'City Council')
check('with no label either, the body is a neutral placeholder - never a guessed chamber',
      fetch_wpdatatables_meetings(
          PAGE_URL, fetch=make_fetch(page, {'22': ROWS}))[0][-1]['body'],
      'Meeting')
check('meetings are sorted newest first',
      [m['date'] for m in meetings],
      sorted((m['date'] for m in meetings), reverse=True))
check('bodies_seen is derived from the kept rows', bodies, ['City Council'])

# ---------------------------------------------------------------------------
print("\nColumn order does not change the result")

ALT_HEADERS = ['Date of Meeting', 'wdt_ID', 'Organization', 'Title of Meeting',
               'Agenda', 'Video', 'Date Posted']
ALT_SLUGS = ['dateofmeeting', 'wdt_ID', 'organization', 'title', 'agenda',
             'video1', 'date']
order = [2, 3, 1, 4, 5, 6, 0]
ALT_ROWS = [[r[i] for i in order] for r in ROWS]

alt_meetings, _ = fetch_wpdatatables_meetings(
    PAGE_URL, body_label='City Council',
    fetch=make_fetch(build_page([('22', ALT_HEADERS, ALT_SLUGS, 'n0nce')]),
                     {'22': ALT_ROWS}))
check('reordering every column yields identical records', alt_meetings, meetings)

# ---------------------------------------------------------------------------
print("\nThe nonce, pagination, and non-meeting tables")

no_nonce = fetch_wpdatatables_meetings(
    PAGE_URL, fetch=make_fetch(build_page([('22', HEADERS, SLUGS, None)]),
                               {'22': ROWS}))
check('a table whose nonce is missing yields no meetings', no_nonce[0], [])

many = []
for i in range(1, 1201):
    many.append(['01-01-26', 'City Council', '01-%02d-26' % ((i % 28) + 1), str(i),
                 'Meeting %d' % i, anchor('https://example.gov/a/%d.pdf' % i),
                 EMPTY_ANCHOR])
paged_fetch = make_fetch(build_page([('22', HEADERS, SLUGS, 'n0nce')]),
                         {'22': many}, page_length=500)
paged, _ = fetch_wpdatatables_meetings(PAGE_URL, fetch=paged_fetch)
check('every page of a long table is read', len(paged), 1200)
check('paging stopped as soon as the table was exhausted',
      paged_fetch.calls['posts'], 3)

# A fee schedule next to the meetings grid: no agenda/minutes column, so it is
# not a meeting table and must not be ingested.
two = build_page([('5', ['wdt_ID', 'Service', 'Fee'], ['wdt_ID', 'service', 'fee'], 'n1'),
                  ('22', HEADERS, SLUGS, 'n0nce')])
mixed, _ = fetch_wpdatatables_meetings(
    PAGE_URL, body_label='City Council',
    fetch=make_fetch(two, {'5': [['1', 'Business license', '$50']],
                           '22': ROWS}))
check('a table with no agenda/minutes column is skipped', len(mixed), 3)
check('the fee schedule contributed no rows',
      [m for m in mixed if not m['id'].startswith('22-')], [])

# A page that cannot be read at all is a failure, never an empty success —
# the generator relies on this to refuse to overwrite good data with nothing.
dead, dead_bodies = fetch_wpdatatables_meetings(
    PAGE_URL, fetch=lambda *a, **k: None)
check('an unreadable page returns (None, None)', (dead, dead_bodies), (None, None))

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("All wpDataTables adapter invariants hold.")
