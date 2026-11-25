"""Month-name dates ("November 03, 2026", "Nov. 3, 2026") -> ISO, for the adapters that
otherwise read numeric dates only (revize, htmltable). A month + day + 4-digit year is
required: anything less returns None, never a guess."""

import re
from datetime import datetime

_MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
     'september', 'october', 'november', 'december'], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS['sept'] = 9

_RE = re.compile(
    r'(?<![a-z])(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|'
    r'aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?'
    r'[\s_-]*(\d{1,2})(?:st|nd|rd|th)?\s*,?[\s_-]*(\d{4})(?!\d)', re.I)


def parse_month_name_date(text):
    """First 'Month D, YYYY' in `text` -> 'YYYY-MM-DD', or None."""
    t = (text or '').replace('%20', ' ').replace('+', ' ')
    for m in _RE.finditer(t):
        try:
            return datetime(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None
