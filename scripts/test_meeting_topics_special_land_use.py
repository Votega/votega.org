#!/usr/bin/env python3
"""Precision / recall guard for the `special-land-use` rule.

Many Georgia zoning codes call a discretionary use approval a "special exception"
rather than a special or conditional use permit, so a home business or a cell tower
approved that way was tagged with no land-use subject at all (Ben Hill's July 2026
minutes; likewise Spalding, Walton and Houston). The MUST_FIRE lines are from county
agendas and minutes. Add a case whenever a keyword is added or removed.

Run: python scripts/test_meeting_topics_special_land_use.py   (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import classify, drop_empty_headings, topic_flags

failures = []


def fires(text):
    return 'special-land-use' in classify(text)


MUST_FIRE = [
    'Public Hearing Special Exception 189 Tanner Cemetery Road',
    'This is allowed by special exception in General Farming and there is no conflict.',
    'SP26-0258 - Special Exception to live in camper while building house',
    'The applicant is requesting a Special Exception for roof mounted solar panels.',
    'New Business 1. Special Exception Applications - Commissioner Talton',
    'Moratorium on the Acceptance of Rezoning and Special Exception Applications',
    'Request for Special Exception Variance from UDC Sec. 211(c)(4) - Side Yard Setback',
    'rezoned from C-2 to C-2 with a Special\n      Exception to allow for a church',
    # Already covered before 'special exception' was added.
    'Special Land Use Permit for a truck terminal',
    'Conditional use request for a daycare',
]

MUST_NOT_FIRE = [
    'With the exception of Commissioner Smith, all voted in favor',
    'Special Called Meeting to review the audit exception report',
    'Special recognition of the exceptional service of county staff',
]

for text in MUST_FIRE:
    if not fires(text):
        failures.append('should fire: %r' % text)
for text in MUST_NOT_FIRE:
    if fires(text):
        failures.append('should NOT fire: %r' % text)

# A meeting whose only land-use business is a special exception gets the flag.
if 'land-use' not in topic_flags(classify(MUST_FIRE[0])):
    failures.append('a special exception should raise the land-use flag')

# A standing heading with nothing under it is still dropped for opted-in places.
if fires(drop_empty_headings('Special Exception: NONE\n')):
    failures.append('an empty "Special Exception: NONE" heading should not tag')

if failures:
    print('%d check(s) FAILED' % len(failures))
    for f in failures:
        print('  FAIL  %s' % f)
    sys.exit(1)
print('special-land-use rule holds (%d fire, %d stay quiet).'
      % (len(MUST_FIRE), len(MUST_NOT_FIRE)))
