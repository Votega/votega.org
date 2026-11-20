#!/usr/bin/env python3
"""drop_misfiled: a document the source filed under the wrong meeting is removed by
exact URL only, a rule that no longer matches is inert, and a past meeting left with
no document is dropped (the adapters' rule for a bare row).

Run: python scripts/test_place_meetings_misfiled.py      (no network, no packages)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_place_meetings import drop_misfiled  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


AG, MIN = 'https://x/FileOpen.aspx?Type=14&ID=2136', 'https://x/FileOpen.aspx?Type=15&ID=2321'


def meetings():
    return [
        {'id': '2674', 'date': '2026-07-02', 'agendaUrl': AG, 'minutesUrl': MIN, 'videoUrl': None},
        {'id': '2677', 'date': '2026-08-18', 'agendaUrl': 'https://x/a', 'minutesUrl': AG, 'videoUrl': None},
        {'id': '9999', 'date': '2999-01-01', 'agendaUrl': AG, 'minutesUrl': None, 'videoUrl': None},
    ]


quiet = lambda *a: None  # noqa: E731
import builtins  # noqa: E402
_print, builtins.print = builtins.print, quiet
both = {'misfiled': [{'meeting': '2674', 'url': AG}, {'meeting': '2674', 'url': MIN}]}
out = drop_misfiled(both, meetings(), 'x')
check('emptied past meeting dropped', [m['id'] for m in out], ['2677', '9999'])
check('same URL on another meeting untouched', out[0]['minutesUrl'], AG)
check('upcoming meeting untouched', out[1]['agendaUrl'], AG)

one = drop_misfiled({'misfiled': [{'meeting': '2674', 'url': AG}]}, meetings(), 'x')
check('meeting with a document left is kept', [(m['id'], m['agendaUrl'], m['minutesUrl']) for m in one][0],
      ('2674', None, MIN))

future = drop_misfiled({'misfiled': [{'meeting': '9999', 'url': AG}]}, meetings(), 'x')
check('an upcoming meeting is kept with no document', '9999' in [m['id'] for m in future], True)

fixed = drop_misfiled({'misfiled': [{'meeting': '2674', 'url': 'https://x/old'}]}, meetings(), 'x')
check('rule that no longer matches is inert', fixed, meetings())
check('no rules, no change', drop_misfiled({}, meetings(), 'x'), meetings())
builtins.print = _print

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
