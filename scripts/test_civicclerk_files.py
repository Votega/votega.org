#!/usr/bin/env python3
"""CivicClerk publishedFiles -> meeting links (agenda, packet, minutes, other).

Run: python scripts/test_civicclerk_files.py      (no network)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.civicclerk import _event_to_meeting, _file_url


def ev(*files):
    return {'id': 7, 'categoryName': 'BOC', 'eventName': 'Meeting',
            'startDateTime': '2026-09-28T18:00:00Z',
            'publishedFiles': [{'fileId': i, 'type': t, 'name': n}
                               for i, t, n in files]}


U = lambda i: _file_url('x', i)
failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


m = _event_to_meeting('x', ev((1, 'Agenda', 'Docket'), (2, 'Agenda Packet', 'Packet'),
                              (3, 'Other', 'Addendum Class & Comp')))
check('agenda', m['agendaUrl'], U(1))
check('packet kept separate', m['agendaPacketUrl'], U(2))
check('other labelled by name', m['otherUrls'], [{'label': 'Addendum Class & Comp', 'url': U(3)}])

m = _event_to_meeting('x', ev((2, 'Agenda Packet', 'Packet')))
check('packet-only stands in as agenda', m['agendaUrl'], U(2))
check('...and is not repeated', 'agendaPacketUrl' in m, False)
check('no other key when empty', 'otherUrls' in m, False)

m = _event_to_meeting('x', ev((3, 'Notice', 'Special Called Notice')))
check('notice-only meeting is kept', m and m['otherUrls'][0]['label'], 'Special Called Notice')
check('...with no agenda', m['agendaUrl'], None)

check('no files still dropped', _event_to_meeting('x', ev()), None)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
