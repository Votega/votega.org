#!/usr/bin/env python3
"""Adapter for Revize-CMS county "Agendas & Minutes" pages.

Revize (revize.com) is a commercial government-website CMS, not a meeting portal:
unlike CivicPlus's AgendaCenter or Granicus's ViewPublisher there is no shared
meeting API and no uniform meeting markup. What Revize agenda pages DO share is a
convention — the board's agendas and minutes are posted as PDF links whose file
name (or link text) carries the meeting date and the word "Agenda"/"Minutes"
(Bartow: `CommissionerOffice/AGENDA.PUBLIC_MEETING_9-2-2026.pdf`; Fayette:
`09-10-2026 BOC Agenda.pdf`, `08-13-2026 Minutes.pdf`). So this adapter is a
link harvester, not a structured scraper:

  1. Fetch the configured agendas page.
  2. Resolve links against the page's `<base href>` — Revize sets one pointing at
     the SITE ROOT, so a bare-filename link like `09-10-2026 BOC Agenda.pdf`
     resolves to `https://host/09-10-2026%20BOC%20Agenda.pdf`, NOT under the
     page's own directory. Getting this wrong yields 404s. Falls back to the
     registry `base_url`, then the page URL, when no `<base>` is present.
  3. Keep only `<a>`s that point at a PDF AND whose href/text contains both a
     parseable date and an agenda/minutes keyword. That pair is the meeting
     signal; it also filters out the unrelated PDFs these CMS pages mix in
     (notices, ADA statements, fee schedules, ...).
  4. Group links by meeting date into one record, routing each to agendaUrl /
     minutesUrl. Cache-buster query strings (`?t=<timestamp>`) are dropped so the
     committed JSON stays byte-identical across quiet re-runs.

Revize pages carry a single board (the county Board of Commissioners), so the
caller sets `body_label` in the registry to name it; every record is emitted with
a neutral placeholder body that body_label/body_map then relabels (see
scope_bodies in generate_place_meetings.py).

Import from a generator in scripts/:
    from lib.revize import fetch_revize_meetings
"""

import re
from urllib.parse import urljoin, urldefrag

from lib.http import fetch_bytes

# <a ... href="..."> inner </a>. Tolerant of the `href = "..."` spacing Revize
# emits and of single quotes; inner text captured non-greedily across newlines.
_ANCHOR_RE = re.compile(
    r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_BASE_RE = re.compile(r'<base\b[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.I)
# M-D-YYYY or M/D/YYYY, 1-2 digit month/day (Bartow uses 9-2-2026, Fayette 09-10-2026).
_DATE_RE = re.compile(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})')
_PDF_RE = re.compile(r'\.pdf(?:$|[?#])', re.I)


def _clean(text):
    text = (text or '').replace('&nbsp;', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', _TAG_RE.sub('', text)).strip()


def _unescape(url):
    return (url or '').replace('&amp;', '&').strip()


def _parse_date(text):
    """First M-D-YYYY / M/D/YYYY in `text` -> ISO date, or None if implausible."""
    m = _DATE_RE.search(text or '')
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
        return None
    return '%04d-%02d-%02d' % (year, month, day)


def _stable_url(base, href):
    """Absolute URL for a PDF link: entity-decode, drop the ?t= cache-buster and
    any fragment, resolve against the site-root `<base>`, and encode spaces."""
    href, _ = urldefrag(_unescape(href))
    href = href.split('?', 1)[0]           # drop cache-buster query
    return urljoin(base, href).replace(' ', '%20')


def _classify(haystack):
    """('minutes' | 'agenda' | None, is_action) from a link's href+text.
    Minutes wins over agenda; `is_action` flags a secondary "Action Agenda" so the
    primary agenda is preferred as agendaUrl when a date has both."""
    h = haystack.lower()
    if 'minute' in h:
        return 'minutes', False
    if 'agenda' in h:
        return 'agenda', 'action' in h
    return None, False


def parse_page(html, base):
    """Parse a Revize agendas page into normalized meeting dicts (newest first)."""
    by_date = {}
    order = []
    for href, inner in _ANCHOR_RE.findall(html):
        if not _PDF_RE.search(href):
            continue
        text = _clean(inner)
        haystack = '%s %s' % (href, text)
        kind, is_action = _classify(haystack)
        if not kind:
            continue
        # Date from the file name first (most reliable), then the link text.
        date = _parse_date(href.split('?', 1)[0]) or _parse_date(text)
        if not date:
            continue
        url = _stable_url(base, href)

        rec = by_date.get(date)
        if rec is None:
            rec = {
                'body': 'Board of Commissioners',
                'date': date,
                'id': date,
                'title': text or date,
                'agendaUrl': None,
                'minutesUrl': None,
                'videoUrl': None,
                'hasPreviousVersions': False,
            }
            by_date[date] = rec
            order.append(date)

        if kind == 'minutes':
            if not rec['minutesUrl']:
                rec['minutesUrl'] = url
        else:  # agenda — prefer a primary agenda over a secondary "Action Agenda"
            if rec['agendaUrl'] is None:
                rec['agendaUrl'] = url
                rec['_agenda_action'] = is_action
            elif rec.get('_agenda_action') and not is_action:
                rec['agendaUrl'] = url          # upgrade action -> primary agenda
                rec['_agenda_action'] = False

    meetings = [by_date[d] for d in order]
    for m in meetings:
        m.pop('_agenda_action', None)
        if m['title'] == m['date']:  # give a title-less date a readable label
            m['title'] = 'Board of Commissioners %s' % m['date']
    meetings.sort(key=lambda x: x['date'], reverse=True)
    return meetings


def fetch_revize_meetings(agendas_url, base_url=None, timeout=40):
    """Fetch and normalize a Revize county agendas page.

    `agendas_url` is the county's Agendas & Minutes page (registry key). Links are
    resolved against the page's `<base href>` (Revize sets one at the site root);
    `base_url` from the registry is the fallback, then the page URL itself.

    Returns (meetings, bodies_seen); (None, None) if the page can't be fetched, so
    the caller never overwrites good data with nothing.
    """
    raw = fetch_bytes(agendas_url, label='revize %s' % agendas_url, timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')

    base_tag = _BASE_RE.search(html)
    base = _unescape(base_tag.group(1)) if base_tag else (base_url or agendas_url)

    meetings = parse_page(html, base)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
