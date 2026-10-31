#!/usr/bin/env python3
"""Precision / recall guard for the `local-taxes` (local taxes & referenda) rule.

Pins phrases that MUST fire (Georgia's local-option sales taxes, millage, bonds,
referenda) and look-alikes that MUST NOT - above all the ordinary English words
'lost', 'most' and 'host', which are also the acronyms of real taxes (LOST, MOST,
HOST) and are therefore deliberately NOT keywords. Add a case whenever a keyword
is added or removed.

Run: python scripts/test_meeting_topics_local_taxes.py   (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import classify, topic_flags, TOPIC_RULES, TOPIC_WORD_RULES

failures = []


def fires(text):
    return 'local-taxes' in classify(text)


MUST_FIRE = [
    'Resolution calling a SPLOST referendum for November 2026',
    'ESPLOST VI project list',
    'TSPLOST 2 intergovernmental agreement',
    'T-SPLOST transportation projects',
    'Special Purpose Local Option Sales Tax distribution',
    'Local Option Sales Tax (LOST) certificate',
    'Homestead Option Sales Tax rollover',
    'FLOST referendum',
    'Resolution to impose a LHOST',
    'OLOST renewal for five years',
    'Call for a referendum election on package store sales of distilled spirits',
    'Education Local Option Sales Tax',
    'Adopt the 2026 millage rate',
    'Millage rate public hearing',
    '5-year history of levy and rollback rate',
    'Notice of property tax increase',
    'ad valorem tax levy',
    'Approve the 2026 tax digest',
    'Increase the homestead exemption',
    'Hotel/Motel Tax proceeds',
    'Create a tax allocation district',
    'Tax abatement for the development authority',
    'Bond-for-title lease with the development authority',
    'Issue general obligation bonds for the jail',
    'Call a special election and bond referendum',
    'SPLOST\nreferendum',
    'Special Purpose\n   Local Option Sales Tax',  # PDF line wrap mid-phrase
]

MUST_NOT_FIRE = [
    'Lost and found items turned in to the clerk',
    'Most members voted in favor',
    'Hosted by the Chamber of Commerce',
    'Host a public meeting at the library',
    'Pay lost time to the employee',
    'Aflost vessel',
    'Approve the sales of surplus vehicles',
    'Renew tag office license plate fee schedule',
    'Approve the budget and fiscal year calendar',
]

for text in MUST_FIRE:
    ok = fires(text)
    print('  %s MUST_FIRE %r' % ('ok  ' if ok else 'FAIL', text))
    if not ok:
        failures.append(text)

for text in MUST_NOT_FIRE:
    ok = not fires(text)
    print('  %s MUST_NOT_FIRE %r' % ('ok  ' if ok else 'FAIL', text))
    if not ok:
        failures.append(text)

# The ambiguous acronyms must never become keywords of their own.
for bad in ('lost', 'most', 'host', 'tax'):
    kws = set(TOPIC_RULES['local-taxes']) | set(TOPIC_WORD_RULES['local-taxes'])
    ok = bad not in kws
    print('  %s %r is not a keyword' % ('ok  ' if ok else 'FAIL', bad))
    if not ok:
        failures.append('keyword ' + bad)

# Flag wiring, and no collateral effect on the existing millage-budget tag.
if topic_flags(['local-taxes']) != ['local-taxes']:
    failures.append('flag')
    print('  FAIL flag')
if 'millage-budget' not in classify('adopt the millage rate'):
    failures.append('millage-budget regression')
    print('  FAIL millage-budget regression')

if failures:
    print('\n%d FAILED' % len(failures))
    sys.exit(1)
print('\nall local-taxes checks passed')
