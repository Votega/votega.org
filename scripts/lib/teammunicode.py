#!/usr/bin/env python3
"""Adapter for Municode "Meetings" (teammunicode.com).

Some GA counties (Banks) run their public meetings on Municode's meetings portal —
a Drupal 7 site, often embedded via an iframe on the county's CivicPlus page, so
the CivicPlus Agenda Center itself is a near-empty stub and this is the real
source. The `/meetings` page is a server-rendered table (a Drupal view); each
<tr> carries:

  * an ISO calendar date  (<span class="date-display-single" content="…">)
  * a Meeting title       (<td class="views-field-title">) — which names the body
  * Agenda / Packet / Minutes / Video document links, one per column, as direct
    PDF URLs (hosted on an Azure blob store). One row already carries every
    document type, so — unlike CivicPlus — there is nothing to de-duplicate.

Markup is stable Drupal-view boilerplate, so regex parsing keeps this dependency-
free (same approach as lib/civicplus.py). Output is the shared normalized schema:
  {body, date, id, title, agendaUrl, minutesUrl, videoUrl, hasPreviousVersions}
`body` is set to the meeting title (the body name lives in it), so a place scopes
with body_map / include_bodies exactly like the CivicClerk places (Cobb, Douglas).

Import from a generator in scripts/ (sys.path[0] is scripts/):
    from lib.teammunicode import fetch_teammunicode_meetings
"""

import re
import time
from datetime import date, timezone, datetime

from lib.http import fetch_bytes

PAGE_DELAY = 1.5  # seconds between pager requests; the host captcha-challenges bursts
_CHALLENGE_RE = re.compile(r'HAProxy Challenge|g-recaptcha', re.I)
_TAG_RE = re.compile(r'<[^>]+>')
# Flat table rows; a meeting row is one that carries a calendar date.
_ROW_RE = re.compile(r'<tr[^>]*>.*?</tr>', re.S | re.I)
_DATE_RE = re.compile(r'date-display-single[^>]*content="([^"]+)"', re.I)
_TITLE_RE = re.compile(r'views-field-title[^>]*>(.*?)</td>', re.S | re.I)
_DETAIL_RE = re.compile(r'/([a-z0-9][a-z0-9-]*)/page/([a-z0-9-]+)', re.I)
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
_VIDEO_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/[^"\'<> ]+', re.I)


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _cell(row, field):
    """First href inside the <td class="views-field-<field>"> cell, or None."""
    m = re.search(r'views-field-%s[^>]*>(.*?)</td>' % re.escape(field), row, re.S | re.I)
    if not m:
        return None
    h = _HREF_RE.search(m.group(1))
    return h.group(1) if h else None


def _parse_row(row):
    date_m = _DATE_RE.search(row)
    title_m = _TITLE_RE.search(row)
    if not date_m or not title_m:
        return None  # not a meeting row (e.g. an alerts/other view)
    title = _clean(title_m.group(1))
    if not title:
        return None
    iso_date = date_m.group(1)[:10]  # YYYY-MM-DD from the ISO datetime
    detail = _DETAIL_RE.search(row)
    code = detail.group(1) if detail else None   # section slug = the body (reliable)
    slug = detail.group(2) if detail else None
    num = re.search(r'-(\d+)$', slug or '')
    meeting_id = num.group(1) if num else (slug or iso_date)

    # Prefer the standalone Agenda; fall back to the Agenda Packet.
    agenda_url = _cell(row, 'field-agendas') or _cell(row, 'field-packets')
    minutes_url = _cell(row, 'field-minutes')
    video = _VIDEO_RE.search(_cell(row, 'field-video-link') or '') \
        or _VIDEO_RE.search(row)
    # Keep a document-less row only if it is UPCOMING (a scheduled meeting whose
    # agenda isn't posted yet — useful to surface); drop a PAST doc-less row, which
    # is just noise (nothing to link to). The UI derives "upcoming" from the date.
    upcoming = iso_date >= date.today().isoformat()
    if not (agenda_url or minutes_url or video) and not upcoming:
        return None
    return {
        # The section slug (detail-link code) is the body — reliable across
        # instances where the title is the body name (Banks) OR just the meeting
        # type (Baldwin: "Regular Meeting"). A place scopes/relabels it via body_map.
        'body': code or title,
        'date': iso_date,
        'id': str(meeting_id),
        'title': title,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video.group(0) if video else None,
        'hasPreviousVersions': False,
    }


def parse_meetings(html):
    """Parse the /meetings table into normalized meeting dicts, newest-first."""
    meetings = []
    seen = set()
    for m in _ROW_RE.finditer(html):
        rec = _parse_row(m.group(0))
        if not rec:
            continue
        key = (rec['body'], rec['date'], rec['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings


def fetch_teammunicode_meetings(base_url, meetings_path='/meetings', timeout=30,
                                max_pages=1):
    """Fetch and parse a county's Municode meetings table.

    `meetings_path` is the path of the meetings view on this instance. The two
    Municode variants differ: `<sub>.teammunicode.com` serves it at `/meetings`
    (Baldwin, Banks — the default), while `<sub>.municodemeetings.com` serves it at
    the site root (Walton) — set meetings_path: "/" for those. Same Drupal-view
    markup either way, so only the URL differs.

    `max_pages` walks the view's pager (`?page=N`, 25 rows a page, newest first).
    The default of 1 reads only the first page, which is all a small county needs
    but is a WINDOW, not an archive, on a busy one: Augusta-Richmond's front page
    is seven weeks of meetings (25 rows) with the rest, back to 2009, behind
    "View Additional Meetings". A page past the end renders an empty table rather
    than a 404, so the walk stops at the first page with no meeting rows. Keep it
    SHORT (Augusta uses 8, ~15 months): a burst of requests trips the host's HAProxy
    captcha, which answers 200 with a challenge page - detected and treated as a
    failed fetch, never as the end of the archive. Adjacent
    pages overlap by a row or two at the seam; parse_meetings' key dedupe absorbs it.

    Returns (meetings, bodies_seen), or (None, None) if the first page could not be
    fetched — the caller decides whether a fetch failure should abort (it should:
    never overwrite good data with nothing). A later page that fails ALSO returns
    (None, None) rather than the pages gathered so far: a truncated archive is
    indistinguishable from a real one once written."""
    path = meetings_path or '/'
    if not path.startswith('/'):
        path = '/' + path
    url = base_url.rstrip('/') + path
    sep = '&' if '?' in url else '?'

    meetings, seen = [], set()
    for page in range(max(1, int(max_pages))):
        page_url = url if page == 0 else '%s%spage=%d' % (url, sep, page)
        raw = fetch_bytes(page_url, label='%s meetings p%d' % (base_url, page),
                          timeout=timeout)
        if raw is None:
            return None, None
        html = raw.decode('utf-8', errors='replace')
        if page > 0 and not _DATE_RE.search(html):
            if _CHALLENGE_RE.search(html):
                # Rate-limited: HTTP 200 with a captcha page. NOT the end of the
                # table, and not something to work around - give up, keep old data.
                print('  %s: bot challenge on page %d; stopping' % (base_url, page))
                return None, None
            break  # past the last page: an empty table, not an error
        if page > 0:
            time.sleep(PAGE_DELAY)
        for rec in parse_meetings(html):
            key = (rec['body'], rec['date'], rec['id'])
            if key not in seen:
                seen.add(key)
                meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
