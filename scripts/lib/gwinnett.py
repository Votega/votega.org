#!/usr/bin/env python3
"""Adapter for Gwinnett County's bespoke meetings portal.

Gwinnett runs its own Liferay-based "Boards, Authorities and Committees" (BAC)
portal rather than a third-party platform — no CivicPlus/Legistar/CivicClerk API.
Its meetings page is a server-rendered search-container table at
    /government/departments/county-clerk/boards-authorities/-/bacs/meetings/<id>
where <id> is the committee id (52 = Board of Commissioners). Each meeting is a
`<tr data-qa-id="row">` with labeled cells:

  * lfr-meeting-date/time-column   "MM/DD/YYYY HH:MM AM/PM"
  * lfr-meeting-column             the meeting TYPE (Business Session, Work Session,
                                   Public Hearing, Executive Session, …) — all
                                   variants of the one committee's body, so a place
                                   folds them with body_label / body_map.
  * lfr-agenda-column              agenda PDF   (/static/upload/bac/<id>/<date>/a_…)
  * lfr-agenda-package-column      full packet  (…/ap_…) — richer agenda fallback
  * lfr-minutes-column             minutes PDF  (…/m_…)
  * lfr-video/audio-column         a CHAMPDS recording link (absolute URL)

Agenda/minutes are direct text-layer PDFs on the county's own host (so this rides
the OCR enricher), and video is an external player link. Markup is stable Liferay
boilerplate, so regex parsing keeps this dependency-free (as lib/teammunicode.py).
One page carries a year+ of rows, so no pagination is needed. Output is the shared
normalized schema:
    {body, date, id, title, agendaUrl, minutesUrl, videoUrl, hasPreviousVersions}

Import from a generator in scripts/:
    from lib.gwinnett import fetch_gwinnett_meetings
"""

import datetime as dt
import re
from urllib.parse import urlparse

from lib.http import fetch_bytes

_ROW_RE = re.compile(r'<tr[^>]*data-qa-id="row".*?</tr>', re.S | re.I)
_DATE_RE = re.compile(r'lfr-meeting-date/time-column[^>]*>(.*?)</td>', re.S | re.I)
_TITLE_RE = re.compile(r'lfr-meeting-column[^>]*>(.*?)</td>', re.S | re.I)
_MDY_RE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')
_DOCID_RE = re.compile(r'/[a-z]+_(\d+)_', re.I)
_TAG_RE = re.compile(r'<[^>]+>')


def _clean(text):
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text or '')).strip()


def _cell_href(row, col):
    """First href inside the <td class="… lfr-<col>-column"> cell, or None."""
    m = re.search(r'lfr-%s[^>]*>(.*?)</td>' % re.escape(col), row, re.S | re.I)
    if not m:
        return None
    h = re.search(r'href="([^"]+)"', m.group(1), re.I)
    return h.group(1) if h else None


def _abs(origin, url):
    if not url:
        return None
    return origin + url if url.startswith('/') else url


def _parse_row(row, origin):
    date_m = _DATE_RE.search(row)
    title_m = _TITLE_RE.search(row)
    if not date_m or not title_m:
        return None
    mdy = _MDY_RE.search(_clean(date_m.group(1)))
    if not mdy:
        return None
    iso_date = '%s-%s-%s' % (mdy.group(3), mdy.group(1), mdy.group(2))
    title = _clean(title_m.group(1))
    if not title:
        return None

    # Prefer the standalone agenda; fall back to the full agenda package.
    agenda = _cell_href(row, 'agenda-column') or _cell_href(row, 'agenda-package-column')
    minutes = _cell_href(row, 'minutes-column')
    video = _cell_href(row, 'video/audio-column')
    agenda_url = _abs(origin, agenda)
    minutes_url = _abs(origin, minutes)
    video_url = _abs(origin, video)

    # Stable id from a document file id when present (a_<id>/m_<id>/…); otherwise a
    # date+title slug (unique per meeting — one type per timeslot).
    docid = None
    for u in (agenda, minutes, _cell_href(row, 'notice-column'), video):
        m = _DOCID_RE.search(u or '')
        if m:
            docid = m.group(1)
            break
    meeting_id = docid or ('%s-%s' % (iso_date, re.sub(r'\W+', '-', title.lower())[:40]))

    # Keep a document-less row only if it is UPCOMING (agenda not posted yet); drop
    # a past doc-less row (e.g. an Executive Session — closed, never has documents).
    upcoming = iso_date >= dt.date.today().isoformat()
    if not (agenda_url or minutes_url or video_url) and not upcoming:
        return None

    return {
        'body': title,   # relabeled to the committee's body via body_label/body_map
        'date': iso_date,
        'id': str(meeting_id),
        'title': title,
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video_url,
        'hasPreviousVersions': False,
    }


def parse_meetings(html, origin):
    meetings, seen = [], set()
    for m in _ROW_RE.finditer(html):
        rec = _parse_row(m.group(0), origin)
        if not rec:
            continue
        key = (rec['body'], rec['date'], rec['id'])
        if key in seen:
            continue
        seen.add(key)
        meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    return meetings


def fetch_gwinnett_meetings(meetings_url, timeout=30):
    """Fetch and parse a Gwinnett BAC committee meetings page.

    `meetings_url` is the committee's meetings page (…/bacs/meetings/<id>). Relative
    PDF links are resolved against that URL's origin. Returns (meetings,
    bodies_seen), or (None, None) if the page could not be fetched."""
    parsed = urlparse(meetings_url)
    origin = '%s://%s' % (parsed.scheme or 'https', parsed.netloc)
    raw = fetch_bytes(meetings_url, label='Gwinnett meetings', timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')
    meetings = parse_meetings(html, origin)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
