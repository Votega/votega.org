#!/usr/bin/env python3
"""Adapter for Simbli (eBOARDsolutions) — the Georgia school boards' platform.

Simbli is the board-governance product of eBOARDsolutions, a subsidiary of the
Georgia School Boards Association, so its penetration among Georgia school
districts is unusually high: the phase-3b census found 15 of the 23 reachable
districts on Simbli and ZERO on BoardDocs (docs/LOCAL-EXPANSION-SCOPE.md §3.5.1).
This is therefore the adapter that opens up school-board meetings.

WHY THERE IS PARSING WORK AT ALL
--------------------------------
The listing's anchors are `href="javascript:void(0)"`. A link scraper finds
nothing. Every row instead carries its identifiers as the arguments of an
`onclick` handler:

    <td><span title='11/03/2026 - 08:30 AM'>11/03/2026 - 08:30 AM</span></td>
    <td><a onclick='javascript:return ViewMeeting("4122","140227","1","0","P",event);'
           href='javascript:void(0);'>Special Session …</a></td>
    <td><a onclick='javascript:return ViewMinutes("4122","140227","UNPUBLISHED","0","P","0",event);'
           href='javascript:void(0);'>UnPublished</a></td>
    <td>Board Meeting</td>

and the page's own `SB_Assets/JS/Pages/SB_MeetingListingJS.js` turns those into
URLs. Read from that file on 2026-11-02, verbatim:

    function ViewMeeting(schoolID, meetingID, meetingStatus, isLoggedInUser, access, event) {
        if (meetingStatus == "1" && isLoggedInUser == "0") {
            window.location.href = "/SB_Meetings/ViewMeeting.aspx?S=" + schoolID + "&MID=" + meetingID;

    function ViewMinutes(schoolID, meetingID, minutesStatus, isLoggedInUser, access, canPrintMinutes, event) {
        ...
        else {   // anonymous
            if (minutesStatus == "PUBLISHED") {
                window.location.href = "/SB_Meetings/ViewMeeting.aspx?S=" + schoolID + "&MID=" + meetingID + "&T=" + 1;

So, for an anonymous visitor:

  * agenda  -> /SB_Meetings/ViewMeeting.aspx?S=<district>&MID=<meeting>
               offered only when meetingStatus == "1"
  * minutes -> the SAME page with &T=1
               offered only when minutesStatus == "PUBLISHED"

CORRECTION TO THE SCOPE DOC: it recorded the minutes URL as
`/Meetings/PrintMinutes.aspx`. That is the COMMENTED-OUT older body of
`ViewMinutes` still sitting in the file above the live one. The live function
uses `ViewMeeting.aspx?…&T=1`. Reading the dead copy is an easy mistake to
repeat, hence this note.

Its own guard, `meetingStatus == "1" && isLoggedInUser == "0"`, is also the
proof that **no login is involved** for published meetings.

TELLING A SERVED PAGE FROM A BLOCK
----------------------------------
The host sits behind Imperva/Incapsula and serves intermittent block pages. The
only safe check is: **does the response contain a meeting grid?** An earlier wrong
call about Simbli came from asserting on response SIZE — a 6,650-byte challenge
page was read as a good fetch. Size says nothing about what a page IS.

A vendor marker is no better as a test, for a plainer reason: it describes the
infrastructure, not the response. The two fixtures here happen to separate on it
(the 150 KB listing carries no `_Incapsula_Resource` reference and the block page
does), so it would pass today, but it asks the wrong question and the answer is
the vendor's to change. `is_listing` therefore tests for the grid and nothing
else, and the tests pin that rather than the marker.

Blocks are transient, so `fetch_listing` retries. Measured from the dev
container on 2026-11-02: one of twelve probes served the full 150 KB listing
with all 50 meetings and the other eleven were blocked, so the retry budget here
is not decoration. That success rate is this container's egress reputation, not
the district's — a CI runner or an ordinary network should do far better, and
that remains UNVERIFIED until this runs there.

WHAT A LISTING CONTAINS
-----------------------
50 rows, no pagination controls, spanning roughly a year either side of today
(Newton: 2025-12-16 through 2026-11-03). There is no archive link to walk, so
this is the window the platform gives and the adapter does not try to page.

`body` is NOT taken from the row. The grid's fourth column is a meeting TYPE
("Board Meeting", "Work Session") — all 50 Newton rows say "Board Meeting" — and
the project's schema wants `body` to name the governing body, so it defaults to
"Board of Education" and is overridable per district. The type is kept as the
title's fallback for a row whose anchor text is empty.

Import from a generator in scripts/:
    from lib.simbli import fetch_simbli_meetings
"""

import re
import time

from lib.http import fetch_bytes

HOST = 'https://simbli.eboardsolutions.com'
LISTING_PATH = '/SB_Meetings/SB_MeetingListing.aspx?S=%s'
MEETING_PATH = '/SB_Meetings/ViewMeeting.aspx?S=%s&MID=%s'
DEFAULT_BODY = 'Board of Education'
# Blocks are transient; see the module docstring for the measured hit rate.
DEFAULT_ATTEMPTS = 4
DEFAULT_PAUSE = 5

_ROW_RE = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S | re.I)
_TD_RE = re.compile(r'<td\b[^>]*>(.*?)</td>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')
# The span's title attribute and its text carry the same value; the title is
# taken because it is a single attribute rather than markup-wrapped text.
_WHEN_RE = re.compile(r"title=['\"](\d{2}/\d{2}/\d{4})\s*-\s*([^'\"]*)['\"]", re.I)
_VIEW_MEETING_RE = re.compile(
    r'ViewMeeting\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"', re.I)
_VIEW_MINUTES_RE = re.compile(
    r'ViewMinutes\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"', re.I)
_ANCHOR_TEXT_RE = re.compile(r'<a\b[^>]*>(.*?)</a>', re.S | re.I)
# A district key, read from any Simbli URL. The vanity paths carry none, which is
# why resolve_district_id exists.
_S_PARAM_RE = re.compile(r'[?&]S=(\d+)', re.I)


class SimbliBlocked(Exception):
    """The host answered, but with a challenge/block page rather than a listing."""


def _text(fragment):
    return re.sub(r'\s+', ' ', _TAG_RE.sub(' ', fragment or '')).strip()


def is_listing(html):
    """True when `html` is a served meeting listing.

    The ONE honest check: a listing names its rows' handler. A block page, a
    challenge page, an error page and a login wall all lack it. Do not replace
    this with a size threshold or an Incapsula-marker substring — both have
    already produced wrong conclusions about this platform (see the docstring).
    """
    return 'ViewMeeting(' in (html or '')


def listing_url(district_id):
    return HOST + LISTING_PATH % district_id


def meeting_url(district_id, meeting_id, minutes=False):
    """Anonymous URL for a meeting's agenda, or its minutes with `minutes=True`.
    `&T=1` is what the live ViewMinutes uses; see the docstring's correction."""
    url = HOST + MEETING_PATH % (district_id, meeting_id)
    return url + '&T=1' if minutes else url


def _iso_date(mmddyyyy):
    mm, dd, yyyy = mmddyyyy.split('/')
    return '%s-%s-%s' % (yyyy, mm, dd)


_TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})\s*([AaPp])', re.I)


def _sort_time(text):
    """A 24-hour "HH:MM" sort key from "07:00 PM", or '' when unparseable.

    Needed because two meetings on one day are ordinary here - Newton held a
    5:30 PM and a 7:00 PM meeting on 2026-10-27 - and their MEETING IDS SORT THE
    OTHER WAY from their times, so an id tiebreak puts the evening session
    above the afternoon one. Returning '' for an odd format sends that row below
    its timed siblings rather than reordering them around a guess.
    """
    m = _TIME_RE.match((text or '').strip())
    if not m:
        return ''
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == 'p':
        hour += 12
    return '%02d:%s' % (hour, m.group(2))


def parse_listing(html, district_id=None, body=DEFAULT_BODY):
    """Parse listing HTML into (meetings, bodies_seen).

    Pure: no network, no clock. Rows that carry no date or no ViewMeeting call
    (the grid's header row, or a future markup change) are skipped rather than
    guessed at. A row whose meetingStatus is not "1" is NOT viewable anonymously,
    so it yields no agenda URL — it is still returned, because the meeting
    genuinely happened and the date and title are real.
    """
    meetings, seen = [], set()
    for row in _ROW_RE.findall(html or ''):
        when = _WHEN_RE.search(row)
        vm = _VIEW_MEETING_RE.search(row)
        if not when or not vm:
            continue
        sid, mid, status = vm.group(1), vm.group(2), vm.group(3)
        if district_id and sid != str(district_id):
            # A listing only ever carries its own district; a mismatch means the
            # page is not the one that was asked for.
            continue
        if mid in seen:
            continue
        seen.add(mid)

        tds = _TD_RE.findall(row)
        title = ''
        if len(tds) > 1:
            title = _text(''.join(_ANCHOR_TEXT_RE.findall(tds[1])))
        meeting_type = _text(tds[-1]) if tds else ''
        # The minutes cell's own anchor text is the state as a word
        # ("UnPublished"); the authoritative value is the handler's argument.
        vmin = _VIEW_MINUTES_RE.search(row)
        published = bool(vmin) and vmin.group(3).upper() == 'PUBLISHED'

        meetings.append({
            'body': body,
            'date': _iso_date(when.group(1)),
            'time': (when.group(2) or '').strip() or None,
            'id': mid,
            'title': title or meeting_type or 'Meeting',
            'agendaUrl': meeting_url(sid, mid) if status == '1' else None,
            'minutesUrl': meeting_url(sid, mid, minutes=True) if published else None,
            'videoUrl': None,
            'hasPreviousVersions': False,
        })

    meetings.sort(key=lambda m: (m['date'], _sort_time(m['time']), m['id']),
                  reverse=True)
    return meetings, sorted({m['body'] for m in meetings})


def resolve_district_id(path_or_id, fetch=fetch_bytes, timeout=30):
    """Return the numeric district key for an `S=` id, a listing URL, or a vanity
    path such as `walton` / `https://simbli.eboardsolutions.com/walton`.

    Some districts link only the vanity form, which carries no key, so it has to
    be fetched and the key read out of whatever Simbli serves there — every
    Simbli link on a district's own pages carries the same `S=<id>`, including
    policy-manual links, which is what makes this reliable.

    Returns None when the key cannot be found. UNVERIFIED against a live vanity
    path: every attempt from the dev container was blocked (see the docstring),
    so this path is exercised only by its test.
    """
    s = str(path_or_id).strip()
    if s.isdigit():
        return s
    found = _S_PARAM_RE.search(s)
    if found:
        return found.group(1)

    url = s if s.startswith('http') else '%s/%s' % (HOST, s.lstrip('/'))
    raw = fetch(url, label='simbli vanity %s' % s, timeout=timeout)
    if not raw:
        return None
    html = raw.decode('utf-8', errors='replace')
    found = _S_PARAM_RE.search(html)
    return found.group(1) if found else None


def fetch_listing(district_id, fetch=fetch_bytes, attempts=DEFAULT_ATTEMPTS,
                  pause=DEFAULT_PAUSE, timeout=30, sleep=time.sleep):
    """Fetch one district's listing HTML, retrying through transient blocks.

    Raises SimbliBlocked when every attempt came back something other than a
    listing, so a caller cannot mistake a block for an empty board. Returns None
    only when the fetcher itself returned nothing on the last attempt — i.e. a
    network/HTTP failure that lib.http already retried under its own policy.

    `fetch` and `sleep` are injected so the retry behaviour is testable without
    a network or a wall clock.
    """
    url = listing_url(district_id)
    blocked = 0
    for attempt in range(1, max(1, attempts) + 1):
        raw = fetch(url, label='simbli listing %s' % district_id, timeout=timeout)
        if raw:
            html = raw.decode('utf-8', errors='replace')
            if is_listing(html):
                return html
            blocked += 1
        if attempt < attempts:
            sleep(pause * attempt)
    if blocked:
        raise SimbliBlocked(
            '%s: %d of %d attempts returned a non-listing page (Incapsula block or '
            'challenge). Not an empty board.' % (url, blocked, attempts))
    return None


def fetch_simbli_meetings(district, body=DEFAULT_BODY, fetch=fetch_bytes,
                          attempts=DEFAULT_ATTEMPTS, pause=DEFAULT_PAUSE,
                          timeout=30, sleep=time.sleep):
    """Fetch and parse one Simbli district.

    `district` is an `S=` id, a listing URL, or a vanity path. Returns
    (meetings, bodies_seen), matching every other adapter in lib/, or
    (None, None) when the district key cannot be resolved or the fetcher failed.
    Raises SimbliBlocked when the host answered only with block pages.
    """
    district_id = resolve_district_id(district, fetch=fetch, timeout=timeout)
    if not district_id:
        return None, None
    html = fetch_listing(district_id, fetch=fetch, attempts=attempts,
                         pause=pause, timeout=timeout, sleep=sleep)
    if html is None:
        return None, None
    return parse_listing(html, district_id=district_id, body=body)
