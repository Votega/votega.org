#!/usr/bin/env python3
"""Recorded results and named votes from IQM2 minutes (Atlanta, Social Circle).

IQM2 ("Meeting Manager") renders a body's minutes from the same agenda record
it published before the meeting. Wherever the clerk recorded an action, it
prints a machine-generated block under the agenda item:

    26-R-4352 (2) - A SUBSTITUTE RESOLUTION BY CITY UTILITIES COMMITTEE
    AUTHORIZING ... MOBILE SURVEILLANCE CAMERAS WITH FMP ...
    RESULT: ADOPTED SUBSTITUTE [11 TO 0]
    MOVER: Dustin Hillis, Councilmember, District 9
    SECONDER: Alex Wan, Councilmember, District 6
    AYES: Bond, Collins, Winston, Amos, Dozier, Wan, Worthy,
    Norwood, Hillis, Boone, Martin
    AWAY: Matt Westmoreland, Kelsea Bond, Liliana Bakhtiari,
    Antonio Lewis

This module reads those blocks into the shared record shape (lib.meeting_votes),
so the place page shows them like CivicClerk and Legistar votes, and the topic
feeds can follow a tagged agenda item to its result
(the follow-through convention in CLAUDE.md).

THE TEXT MUST BE READ WITH `pdftotext -raw`, NOT `-layout`. Atlanta prints the
file number in a left column. In layout (and default) mode, poppler stacks the
file numbers of consecutive items ("26-O-1124 (3) -", "26-O-1340 (4) -",
"26-O-1474 (5) -  AUTHORIZING ...") ahead of their captions, so a reader that
takes the nearest heading above a RESULT line gives one ordinance's result to
another. Raw mode emits the content stream, which keeps each number on the line
with its caption. Measured on the 2026-11-16 council minutes: same file, three
extraction modes, only raw pairs them correctly. extract_minutes_text() is the
one way this module reads a PDF for that reason.

WHAT IS AND IS NOT CLAIMED
  * Only an item with a RESULT block is published. Chatham's IQM2 minutes are a
    narrative transcript with no RESULT lines, so Chatham gets no file, the same
    "the portal records none" outcome as a CivicClerk place without votes.
  * `resultText` is the city's own wording ("Adopted substitute", "Returned as
    held"). `result` is "passed" only for wording that says the measure itself
    was adopted / approved / confirmed, and "failed" only for failed / denied.
    FAVORABLE (a committee recommends), ADVERSED, HELD, REFERRED and FILED stay
    None: those are steps, and calling them passed or failed would be a guess.
    `resultClass` groups the wording; wording it does not know is None and is
    listed by the caller, never bucketed (the lesson of pass_fail() in the
    federal votes generator, where "Agreed to" published as FAILED).
  * Draft minutes are flagged (`minutesDraft`), and re-read until final.
"""

import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile

from lib.meeting_votes import clean_text

RECHECK_DAYS = 60       # a final record older than this is carried forward
DRAFT_RECHECK_DAYS = 365  # a draft is re-read until final, within this age

_PDFTOTEXT_TIMEOUT = 180

# A legislation file number at the start of a line: 26-R-4352, 26-O-1474, 26-C-5097.
_FILE_RE = re.compile(r'^\s*(\d{2}-[A-Z]{1,2}-\d{3,5})\b\s*(?:\(\d+\))?\s*-?\s*(.*)$')
# Outline headings. A section is a roman numeral or a single capital letter
# ("VIII. PUBLIC HEARINGS", "C. ADOPTION OF AGENDA"); an item is a number.
_SECTION_RE = re.compile(r'^\s*([IVXL]{1,5}|[A-Z])\.\s+([A-Z(].*)$')
_ITEM_RE = re.compile(r'^\s*(\d{1,2}|[a-z])\.\s+(\S.*)$')   # "2." or a sub-item "a."
_LABEL_RE = re.compile(
    r'^\s*(RESULT|MOVER|SECONDER|AYES|NAYS|AWAY|ABSENT|EXCUSED|ABSTAIN|ABSTAINED|'
    r'RECUSED|TO)\s*:\s*(.*)$')
# Page furniture: "Page | 66", a bare date, and the running header Social Circle
# prints on every page ("Agenda Mayor and Council August 18, 2026").
_FOOTER_RE = re.compile(r'^\s*(Page\s*\|?\s*\d+|\d{1,2}/\d{1,2}/\d{2,4}'
                        r'|(Agenda|Minutes)(\s+Draft)?\s.*\b(?:19|20)\d\d\b.*)\s*$', re.I)
_DRAFT_RE = re.compile(r'\*{2,}\s*DRAFT\s*\*{2,}|\bminutes\s+draft\b', re.I)
_TALLY_RE = re.compile(r'\[\s*(\d+)\s+TO\s+(\d+)\s*\]', re.I)
_BRACKET_RE = re.compile(r'\[[^\]]*\]')
_NEXT_RE = re.compile(r'\bNext:\s*(.*)$', re.I)

# A document is keyed by file numbers when it carries at least this many file
# number headings (an Atlanta special called meeting has three); numbered outline lines are then ignored (in Atlanta they are
# narrative lists inside an item, and treating them as headings would cut an
# item in two and hand its RESULT to the fragment).
FILE_MODE_MIN = 1

MAX_CAPTION_LINES = 20
# Captions are capped when stored: Atlanta's run to 1,000+ characters and were
# 1.7 MB of a 3.6 MB year. The topic terms sit early (sponsors, then the subject).
MAX_CAPTION_CHARS = 400

# A caption line ending in an initial or a common abbreviation ("BYRON D.",
# "PRYOR ROAD, SW.") has not ended its sentence. Used for agenda captions, which
# end at a full stop; Atlanta's all-caps captions are bounded by case instead
# (_caption_continues), which is what keeps 26-O-1474 whole past "BYRON D.".
_NOT_AN_END_RE = re.compile(
    r'(\b[A-Z]\.|\b(NO|ST|DR|MR|MRS|MS|JR|SR|NW|NE|SW|SE|INC|CO|VS)\.)$', re.I)

VOTE_LABELS = {'AYES': 'yes', 'NAYS': 'no', 'ABSTAIN': 'abstain', 'ABSTAINED': 'abstain',
               'RECUSED': 'abstain', 'AWAY': 'absent', 'ABSENT': 'absent',
               'EXCUSED': 'absent'}

# Wording -> class, checked in order on the normalised RESULT (no brackets, no
# "BY CONSENT VOTE", no "Next:"). Longest phrases first.
RESULT_CLASSES = [
    ('ADOPTED SUBSTITUTE AS AMENDED', 'adopted-substitute'),
    ('ADOPTED ON SUBSTITUTE', 'adopted-substitute'),
    ('ADOPTED SUBSTITUTE', 'adopted-substitute'),
    ('ADOPTED AS AMENDED', 'adopted-amended'),
    ('ADOPTED', 'adopted'),
    ('APPROVED AS AMENDED', 'adopted-amended'),
    ('APPROVED', 'adopted'),
    ('CONFIRMED', 'adopted'),
    ('ACCEPTED AND FILED', 'filed'),
    ('ACCEPTED & FILED', 'filed'),
    ('ACCEPTED/FILED', 'filed'),
    ('ACCEPTED', 'filed'),
    ('AUTOMATICALLY TERMINATED', 'filed'),
    ('AUTOMATIC TERMINATION', 'filed'),
    ('FORWARDED WITH NO RECOMMENDATION', 'forwarded'),
    ('FORWARDED W/NO RECOMMENDATION', 'forwarded'),
    ('FORWARDED', 'forwarded'),
    ('SUBSTITUTED AS AMENDED', 'amended'),
    ('SUBSTITUTE AS AMENDED', 'amended'),
    ('FILED BY COMMITTEE', 'filed'),
    ('FILED', 'filed'),
    ('FAVORABLE ON SUBSTITUTE', 'recommended'),
    ('FAVORABLE AS AMENDED', 'recommended'),
    ('FAVORABLE', 'recommended'),
    ('ADVERSED', 'adversed'),
    ('RETURNED AS HELD', 'held'),
    ('HELD IN COMMITTEE', 'held'),
    ('REFERRED TO COMMITTEE', 'referred'),
    ('REFERRED WITHOUT OBJECTION', 'referred'),
    ('REFERRED', 'referred'),
    ('BRING FORTH SUBSTITUTE', 'amended'),
    ('AMENDED', 'amended'),
    ('SCHEDULED FOR', 'scheduled'),
    ('COMPLETED', 'completed'),
    ('NO ACTION REQUIRED', 'no-action'),
    ('TABLED', 'tabled'),
    ('WITHDRAWN', 'withdrawn'),
    ('DENIED', 'failed'),
    ('FAILED', 'failed'),
    ('DEFEATED', 'failed'),
]
PASSED_CLASSES = {'adopted', 'adopted-amended', 'adopted-substitute'}
FAILED_CLASSES = {'failed'}


# ---------------------------------------------------------------- text helpers

def extract_minutes_text(pdf_path):
    """`pdftotext -raw` text of a minutes PDF, or None. See the module docstring:
    layout mode misattributes Atlanta's file numbers, so do not swap this for
    lib.pdf_text.extract_text."""
    if not shutil.which('pdftotext'):
        print('    pdftotext not installed; cannot read IQM2 minutes')
        return None
    try:
        proc = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-raw', pdf_path, '-'],
                              capture_output=True, timeout=_PDFTOTEXT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print('    pdftotext failed: %s' % exc)
        return None
    if proc.returncode != 0:
        print('    pdftotext exit %s' % proc.returncode)
        return None
    return proc.stdout.decode('utf-8', errors='replace')


def is_draft(text):
    return bool(_DRAFT_RE.search(text or ''))


def normalise_result(value):
    """'ADOPTED AS AMENDED BY CONSENT VOTE [10 TO 0]' -> 'ADOPTED AS AMENDED'."""
    v = _NEXT_RE.sub('', value or '')
    v = _BRACKET_RE.sub('', v)
    v = re.sub(r'\bBY\s+(A\s+)?(ROLL\s+CALL\s+|CONSENT\s+)?VOTE\b.*$', '', v, flags=re.I)
    return re.sub(r'\s+', ' ', v).strip().upper()


def result_class(value):
    norm = normalise_result(value)
    for phrase, cls in RESULT_CLASSES:
        if norm == phrase or norm.startswith(phrase + ' ') or norm.startswith(phrase + '/') \
                or norm.startswith(phrase + ' ('):
            return cls
    return None


def _sentence_case(norm):
    return norm[:1] + norm[1:].lower() if norm else None


def _names(value):
    out = []
    for part in (value or '').split(','):
        n = clean_text(part)
        if n:
            out.append(n)
    return out


def _is_heading(line, file_mode):
    if _FILE_RE.match(line):
        return True
    if _section_match(line):
        return True
    return (not file_mode) and bool(_ITEM_RE.match(line))


# ---------------------------------------------------------------- the parser

def _new_item(outline, reference, first):
    return {'outline': outline, 'reference': reference, 'caption': [first] if first else [],
            'captionOpen': True, 'motions': []}


def _add_raw(motion, key, value):
    """Accumulate a vote list's raw text. A list wraps either after a comma
    ("Worthy," / "Norwood, ...") or inside a name ("Council Member (3)" /
    "Conavay, ..."), so lines are joined with a space and split on commas once."""
    raw = motion.setdefault('_raw', {})
    raw[key] = ((raw.get(key) or '') + ' ' + (value or '')).strip()


def _finish_motion(m):
    for key, value in (m.pop('_raw', None) or {}).items():
        m[key].extend(_names(value))
    result = m.pop('_result', '') or ''
    norm = normalise_result(result)
    cls = result_class(result)
    tally = _TALLY_RE.search(result)
    nxt = _NEXT_RE.search(result)
    nxt_text = clean_text(nxt.group(1)) if nxt else None
    if m.get('_to'):
        nxt_text = ' '.join(x for x in (clean_text(m['_to']), nxt_text and '(%s)' % nxt_text) if x)
    m.pop('_to', None)
    motion = {
        'motion': None,
        'movedBy': clean_text(m.get('movedBy')),
        'secondedBy': clean_text(m.get('secondedBy')),
        'result': ('passed' if cls in PASSED_CLASSES else
                   'failed' if cls in FAILED_CLASSES else None),
        'resultText': _sentence_case(norm),
        'resultClass': cls,
        'unanimous': True if re.search(r'\[\s*UNANIMOUS\s*\]', result, re.I) else None,
        'tally': [int(tally.group(1)), int(tally.group(2))] if tally else None,
        'next': nxt_text or None,
        'yes': m['yes'], 'no': m['no'], 'abstain': m['abstain'], 'absent': m['absent'],
    }
    # The IQM2-only fields are omitted when unset (lib.meeting_votes: optional
    # fields are None or omitted); a year of Atlanta is ~4,000 motions.
    for key in ('resultClass', 'unanimous', 'tally', 'next'):
        if motion[key] is None:
            del motion[key]
    return motion


def _caps(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.85


def _section_match(line):
    """A section heading, title in capitals ("VIII. PUBLIC HEARINGS"). Requiring
    capitals keeps a narrative line such as "A. Smith asked ..." from closing the
    item above it and taking its RESULT."""
    m = _SECTION_RE.match(line)
    return m if m and _caps(m.group(2)) else None


def _caption_key(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())[:80]


def agenda_outline(text):
    """{(section, number, index): (caption key, caption)} for the numbered items of
    an agenda read with pdftotext -raw. Used to verify outline headings in minutes,
    where the clerk's narrative also uses numbered lists (a rezoning's conditions
    "1. ... 4. There shall be a decel lane ...") that look exactly like agenda
    items, and to name a verified item by the agenda's own caption, which has no
    narrative running into it."""
    out, section, cur = {}, None, None
    for line in (text or '').splitlines():
        if not line.strip():
            continue
        sm = _section_match(line)
        if sm:
            section, cur = sm.group(1) + '.', None
            continue
        im = _ITEM_RE.match(line)
        if im and section:
            # keyed with a running index: sub-items "a." repeat under each number
            cur = (section, im.group(1), len(out))
            out[cur] = [_caption_key(im.group(2)), [im.group(2).strip()]]
            continue
        if _FOOTER_RE.match(line):
            cur = None          # a page break ends the caption; what follows is boilerplate
            continue
        last = out[cur][1][-1].rstrip() if cur is not None else ''
        if cur is not None and len(out[cur][1]) < 6                 and not (last.endswith('.') and not _NOT_AN_END_RE.search(last)):
            out[cur][1].append(line.strip())
    return {k: (key, clean_text(' '.join(lines))) for k, (key, lines) in out.items()}


def _verified(agenda, section, number, caption):
    """The agenda's caption if "<number>. <caption>" under `section` is one of the
    agenda's own items, else None.

    Matched on the caption, not the number: when a body amends its agenda the
    minutes renumber (Social Circle 2026-08-18 moved XI.1 to VIII, so the agenda's
    XI.2 is the minutes' XI.1). `number` is kept in the signature for the reader."""
    mine = _caption_key(caption)
    if not mine:
        return None
    hits = []
    for (sec, n, _i), (key, full) in (agenda or {}).items():
        if sec != section or not key:
            continue
        short = min(len(key), len(mine))
        if (key == mine) if short < 12 else (key.startswith(mine) or mine.startswith(key)):
            hits.append((n == number, full))
    if len(hits) == 1:
        return hits[0][1]
    same_number = [full for ok, full in hits if ok]
    # Two agenda items with the same opening words: only the number can tell them
    # apart. Neither matching it means we cannot say which one this is.
    return same_number[0] if len(same_number) == 1 else None


# The clerk's own narrative contradicting the RESULT block printed under it.
# Social Circle 2026-08-18, REZ-2026-006: "Voting against were Council Member
# Jackson and Council Member Conavay. Mayor Keener voted in favor to break the
# tie." over "RESULT: ADOPTED [UNANIMOUS]" with all five listed as ayes.
_AGAINST_RE = re.compile(r'\bvot(?:ed|ing|es)\s+(?:against|no|nay)\b|'
                         r'\bbreak(?:s|ing)?\s+the\s+tie\b|\bdissenting\s+vote\b', re.I)


def _text_disagrees(narrative, motion):
    """True when the narrative above a RESULT block says someone voted against,
    or a tie was broken, while the block records no nays; else None.

    One direction only, on purpose. A narrative often covers several motions on
    one item (Atlanta: adopt on substitute 10-1, then "send post haste" by
    Unanimous Consent), so "unanimous" in the text over a tally with a nay is
    normal and was a false flag on both Atlanta cases it raised. "Opposed" is left
    out too: "there being no one opposed" is common wording."""
    if not narrative:
        return None
    no_dissent = motion.get('unanimous') or (motion['yes'] and not motion['no'])
    if no_dissent and _AGAINST_RE.search(narrative):
        return True
    return None


def parse_minutes(text, agenda=None):
    """Parse IQM2 minutes text (pdftotext -raw) into (items, problems).

    items:    [{outline, name, reference, district, motions: [motion]}] for every
              agenda item that carries at least one RESULT block, in document order.
    problems: strings describing anything read but not attributed, for the run
              report. Never raises on odd input.

    Minutes keyed by file number (Atlanta) need nothing else. Minutes keyed by
    outline number (Social Circle) need `agenda`, from agenda_outline() on the
    same meeting's agenda: a numbered line is an agenda item only if the agenda
    has that number in that section with the same caption. Without it nothing is
    returned, because an unverified heading can hand one item's vote to another."""
    # A RESULT label can land mid-line in raw text (Atlanta 2026-11-02: "BY A ROLL
    # CALL VOTE OF 10 YEAS; 0 NAYS RESULT:" with the value on the next line). Put
    # it back at the start of its own line so it is read, not silently skipped.
    lines = []
    for ln in (text or '').splitlines():
        head, sep, tail = ln.partition('RESULT:')
        if sep and head.strip():
            lines.extend([head, sep + tail])
        else:
            lines.append(ln)
    file_mode = sum(1 for ln in lines if _FILE_RE.match(ln)) >= FILE_MODE_MIN
    if not file_mode and not agenda:
        n = sum(1 for ln in lines if ln.strip().startswith('RESULT:'))
        return [], (['%d RESULT lines not read: outline-numbered minutes need the '
                     'agenda to verify item headings' % n] if n else [])
    items, problems = [], []
    section = None          # current section label, e.g. "VIII."
    parent = None           # last item number in the section, for sub-items "a."
    item = None             # item being read
    motion = None           # motion block being read
    field = None            # label whose value may continue on the next line

    def close_motion():
        nonlocal motion, field
        if motion is not None and item is not None:
            narrative = motion.pop('_narr', '')
            done = _finish_motion(motion)
            if _text_disagrees(narrative, done):
                done['textDisagrees'] = True
            item['motions'].append(done)
        motion, field = None, None

    def close_item():
        nonlocal item
        close_motion()
        if item is not None and item['motions'] and not item.get('_orphan'):
            name = clean_text(' '.join(item['caption']))
            if name and len(name) > MAX_CAPTION_CHARS:
                name = name[:MAX_CAPTION_CHARS].rsplit(' ', 1)[0] + '…'
            items.append({'outline': item['outline'], 'name': name,
                          'reference': item['reference'], 'district': None,
                          'motions': item['motions']})
        item = None

    def start_motion(value):
        nonlocal motion, field
        motion = {'_result': value, '_narr': ' '.join(item.pop('_narr', [])),
                  'yes': [], 'no': [], 'abstain': [], 'absent': []}
        field = 'RESULT'

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        label = _LABEL_RE.match(line)

        # -- inside a RESULT block: labels and their continuation lines
        if motion is not None:
            if label:
                key, value = label.group(1), label.group(2)
                if key == 'RESULT':          # a second motion on the same item
                    close_motion()
                    start_motion(value)
                elif key == 'MOVER':
                    motion['movedBy'], field = value, 'MOVER'
                elif key == 'SECONDER':
                    motion['secondedBy'], field = value, 'SECONDER'
                elif key == 'TO':
                    motion['_to'], field = value, 'TO'
                else:
                    _add_raw(motion, VOTE_LABELS[key], value)
                    field = key
                continue
            if _continues(field, motion, line, file_mode):
                if field == 'RESULT':
                    motion['_result'] = motion['_result'] + ' ' + line.strip()
                elif field in VOTE_LABELS:
                    _add_raw(motion, VOTE_LABELS[field], line)
                elif field == 'TO':
                    motion['_to'] = (motion.get('_to') or '') + ' ' + line.strip()
                continue
            close_motion()      # the block ended; fall through and read this line

        if label and label.group(1) == 'RESULT':
            if item is None:
                problems.append('RESULT with no agenda item above it: %s'
                                % label.group(2).strip()[:80])
                # read the block anyway so its lines are not mistaken for captions
                item = _new_item(None, None, None)
                item['_orphan'] = True
            item['captionOpen'] = False
            start_motion(label.group(2))
            continue

        fm = _FILE_RE.match(line)
        sm = None if fm else _section_match(line)
        # A caption wrapped at an initial looks like a section heading: "... BYRON"
        # then "D. AMOS, AND MICHAEL JULIAN BOND REQUIRING DATA CENTERS ..." split
        # Atlanta's data-center ordinance in its committee minutes. While a caption
        # is open mid-sentence, that line is more caption.
        if sm and item is not None and item['captionOpen'] and item['caption'] and \
                not re.search(r'[.:;)]$', item['caption'][-1].rstrip()):
            sm = None
        im = None if (fm or sm or file_mode) else _ITEM_RE.match(line)
        agenda_caption = _verified(agenda, section, im.group(1), im.group(2)) if im else None
        if im and not agenda_caption:
            im = None           # a numbered line in the narrative, not an agenda item
        if fm:
            close_item()
            item = _new_item(None, fm.group(1), fm.group(2).strip())
            continue
        if sm:
            close_item()
            section, parent = sm.group(1) + '.', None
            # A section can carry its own RESULT ("C. ADOPTION OF AGENDA").
            item = _new_item(section, None, sm.group(2).strip())
            item['sectionRow'] = True
            continue
        if im:
            close_item()
            num = im.group(1)
            if num.isdigit():
                parent = num
                outline = '%s %s.' % (section, num)
            else:
                outline = '%s %s%s.' % (section, (parent + '.') if parent else '', num)
            item = _new_item(outline, None, agenda_caption)
            item['captionOpen'] = False   # the agenda's caption is the whole caption
            continue

        if item is not None and item.get('_orphan'):
            item = None
            continue
        if item is None:
            continue
        # Caption continuation, until the caption ends or hits a footer. After it
        # comes the clerk's narrative, kept only to check it against the RESULT.
        if item['captionOpen']:
            if _FOOTER_RE.match(line) or line.lstrip().startswith('►'):
                item['captionOpen'] = False
                continue
            if _caption_continues(item['caption'], line.strip(),
                                  file_mode or item.get('sectionRow')):
                item['caption'].append(line.strip())
                continue
            item['captionOpen'] = False
        item.setdefault('_narr', []).append(line.strip())

    close_item()
    return items, problems


def _caption_continues(caption, line, file_mode):
    """Is `line` more of the caption? Atlanta's captions (file mode) are set in
    capitals and the discussion after them is not, so a line in capitals
    continues, up to "AND FOR OTHER PURPOSES.". An outline caption (Social Circle)
    runs to the end of its sentence."""
    if not caption:
        return True
    if len(caption) >= MAX_CAPTION_LINES:
        return False
    prev = caption[-1].rstrip()
    if file_mode:
        if prev.upper().endswith('PURPOSES.'):
            return False
        letters = [c for c in line if c.isalpha()]
        return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= 0.85
    return not (prev.endswith('.') and not _NOT_AN_END_RE.search(prev))


def _continues(field, motion, line, file_mode):
    """Does `line` continue the value of `field` (a wrapped RESULT or name list)?"""
    if _is_heading(line, file_mode) or _FOOTER_RE.match(line):
        return False
    s = line.strip()
    if field == 'RESULT':
        # Raw text wraps the RESULT line wherever the PDF did: "...BY CONSENT VOTE"
        # then "[13 TO 0] Next: 11/24/2026 10:00 AM", or "...Next:" then the date.
        cur = (motion.get('_result') or '').strip()
        if not cur:
            return True         # "RESULT:" at the end of a line, value on the next
        if cur.count('[') > cur.count(']'):
            return True
        if s.startswith('[') or s.lower().startswith('next:'):
            return True
        if re.search(r'\bNext:$', cur, re.I) and re.match(r'\d{1,2}/\d{1,2}/\d{4}\b', s):
            return True
        if re.search(r'\bNext:\s*\d{1,2}/\d{1,2}/\d{4}$', cur, re.I) and \
                re.match(r'\d{1,2}:\d{2}\s*[AP]M\b', s, re.I):
            return True
        if re.search(r'\b(BY|AS|ON)$', cur):
            return True
        # A word broken at the margin: "FORWARDED WITH NO RECOMMENDATI" / "ON [6 TO 0]".
        return '[' not in cur and bool(re.match(
            r'[A-Z/&]{1,15}(\s+[A-Z/&]{1,15}){0,3}\s*(\[[^\]]*\])?\s*(Next:.*)?$', s))
    if field in VOTE_LABELS:
        raw = (motion.get('_raw') or {}).get(VOTE_LABELS[field])
        if not raw:
            return False
        if raw.rstrip().endswith(','):
            return not _LABEL_RE.match(line)
        # a wrapped name list: a short comma list, or a name or two, with no
        # sentence in it
        if s.endswith('.') or len(s) > 140 or re.search(r'\b(the|and|was|were|of)\b', s):
            return False
        return ',' in s or len(s.split()) <= 3
    if field == 'TO':
        return False
    return False


# ---------------------------------------------------------------- the reader

def _age(date, today):
    try:
        return (today - dt.date.fromisoformat(date[:10])).days
    except (TypeError, ValueError):
        return 0


def is_file_mode(text):
    """True for minutes keyed by legislation file number (Atlanta)."""
    return sum(1 for ln in (text or '').splitlines() if _FILE_RE.match(ln)) >= FILE_MODE_MIN


def _read_pdf(url, fetch, extract):
    pdf = fetch(url) if (fetch and url) else None
    if not pdf:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'doc.pdf')
        with open(path, 'wb') as f:
            f.write(pdf)
        return extract(path)


def read_meeting(meeting, fetch, extract=extract_minutes_text):
    """(items, problems, draft) for one meeting, or None if its minutes (or, for
    outline-numbered minutes, its agenda) could not be read."""
    text = _read_pdf(meeting.get('minutesUrl'), fetch, extract)
    if not text:
        return None
    agenda = None
    if not is_file_mode(text):
        if not meeting.get('agendaUrl'):
            return [], ['outline-numbered minutes with no agenda to verify them'], is_draft(text)
        agenda_text = _read_pdf(meeting['agendaUrl'], fetch, extract)
        if not agenda_text:
            return None
        agenda = agenda_outline(agenda_text)
    items, problems = parse_minutes(text, agenda)
    return items, problems, is_draft(text)


def fetch_votes(meetings, previous=None, months=12, today=None, fetch=None,
                extract=extract_minutes_text, log=print):
    """Vote records for the IQM2 meetings in `meetings` (the place's committed
    local-<slug>-meetings.json list) that have minutes, newest `months` months.

    Returns (records, report). A record is the shared meeting shape plus
    `minutesUrl` and `minutesDraft`. Incremental like the CivicClerk reader: a
    final record older than RECHECK_DAYS whose minutes URL is unchanged is carried
    forward; a draft is re-read until final. A failed fetch keeps the previous
    record (or leaves the meeting out to retry); a re-read that finds FEWER results
    than the previous read of the same URL keeps the previous record, because a
    changed layout or a scanned replacement is not evidence the actions vanished.
    """
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=int(months * 30.5))).isoformat()
    prev = {m['id']: m for m in (previous or [])}
    report = {'read': 0, 'carried': 0, 'failed': [], 'keptPrevious': [],
              'unrecognized': {}, 'problems': [], 'textDisagrees': []}
    out = []
    for m in meetings or []:
        url, date = m.get('minutesUrl'), m.get('date') or ''
        if not url or date < since or date > today.isoformat():
            continue
        mid = str(m.get('id'))
        old = prev.get(mid)
        age = _age(date, today)
        if old is not None and old.get('minutesUrl') == url:
            if age > (DRAFT_RECHECK_DAYS if old.get('minutesDraft') else RECHECK_DAYS):
                out.append(old)
                report['carried'] += 1
                continue
        got = read_meeting(m, fetch, extract)
        if got is None:
            log('    %s: minutes could not be read; %s' % (
                mid, 'keeping the previous record' if old else 'will retry next run'))
            report['failed'].append(mid)
            if old is not None:
                out.append(old)
            continue
        items, problems, draft = got
        report['read'] += 1
        report['problems'].extend('%s: %s' % (mid, p) for p in problems)
        for it in items:
            for mo in it['motions']:
                if mo.get('resultClass') is None and mo.get('resultText'):
                    report['unrecognized'][mo['resultText']] =                         report['unrecognized'].get(mo['resultText'], 0) + 1
                if mo.get('textDisagrees'):
                    report['textDisagrees'].append('%s %s' % (mid, it['reference'] or it['outline']))
        rec = {'id': mid, 'date': date[:10], 'body': m.get('body'), 'title': m.get('title'),
               'minutesUrl': url, 'minutesDraft': draft, 'items': items}
        if old is not None and old.get('minutesUrl') == url and                 _motion_count(items) < _motion_count(old.get('items')):
            log('    %s: re-read found %d results where the last read found %d; keeping it'
                % (mid, _motion_count(items), _motion_count(old.get('items'))))
            report['keptPrevious'].append(mid)
            out.append(old)
            continue
        out.append(rec)
    out.sort(key=lambda r: (r['date'], r['id']), reverse=True)
    return out, report


def _motion_count(items):
    return sum(len(i.get('motions') or []) for i in items or [])
