#!/usr/bin/env python3
"""IQM2 minutes: RESULT blocks read onto the right item, and the reader's guards.

The fixtures are cut, unedited, from `pdftotext -raw` output of real minutes:
  * iqm2-atlanta-council-minutes.txt: Atlanta City Council 2026-11-16 (six items)
    plus one item from 2026-11-02 whose RESULT label sits at the end of a line.
  * iqm2-socialcircle-minutes.txt / -agenda.txt: Social Circle Mayor and Council
    2026-08-18, where a rezoning's numbered conditions look like agenda items, the
    agenda was amended so the minutes renumber section XI, and the clerk's
    narrative contradicts the RESULT block printed under it.

Run: python scripts/test_iqm2_votes.py      (no network, no pdftotext)
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib.iqm2_votes import (_text_disagrees, agenda_outline, fetch_votes, is_draft,
                            normalise_result, parse_minutes, result_class)

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


def fixture(name):
    with open(os.path.join(HERE, 'fixtures', name), encoding='utf-8') as f:
        return f.read()


ATL = fixture('iqm2-atlanta-council-minutes.txt')
SC_MIN = fixture('iqm2-socialcircle-minutes.txt')
SC_AGENDA = fixture('iqm2-socialcircle-agenda.txt')

# ---- Atlanta: keyed by file number ------------------------------------------
items, problems = parse_minutes(ATL)
by_ref = {i['reference']: i for i in items}
check('every file item read', sorted(by_ref),
      ['26-O-1474', '26-O-1641', '26-O-1650', '26-R-3853', '26-R-4329', '26-R-4352'])
check('no problems', problems, [])

alpr = by_ref['26-R-4352']['motions'][0]
check('ALPR cameras: result wording', alpr['resultText'], 'Adopted substitute')
check('ALPR cameras: class', alpr['resultClass'], 'adopted-substitute')
check('ALPR cameras: passed', alpr['result'], 'passed')
check('ALPR cameras: tally', alpr['tally'], [11, 0])
check('ALPR cameras: wrapped AYES list', len(alpr['yes']), 11)
check('ALPR cameras: AWAY is absent', alpr['absent'],
      ['Matt Westmoreland', 'Kelsea Bond', 'Liliana Bakhtiari', 'Antonio Lewis'])
check('ALPR cameras: mover', alpr['movedBy'], 'Dustin Hillis, Councilmember, District 9')

dc = by_ref['26-O-1474']
check('data-center ordinance: caption runs past "BYRON D."',
      'REQUIRING DATA CENTERS' in (dc['name'] or ''), True)
check('data-center ordinance: held is not passed or failed', dc['motions'][0]['result'], None)
check('data-center ordinance: class held', dc['motions'][0]['resultClass'], 'held')
check('data-center ordinance: next stop',
      dc['motions'][0]['next'], 'City Utilities Committee (11/24/2026 10:00 AM)')

ref = by_ref['26-O-1641']['motions'][0]
check('tally wrapped onto the next line is kept', ref['tally'], [13, 0])
check('referred wording', ref['resultText'], 'Referred to committee')

mid_line = by_ref['26-R-4329']['motions'][0]
check('RESULT label at the end of a line is still read', mid_line['resultText'], 'Adopted')
check('... with its tally', mid_line['tally'], [10, 0])

# ---- Atlanta committee minutes (City Utilities, 2026-11-10, a draft) --------
# The caption wraps at an initial: "... BYRON" / "D. AMOS, AND MICHAEL JULIAN BOND
# REQUIRING DATA CENTERS ...", and "D. AMOS ..." looks like section heading D.
COMMITTEE = fixture('iqm2-atlanta-committee-minutes.txt')
ci, _ = parse_minutes(COMMITTEE)
dc_c = [i for i in ci if 'DATA CENTERS' in (i['name'] or '')]
check('wrapped initial is not a section heading',
      [(i['reference'], i['outline']) for i in dc_c], [('26-O-1474', None)])
check('committee result is held in committee',
      dc_c[0]['motions'][0]['resultText'] if dc_c else None, 'Held in committee')
check('committee minutes are a draft', is_draft(COMMITTEE), True)

# ---- Social Circle: keyed by outline number, verified against the agenda ----
check('outline minutes without the agenda are not read',
      parse_minutes(SC_MIN)[0], [])
agenda = agenda_outline(SC_AGENDA)
sc, sc_problems = parse_minutes(SC_MIN, agenda)
outlines = [i['outline'] for i in sc]
check('numbered conditions are not agenda items', 'VIII. 4.' in outlines and
      not any('decel lane' in (i['name'] or '') for i in sc), True)
rez = [i for i in sc if (i['name'] or '').startswith('REZ-2026-006')]
check('rezoning keeps its own result', len(rez), 1)
check('rezoning: narrative contradicts "unanimous"', rez[0]['motions'][0].get('textDisagrees'), True)
check('renumbered item matched by caption, not number',
      [i['name'][:30] for i in sc if i['outline'] == 'XI. 1.'],
      ['Authorization to Submit Grant '])
same_start = [i['name'] for i in sc if i['outline'] in ('VIII. 3.', 'VIII. 4.')]
check('two captions with the same opening words stay apart', len(set(same_start)), 2)
check('caption taken from the agenda, without page furniture',
      any('Persons with hearing' in (i['name'] or '') for i in sc), False)
millage = [i for i in sc if i['outline'] == 'VIII. 1.'][0]['motions']
check('a hearing then a vote: two motions', [m['resultText'] for m in millage],
      ['Completed', 'Adopted'])
check('4-1 vote keeps its no', millage[1]['no'], ['Council Member (2) Jackson'])
check('4-1 vote is not flagged', millage[1].get('textDisagrees'), None)
# Atlanta 2026-10-05, 26-O-1532: one item, two motions in one narrative (adopt
# on substitute 10-1, then "send post haste" by Unanimous Consent). Not a conflict.
POST_HASTE = ('Motion to Adopt on Substitute ... CARRIED by a roll call vote of 10 yeas; 1 nay. '
              'Lastly ... Motion to Send post haste ... CARRIED by Unanimous Consent of '
              'Councilmembers present 11 yeas; 0 nays.')
check('a second motion carried unanimously is not a conflict',
      _text_disagrees(POST_HASTE, {'unanimous': None, 'yes': ['a'] * 10, 'no': ['b']}), None)
check('"no one opposed" is not a conflict',
      _text_disagrees('There being no one opposed, the hearing closed.',
                      {'unanimous': True, 'yes': ['a'], 'no': []}), None)
check('draft marker read', is_draft(SC_MIN), True)
check('Atlanta council minutes are final', is_draft(ATL), False)

# ---- wording ---------------------------------------------------------------
check('normalise strips consent and tally',
      normalise_result('ADOPTED AS AMENDED BY CONSENT VOTE [10 TO 0]'), 'ADOPTED AS AMENDED')
check('normalise strips Next',
      normalise_result('RETURNED AS HELD Next: 11/24/2026 1:30 PM'), 'RETURNED AS HELD')
check('favorable is a recommendation', result_class('FAVORABLE AS AMENDED [6 TO 0]'), 'recommended')
check('adversed has its own class', result_class('ADVERSED BY CONSENT VOTE [13 TO 0]'), 'adversed')
check('unknown wording is not bucketed', result_class('SENT BACK FOR REWORK'), None)

# ---- reader: incremental, failures, never worse ----------------------------
TODAY = dt.date(2026, 11, 20)
MEETINGS = [
    {'id': '1', 'date': '2026-11-16', 'body': 'City Council', 'title': 'Regular',
     'minutesUrl': 'https://x/min1', 'agendaUrl': 'https://x/ag1'},
    {'id': '2', 'date': '2026-06-01', 'body': 'City Council', 'title': 'Regular',
     'minutesUrl': 'https://x/min2', 'agendaUrl': 'https://x/ag2'},
    {'id': '3', 'date': '2026-11-17', 'body': 'City Council', 'title': 'No minutes yet',
     'minutesUrl': None, 'agendaUrl': 'https://x/ag3'},
]
DOCS = {'https://x/min1': ATL, 'https://x/min2': ATL}


def fetch(url):
    return url.encode() if url in DOCS else None


def extract(path):
    with open(path, 'rb') as f:
        return DOCS[f.read().decode()]


recs, report = fetch_votes(MEETINGS, today=TODAY, fetch=fetch, extract=extract, log=lambda *a: None)
check('meetings without minutes are skipped', [r['id'] for r in recs], ['1', '2'])
check('record carries the minutes link', recs[0]['minutesUrl'], 'https://x/min1')
check('six items read', len(recs[0]['items']), 6)

calls = []


def counting(url):
    calls.append(url)
    return fetch(url)


again, report = fetch_votes(MEETINGS, previous=recs, today=TODAY, fetch=counting,
                            extract=extract, log=lambda *a: None)
check('old final record carried, recent one re-read', calls, ['https://x/min1'])
check('carried count', report['carried'], 1)

kept, report = fetch_votes(MEETINGS, previous=recs, today=TODAY, fetch=lambda u: None,
                           extract=extract, log=lambda *a: None)
check('failed read keeps the previous record', [r['id'] for r in kept], ['1', '2'])
check('failure reported', report['failed'], ['1'])
none, _ = fetch_votes(MEETINGS, today=TODAY, fetch=lambda u: None, extract=extract,
                      log=lambda *a: None)
check('failed read is never published as empty', none, [])

DOCS_WORSE = dict(DOCS, **{'https://x/min1': ATL[:ATL.index('26-R-4329 (')]})   # last item lost


def extract_worse(path):
    with open(path, 'rb') as f:
        return DOCS_WORSE[f.read().decode()]


worse, report = fetch_votes(MEETINGS, previous=recs, today=TODAY, fetch=fetch,
                            extract=extract_worse, log=lambda *a: None)
check('a re-read with fewer results keeps the earlier one', len(worse[0]['items']), 6)
check('... and says so', report['keptPrevious'], ['1'])

# Wording the reader does not know is reported by the run, and the record still
# carries it (with no resultClass key: unset optional fields are omitted).
ODD = ATL.replace('RESULT: ADOPTED SUBSTITUTE [11 TO 0]', 'RESULT: SENT BACK FOR REWORK [11 TO 0]')
DOCS_ODD = dict(DOCS, **{'https://x/min1': ODD})


def extract_odd(path):
    with open(path, 'rb') as f:
        return DOCS_ODD[f.read().decode()]


odd, report = fetch_votes(MEETINGS, today=TODAY, fetch=fetch, extract=extract_odd,
                          log=lambda *a: None)
check('unknown wording reported', report['unrecognized'], {'Sent back for rework': 1})
odd_motion = [i for i in odd[0]['items'] if i['reference'] == '26-R-4352'][0]['motions'][0]
check('unknown wording kept verbatim, unclassified',
      (odd_motion['resultText'], 'resultClass' in odd_motion, odd_motion['result']),
      ('Sent back for rework', False, None))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('ok')
