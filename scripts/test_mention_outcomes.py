#!/usr/bin/env python3
"""The published follow-through fields: every key present, the three "no outcome"
cases kept apart, steps never published as passed, counts only.

Run: python scripts/test_mention_outcomes.py      (no network, no packages)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.mention_outcomes import (FOLLOW_THROUGH, MOTION_KEYS, outcome_schema,  # noqa: E402
                                  outcome_summary, publish_outcomes)

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


# A feed mention as generate_topic_mentions.py writes it: set keys only.
FEED = {
    'followThrough': 'recorded', 'minutesUrl': 'https://x/min',
    'outcomes': [
        {'reference': '26-R-4352', 'name': 'MOBILE SURVEILLANCE CAMERAS',
         'motions': [{'resultText': 'Adopted substitute', 'result': 'passed',
                      'resultClass': 'adopted-substitute', 'tally': [11, 0], 'yes': 11, 'absent': 4}]},
        {'reference': '26-R-4423', 'name': 'E911 CONTACT CENTER',
         'motions': [{'resultText': 'Referred without objection', 'resultClass': 'referred',
                      'next': 'Public Safety Committee (11/23/2026 1:00 PM)'}]},
        {'outline': 'VIII. 2.', 'name': 'REZ-2026-006',
         'motions': [{'resultText': 'Adopted', 'result': 'passed', 'yes': 5, 'textDisagrees': True}]},
    ],
}
out = publish_outcomes(FEED)
check('top-level keys', sorted(out), ['followThrough', 'minutesDraft', 'minutesUrl', 'outcomes'])
for o in out['outcomes']:
    check('item keys', sorted(o), ['motions', 'name', 'outline', 'reference'])
    for m in o['motions']:
        check('every motion key present', sorted(m), sorted(MOTION_KEYS))
held = out['outcomes'][1]['motions'][0]
check('a step is not passed', held['result'], None)
check('counts default to 0', (held['yes'], held['no'], held['abstain'], held['absent']), (0, 0, 0, 0))
check('textDisagrees is a boolean', [m['textDisagrees'] for o in out['outcomes'] for m in o['motions']],
      [False, False, True])
check('no names of who voted', any(isinstance(v, list) and v and isinstance(v[0], str)
                                    for o in out['outcomes'] for m in o['motions'] for v in m.values()), False)

check('no votes record is null, not "nothing happened"',
      publish_outcomes({}), {'followThrough': None, 'outcomes': [], 'minutesUrl': None, 'minutesDraft': None})
check('minutes read, no results', publish_outcomes({'followThrough': 'no-results', 'minutesUrl': 'u'})['followThrough'],
      'no-results')
check('enum covers every status', set(FOLLOW_THROUGH) >= {'recorded', 'not-in-minutes', 'no-results', None}, True)

check('CSV summary',
      outcome_summary(out['outcomes']),
      "26-R-4352: Adopted substitute 11-0; 26-R-4423: Referred without objection; "
      "VIII. 2.: Adopted 5-0 (minutes' text disagrees with this tally)")
check('CSV summary empty is null', outcome_summary([]), None)
check('schema describes the four fields', sorted(outcome_schema()),
      ['followThrough', 'minutesDraft', 'minutesUrl', 'outcomes'])
check('schema motion keys match the published keys',
      sorted(outcome_schema()['outcomes']['items']['properties']['motions']['items']['properties']),
      sorted(MOTION_KEYS))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
