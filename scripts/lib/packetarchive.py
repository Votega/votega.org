#!/usr/bin/env python3
"""Adapter for a government page that shows ONLY the current meeting packet.

Rossville's Squarespace page carries one "Download Meeting Agenda" link to this
month's packet; last month's is replaced, not archived. Walking the page therefore
yields a single meeting, and every other adapter would publish it, then silently
lose it next month. This adapter turns that into a record that GROWS:

  * each run reads the packet link(s) now on the page;
  * the link is resolved through its redirect to the real file (Rossville's
    `/s/Agenda-Packet-October-2026.pdf` is only a 302 to a Squarespace CDN URL,
    and that CDN URL is what must be hashed and archived);
  * the file is hashed (sha256, bytes, fetched-at) and sent to the Wayback Machine
    once, the first time it is seen;
  * the previous run's records are carried forward. Once the city has replaced a
    packet its own link no longer works, so a carried-forward meeting's
    `agendaUrl` becomes the archived copy and the city's link is kept in
    `agendaOriginalUrl`.

History therefore starts the day the adapter first runs, and a month this job does
not see (the city posts and replaces a packet between two runs) is a permanent gap.
Nothing is back-filled.

⚠ The meeting DATE is not on the page. The file name gives the month and year
("Agenda-Packet-October-2026"), the day comes from, in order: a "Month D, YYYY"
in the PDF's own first page naming that month, else the registry's usual meeting
day (`meeting_nth` + `meeting_weekday`, Monday=0). `dateSource` says which, so a
rescheduled meeting that falls back to the rule is a labelled inference, never a
silent fact.

Import from a generator in scripts/:
    from lib.packetarchive import fetch_packetarchive_meetings
"""

import calendar
import hashlib
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from urllib.parse import unquote, urljoin

from lib.http import fetch_bytes

_ANCHOR = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_PDF = re.compile(r'\.pdf(?:$|[?#])', re.I)
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTH_YEAR = re.compile(
    r'(%s)[^a-z0-9]*(?:\d{1,2}[^a-z0-9]+)?(20\d{2})' % '|'.join(_MONTHS), re.I)
_DATE_TEXT = re.compile(r'(%s)\s+(\d{1,2}),?\s+(20\d{2})' % '|'.join(_MONTHS), re.I)
UA = 'Mozilla/5.0 (votega.org meeting-list)'


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def month_year(name):
    """(year, month) from a packet file name, or None. Needs both; never guessed."""
    m = _MONTH_YEAR.search(unquote(name).replace('+', ' '))
    if not m:
        return None
    return int(m.group(2)), _MONTHS[m.group(1).lower()]


def nth_weekday(year, month, nth, weekday):
    """The nth `weekday` (Monday=0) of a month, or None when the month has no nth."""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if date(year, month, d).weekday() == weekday]
    return date(year, month, days[nth - 1]) if 0 < nth <= len(days) else None


def date_from_text(text, year, month):
    """A 'Month D, YYYY' in `text` that falls in the given month/year, else None.
    The packet quotes other dates (prior minutes), so only the named month counts."""
    for m in _DATE_TEXT.finditer(text or ''):
        if int(m.group(3)) == year and _MONTHS[m.group(1).lower()] == month:
            try:
                return date(year, month, int(m.group(2)))
            except ValueError:
                continue
    return None


def packet_links(page_html, page_url):
    """[(absolute url, link text)] for each PDF link whose file name carries a month and year."""
    out, seen = [], set()
    for href, label in _ANCHOR.findall(page_html or ''):
        if not _PDF.search(href):
            continue
        url = urljoin(page_url, href.replace('&amp;', '&'))
        if url in seen or not month_year(url.rsplit('/', 1)[-1]):
            continue
        seen.add(url)
        out.append((url, re.sub(r'<[^>]+>', '', label).strip()))
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def resolve_redirect(url, hops=4):
    """The final file URL behind a redirecting link; the input when there is no redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(hops):
        try:
            opener.open(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30).close()
            return url
        except urllib.error.HTTPError as e:
            loc = e.headers.get('Location')
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urljoin(url, loc)
                continue
            return url
        except Exception:  # noqa: BLE001
            return url
    return url


def _pdf_first_pages_text(data):
    """Text of the packet's first pages via poppler, or '' (no poppler / scanned)."""
    import os
    import shutil
    import subprocess
    import tempfile
    if not shutil.which('pdftotext'):
        return ''
    fd, path = tempfile.mkstemp(suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        proc = subprocess.run(['pdftotext', '-l', '3', '-layout', path, '-'],
                              capture_output=True, timeout=60)
        return proc.stdout.decode('utf-8', 'replace') if proc.returncode == 0 else ''
    except Exception:  # noqa: BLE001
        return ''
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _iso(d):
    return d.isoformat()


def build_current(url, label, body, nth, weekday, previous_by_key, fetch, resolve, archive,
                  pdf_text, now):
    """One meeting record for a packet link now on the page."""
    ym = month_year(url.rsplit('/', 1)[-1])
    year, month = ym
    file_url = resolve(url)
    prev = previous_by_key.get((year, month))
    reuse = prev if prev and prev.get('agendaFileUrl') == file_url else None

    sha, nbytes, fetched, text = None, None, None, ''
    if reuse and reuse.get('agendaSha256'):
        sha, nbytes, fetched = reuse['agendaSha256'], reuse.get('agendaBytes'), reuse.get('agendaFetchedAt')
    else:
        data = fetch(file_url)
        if data:
            sha, nbytes, fetched = hashlib.sha256(data).hexdigest(), len(data), now
            text = pdf_text(data)

    d, source = None, None
    if reuse and reuse.get('date', '')[:7] == '%04d-%02d' % (year, month):
        d, source = datetime.strptime(reuse['date'], '%Y-%m-%d').date(), reuse.get('dateSource')
    if d is None:
        d = date_from_text(text, year, month)
        source = 'packet text' if d else None
    if d is None and nth and weekday is not None:
        d, source = nth_weekday(year, month, nth, weekday), 'schedule rule'
    if d is None:
        d, source = date(year, month, 1), 'month only'

    snap = (reuse or {}).get('agendaArchiveUrl')
    if not snap and sha:  # archive only a file we actually received
        snap = archive(file_url)
    title = '%s %s Meeting' % (calendar.month_name[month], body) if False else \
        '%s %d, %d %s Meeting' % (calendar.month_name[month], d.day, d.year, body)
    return {
        'body': body, 'date': _iso(d), 'id': '%04d-%02d-%s' % (year, month, _slug(body)),
        'title': title, 'agendaUrl': url, 'minutesUrl': None, 'videoUrl': None,
        'hasPreviousVersions': False,
        'agendaFileUrl': file_url, 'agendaSha256': sha, 'agendaBytes': nbytes,
        'agendaFetchedAt': fetched, 'agendaArchiveUrl': snap, 'dateSource': source,
    }


def carry_forward(prev):
    """A record no longer on the page: the city's link is gone, so point at the archive."""
    rec = dict(prev)
    snap = rec.get('agendaArchiveUrl')
    if snap and rec.get('agendaUrl') != snap:
        rec['agendaOriginalUrl'] = rec.get('agendaOriginalUrl') or rec.get('agendaUrl')
        rec['agendaUrl'] = snap
    return rec


def fetch_packetarchive_meetings(agendas_url, body='City Council', meeting_nth=None,
                                 meeting_weekday=None, previous=None, fetcher=None,
                                 resolver=None, archiver=None, pdf_text=None, page_fetcher=None,
                                 now=None):
    """Returns (meetings, [body]) or (None, None) when the page cannot be read.
    `previous` is the last published meeting list; every record in it is kept."""
    page = (page_fetcher or (lambda u: fetch_bytes(u, headers={'User-Agent': UA})))(agendas_url)
    if not page:
        print('  packetarchive: page could not be read - giving up', file=sys.stderr)
        return None, None
    if archiver is None:
        from lib.wayback import archive as archiver
    now = now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prev_by_key = {}
    for p in previous or []:
        try:
            prev_by_key[(int(p['id'][:4]), int(p['id'][5:7]))] = p
        except (KeyError, ValueError, TypeError):
            continue

    links = packet_links(page.decode('utf-8', 'replace'), agendas_url)
    current = {}
    for url, label in links:
        rec = build_current(url, label, body, meeting_nth, meeting_weekday, prev_by_key,
                            fetcher or (lambda u: fetch_bytes(u, headers={'User-Agent': UA})),
                            resolver or resolve_redirect, archiver,
                            pdf_text or _pdf_first_pages_text, now)
        current[(int(rec['id'][:4]), int(rec['id'][5:7]))] = rec

    meetings = list(current.values())
    meetings += [carry_forward(p) for k, p in prev_by_key.items() if k not in current]
    if not links:
        print('  packetarchive: no packet link on the page - keeping %d earlier record(s)'
              % len(meetings), file=sys.stderr)
    if not meetings:
        return None, None
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    print('  packetarchive: %d on the page, %d carried forward, %d without an archive copy'
          % (len(current), len(meetings) - len(current),
             sum(1 for m in meetings if not m.get('agendaArchiveUrl'))))
    return meetings, [body]
