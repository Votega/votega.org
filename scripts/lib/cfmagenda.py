#!/usr/bin/env python3
"""Adapter for the "Agenda Center" of a ColdFusion county CMS (Haralson County's
`/agenda-center.cfm`): one `<h2>` per meeting type, then a `div.agenda-meeting` per
meeting holding `h3.agenda-date` ("Nov 17, 2026"), `em.agenda-title` and a
`div.agenda-files` list of links.

Only the newest year is in the page itself. Each type has year buttons
(`data-action="changeYear" data-year=2024 data-type=185`) that the page's script
resolves with `POST /agenda-center.cfm` (form fields y=<year>, t=<type>, q/s/e blank)
and splices the returned fragment (the same `div.agenda-meeting` blocks) in. This
adapter reads the page, discovers every (type, year) pair from those buttons, replays
the POST for the years not already on the page, and parses all of it. It is a
read-only POST, so retries are safe.

Rules (a bespoke CMS changes without notice, and a wrong link is worse than none):
  * Structure is found by class name, never position.
  * A meeting with an unparseable date is skipped and counted, never guessed.
  * A meeting whose title says CANCELLED is skipped: nothing met.
  * Files are classified by their own text + file name: "minute" -> minutes,
    "agenda" -> agenda, "packet" -> agenda only when there is no agenda file. When
    several different files compete for one slot, a non-"amended" one wins if
    exactly one exists; otherwise the slot is left empty rather than picking.
    Everything else (quotes, resolutions, proclamations) is ignored.
  * A PAST meeting with no agenda or minutes link is dropped (counted
    `skippedNoDocs`): the county lists them with only unrelated files or nothing, and
    a row with nothing to open is not a record. Upcoming meetings are kept.
  * ANY failed year fetch fails the whole run (None), so a partial history can never
    replace a complete one. A page with meetings but no document links anywhere is
    treated as a layout change and also fails.

`parse_fragment`, `discover_year_buttons` and `type_sections` are pure (HTML in) and
tested offline; `fetch_cfmagenda_meetings` takes an injectable fetcher.
"""

import html
import re
import sys
import urllib.parse
from datetime import date as _date, datetime
from urllib.parse import quote, urljoin

from lib.http import fetch_bytes

_BLOCK = re.compile(r'<div class="agenda-meeting">(.*?)(?=<div class="agenda-meeting">|\Z)',
                    re.S)
_DATE = re.compile(r'<h3 class="agenda-date">(.*?)</h3>', re.S)
_TITLE = re.compile(r'<em class="agenda-title">(.*?)</em>', re.S)
_ID = re.compile(r'download-package\.cfm\?id=(\d+)')
_FILES = re.compile(r'<div class="agenda-files"[^>]*>(.*)', re.S)
_ANCHOR = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_BUTTON = re.compile(r'<a\b[^>]*data-action="changeYear"[^>]*>', re.S)
_ATTR = re.compile(r'data-(year|type)="(\d+)"')
_H2 = re.compile(r'<h2>\s*(.*?)\s*</h2>(?:\s*<div id="Type(\d+)">)?', re.S)


def _clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def parse_date(text):
    """'Nov 17, 2026' / 'Sept 3, 2026' -> '2026-11-17', or None."""
    m = re.match(r'^([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$', _clean(text))
    if not m:
        return None
    try:
        return datetime.strptime('%s %s %s' % (m.group(1).title(), m.group(2), m.group(3)),
                                 '%b %d %Y').strftime('%Y-%m-%d')
    except ValueError:
        return None


def _abs(href, base):
    url = urljoin(base, html.unescape(href).strip())
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc,
                                    quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
                                    parts.query, ''))


def _pick(items):
    """One url from competing (url, text) files for a slot, or None when ambiguous."""
    uniq = list(dict.fromkeys(items))
    if len({u for u, _ in uniq}) == 1:
        return uniq[0][0]
    plain = {u for u, t in uniq if 'amend' not in ('%s %s' % (u, t)).lower()}
    return plain.pop() if len(plain) == 1 else None


def classify_files(files):
    """files: [(url, text)] -> (agendaUrl, minutesUrl)."""
    ag, mi, pk = [], [], []
    for url, text in files:
        probe = ('%s %s' % (text, urllib.parse.unquote(url.rsplit('/', 1)[-1]))).lower()
        if 'minute' in probe:
            mi.append((url, text))
        elif 'agenda' in probe:
            ag.append((url, text))
        elif 'packet' in probe:
            pk.append((url, text))
    return (_pick(ag) if ag else _pick(pk)), _pick(mi)


def parse_fragment(fragment, page_url, meeting_type, stats=None):
    """Parse every div.agenda-meeting in `fragment` for one meeting type."""
    stats = stats if stats is not None else {}
    out = []
    for m in _BLOCK.finditer(fragment):
        block = m.group(1)
        dm = _DATE.search(block)
        date = parse_date(dm.group(1)) if dm else None
        tm = _TITLE.search(block)
        title = _clean(tm.group(1)) if tm else meeting_type
        if not date:
            stats['skippedNoDate'] = stats.get('skippedNoDate', 0) + 1
            continue
        if re.search(r'cancel', title, re.I):
            stats['skippedCancelled'] = stats.get('skippedCancelled', 0) + 1
            continue
        im = _ID.search(block)
        files = []
        fm = _FILES.search(block)
        for href, inner in _ANCHOR.findall(fm.group(1) if fm else ''):
            text = _clean(inner)
            if not text or text.lower() == 'download file':
                continue
            files.append((_abs(href, page_url), text))
        agenda, minutes = classify_files(files)
        stats['documents'] = stats.get('documents', 0) + len(files)
        out.append({
            'body': meeting_type, 'date': date,
            'id': ('cfm-%s' % im.group(1)) if im else None,
            'title': title or meeting_type,
            'agendaUrl': agenda, 'minutesUrl': minutes, 'videoUrl': None,
            'hasPreviousVersions': False,
        })
    return out


def discover_year_buttons(page):
    """-> {type: [years, newest first]} from the changeYear buttons."""
    found = {}
    for tag in _BUTTON.findall(page):
        a = dict(_ATTR.findall(tag))
        if 'year' in a and 'type' in a:
            found.setdefault(a['type'], set()).add(int(a['year']))
    return {t: sorted(ys, reverse=True) for t, ys in found.items()}


def type_sections(page):
    """-> [(type_id, type_name, fragment)] for the h2 sections on the page."""
    marks = [(m.start(), m.end(), _clean(m.group(1)), m.group(2)) for m in _H2.finditer(page)]
    out = []
    for i, (_, end, name, tid) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(page)
        out.append((tid, name, page[end:stop]))
    return out


def fetch_cfmagenda_meetings(page_url, timeout=40, fetch=fetch_bytes, today=None):
    """Returns (meetings, bodies_seen), or (None, None) if anything cannot be read.
    `fetch` is injectable for tests."""
    raw = fetch(page_url, timeout=timeout, label='cfmagenda')
    if not raw:
        return None, None
    page = raw.decode('utf-8', 'replace')
    buttons = discover_year_buttons(page)
    sections = [s for s in type_sections(page) if s[0]]
    if not sections:
        print('  cfmagenda: no meeting-type sections found (%s)' % page_url, file=sys.stderr)
        return None, None
    names = {tid: name for tid, name, _ in sections}
    stats = {}
    meetings = []
    for tid, name, frag in sections:
        meetings.extend(parse_fragment(frag, page_url, name, stats))
    # The page shows each type's newest year; replay the POST for every other button.
    for tid, years in buttons.items():
        if tid not in names:
            continue
        for y in years[1:]:
            body = urllib.parse.urlencode({'y': y, 't': tid, 'q': '', 's': '', 'e': ''}).encode()
            resp = fetch(page_url, timeout=timeout, data=body,
                         label='cfmagenda %s/%s' % (tid, y))
            if resp is None:
                print('  cfmagenda: year fetch failed (type %s, %s); refusing a partial '
                      'history' % (tid, y), file=sys.stderr)
                return None, None
            meetings.extend(parse_fragment(resp.decode('utf-8', 'replace'), page_url,
                                           names[tid], stats))
    if meetings and not stats.get('documents'):
        print('  cfmagenda: meetings but no document links - layout change?', file=sys.stderr)
        return None, None
    today = (today or _date.today()).isoformat()
    seen, uniq = set(), []
    for m in meetings:
        if m['date'] < today and not (m['agendaUrl'] or m['minutesUrl']):
            stats['skippedNoDocs'] = stats.get('skippedNoDocs', 0) + 1
            continue
        k = m['id'] or (m['date'], m['body'], m['title'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(m)
    uniq.sort(key=lambda m: m['date'], reverse=True)
    print('  cfmagenda: %d meetings; skipped %s'
          % (len(uniq), {k: v for k, v in stats.items() if k.startswith('skipped')} or 'none'))
    return uniq, sorted({m['body'] for m in uniq})
