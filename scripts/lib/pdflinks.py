#!/usr/bin/env python3
"""Adapter for small-county sites that post agendas and minutes as loose PDF links.

Some Georgia counties (Appling, Atkinson, Bacon) have no meeting portal and no
shared CMS convention: the "Agendas & Minutes" page is a list of links to PDFs the
clerk uploaded by hand. `lib.revize` harvests the same shape, but it only
understands one date spelling (`M-D-YYYY`), so pointed at these pages it either
finds almost nothing (Bacon: 3 of 48 files) or, worse, invents dates (Appling:
12 "meetings" dated 2022-07-01 .. 2022-07-06). This adapter exists because the
dates have to be RESOLVED, not merely matched, and because a wrong date published
as a fact is worse than a missing row.

Where a meeting's date comes from, tried in this order for each PDF link
(file name first, then the link text):

  1. A full date in any of the spellings the clerks actually use:
     `2026-07-21`, `9-15-26`, `7-21-2026`, `July-21-2026`, `September 16, 2025`,
     `July 21 26`, `APR-10-25`, `2025-January-7`, `JUNE1225`, `051226` (MMDDYY).
  2. Month and day with NO year (`Aug 17 work session agenda`, `4-2 called
     meeting`, `04-14-Agenda`). The year is then inferred, from the WordPress
     `/uploads/YYYY/MM/` path when the link has one, else (opt-in:
     `year_from_order`) from the nearest dated link above it on a newest-first
     list. The year chosen is the latest one that does not put the meeting more
     than 45 days after the reference date, which handles December meetings
     filed in January.

Everything else is SKIPPED and counted, never guessed:

  * **Ambiguous `NN-NN` / `Month NN` where NN is 24-27.** `Oct 25 minutes` is
    October 25th or October 2025; `09-26-Minutes` is Sept 26th or Sept 2026. The
    file names alone cannot say, and both readings are plausible, so neither is
    published.
  * Month + year with no day (`September 2025 minutes`), bare `Agenda-2.pdf`,
    `agenda33.pdf`, `Meeting Agenda 520.pdf`.

Only links that carry BOTH a resolvable date and an agenda/minutes keyword become
meetings; that pair is what filters out the budgets, fee schedules and ADA notices
these pages mix in. Links are grouped by date into one record, routed to
agendaUrl / minutesUrl (a file used for both, e.g. `051226-Combined.pdf`, fills
both). When two distinct meetings share a date (two public hearings in a day)
the first link of each kind wins.

⚠ Kind comes from the link TEXT first ("Agenda"/"Minutes"), then the file name.
Bacon's `012125 meeting.pdf` has no keyword in its name at all, only in its text.

Import from a generator in scripts/:
    from lib.pdflinks import fetch_pdflinks_meetings
"""

import datetime
import re
from urllib.parse import unquote, urljoin, urldefrag, urlsplit, urlunsplit, quote

from lib.http import fetch_bytes

_ANCHOR_RE = re.compile(
    r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_PDF_RE = re.compile(r'\.pdf(?:$|[?#])', re.I)
_UPLOAD_RE = re.compile(r'/uploads/(\d{4})/(\d{2})/')

_MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9, 'oct': 10,
    'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}
# Not preceded/followed by a letter, so "mar" never matches inside "marked" or
# "may" inside "mayor". Digits may follow ("JUNE1225").
_MON = (r'(?<![a-z])(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|'
        r'july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|'
        r'dec(?:ember)?)(?![a-z])')

# Two-digit years are accepted only in this window; it is what keeps a stray
# "10-12-18" (a form number) from becoming a 2018 meeting.
_YY_MIN, _YY_MAX = 20, 35
_SLACK = datetime.timedelta(days=45)


def _clean(text):
    text = (text or '').replace('&nbsp;', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text)).strip()


def _unescape(url):
    return (url or '').replace('&amp;', '&').replace('&#038;', '&').strip()


def _norm(s):
    """Lower-case and collapse every run of non-alphanumerics to '-', so that
    `9.15.26`, `9/15/26`, `9 15 26` and `9-15-26` are one spelling."""
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def _date(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def _yy(v):
    v = int(v)
    return 2000 + v if _YY_MIN <= v <= _YY_MAX else None


def parse_date(text):
    """Read a date out of a file name or link text.

    Returns ('full', date) for a complete date, ('md', (month, day)) when the year
    is missing, or None (nothing usable, or deliberately ambiguous - see module
    docstring)."""
    s = _norm(text)
    if not s:
        return None

    # --- complete dates -------------------------------------------------
    m = re.search(r'(?<!\d)(20\d\d)-(\d{1,2})-(\d{1,2})(?!\d)', s)           # 2026-07-21
    if m:
        d = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(\d{1,2})-(\d{1,2})-(20\d\d)(?!\d)', s)           # 7-21-2026
    if m:
        d = _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(20\d\d)-' + _MON + r'-(\d{1,2})(?!\d)', s)        # 2025-january-7
    if m:
        d = _date(int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))
        if d:
            return 'full', d
    m = re.search(_MON + r'-?(\d{1,2})-?(20\d\d)(?!\d)', s)                   # july-21-2026, may-8-2025
    if m:
        d = _date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(_MON + r'-?(\d{1,2})-(\d{2})(?!\d)', s)                     # july-21-26, apr-10-25
    if m and _yy(m.group(3)):
        d = _date(_yy(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(_MON + r'-?(\d{2})(\d{2})(?!\d)', s)                        # JUNE1225 -> June 12, 2025
    # "sept2025" is month+year, not Sept 20 '25: a DD of 20 is left unread.
    if m and m.group(2) != '20' and _yy(m.group(3)):
        d = _date(_yy(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(\d{1,2})-(\d{1,2})-(\d{2})(?!\d)', s)             # 9-15-26
    if m and _yy(m.group(3)):
        d = _date(_yy(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(20\d\d)(\d{2})(\d{2})(?!\d)', s)                  # 20260721
    if m:
        d = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(\d{2})(\d{2})(20\d\d)(?!\d)', s)                  # 07212026
    if m:
        d = _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return 'full', d
    m = re.search(r'(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)', s)                   # 051226 (MMDDYY)
    # "122022" is Dec 2022 (MMYYYY) as readily as Dec 20 '22: a DD of 20 is left unread.
    if m and m.group(2) != '20' and _yy(m.group(3)):
        d = _date(_yy(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return 'full', d

    # --- month + day, no year --------------------------------------------
    # A 4-digit year left over at this point means month+year naming
    # ("06-2025-Combined-June-1", "September 2025"): any short number beside a
    # month is a duplicate-file suffix, not a day.
    if re.search(r'(?<!\d)20\d\d(?!\d)', s):
        return None
    m = re.search(_MON + r'-?(\d{1,2})(?!\d)', s)                             # aug-17, november18
    if m:
        day = int(m.group(2))
        if 24 <= day <= 27:
            return None                     # "Oct 25": the 25th or 2025 - cannot say
        if _date(2000, _MONTHS[m.group(1)], day):
            return 'md', (_MONTHS[m.group(1)], day)
    m = re.search(r'(?<!\d)(?<!\d-)(\d{1,2})-(\d{1,2})(?!\d|-\d)', s)         # 4-2, 04-14
    if m:
        mo, day = int(m.group(1)), int(m.group(2))
        if 24 <= day <= 27:
            return None                     # "09-26": Sept 26th or Sept 2026
        if _date(2000, mo, day):
            return 'md', (mo, day)
    return None


def _latest_year(month, day, ref):
    """Largest year for which month/day is not more than 45 days after `ref`."""
    for y in (ref.year + 1, ref.year, ref.year - 1, ref.year - 2):
        d = _date(y, month, day)
        if d and d <= ref + _SLACK:
            return d
    return None


def _classify(href, text):
    """('minutes' | 'agenda' | None, is_action). Link text wins over the file name:
    a file called `012125 meeting.pdf` is a minutes file only because its text says
    so. Within either, minutes beat agenda. `is_action` marks a secondary "Action
    Agenda" so a primary agenda is preferred when a date has both."""
    t = (text or '').lower()
    if 'minute' in t:
        return 'minutes', False
    if 'agenda' in t:
        return 'agenda', 'action' in t
    h = unquote(href.split('?', 1)[0]).lower()
    if 'minute' in h:
        return 'minutes', False
    if 'agenda' in h:
        return 'agenda', 'action' in h
    return None, False


def _stable_url(page_url, href):
    """Absolute, encoded PDF URL. Drops query/fragment (cache-busters), encodes the
    spaces and curly quotes clerks leave in file names, and upgrades http to https
    on the page's own host (Atkinson's links are http:// on an https page)."""
    href, _ = urldefrag(_unescape(href))
    parts = urlsplit(urljoin(page_url, href))
    page = urlsplit(page_url)
    scheme = parts.scheme
    if scheme == 'http' and page.scheme == 'https' and parts.netloc == page.netloc:
        scheme = 'https'
    path = quote(unquote(parts.path), safe="/:@!$&'()*+,;=~-._")
    return urlunsplit((scheme, parts.netloc, path, '', ''))


def _title(text, body, iso):
    """The link text minus its generic Agenda/Minutes label, when something
    meaningful is left ("Call Meeting", "Public Hearing"); else '<body> <date>'."""
    t = re.sub(r'(?i)\b(agendas?|minutes?|combined|packet)\b', ' ', text or '')
    t = re.sub(r'[\s\-–—:]+$|^[\s\-–—:]+', '', re.sub(r'\s+', ' ', t)).strip()
    if len(re.findall(r'[A-Za-z]', t)) >= 4 and len(t) <= 60:
        return t
    return '%s %s' % (body, iso)


def parse_page(html, page_url, body='Board of Commissioners', year_from_order=False,
               today=None, stats=None):
    """Parse one page's PDF links into {date: record} entries, in document order.

    Returns a list of (date_iso, kind, url, is_action, text). `stats` (a dict) is
    filled with counters for the run log."""
    today = today or datetime.date.today()
    stats = stats if stats is not None else {}
    for k in ('links', 'kept', 'skipped_nodate', 'skipped_nokind'):
        stats.setdefault(k, 0)
    out = []
    anchor = None                      # last FULL date seen, for newest-first lists
    for href, inner in _ANCHOR_RE.findall(html):
        if not _PDF_RE.search(href):
            continue
        stats['links'] += 1
        text = _clean(inner)
        kind, is_action = _classify(href, text)
        if not kind:
            stats['skipped_nokind'] += 1
            continue
        name = unquote(href.split('?', 1)[0].rsplit('/', 1)[-1])
        name = re.sub(r'(?i)\.pdf$', '', name)

        full = md = None
        for src in (name, text):
            r = parse_date(src)
            if not r:
                continue
            if r[0] == 'full':
                full = r[1]
                break
            if md is None:
                md = r[1]

        date = full
        if date is None and md is not None:
            ref = None
            up = _UPLOAD_RE.search(href)
            if up:
                y, mo = int(up.group(1)), int(up.group(2))
                ref = _date(y + (mo == 12), (mo % 12) + 1, 1) - datetime.timedelta(days=1)
            elif year_from_order and anchor is not None:
                ref = anchor
            if ref is not None:
                date = _latest_year(md[0], md[1], ref)
        if date is None:
            stats['skipped_nodate'] += 1
            continue
        if not (2015 <= date.year <= today.year + 1):
            stats['skipped_nodate'] += 1
            continue
        if full is not None:
            anchor = date
        out.append((date.isoformat(), kind, _stable_url(page_url, href), is_action, text))
        stats['kept'] += 1
    return out


def build_meetings(links, body='Board of Commissioners'):
    """Group (date, kind, url, is_action, text) tuples into meeting records,
    newest first. A "Combined" file listed under both kinds fills both slots."""
    by_date = {}
    for iso, kind, url, is_action, text in links:
        rec = by_date.get(iso)
        if rec is None:
            rec = {
                'body': body,
                'date': iso,
                'id': iso,
                'title': _title(text, body, iso),
                'agendaUrl': None,
                'minutesUrl': None,
                'videoUrl': None,
                'hasPreviousVersions': False,
                '_action': False,
            }
            by_date[iso] = rec
        if kind == 'minutes':
            rec['minutesUrl'] = rec['minutesUrl'] or url
        elif rec['agendaUrl'] is None:
            rec['agendaUrl'] = url
            rec['_action'] = is_action
        elif rec['_action'] and not is_action:
            rec['agendaUrl'] = url
            rec['_action'] = False
    meetings = sorted(by_date.values(), key=lambda m: m['date'], reverse=True)
    for m in meetings:
        m.pop('_action', None)
    return meetings


def fetch_pdflinks_meetings(agendas_url, extra_urls=None, body='Board of Commissioners',
                            year_from_order=False, timeout=40):
    """Fetch and normalize a loose-PDF agendas page (and any `extra_urls`, e.g. a
    separate minutes page).

    Returns (meetings, bodies_seen); (None, None) if ANY page can't be fetched, so
    a half-read set never overwrites a complete one."""
    all_links = []
    stats = {}
    for url in [agendas_url] + list(extra_urls or []):
        raw = fetch_bytes(url, label='pdflinks %s' % url, timeout=timeout)
        if raw is None:
            return None, None
        html = raw.decode('utf-8', errors='replace')
        all_links.extend(parse_page(html, url, body=body,
                                    year_from_order=year_from_order, stats=stats))
    meetings = build_meetings(all_links, body=body)
    print('  pdflinks: %(links)d PDF link(s), %(kept)d dated, %(skipped_nodate)d skipped '
          '(no usable date), %(skipped_nokind)d skipped (not agenda/minutes)' % stats)
    return meetings, sorted({m['body'] for m in meetings})
