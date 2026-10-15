#!/usr/bin/env python3
"""Adapter for WordPress sites that publish meetings through **wpDataTables**.

wpDataTables (wpdatatables.com) is a general-purpose WordPress table plugin, not
a meeting portal — small Georgia cities with no CMS budget use it as one, pasting
a Date / Title / Agenda / Minutes / Video grid onto an ordinary page. City of
Fort Oglethorpe is the first here (fortogov.com/mayor-council/).

Unlike `lib.revize` and `lib.gdrive`, which harvest loose PDF links, this IS a
structured source: the plugin stores real columns, so we get the body, the
meeting title and the agenda/minutes/video links as separate fields rather than
inferring them from file names. Three things make it awkward anyway.

**1. The rows are not in the page.** The tables are configured `serverSide: true`
— the HTML carries only the first page (5 rows of Fort Oglethorpe's 48) and the
rest come from an admin-ajax endpoint:

    POST /wp-admin/admin-ajax.php?action=get_wdtable&table_id=<n>

**⚠ That POST needs a nonce, and without it returns HTTP 200 with a ZERO-BYTE
body** — not a 403, not an error document. A caller that forgets it sees an empty
string, not a failure, so a naive implementation silently publishes nothing while
looking like it worked. The nonce is public: the page renders it in a hidden
`wdtNonceFrontendEdit_<n>` input, and it must be sent as the field `wdtNonce`
(sending it under its own input name also yields the empty body). This is the
only reason this adapter needs `fetch_bytes(data=...)`; the request is a
paginated *read*, which is why replaying it on retry is safe.

**2. Column ORDER is not stable, so roles are read from the header text.**
Fort Oglethorpe's four meeting tables each order their columns differently (one
leads with the row id, another with the date). Worse, two different columns are
both called some kind of "date". So `_column_roles` matches the `<thead>` text,
not the position and not the plugin's internal slug — the slug for "Date Posted"
is just `date`, which is exactly the column we must not read as a meeting date.

**3. ⚠ The leading date column is the POSTING date, and it is dirty.** On the
live table one row reads `07-15-20` for a July **2026** meeting. Publishing that
as the meeting date would be a silently wrong fact, so `_row_date` resolves in a
fixed order and refuses to guess:

    a. an explicit meeting-date column ("Date of Meeting", "Meeting Date")
    b. a long-form date inside the title ("September 28, 2026 ~ Council Meeting")
    c. a bare "Date" column, only on tables that have no (a) at all
    d. otherwise the row is DROPPED — never fall back to a posting date.

(b) matters more than it looks: the live table leaves the meeting-date cell empty
for every pre-2026 row, and the title is the only place the real date survives.

Import from a generator in scripts/:
    from lib.wpdatatables import fetch_wpdatatables_meetings
"""

import datetime as dt
import json
import re
import urllib.parse
from urllib.parse import urljoin, urlparse

from lib.http import fetch_bytes

#: wpDataTables refuses nothing at this size; Fort Oglethorpe's largest table is
#: 48 rows. Paging is still implemented (see _fetch_rows) for a site that grows.
PAGE_LENGTH = 500
#: Stop after this many pages, so a misbehaving endpoint cannot loop forever.
MAX_PAGES = 20

_TABLE_RE = re.compile(
    r'<table\b[^>]*\bid=["\'](table_\d+)["\'][^>]*>', re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_THEAD_RE = re.compile(r'<thead\b.*?</thead>', re.S | re.I)
_TH_RE = re.compile(r'<th\b[^>]*>(.*?)</th>', re.S | re.I)
_ANCHOR_RE = re.compile(
    r'<a\b[^>]*?href\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.S | re.I)
# MM-DD-YY / MM-DD-YYYY / MM/DD/YYYY.
_NUM_DATE_RE = re.compile(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})\b')
# "September 28, 2026" / "Sept 28, 2026" / "September 28 2026". The comma after
# the MONTH is typo tolerance, not style: the live table has "February, 24,
# 2025 ~ City Council Meeting", and that row is the only record of a real
# meeting whose meeting-date cell was left blank.
_LONG_DATE_RE = re.compile(
    r'\b([A-Za-z]{3,9})\.?,?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b')

_MONTHS = {}
for _i in range(1, 13):
    _d = dt.date(2000, _i, 1)
    _MONTHS[_d.strftime('%B').lower()] = _i
    _MONTHS[_d.strftime('%b').lower()] = _i
_MONTHS['sept'] = 9  # the abbreviation strftime doesn't produce


def _clean(text):
    text = (text or '').replace('&nbsp;', ' ').replace('\xa0', ' ')
    text = text.replace('&amp;', '&').replace('&#8217;', "'")
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text)).strip()


def _norm(text):
    """Header text -> comparison key: lowercase, letters and digits only."""
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


def _iso(year, month, day):
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if year < 100:  # wpDataTables renders two-digit years (mm-dd-y)
        year += 2000
    if not (2000 <= year <= 2100):
        return None
    try:
        dt.date(year, month, day)
    except ValueError:
        return None
    return '%04d-%02d-%02d' % (year, month, day)


def _parse_numeric_date(text):
    m = _NUM_DATE_RE.search(text or '')
    if not m:
        return None
    return _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def _parse_long_date(text):
    m = _LONG_DATE_RE.search(text or '')
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    return _iso(int(m.group(3)), month, int(m.group(2)))


# ---------------------------------------------------------------------------
# Column roles. Ordered: the first rule whose test passes claims the column, so
# the specific "date of meeting" / "date posted" rules must precede bare "date".
# ---------------------------------------------------------------------------

def _column_roles(headers):
    """[header text] -> {role: index}. Roles: date, posted, title, body,
    agenda, minutes, video, id. A header matching nothing is ignored."""
    roles = {}
    weak_date = None
    for i, raw in enumerate(headers):
        h = _norm(raw)
        if not h:
            continue
        if 'minute' in h:
            role = 'minutes'
        elif 'agenda' in h or 'packet' in h:
            role = 'agenda'
        elif 'video' in h or 'recording' in h or 'media' in h:
            role = 'video'
        elif h in ('dateofmeeting', 'meetingdate') or 'dateofmeeting' in h:
            role = 'date'
        elif 'posted' in h or 'datepublished' in h:
            role = 'posted'
        elif h.startswith('date'):
            # A bare "Date" column: only a meeting date if the table has no
            # explicit one. Held back and resolved after the full pass.
            if weak_date is None:
                weak_date = i
            continue
        elif 'title' in h or h == 'name' or 'subject' in h:
            role = 'title'
        elif ('organization' in h or h.startswith('body') or 'board' in h
              or 'committee' in h or 'department' in h):
            role = 'body'
        elif h in ('wdtid', 'id'):
            role = 'id'
        else:
            continue
        roles.setdefault(role, i)
    if 'date' not in roles and weak_date is not None:
        roles['date'] = weak_date
    return roles


def _anchor(cell):
    """First non-empty href in a cell -> absolute-ish URL, else None.

    wpDataTables emits `<a href='' target='_blank'></a>` for an empty cell, so
    an anchor's presence means nothing; only a non-empty href does.
    """
    for match in _ANCHOR_RE.finditer(cell or ''):
        href = (match.group(1) or '').replace('&amp;', '&').strip()
        if href and not href.startswith('#'):
            return href
    return None


def _row_date(cells, roles):
    """Resolve a row's meeting date. See the module docstring: an explicit
    meeting-date column wins, then a date inside the title, then a bare date
    column — and a POSTING date is never used."""
    idx = roles.get('date')
    if idx is not None and idx < len(cells):
        iso = _parse_numeric_date(_clean(cells[idx])) or _parse_long_date(_clean(cells[idx]))
        if iso:
            return iso
    tidx = roles.get('title')
    if tidx is not None and tidx < len(cells):
        title = _clean(cells[tidx])
        iso = _parse_long_date(title) or _parse_numeric_date(title)
        if iso:
            return iso
    return None


def _parse_row(cells, roles, table_id, body_label, base_url):
    date = _row_date(cells, roles)
    if not date:
        return None

    def cell(role):
        i = roles.get(role)
        return cells[i] if i is not None and i < len(cells) else ''

    agenda_url = _anchor(cell('agenda'))
    minutes_url = _anchor(cell('minutes'))
    video_url = _anchor(cell('video'))
    if not (agenda_url or minutes_url or video_url):
        # Nothing published for this row yet — drop it, as every other adapter
        # drops link-less placeholder rows.
        return None

    def absolute(url):
        return urljoin(base_url, url) if url else None

    title = _clean(cell('title')) or None
    # 'Meeting' matches the other adapters' neutral placeholder: the registry's
    # body_label / body_map does the naming, and guessing a chamber here would
    # label a county board "City Council" on the next site that uses the plugin.
    body = _clean(cell('body')) or body_label or 'Meeting'
    row_id = _clean(cell('id'))
    # Namespace the plugin's row id by table, so two tables on one site cannot
    # collide. Stable across runs, which keeps a quiet re-run byte-identical.
    meeting_id = ('%s-%s' % (table_id, row_id) if row_id
                  else '%s-%s' % (table_id, date))

    return {
        'body': body,
        'date': date,
        'id': meeting_id,
        'title': title or body,
        'agendaUrl': absolute(agenda_url),
        'minutesUrl': absolute(minutes_url),
        'videoUrl': absolute(video_url),
        'hasPreviousVersions': False,
    }


# ---------------------------------------------------------------------------
# Page + endpoint plumbing
# ---------------------------------------------------------------------------

def _find_tables(html):
    """Locate every wpDataTable on a page.

    Returns [{dom_id, table_id, headers, nonce}]. `table_id` is the plugin's own
    numeric id (what the ajax endpoint takes); `dom_id` is the `table_N` element
    id that ties the table to its nonce input.
    """
    tables = []
    for m in _TABLE_RE.finditer(html):
        tag = m.group(0)
        dom_id = m.group(1)
        tid = re.search(r'data-wpdatatable_id=["\'](\d+)["\']', tag, re.I)
        if not tid:
            tid = re.search(r'wpDataTableID-(\d+)', tag, re.I)
        if not tid:
            continue
        table_id = tid.group(1)

        # Headers come from this table's own <thead>, which follows the tag.
        thead = _THEAD_RE.search(html, m.end())
        headers = [_clean(h) for h in _TH_RE.findall(thead.group(0))] if thead else []

        nonce = re.search(
            r'wdtNonceFrontendEdit_%s["\'][^>]*?value=["\']([^"\']+)["\']' % re.escape(table_id),
            html, re.I)
        tables.append({
            'dom_id': dom_id,
            'table_id': table_id,
            'headers': headers,
            'nonce': nonce.group(1) if nonce else None,
        })
    return tables


def _column_slugs(html, dom_id):
    """Ordered internal column slugs from the table's descriptor JSON.

    Only used to build the ajax `columns[i][name]` parameters — role detection
    reads the human header text instead (see _column_roles).
    """
    m = re.search(
        r'id=["\']%s_desc["\'][^>]*value=\'(.*?)\'' % re.escape(dom_id), html, re.S)
    if not m:
        m = re.search(
            r'id=["\']%s_desc["\'][^>]*value="(.*?)"(?:\s|/?>)' % re.escape(dom_id),
            html, re.S)
    if not m:
        return []
    try:
        desc = json.loads(m.group(1).replace('&quot;', '"'))
    except ValueError:
        return []
    cols = desc.get('columnsDecimalPlaces')
    return list(cols.keys()) if isinstance(cols, dict) else []


def _ajax_body(slugs, nonce, start, length):
    params = [('draw', '1'), ('start', str(start)), ('length', str(length)),
              ('search[value]', ''), ('search[regex]', 'false')]
    for i, slug in enumerate(slugs):
        params += [
            ('columns[%d][data]' % i, str(i)),
            ('columns[%d][name]' % i, slug),
            ('columns[%d][searchable]' % i, 'true'),
            ('columns[%d][orderable]' % i, 'true'),
            ('columns[%d][search][value]' % i, ''),
            ('columns[%d][search][regex]' % i, 'false'),
        ]
    params += [('order[0][column]', '0'), ('order[0][dir]', 'asc')]
    if nonce:
        params.append(('wdtNonce', nonce))
    return urllib.parse.urlencode(params).encode('utf-8')


def _fetch_rows(page_url, table, slugs, timeout=40, fetch=None):
    """Page the ajax endpoint for one table. Returns a list of raw cell lists,
    or None if the endpoint could not be read."""
    fetch = fetch or fetch_bytes
    parsed = urlparse(page_url)
    endpoint = '%s://%s/wp-admin/admin-ajax.php?action=get_wdtable&table_id=%s' % (
        parsed.scheme or 'https', parsed.netloc, table['table_id'])
    headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': page_url,
               'Accept': 'application/json, text/javascript, */*; q=0.01'}

    rows, start = [], 0
    for _page in range(MAX_PAGES):
        raw = fetch(endpoint,
                    headers=headers,
                    data=_ajax_body(slugs, table['nonce'], start, PAGE_LENGTH),
                    timeout=timeout,
                    label='wpDataTables %s table %s' % (parsed.netloc, table['table_id']))
        if not raw:
            # Empty body = the nonce was missing or stale (see module docstring).
            # Indistinguishable from a real failure, and treated as one.
            return None
        try:
            payload = json.loads(raw.decode('utf-8', errors='replace'))
        except ValueError:
            return None
        batch = payload.get('data') or []
        rows.extend(batch)
        try:
            total = int(payload.get('recordsTotal') or 0)
        except (TypeError, ValueError):
            total = len(rows)
        if len(batch) < PAGE_LENGTH or len(rows) >= total:
            break
        start += PAGE_LENGTH
    return rows


def fetch_wpdatatables_meetings(page_url, table_ids=None, body_label=None,
                                timeout=40, fetch=None):
    """Fetch and normalize the meeting tables on a wpDataTables page.

    `page_url` is the public page that renders the table(s). By default every
    table on the page that has an agenda or minutes column is ingested, so a
    page that also carries an unrelated grid (a fee schedule) is handled without
    configuration; `table_ids` pins an explicit list when that is not enough.

    `fetch` injects a replacement for lib.http.fetch_bytes, so the parsing can be
    tested against saved fixtures with no network (see test_wpdatatables.py).

    Returns (meetings, bodies_seen), or (None, None) if the page itself could not
    be read — never a partial list dressed up as a complete one.
    """
    fetch = fetch or fetch_bytes
    raw = fetch(page_url, label='wpDataTables page %s' % page_url, timeout=timeout)
    if not raw:
        return None, None
    html = raw.decode('utf-8', errors='replace')

    wanted = {str(t) for t in table_ids} if table_ids else None
    meetings, seen = [], set()
    for table in _find_tables(html):
        if wanted is not None and table['table_id'] not in wanted:
            continue
        roles = _column_roles(table['headers'])
        if wanted is None and not (roles.get('agenda') or roles.get('minutes')):
            continue  # not a meeting table
        slugs = _column_slugs(html, table['dom_id'])
        rows = _fetch_rows(page_url, table, slugs, timeout=timeout, fetch=fetch)
        if rows is None:
            continue
        for cells in rows:
            if not isinstance(cells, list):
                continue
            meeting = _parse_row(cells, roles, table['table_id'], body_label, page_url)
            if not meeting:
                continue
            key = (meeting['date'], meeting['id'])
            if key in seen:
                continue
            seen.add(key)
            meetings.append(meeting)

    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings, sorted({m['body'] for m in meetings})
