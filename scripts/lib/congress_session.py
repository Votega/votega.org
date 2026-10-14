#!/usr/bin/env python3
"""Which Congress is sitting — derived from the date, not pinned in source.

Four generators each carried their own ``CURRENT_CONGRESS = 119`` literal
(current members, federal votes, presidential laws, VP tie votes), and nothing
in RECURRING-TASKS.md tracked them, so the 120th would have convened with the
site still fetching the 119th from four separate places. CLAUDE.md's
cycle-agnostic rule exists for exactly this: derive the number, don't comment
"bump this next time".

A Congress is seated for two years beginning 3 January of each odd year
(20th Amendment, §2), numbered from the 1st in 1789, so::

    congress = (congressional_year - 1787) // 2

where ``congressional_year`` is the calendar year, except on 1–2 January, when
the previous Congress still holds the seats and the previous year applies.

The ``CONGRESS`` environment variable overrides the derivation. That is for
backfills and for the days around a transition when a chamber has not yet
organised — not a place to park the current number.
"""

import os
from datetime import date

#: Year before the 1st Congress convened (March 1789), as the formula's origin:
#: (1789 - 1787) // 2 == 1.
_EPOCH_YEAR = 1787

#: A new Congress convenes on 3 January of an odd-numbered year.
_CONVENE_MONTH, _CONVENE_DAY = 1, 3


def congress_for_date(when=None):
    """Congress number seated on ``when`` (a date; today in UTC terms if None)."""
    when = when or date.today()
    year = when.year
    # 1-2 January belongs to the outgoing Congress: the new one is not yet sworn.
    if (when.month, when.day) < (_CONVENE_MONTH, _CONVENE_DAY):
        year -= 1
    return (year - _EPOCH_YEAR) // 2


def current_congress():
    """Congress to generate data for: $CONGRESS if set, else derived from today.

    Raises ValueError on a non-numeric or implausible override rather than
    silently fetching an empty Congress — a typo'd env var that produced a
    clean, empty run would look identical to a quiet week.
    """
    raw = os.environ.get('CONGRESS')
    if raw is None or raw.strip() == '':
        return congress_for_date()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"CONGRESS must be an integer, got {raw!r}")
    if not 1 <= value <= congress_for_date() + 1:
        raise ValueError(
            f"CONGRESS={value} is outside 1..{congress_for_date() + 1}; "
            "refusing to fetch a Congress that has not convened")
    return value


def congress_years(congress):
    """(first_year, second_year) the given Congress sits across."""
    first = _EPOCH_YEAR + congress * 2
    return first, first + 1


def congress_ordinal(congress):
    """'119th', '120th', '121st' — for titles and congress.gov URL slugs."""
    if 11 <= congress % 100 <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(congress % 10, 'th')
    return f"{congress}{suffix}"
