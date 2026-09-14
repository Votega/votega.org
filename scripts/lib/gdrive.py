#!/usr/bin/env python3
"""Adapter for a public Google Drive folder of agendas/minutes.

Some GA governments don't run a meeting portal at all — they drop their agendas,
summaries and minutes into a shared Google Drive folder and link it from a plain
CMS page. City of Carrollton is the first: carrolltonga.com links a public Drive
folder ("Council Meeting Agendas and Minutes") that is nested one level:

    <root folder>
      1-2026 Agenda Packets/   09 14 2026 Agenda Packet.pdf, ...
      2-2026 Summaries/        ...
      3-2026 Minutes/          ...
      Public Notices/          (ignored)
      2026 ... Meeting Calendar (a file, ignored)

Like Revize, this is a link harvester, not a structured scraper. The signal is
the same "date + agenda/minutes keyword" convention Revize relies on — except the
DOC TYPE here comes from the *subfolder* name, not the file name, and each file's
date sits in the file name (`MM DD YYYY`, also tolerant of `-`/`/` separators).

No API key or OAuth is needed: a publicly-shared folder is listable through the
`embeddedfolderview` endpoint, which returns a static HTML list of entries — each
a `flip-entry` whose anchor is `/drive/folders/<id>` (a subfolder) or
`/file/d/<id>/view` (a file) and whose `flip-entry-title` is the name.

    1. List the ROOT folder. Classify each SUBFOLDER by name keyword — agenda /
       minutes / summaries — and ignore the rest (notices, calendar). Discovering
       subfolders by name (not by hard-coded id) is deliberate: the city makes a
       fresh "1-2027 Agenda Packets" folder each year with a new id, and every
       year's agenda folder still contains "agenda", so this keeps working with
       no per-cycle edit (see CLAUDE.md's cycle-agnostic rule).
    2. List each classified subfolder, parse the date from every file name, and
       group by date into one meeting record, routing the file to
       agendaUrl / minutesUrl (a Summary backs minutesUrl when no Minutes exist).
    3. Emit the friendly `/file/d/<id>/view` URL (Drive's in-browser preview) as
       the link. The OCR enricher translates it to a download URL at fetch time
       via drive_download_url() — see enrich_ocr_meetings.py.

Records carry a single board (the city council); the caller sets `body_label` in
the registry to name it, exactly as the Revize places do.

Import from a generator in scripts/:
    from lib.gdrive import fetch_gdrive_meetings, drive_download_url
"""

import re

from lib.http import fetch_bytes

EMBED_URL = 'https://drive.google.com/embeddedfolderview?id=%s#list'

# One flip-entry: its anchor (folder or file) followed by the title div. Non-greedy
# so each href binds to the NEXT title, i.e. its own entry.
_ENTRY_RE = re.compile(
    r'href="https://drive\.google\.com/(drive/folders/|file/d/)([A-Za-z0-9_-]+)'
    r'[^"]*"[\s\S]*?flip-entry-title"[^>]*>([^<]*)<', re.I)
# MM DD YYYY (or - / separators), 1-2 digit month/day.
_DATE_RE = re.compile(r'(\d{1,2})[ \-/](\d{1,2})[ \-/](\d{4})')


def _parse_date(text):
    """First MM DD YYYY / MM-DD-YYYY / MM/DD/YYYY in `text` -> ISO date, or None."""
    m = _DATE_RE.search(text or '')
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
        return None
    return '%04d-%02d-%02d' % (year, month, day)


def _classify_folder(name):
    """Which document type a subfolder holds, by name keyword, or None to skip."""
    n = (name or '').lower()
    if 'agenda' in n:
        return 'agenda'
    if 'minute' in n:
        return 'minutes'
    if 'summ' in n:
        return 'summary'
    return None


def _descriptor(name):
    """A short meeting descriptor from a file name: drop the leading date and the
    trailing document-type words, leaving e.g. 'Work Session' or 'Special Called'."""
    text = _DATE_RE.sub('', name or '', count=1)
    text = re.sub(r'\b(agenda|packet|minutes?|summar(?:y|ies)|city of carrollton)\b',
                  '', text, flags=re.I)
    text = re.sub(r'[-–—]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _view_url(file_id):
    return 'https://drive.google.com/file/d/%s/view' % file_id


def drive_download_url(url):
    """A direct-download URL for a Google Drive `/file/d/<id>/view` link.

    Returns the usercontent download endpoint with `confirm=t`, which bypasses the
    large-file virus-scan interstitial (agenda packets run tens of MB). Any URL
    that isn't a Drive file link is returned unchanged, so callers can pass every
    meeting URL through it blindly.
    """
    m = re.search(r'/file/d/([A-Za-z0-9_-]+)', url or '')
    if not m:
        return url
    return ('https://drive.usercontent.google.com/download'
            '?id=%s&export=download&confirm=t' % m.group(1))


def _list_folder(folder_id, timeout):
    """(subfolders, files) for one Drive folder, each as [(id, name), ...].

    Returns (None, None) if the folder page can't be fetched, so a caller can tell
    a transient failure apart from a genuinely empty folder.
    """
    raw = fetch_bytes(EMBED_URL % folder_id,
                      label='gdrive folder %s' % folder_id, timeout=timeout)
    if raw is None:
        return None, None
    html = raw.decode('utf-8', errors='replace')
    subfolders, files = [], []
    for kind, gid, name in _ENTRY_RE.findall(html):
        name = re.sub(r'\s+', ' ', name.replace('&amp;', '&')).strip()
        (subfolders if kind.startswith('drive/folders') else files).append((gid, name))
    return subfolders, files


def fetch_gdrive_meetings(folder_id, body='City Council', timeout=40):
    """Fetch and normalize a public Google Drive agendas/minutes folder.

    `folder_id` is the ROOT folder id. Its agenda/minutes/summary subfolders are
    discovered by name and each is listed for dated files. Returns
    (meetings, bodies_seen); (None, None) if the root folder can't be fetched, so
    the caller never overwrites good data with nothing.
    """
    subfolders, _ = _list_folder(folder_id, timeout)
    if subfolders is None:
        return None, None

    by_date = {}
    order = []
    for gid, name in subfolders:
        kind = _classify_folder(name)
        if not kind:
            continue
        _, files = _list_folder(gid, timeout)
        for file_id, fname in (files or []):
            date = _parse_date(fname)
            if not date:
                continue
            rec = by_date.get(date)
            if rec is None:
                rec = {
                    'body': body,
                    'date': date,
                    'id': date,
                    'title': None,
                    'agendaUrl': None,
                    'minutesUrl': None,
                    'videoUrl': None,
                    'hasPreviousVersions': False,
                    '_descriptor': '',
                }
                by_date[date] = rec
                order.append(date)
            url = _view_url(file_id)
            if kind == 'agenda':
                if not rec['agendaUrl']:
                    rec['agendaUrl'] = url
                # the agenda file names the meeting best (Work Session / Special Called)
                desc = _descriptor(fname)
                if desc and not rec['_descriptor']:
                    rec['_descriptor'] = desc
            elif kind == 'minutes':
                if not rec['minutesUrl']:
                    rec['minutesUrl'] = url
            else:  # summary — only a fallback when there are no adopted minutes yet
                if not rec['minutesUrl']:
                    rec['minutesUrl'] = url

    meetings = [by_date[d] for d in order]
    for m in meetings:
        desc = m.pop('_descriptor', '')
        label = '%s %s' % (m['body'], desc) if desc else m['body']
        m['title'] = '%s %s' % (label, m['date'])
    meetings.sort(key=lambda x: x['date'], reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
