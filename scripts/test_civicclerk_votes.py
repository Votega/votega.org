#!/usr/bin/env python3
"""CivicClerk votes: tree walk, empty handling, and incremental carry-forward.

Run: python scripts/test_civicclerk_votes.py      (no network)
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.civicclerk_votes import extract_items, fetch_votes

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


VOTE = {'motionName': 'Approve', 'initiatedBy': 'A', 'secondedBy': 'B', 'passFail': 1,
        'yesVotes': ['A', 'B', ' '], 'noVotes': [], 'abstainVotes': ['C']}
TREE = [
    {'agendaObjectItemName': 'CONSENT', 'minutesItemVotes': [], 'childItems': [
        {'agendaObjectItemOutlineNumber': '1.', 'agendaObjectItemName': '<b data-x="1">Adopt​ Budget</b>',
         'ordinanceNumber': 7, 'resolutionNumber': 0, 'minutesItemVotes': [VOTE],
         'childItems': []},
        {'agendaObjectItemName': 'No motion', 'minutesItemVotes': None},
    ]},
    {'agendaObjectItemName': 'Blank motion', 'minutesItemVotes': [{'yesVotes': []}]},
]
items = extract_items(TREE)
check('only motion items kept', [i['name'] for i in items], ['Adopt Budget'])
m = items[0]['motions'][0]
check('blank voter dropped', m['yes'], ['A', 'B'])
check('abstain kept', m['abstain'], ['C'])
check('ordinance becomes reference', items[0]['reference'], '7')
check('result from tally, not passFail', items[0]['motions'][0]['result'], 'passed')
check('absent present but empty', items[0]['motions'][0]['absent'], [])
check('no empty strings', items[0]['motions'][0]['secondedBy'], 'B')

# --- incremental behaviour with a fake API ---
TODAY = dt.date(2026, 11, 2)
EVENTS = {'value': [
    {'id': 2, 'agendaId': 20, 'startDateTime': '2026-10-20T10:00:00Z', 'categoryName': 'BOC', 'eventName': 'Recent'},
    {'id': 1, 'agendaId': 10, 'startDateTime': '2026-03-01T10:00:00Z', 'categoryName': 'BOC', 'eventName': 'Old'},
    {'id': 3, 'agendaId': 0, 'startDateTime': '2026-02-01T10:00:00Z', 'categoryName': 'BOC'},
]}
calls = []


def fake(url, **kw):
    calls.append(url)
    if '/Events' in url:
        return EVENTS
    return {'items': [{'agendaObjectItemName': 'X', 'minutesItemVotes': [VOTE]}]}


first = fetch_votes('x', previous=None, years=2, today=TODAY, fetch=fake)
check('agendaId 0 skipped', [m['id'] for m in first], ['2', '1'])
check('votes captured', [bool(m['items']) for m in first], [True, True])

calls.clear()
second = fetch_votes('x', previous=first, years=2, today=TODAY, fetch=fake)
meeting_calls = [c for c in calls if '/Meetings/' in c]
check('old meeting not re-read, recent one is', meeting_calls, ['https://x.api.civicclerk.com/v1/Meetings/20'])
check('result stable', second, first)


def failing(url, **kw):
    return EVENTS if '/Events' in url else None


kept = fetch_votes('x', previous=first, years=2, today=TODAY, fetch=failing)
check('failed read keeps previous entry', [m['id'] for m in kept], ['2', '1'])
dropped = fetch_votes('x', previous=None, years=2, today=TODAY, fetch=failing)
check('failed read never published as empty', dropped, [])
check('listing failure is None', fetch_votes('x', fetch=lambda u, **k: None), None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
