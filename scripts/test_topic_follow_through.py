#!/usr/bin/env python3
"""Topic feeds: a tagged meeting is followed to what its minutes record.

generate_topic_mentions.follow_through() joins a mention to the same meeting's
recorded-votes record and keeps only the items that carry the page's topic, by
the one taxonomy (lib/meeting_topics.classify). See the follow-through convention in CLAUDE.md.

Run: python scripts/test_topic_follow_through.py      (no network, no packages)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_topic_mentions import follow_through, topic_in_tags

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


def motion(**kw):
    base = {'motion': None, 'movedBy': None, 'secondedBy': None, 'result': None,
            'yes': [], 'no': [], 'abstain': [], 'absent': []}
    base.update(kw)
    return base


MEETING = {'id': '4421', 'minutesUrl': 'https://x/min', 'minutesDraft': False, 'items': [
    {'reference': '26-R-4352', 'outline': None, 'district': None,
     'name': 'A SUBSTITUTE RESOLUTION ... MOBILE SURVEILLANCE CAMERAS WITH FMP INNOVATIONS',
     'motions': [motion(result='passed', resultText='Adopted substitute',
                        resultClass='adopted-substitute', tally=[11, 0],
                        yes=['A'] * 11, absent=['B'] * 4)]},
    {'reference': '26-O-1474', 'outline': None, 'district': None,
     'name': 'AN ORDINANCE ... REQUIRING DATA CENTERS LOCATED WITHIN THE CITY',
     'motions': [motion(resultText='Returned as held', resultClass='held',
                        next='City Utilities Committee (11/24/2026 10:00 AM)')]},
    {'reference': '26-R-4329', 'outline': None, 'district': None,
     'name': 'A RESOLUTION AUTHORIZING A LEASE', 'motions': [motion(result='passed')]},
]}

status, outcomes, extra = follow_through('alpr', MEETING)
check('alpr: recorded', status, 'recorded')
check('alpr: only the camera item', [o['reference'] for o in outcomes], ['26-R-4352'])
m = outcomes[0]['motions'][0]
check('alpr: wording kept', m['resultText'], 'Adopted substitute')
check('alpr: counts, not names', (m['yes'], m['absent']), (11, 4))
check('alpr: unset fields dropped', 'next' in m or 'no' in m or 'abstain' in m, False)
check('minutes link carried', extra['minutesUrl'], 'https://x/min')

status, outcomes, _ = follow_through('data-center', MEETING)
check('data center: held item', [(o['reference'], o['motions'][0]['resultClass'])
                                 for o in outcomes], [('26-O-1474', 'held')])
check('data center: next stop kept', outcomes[0]['motions'][0]['next'],
      'City Utilities Committee (11/24/2026 10:00 AM)')

status, outcomes, _ = follow_through('local-taxes', MEETING)
check('topic absent from every recorded item', (status, outcomes), ('not-in-minutes', []))
check('minutes with no votes', follow_through('alpr', dict(MEETING, items=[]))[0], 'no-results')
check('no votes record', follow_through('alpr', None), (None, [], {}))

check('land use rolls up subtags', topic_in_tags('land-use', ['rezoning']), True)
check('data centers are not land use here', topic_in_tags('land-use', ['data-center']), False)

LEGISTAR = {'id': '9', 'items': [{'reference': None, 'outline': '3.', 'district': None,
            'name': 'Rezoning of parcel 12 from R-1 to C-2',
            'motions': [motion(motion='Approve', result='passed', yes=['A', 'B'])]}]}
_, outcomes, _ = follow_through('land-use', LEGISTAR)
check('platform without wording gets the result as wording',
      outcomes[0]['motions'][0]['resultText'], 'Passed')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
