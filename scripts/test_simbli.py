#!/usr/bin/env python3
"""Invariants of the Simbli adapter (lib/simbli.py). No network, no clock.

Fixtures are REAL responses captured 2026-11-02:
  * fixtures/simbli-newton-listing.html  - the live listing for district 4122
    (Newton County Schools), cut from 50 rows to 7: three with UNPUBLISHED
    minutes and four PUBLISHED, plus the two meetings Newton held on 2026-10-27
    whose ids sort the opposite way from their times.
  * fixtures/simbli-incapsula-block.html - the block page the same host serves
    intermittently.

What is pinned, and why:
  * The agenda and minutes URLs are checked against the shapes read out of the
    platform's own SB_MeetingListingJS.js, including that MINUTES IS
    ViewMeeting.aspx with &T=1 - not PrintMinutes.aspx, which is the
    commented-out older code in that file and what the scope doc first recorded.
  * The anchors are href="javascript:void(0)", so a row's URLs exist only if the
    onclick arguments were parsed. A regression here yields meetings with no
    links rather than an exception, so the links are asserted literally.
  * UNPUBLISHED minutes must come out as None, not "" and not a URL that would
    send a reader to a login wall.
  * `body` is "Board of Education", NOT the grid's "Board Meeting" - that column
    is a meeting type, and the schema's `body` names the governing body.
  * A served listing and a block page are told apart by the presence of a
    meeting grid. Not by size: an earlier wrong call about this platform came
    from reading a 6,650-byte challenge page as a good fetch.
  * Blocks are transient, so fetch_listing retries - and when every attempt is
    blocked it RAISES, because a caller must not record a blocked district as a
    board with no meetings.

Run: python scripts/test_simbli.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import simbli as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LISTING = open(os.path.join(HERE, 'fixtures', 'simbli-newton-listing.html'),
               encoding='utf-8').read()
BLOCK = open(os.path.join(HERE, 'fixtures', 'simbli-incapsula-block.html'),
             encoding='utf-8').read()

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def raises(fn, exc, needle=''):
    try:
        fn()
    except exc as e:
        return needle in str(e)
    except Exception:
        return False
    return False


# --------------------------------------------------------------- real listing
print('Real listing fixture (district 4122)')
meetings, bodies = S.parse_listing(LISTING, district_id='4122')
by_id = {m['id']: m for m in meetings}

check(len(meetings) == 7, '7 rows parsed, got %d' % len(meetings))
check([m['date'] for m in meetings] == sorted((m['date'] for m in meetings), reverse=True),
      'newest first')
check(bodies == ['Board of Education'],
      'body is the governing body, not the grid\'s meeting type: %r' % bodies)
check(all(m['body'] == 'Board of Education' for m in meetings),
      'every row carries the body')

top = by_id.get('140227')
check(top is not None, 'the 11/03/2026 row is present as meeting 140227')
if top:
    check(top['date'] == '2026-11-03', 'MM/DD/YYYY became ISO: %r' % top['date'])
    check(top['time'] == '08:30 AM', 'time kept from the span title: %r' % top['time'])
    check(top['agendaUrl'] == 'https://simbli.eboardsolutions.com/SB_Meetings/'
                              'ViewMeeting.aspx?S=4122&MID=140227',
          'agenda URL built from the ViewMeeting arguments: %r' % top['agendaUrl'])
    check(top['minutesUrl'] is None,
          'UNPUBLISHED minutes is None, not a link to a wall: %r' % top['minutesUrl'])
    check('Tribunal Appeal' in (top['title'] or ''),
          'title comes from the anchor text: %r' % top['title'])
    check(top['videoUrl'] is None and top['hasPreviousVersions'] is False,
          'schema keys present with the adapterless defaults')

published = [m for m in meetings if m['minutesUrl']]
unpublished = [m for m in meetings if not m['minutesUrl']]
check(len(published) == 4 and len(unpublished) == 3,
      '4 PUBLISHED / 3 UNPUBLISHED, got %d/%d' % (len(published), len(unpublished)))
check(all(m['minutesUrl'].endswith('&T=1') for m in published),
      'minutes is ViewMeeting.aspx with &T=1 (the LIVE ViewMinutes), '
      'not PrintMinutes.aspx')
check(all(m['minutesUrl'] == m['agendaUrl'] + '&T=1' for m in published),
      'minutes is the agenda URL plus &T=1')
check(all(m['agendaUrl'] for m in meetings),
      'every row has an agenda URL (meetingStatus "1" throughout this fixture)')
check(not any(m['agendaUrl'] == '' or m['minutesUrl'] == '' for m in meetings),
      'no empty-string URL anywhere - None means absent')
check(all(m['title'] and m['title'] != 'Board Meeting' for m in meetings),
      'titles are the real anchor text, not the type column')

# The grid's <thead> row has no date and no handler; it must not become a meeting.
check(all(len(m['date']) == 10 and m['date'][4] == '-' for m in meetings),
      'no header or chrome row leaked in as a meeting')

same_day = [m for m in meetings if m['date'] == '2026-10-27']
check(len(same_day) == 2, 'both 2026-10-27 meetings parsed')
if len(same_day) == 2:
    check([m['time'] for m in same_day] == ['07:00 PM', '05:30 PM'],
          'two meetings on one day sort by TIME, latest first: %r'
          % [m['time'] for m in same_day])
    check(same_day[0]['id'] == '139133' and same_day[1]['id'] == '140028',
          'and NOT by meeting id, which sorts them the other way round')

print('Time parsing')
check(S._sort_time('07:00 PM') == '19:00', 'PM hours shift by 12')
check(S._sort_time('12:30 AM') == '00:30', 'midnight hour is 00, not 12')
check(S._sort_time('12:15 PM') == '12:15', 'noon hour stays 12')
check(S._sort_time('08:30 AM') == '08:30', 'AM hours are zero-padded as given')
check(S._sort_time('') == '' and S._sort_time(None) == '' and S._sort_time('noon') == '',
      'an unparseable time sorts last instead of guessing')

print('District scoping')
other, _ = S.parse_listing(LISTING, district_id='9999')
check(other == [], 'a listing for another district yields nothing, not mismatched rows')
unscoped, _ = S.parse_listing(LISTING)
check(len(unscoped) == 7, 'parsing without a district id still works')

print('Custom body')
named, named_bodies = S.parse_listing(LISTING, district_id='4122',
                                      body='Newton County Board of Education')
check(named_bodies == ['Newton County Board of Education'], 'body is overridable')
check(len(named) == 7, 'overriding the body changes nothing else')

# ------------------------------------------------------------- block page
print('Telling a served page from a block')
check(S.is_listing(LISTING) is True, 'the real listing is recognised')
check(S.is_listing(BLOCK) is False, 'the real block page is rejected')
check(S.is_listing('') is False and S.is_listing(None) is False,
      'empty and None are not listings')
check(len(BLOCK) < len(LISTING),
      'the block page is SMALLER than the listing here - which is exactly why '
      'size is not the test (a paged or small listing would invert it)')
blocked_meetings, blocked_bodies = S.parse_listing(BLOCK)
check(blocked_meetings == [] and blocked_bodies == [],
      'parsing a block page yields nothing rather than junk')

# ------------------------------------------------------------- URL builders
print('URL shapes, against the platform\'s own JS')
check(S.listing_url('4122') == 'https://simbli.eboardsolutions.com/SB_Meetings/'
                               'SB_MeetingListing.aspx?S=4122', 'listing URL')
check(S.meeting_url('4122', '140227') == 'https://simbli.eboardsolutions.com/'
      'SB_Meetings/ViewMeeting.aspx?S=4122&MID=140227', 'agenda URL')
check(S.meeting_url('4122', '140227', minutes=True) ==
      'https://simbli.eboardsolutions.com/SB_Meetings/ViewMeeting.aspx?'
      'S=4122&MID=140227&T=1', 'minutes URL is the agenda URL plus &T=1')


# ------------------------------------------------------------- retry policy
class Fetcher(object):
    """Returns the queued responses in order, then repeats the last one."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append(url)
        i = min(len(self.calls) - 1, len(self.responses) - 1)
        body = self.responses[i]
        return None if body is None else body.encode('utf-8')


class Clock(object):
    def __init__(self):
        self.slept = []

    def __call__(self, seconds):
        self.slept.append(seconds)


print('Retrying through a transient block')
f = Fetcher(BLOCK, BLOCK, LISTING)
c = Clock()
html = S.fetch_listing('4122', fetch=f, attempts=4, pause=5, sleep=c)
check(S.is_listing(html), 'a listing on the third attempt is returned')
check(len(f.calls) == 3, 'stopped as soon as it got one: %d calls' % len(f.calls))
check(c.slept == [5, 10], 'backoff is pause * attempt: %r' % c.slept)
check(all(url == S.listing_url('4122') for url in f.calls), 'same URL each time')

print('Every attempt blocked')
f = Fetcher(BLOCK)
c = Clock()
check(raises(lambda: S.fetch_listing('4122', fetch=f, attempts=3, pause=1, sleep=c),
             S.SimbliBlocked, 'Not an empty board'),
      'raises SimbliBlocked rather than returning an empty list')
check(len(f.calls) == 3, 'used its whole budget: %d calls' % len(f.calls))
check(c.slept == [1, 2], 'no sleep after the final attempt: %r' % c.slept)

print('Fetcher failure is not a block')
f = Fetcher(None)
check(S.fetch_listing('4122', fetch=f, attempts=2, pause=1, sleep=Clock()) is None,
      'a network/HTTP failure returns None instead of raising - lib.http has '
      'already applied the retry policy for those')

print('A single attempt is honoured')
f = Fetcher(LISTING)
c = Clock()
S.fetch_listing('4122', fetch=f, attempts=1, pause=9, sleep=c)
check(len(f.calls) == 1 and c.slept == [], 'attempts=1 fetches once and never sleeps')


# --------------------------------------------------- district id resolution
print('Resolving a district key')
check(S.resolve_district_id('4122') == '4122', 'a bare id passes through')
check(S.resolve_district_id(4122) == '4122', 'an int id is accepted')
check(S.resolve_district_id(S.listing_url('4020')) == '4020', 'read out of a listing URL')
check(S.resolve_district_id('https://simbli.eboardsolutions.com/SB_Policy/'
                            'SB_PolicyOverview.aspx?S=36031609') == '36031609',
      'read out of a policy URL too - every Simbli link carries the same key')

vanity = Fetcher('<a href="/SB_Meetings/SB_MeetingListing.aspx?S=4567">Meetings</a>')
check(S.resolve_district_id('walton', fetch=vanity) == '4567',
      'a vanity path is fetched and its key read out')
check(vanity.calls == ['https://simbli.eboardsolutions.com/walton'],
      'the vanity path is requested on the Simbli host: %r' % vanity.calls)
check(S.resolve_district_id('https://simbli.eboardsolutions.com/walton',
                            fetch=Fetcher('<a href="?S=4567">x</a>')) == '4567',
      'a full vanity URL works the same way')
check(S.resolve_district_id('walton', fetch=Fetcher(BLOCK)) is None,
      'a blocked vanity fetch resolves to None, not a guess')
check(S.resolve_district_id('walton', fetch=Fetcher(None)) is None,
      'a failed vanity fetch resolves to None')


# ------------------------------------------------------------- end to end
print('fetch_simbli_meetings end to end')
f = Fetcher(LISTING)
got, got_bodies = S.fetch_simbli_meetings('4122', fetch=f, sleep=Clock())
check(len(got) == 7 and got_bodies == ['Board of Education'],
      'an id goes straight to the listing and parses')
check(len(f.calls) == 1, 'a numeric id needs no resolution fetch')

f = Fetcher('<a href="?S=4122">x</a>', LISTING)
got, _ = S.fetch_simbli_meetings('newton', fetch=f, sleep=Clock())
check(len(got) == 7, 'a vanity path resolves then parses')
check(f.calls == ['https://simbli.eboardsolutions.com/newton',
                  S.listing_url('4122')], 'two fetches, in order: %r' % f.calls)

got, got_bodies = S.fetch_simbli_meetings('walton', fetch=Fetcher(None), sleep=Clock())
check(got is None and got_bodies is None,
      'an unresolvable district returns (None, None), the adapter convention')

check(raises(lambda: S.fetch_simbli_meetings('4122', fetch=Fetcher(BLOCK),
                                             attempts=2, pause=0, sleep=Clock()),
             S.SimbliBlocked),
      'a wholly blocked district raises rather than reporting zero meetings')

print('')
if failures:
    print('FAILED %d check(s):' % len(failures))
    for f_ in failures:
        print('  - %s' % f_)
    sys.exit(1)
print('All Simbli adapter checks passed.')
