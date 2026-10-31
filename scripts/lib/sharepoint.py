#!/usr/bin/env python3
"""Adapter for a city that publishes agendas and minutes in a public SharePoint library.

LaFayette's Agendas & Minutes page is a link to a SharePoint "anyone with the link"
folder share. Three facts shape this adapter:

  * The share link only works in a browser. `curl` is bounced to a Microsoft sign-in, but
    a real browser follows the link, is issued an ANONYMOUS session (the page context
    reports `urn:spo:tenantanon#...`), and from then on the library's REST API lists the
    files and serves them. So listing and downloading both need a browser session.
  * A direct file link has no session of its own. A visitor who opens
    `.../Council Agendas/0 AGENDA 10 20 26.pdf` cold is sent to a Microsoft sign-in.
    So the links we PUBLISH are the folder share link (which a visitor can open), and
    the direct file URLs are kept in separate `agendaFileUrl` / `minutesFileUrl` fields
    that only the enricher reads, inside the same kind of browser session.
  * The only metadata is the file name: `0 AGENDA 10 20 26.pdf`,
    `MINUTES 05 22 26 SPECIAL CALLED.pdf`. The date is the three two-digit numbers
    (month, day, year); whatever words remain are the meeting's label.

`parse_listing` is pure (file names in, meetings out) so it is tested offline;
`list_library` and `SharePointSession` are the only parts that need a browser.

Never guess: a file whose name carries no valid date is skipped and reported, minutes
are paired to an agenda only on the same date and the same label (or as the sole
leftover on a single-agenda date), and anything else stands as its own meeting.

Import from a generator or the enricher in scripts/:
    from lib.sharepoint import fetch_sharepoint_meetings, SharePointSession
"""

import os
import re
import sys
from datetime import datetime
from urllib.parse import parse_qs, quote, unquote, urlsplit

_DATE = re.compile(r'(?<!\d)(\d{2})[ _.\-](\d{2})[ _.\-](\d{2}|\d{4})(?!\d)')
_NOISE = {'agenda', 'agendas', 'minutes', '0'}


def _iso(m, d, y):
    y = ('20' + y) if len(y) == 2 else y
    try:
        return datetime(int(y), int(m), int(d)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def _long_date(iso):
    d = datetime.strptime(iso, '%Y-%m-%d')
    return '%s %d, %d' % (d.strftime('%B'), d.day, d.year)


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def parse_name(name):
    """'MINUTES 05 22 26 SPECIAL CALLED.pdf' -> ('2026-05-22', 'Special Called'), or
    None when the name carries no valid date."""
    stem = re.sub(r'\.[A-Za-z0-9]{2,4}$', '', name or '')
    m = _DATE.search(stem)
    if not m:
        return None
    date = _iso(*m.groups())
    if not date:
        return None
    rest = (stem[:m.start()] + ' ' + stem[m.end():]).split()
    words = [w for w in rest if w.lower() not in _NOISE]
    return date, ' '.join(w.capitalize() for w in words)


def _title_label(label):
    """'' -> 'Council Meeting'; 'Special Called' -> 'Special Called Meeting';
    'Public Hearing' and 'Special Called Meeting' are left as they are."""
    if not label:
        return 'Council Meeting'
    return label if re.search(r'meeting|hearing', label, re.I) else label + ' Meeting'


def _norm(label):
    return re.sub(r'\bmeeting\b', '', (label or '').lower()).strip()


def parse_listing(agenda_files, minutes_files, share_url, body='City Council'):
    """Two file listings -> (meetings, report).

    Each file is {'name', 'url'}, `url` being the direct file URL. Published links
    (`agendaUrl` / `minutesUrl`) are `share_url` where a document exists, and None where
    it does not; the direct URLs ride along as `agendaFileUrl` / `minutesFileUrl`."""
    skipped = []
    by_date = {}

    def add(kind, f):
        parsed = parse_name(f.get('name'))
        if not parsed:
            skipped.append(f.get('name'))
            return
        date, label = parsed
        by_date.setdefault(date, {'agenda': [], 'minutes': []})[kind].append(
            {'label': label, 'url': f['url']})

    for f in agenda_files:
        add('agenda', f)
    for f in minutes_files:
        add('minutes', f)

    meetings = []
    for date, g in by_date.items():
        agendas, minutes = g['agenda'], list(g['minutes'])
        rows = []
        for a in agendas:
            hit = next((m for m in minutes if _norm(m['label']) == _norm(a['label'])), None)
            if hit is None and len(agendas) == 1 and len(minutes) == 1:
                hit = minutes[0]          # the only two documents of the day belong together
            if hit is not None:
                minutes.remove(hit)
            rows.append((a, hit))
        rows += [(None, m) for m in minutes]
        seen = {}
        for a, m in rows:
            label = a['label'] if a and a['label'] else (m['label'] if m else '')
            n = seen[label] = seen.get(label, 0) + 1
            meetings.append({
                'body': body,
                'date': date,
                'id': date + '-' + (_slug(label) or 'council-meeting') + ('' if n == 1 else '-%d' % n),
                'title': '%s %s' % (_long_date(date), _title_label(label)),
                'agendaUrl': share_url if a else None,
                'minutesUrl': share_url if m else None,
                'videoUrl': None,
                'hasPreviousVersions': False,
                'agendaFileUrl': a['url'] if a else None,
                'minutesFileUrl': m['url'] if m else None,
            })
    meetings.sort(key=lambda x: (x['date'], x['id']), reverse=True)
    report = {'agendas': len(agenda_files), 'minutes': len(minutes_files),
              'skipped': skipped, 'meetings': len(meetings)}
    if not agenda_files and not minutes_files:
        raise ValueError('the library listed no files')
    if not meetings:
        raise ValueError('no file name carried a date - the naming has changed')
    return meetings, report


# --- browser side -----------------------------------------------------------------

def _launch():
    from playwright.sync_api import sync_playwright  # lazy: parser tests need no browser
    pw = sync_playwright().start()
    opts = {'channel': os.environ['CHROME_CHANNEL']} if os.environ.get('CHROME_CHANNEL') else {}
    return pw, pw.chromium.launch(**opts)


class SharePointSession:
    """An anonymous SharePoint session opened from a share link. Lazy: no browser starts
    until the first call. Use as a context manager."""

    def __init__(self, share_url, timeout=60):
        self.share_url = share_url
        self.timeout = timeout
        self._pw = self._browser = self._ctx = None
        self.origin = self.web = self.library = None

    def _open(self):
        if self._ctx is not None:
            return
        self._pw, self._browser = _launch()
        self._ctx = self._browser.new_context()
        page = self._ctx.new_page()
        page.goto(self.share_url, wait_until='domcontentloaded', timeout=self.timeout * 1000)
        page.wait_for_url(re.compile(r'AllItems\.aspx'), timeout=self.timeout * 1000)
        parts = urlsplit(page.url)
        self.origin = '%s://%s' % (parts.scheme, parts.netloc)
        # `id` is the server-relative folder the share link points at.
        self.library = unquote(parse_qs(parts.query)['id'][0])
        self.web = '/' + self.library.strip('/').split('/')[0]
        page.close()

    def list_folder(self, subfolder):
        """Files directly inside `<share folder>/<subfolder>`: [{'name', 'url'}]."""
        self._open()
        folder = '%s/%s' % (self.library.rstrip('/'), subfolder)
        api = ("%s%s/_api/web/GetFolderByServerRelativeUrl('%s')/Files"
               "?$select=Name,ServerRelativeUrl&$top=5000"
               % (self.origin, self.web, quote(folder.replace("'", "''"), safe="/%'")))
        out = []
        while api:
            r = self._ctx.request.get(api, headers={'Accept': 'application/json;odata=nometadata'},
                                      timeout=self.timeout * 1000)
            if not r.ok:
                raise RuntimeError('listing %s -> HTTP %s' % (folder, r.status))
            j = r.json()
            for f in j.get('value', []):
                out.append({'name': f['Name'], 'url': self.origin + quote(f['ServerRelativeUrl'])})
            api = j.get('odata.nextLink') or j.get('@odata.nextLink')
        return out

    def get(self, url):
        """Bytes of a file URL from this library, or None."""
        self._open()
        r = self._ctx.request.get(url, timeout=self.timeout * 1000)
        if not r.ok or 'html' in (r.headers.get('content-type') or ''):
            return None
        return r.body()

    def close(self):
        for obj in (self._browser, self._pw):
            try:
                if obj is not None:
                    obj.close() if obj is self._browser else obj.stop()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._ctx = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fetch_sharepoint_meetings(share_url, agenda_folder, minutes_folder, body='City Council',
                              session_factory=SharePointSession):
    """Returns (meetings, bodies_seen), or (None, None) if the library cannot be read.
    `session_factory` is injectable so tests need no browser."""
    last = None
    for attempt in range(2):
        try:
            with session_factory(share_url) as s:
                agendas = s.list_folder(agenda_folder)
                minutes = s.list_folder(minutes_folder)
            meetings, report = parse_listing(agendas, minutes, share_url, body=body)
            break
        except Exception as e:  # noqa: BLE001 - one place's failure must not stop the run
            last = e
            print('  sharepoint: attempt %d failed: %s' % (attempt + 1, e), file=sys.stderr)
    else:
        print('  sharepoint: giving up (%s)' % last, file=sys.stderr)
        return None, None
    print('  sharepoint: %d agendas + %d minutes files -> %d meetings; skipped (no date) %s'
          % (report['agendas'], report['minutes'], report['meetings'], report['skipped'] or 'none'))
    return meetings, [body]
