#!/usr/bin/env python3
"""Legistar votes: value normalisation, title split, incremental reads.

Run: python scripts/test_legistar_votes.py      (no network)
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.legistar_votes import fetch_votes, motion_from, split_title
from lib.meeting_votes import bucket, clean_text, result_from_tally

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


check('Yea/Yes both yes', (bucket('Yea'), bucket('Yes')), ('yes', 'yes'))
check('Nay/No both no', (bucket('Nay'), bucket('No')), ('no', 'no'))
check('absent', bucket(' Absent '), 'absent')
check('unknown value ignored', bucket('Recused'), None)
check('tag strip', clean_text('<b x="1">Hi</b>​  there'), 'Hi there')
check('empty -> None', clean_text('  '), None)
check('tie is not passed', result_from_tally(['a'], ['b']), 'failed')
check('nobody voted -> None', result_from_tally([], []), None)

check('district split',
      split_title('Commission District(s): 3 & 7\r\nTraffic Calming Petition'),
      ('3 & 7', 'Traffic Calming Petition'))
check('no district', split_title('Adopt the agenda'), (None, 'Adopt the agenda'))

ITEM = {'EventItemActionName': 'Approved', 'EventItemMover': 'A B', 'EventItemSeconder': '',
        'EventItemPassedFlagName': 'Pass'}
VOTES = [{'VotePersonName': 'A B', 'VoteValueName': 'Yes'},
         {'VotePersonName': 'C D', 'VoteValueName': 'Absent'},
         {'VotePersonName': 'E F', 'VoteValueName': 'Nay'}]
m = motion_from(ITEM, VOTES)
check('columns', (m['yes'], m['no'], m['absent'], m['abstain']),
      (['A B'], ['E F'], ['C D'], []))
check('Legistar states the result, not the tally (1-1 but "Pass")', m['result'], 'passed')
check('blank seconder is None', m['secondedBy'], None)

TODAY = dt.date(2026, 11, 2)
EVENTS = [
    {'EventId': 2, 'EventDate': '2026-10-20T00:00:00', 'EventBodyName': 'Board'},
    {'EventId': 1, 'EventDate': '2026-03-01T00:00:00', 'EventBodyName': 'Board'},
]
calls = []


def fake(url, **kw):
    calls.append(url)
    if url.endswith('/Votes'):
        return VOTES
    if '/EventItems' in url:
        return [{'EventItemId': 9, 'EventItemActionName': 'Approved',
                 'EventItemTitle': 'T', 'EventItemMatterFile': '26-1',
                 'EventItemPassedFlagName': 'Pass'},
                {'EventItemId': 10, 'EventItemActionName': None, 'EventItemTitle': 'Heading'}]
    return EVENTS


first = fetch_votes('c', previous=None, months=12, today=TODAY, fetch=fake)
check('events read', [x['id'] for x in first], ['2', '1'])
check('only acted items kept', [len(x['items']) for x in first], [1, 1])
check('reference is the file number', first[0]['items'][0]['reference'], '26-1')

calls.clear()
second = fetch_votes('c', previous=first, months=12, today=TODAY, fetch=fake)
check('old meeting not re-read', [c for c in calls if '/Events/1/' in c], [])
check('recent meeting re-read', bool([c for c in calls if '/Events/2/' in c]), True)
check('stable', second, first)


def votes_fail(url, **kw):
    return None if url.endswith('/Votes') else fake(url)


check('partial meeting keeps previous', fetch_votes('c', previous=first, months=12, today=TODAY,
                                                   fetch=votes_fail)[0], first[0])
check('partial meeting never published as complete',
      [x['id'] for x in fetch_votes('c', previous=None, months=12, today=TODAY, fetch=votes_fail)], [])
check('listing failure is None', fetch_votes('c', fetch=lambda u, **k: None), None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
