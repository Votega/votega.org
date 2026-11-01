#!/usr/bin/env python3
"""Invariants of the CivicPlus RSS top-up (lib/civicplus_rss.py). No network.
Run: python scripts/test_civicplus_rss.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import civicplus_rss as R  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


def item(title, id_, pub='Wed, 28 Oct 2026 09:39:35 -0500'):
    return ('<item><title>%s</title><link>https://c.example/AgendaCenter/PreviousVersions/%s</link>'
            '<pubDate>%s</pubDate></item>' % (title, id_, pub))


def feed(*items):
    return '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>%s</channel></rss>' % ''.join(items)


RULES = [{'match': 'planning commission', 'label': 'Planning Commission'},
         {'match': 'boc', 'label': 'Board of Commissioners'}]
BASE = 'https://c.example'

print('Parsing')
check(R.title_date('10/27/26 Planning Commission Agenda').isoformat() == '2026-10-27', '2-digit year')
check(R.title_date('Wrap Up for 9/29/2026 PC').isoformat() == '2026-09-29', '4-digit year, anywhere in the title')
check(R.title_date('Special Called Meeting') is None, 'no date -> None')
check(R.title_date('13/45/26 Agenda') is None, 'an impossible date -> None')
check(R.body_for('BOC Special Called Meeting', RULES) == 'Board of Commissioners', 'body from a rule')
check(R.body_for('Library Board', RULES) is None, 'no rule -> None, never guessed')

print('Supplement')
f = feed(item('10/27/26 Planning Commission Wrap Up Agenda', 1011), item('10/27/26 Planning Commission Agenda', 1010))
prev = [{'id': '1006', 'date': '2026-09-29', 'body': 'Planning Commission', 'title': 'x',
         'agendaUrl': 'u', 'minutesUrl': 'm'}]
ms, added, skipped = R.supplement(prev, f, BASE, RULES)
check(len(ms) == 3 and len(added) == 2 and not skipped, 'two new items added to the existing record')
check(any(a['agendaUrl'] == BASE + '/AgendaCenter/ViewFile/Agenda/_10272026-1011' for a in added),
      'the agenda address is rebuilt the way the Agenda Center builds it')
check(ms[0]['date'] == '2026-10-27' and ms[-1]['id'] == '1006', 'newest first, history kept')
ms2, added2, _ = R.supplement(ms, f, BASE, RULES)
check(not added2 and len(ms2) == 3, 'a second run adds nothing (idempotent)')
held = [{'id': '1010', 'date': '2026-10-27', 'body': 'Planning Commission', 'title': 'full scrape',
         'agendaUrl': 'real', 'minutesUrl': 'min'}]
ms3, added3, _ = R.supplement(held, f, BASE, RULES)
check([m for m in ms3 if m['id'] == '1010'][0]['minutesUrl'] == 'min',
      'a record the full scrape already holds is never overwritten')

print('Skips are reported, not guessed')
_, a, s = R.supplement([], feed(item('Special Called Meeting', 2000)), BASE, RULES)
check(not a and s and 'no meeting date' in s[0][1], 'no date in the title -> skipped with a reason')
_, a, s = R.supplement([], feed(item('10/27/26 Library Board Agenda', 2001)), BASE, RULES)
check(not a and s and 'rss_bodies' in s[0][1], 'no body rule -> skipped with a reason')
check(R.supplement([], feed(), BASE, RULES)[1:] == ([], []), 'an empty feed adds nothing')
try:
    R.parse_feed('<html>Just a moment...')
    check(False, 'a challenge page raises')
except ValueError:
    check(True, 'a challenge page raises rather than reading as empty')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll RSS top-up invariants hold.')
