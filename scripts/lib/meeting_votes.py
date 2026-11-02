#!/usr/bin/env python3
"""The one recorded-vote record shape, shared by every platform's reader.

CivicClerk (`lib.civicclerk_votes`) and Legistar (`lib.legistar_votes`) describe
a vote differently - CivicClerk lists yes/no/abstain names per motion with a
numeric `passFail`, Legistar one named row per member ("Yea", "Yes", "Absent")
with a "Pass"/"Fail" flag - so each reader maps onto this shape and the page
renders one format:

  meeting: {id, date, body, title, items: [item]}
  item:    {outline, name, reference, district, motions: [motion]}
  motion:  {motion, movedBy, secondedBy, result, yes[], no[], abstain[], absent[]}

Optional fields are None (or omitted), never ''. `absent` is filled only where
the source says who was absent (Legistar); an empty list from CivicClerk means
"not recorded", not "everyone was there".

`result` is "passed" / "failed" / None. Legistar states it. CivicClerk's own
`passFail` is NOT trusted: across 4,100 motions it reads 1 on a 0-yes/0-no
motion and on a "Deny" carried 0-9, and -1 ("unset") on 250+ motions that
carried 9-0. For CivicClerk the result is the tally (more yes than no) when
anyone voted, else None.
"""

import re

_TAG_RE = re.compile(r'<[^>]*>')

# Normalised vote values. Anything else (Present, Recused, ...) is ignored
# rather than guessed into a column.
YES = {'yea', 'yes', 'aye', 'for'}
NO = {'nay', 'no', 'against'}
ABSTAIN = {'abstain', 'abstained', 'present'}
ABSENT = {'absent', 'excused', 'not voting'}


def clean_text(value):
    """Strip markup and zero-width characters; collapse whitespace; '' -> None.
    Item names come from clerks' rich-text editors and arrive with stray tags
    (Carroll: an Outlook <b data-olk-copy-source=...> wrapper)."""
    text = _TAG_RE.sub('', value or '').replace('​', '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip() or None


def names(values):
    return [n for n in (clean_text(v) for v in values or []) if n]


def result_from_tally(yes, no):
    if not (yes or no):
        return None
    return 'passed' if len(yes) > len(no) else 'failed'


def result_from_flag(flag_name):
    f = (flag_name or '').strip().lower()
    if f == 'pass':
        return 'passed'
    if f == 'fail':
        return 'failed'
    return None


def bucket(value_name):
    """Legistar-style vote value -> 'yes' | 'no' | 'abstain' | 'absent' | None."""
    v = (value_name or '').strip().lower()
    for key, words in (('yes', YES), ('no', NO), ('abstain', ABSTAIN),
                       ('absent', ABSENT)):
        if v in words:
            return key
    return None
