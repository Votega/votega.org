#!/usr/bin/env python3
"""Adapter for CivicPlus / CivicEngage county websites.

Today this covers one thing: the **Agenda Center** (public meeting agendas,
minutes, and linked video). CivicPlus exposes two access paths and this module
deliberately prefers the second:

  RSS   /RSSFeed.aspx?ModID=65&CID=<Body>-<catId>
        Clean XML, but *recent-only* (a "latest agendas" feed, a handful of
        items), the <link> points at PreviousVersions rather than the file, and
        it carries no agenda-vs-minutes distinction or reliable body field. Some
        bodies return an empty feed even when the Agenda Center HTML lists their
        meetings (observed on Newton's Board of Commissioners). Insufficient on
        its own.

  HTML  /AgendaCenter
        Fully server-rendered and complete: every body is a collapsible panel
        headed by an <h2 data-cp-toggle>, and every meeting is a
        <tr class="catAgendaRow"> carrying explicit
        /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-<id> and .../Minutes/... links.
        This is the authoritative source, so it is what we parse.

The markup is stable CivicPlus boilerplate, so regex parsing (as in
generate_ga_executive_orders.py) is appropriate and keeps this dependency-free.
If CivicPlus reskins, scripts/validate_county_meetings.py is what catches it.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`, so the `lib` package resolves):

    from lib.civicplus import fetch_agenda_center
"""

import datetime as dt
import re
import urllib.error
import urllib.parse
import urllib.request

from lib.http import fetch_bytes

AGENDA_MODULE_ID = 65
# How many years back to pull per category via the year-toggle (see fetch_agenda_center).
DEFAULT_YEARS = 4

# A category panel header ties a catID to a body name: the <h2>'s
# aria-controls="category-panel-<catID>" is the same number the year toggle and the
# UpdateCategoryList POST use. This is what lets us map POSTed rows to their body.
_CATPANEL_RE = re.compile(
    r'aria-controls="category-panel-(\d+)"[^>]*>\s*([^<]+?)\s*<', re.I)
# The year dropdown emits changeYear(<year>, <catID>, ...) for every year that
# category has data — our menu of which (catID, year) pairs are worth POSTing.
_CHANGEYEAR_RE = re.compile(r'changeYear\((\d{4})\s*,\s*(\d+)', re.I)

# A meeting row: <tr ... class="catAgendaRow"> ... </tr>. Rows are flat (no
# nested <tr>), so a non-greedy match to the first </tr> is exact.
_ROW_RE = re.compile(r'<tr[^>]*class="catAgendaRow".*?</tr>', re.S | re.I)
# Collapsible body headers, in document order. Rows belong to the header above them.
_HEADER_RE = re.compile(r'<h2[^>]*data-cp-toggle[^>]*>(.*?)</h2>', re.S | re.I)
# A ViewFile link classifies the file (Agenda|Minutes) and carries _MMDDYYYY-<id>.
_VIEWFILE_RE = re.compile(
    r'/AgendaCenter/ViewFile/(Agenda|Minutes)/(_(\d{2})(\d{2})(\d{4})-(\d+))', re.I)
_PREVVERS_RE = re.compile(r'/AgendaCenter/PreviousVersions/\d+', re.I)
_VIDEO_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/[^"\'<> ]+', re.I)
# Text of the agenda link, used as a human label ("BOC Agenda").
_AGENDA_LINK_TEXT_RE = re.compile(
    r'<a[^>]*ViewFile/Agenda[^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')


def _clean(text):
    """Strip tags and collapse whitespace to a single line."""
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _abs(base_url, path):
    return base_url.rstrip('/') + path


def _header_positions(html):
    """[(char_offset, body_name), ...] in document order."""
    return [(m.start(), _clean(m.group(1))) for m in _HEADER_RE.finditer(html)]


def _body_for(offset, headers):
    body = None
    for pos, name in headers:
        if pos < offset:
            body = name
        else:
            break
    return body


def _parse_row(row, base_url, body):
    files = _VIEWFILE_RE.findall(row)
    if not files:
        return None  # a row with no downloadable file is not a usable record

    agenda_url = minutes_url = None
    meeting_id = iso_date = None
    for kind, token, mm, dd, yyyy, num in files:
        url = _abs(base_url, '/AgendaCenter/ViewFile/%s/%s' % (kind, token))
        if kind.lower() == 'agenda' and agenda_url is None:
            agenda_url = url
        elif kind.lower() == 'minutes' and minutes_url is None:
            minutes_url = url
        # date + id come from the token; agenda and minutes of one meeting share it
        if iso_date is None:
            iso_date, meeting_id = '%s-%s-%s' % (yyyy, mm, dd), num

    link_text = _AGENDA_LINK_TEXT_RE.search(row)
    label = _clean(link_text.group(1)) if link_text else None
    video = _VIDEO_RE.search(row)

    return {
        'body': body,
        'date': iso_date,
        'id': meeting_id,
        'title': label,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video.group(0) if video else None,
        'hasPreviousVersions': bool(_PREVVERS_RE.search(row)),
    }


def parse_agenda_center(html, base_url):
    """Parse Agenda Center HTML into a list of normalized meeting dicts.

    Meetings are sorted newest-first (date desc, then id desc). Bodies come from
    the panel header each row sits under.
    """
    headers = _header_positions(html)
    meetings = []
    seen = set()
    for m in _ROW_RE.finditer(html):
        meeting = _parse_row(m.group(0), base_url, _body_for(m.start(), headers))
        if not meeting or not meeting['date']:
            continue
        key = (meeting['body'], meeting['date'], meeting['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(meeting)

    meetings.sort(key=lambda x: (x['date'], int(x['id'])), reverse=True)
    return meetings


def _category_map(html):
    """{catID: body_name} from the category-panel headers."""
    return {int(cid): _clean(name) for cid, name in _CATPANEL_RE.findall(html)}


def _category_years(html):
    """{catID: sorted set of years that category has data} from the year toggles."""
    years = {}
    for y, cid in _CHANGEYEAR_RE.findall(html):
        years.setdefault(int(cid), set()).add(int(y))
    return years


def _post_category(base_url, cat_id, year, timeout, retries=2):
    """POST /AgendaCenter/UpdateCategoryList {year, catID} → the rows HTML for that
    category+year (the year-toggle AJAX). Returns '' on failure."""
    url = _abs(base_url, '/AgendaCenter/UpdateCategoryList')
    data = urllib.parse.urlencode({'year': year, 'catID': cat_id}).encode()
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': 'votega.org/1.0',
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest'})
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read().decode(
                'utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return ''  # 4xx: non-retryable
        except Exception:
            pass
    return ''


def _parse_rows(html, base_url, body):
    """Parse the catAgendaRow blocks in a POST fragment, all under one body."""
    out = []
    for m in _ROW_RE.finditer(html):
        rec = _parse_row(m.group(0), base_url, body)
        if rec and rec['date']:
            out.append(rec)
    return out


def fetch_agenda_center(base_url, module_id=AGENDA_MODULE_ID, timeout=30,
                        years=DEFAULT_YEARS, only_bodies=None):
    """Fetch and parse a county's Agenda Center. Returns (meetings, bodies_seen).

    The static /AgendaCenter page shows only the most-recent year *per category*;
    older years sit behind a year-toggle that fires a POST to UpdateCategoryList.
    So we parse the static page for the category map (catID → body) and each
    category's available years, then POST for every (catID, year) within the last
    `years` years and merge — giving the full recent window with correct body
    labels, not just whatever single year each category defaulted to. Pass
    years=0/None to keep only the static default parse (no extra requests).

    `only_bodies` (list of case-insensitive substrings) limits the year-toggle
    POSTs to categories whose name matches one — pass the place's body_map /
    include_bodies terms so a place that publishes 3 of 30 boards doesn't fetch
    history for the 27 it drops. When None, every category is paginated.

    Returns (None, None) only if the initial page fetch fails — the caller decides
    whether that should abort (it should: never overwrite good data with nothing).
    """
    url = _abs(base_url, '/AgendaCenter')
    raw = fetch_bytes(url, label='%s Agenda Center' % base_url, timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')

    # Base: the static default rows (labeled by their panel header).
    meetings = parse_agenda_center(html, base_url)
    seen = {(m['body'], m['date'], m['id']) for m in meetings}

    # Fill history: POST each active category's recent years, label by catID → body.
    if years:
        cats = _category_map(html)
        cat_years = _category_years(html)
        cutoff = dt.date.today().year - (years - 1)
        wanted = [s.lower() for s in only_bodies] if only_bodies else None
        for cid, body in cats.items():
            if wanted and not any(w in body.lower() for w in wanted):
                continue  # a body this place drops — don't fetch its history
            for yr in sorted((y for y in cat_years.get(cid, ()) if y >= cutoff),
                             reverse=True):
                frag = _post_category(base_url, cid, yr, timeout)
                for rec in _parse_rows(frag, base_url, body):
                    key = (rec['body'], rec['date'], rec['id'])
                    if key not in seen:
                        seen.add(key)
                        meetings.append(rec)
        meetings.sort(key=lambda x: (x['date'], int(x['id'])), reverse=True)

    bodies_seen = sorted({m['body'] for m in meetings}) or \
        [name for _, name in _header_positions(html)]
    return meetings, bodies_seen
