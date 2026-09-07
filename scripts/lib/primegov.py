#!/usr/bin/env python3
"""Adapter for PrimeGov (OneMeeting) public meeting portals.

Some GA counties (Clayton) run meetings on PrimeGov — `<sub>.primegov.com`, often
iframe-embedded on the county site. Unlike a scraped HTML page, PrimeGov exposes a
clean JSON API:

  GET /api/v2/PublicPortal/ListUpcomingMeetings          upcoming meetings
  GET /api/v2/PublicPortal/ListArchivedMeetings?year=Y   past meetings for year Y

Each meeting: {id, committeeId, meetingTypeId, dateTime (ISO), title, location,
videoUrl (a public Granicus player), documentList[]}. A documentList entry is
{templateId, compileOutputType, publishStatus, templateName ("Agenda"/"Minutes"/…)}
with link=null — the PUBLIC file URL is built as
  <base>/Public/CompiledDocument?meetingTemplateId=<templateId>&compileOutputType=<n>
The finalized/public documents are PDFs (compileOutputType 1); an unfinalized
upcoming HTML agenda (type 3) 404s, so we only link the PDFs.

`body` is the numeric committeeId (the API carries no committee NAME). Most GA
PrimeGov counties run a single committee (Clayton = the Board of Commissioners),
so scope with `body_label`; a multi-committee county would map committeeIds with a
body_map (revisit when one appears).

Output is the shared normalized schema. Import from a generator in scripts/:
    from lib.primegov import fetch_primegov_meetings
"""

import json
import re
from datetime import date

from lib.http import fetch_bytes

_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_HEADERS = {'Accept': 'application/json'}


def _api(base, path, timeout):
    raw = fetch_bytes(base + path, headers=_HEADERS, label='%s%s' % (base, path),
                      timeout=timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _doc_url(base, d):
    return ('%s/Public/CompiledDocument?meetingTemplateId=%s&compileOutputType=%s'
            % (base, d.get('templateId'), d.get('compileOutputType')))


def _normalize(base, m):
    iso = (m.get('dateTime') or '')[:10]
    if not _ISO.match(iso):
        return None
    agenda_url = minutes_url = None
    for d in m.get('documentList') or []:
        # Only the finalized, public PDFs (compileOutputType 1) resolve publicly;
        # unfinalized upcoming HTML agendas (type 3) 404, so skip them.
        if d.get('compileOutputType') != 1 or not d.get('publishStatus'):
            continue
        name = (d.get('templateName') or '').lower()
        url = _doc_url(base, d)
        if 'agenda' in name and not agenda_url:
            agenda_url = url
        elif 'minutes' in name and not minutes_url:
            minutes_url = url
    video = m.get('videoUrl') or None
    # Keep a document-less row only if it is UPCOMING (a scheduled meeting whose
    # agenda isn't compiled yet); drop a past row with nothing to link.
    upcoming = iso >= date.today().isoformat()
    if not (agenda_url or minutes_url or video) and not upcoming:
        return None
    return {
        'body': str(m.get('committeeId')),  # committee id; name it via body_label
        'date': iso,
        'id': str(m.get('id')),
        'title': (m.get('title') or '').strip() or 'Meeting',
        'agendaUrl': agenda_url,
        'minutesUrl': minutes_url,
        'videoUrl': video,
        'hasPreviousVersions': False,
    }


def fetch_primegov_meetings(base_url, years=2, timeout=30):
    """Fetch upcoming + the last `years` years of archived meetings.

    Returns (meetings, bodies_seen), or (None, None) if the API is unreachable —
    the caller decides whether to abort (it should: never overwrite good data with
    nothing)."""
    base = base_url.rstrip('/')
    upcoming = _api(base, '/api/v2/PublicPortal/ListUpcomingMeetings', timeout)
    if upcoming is None:
        return None, None  # API down / unreachable — treat as a fetch failure
    rows = list(upcoming)
    this_year = date.today().year
    for yr in range(this_year, this_year - years, -1):
        arch = _api(base, '/api/v2/PublicPortal/ListArchivedMeetings?year=%d' % yr, timeout)
        if arch:
            rows += arch

    meetings, seen = [], set()
    for m in rows:
        rec = _normalize(base, m)
        if not rec or rec['id'] in seen:
            continue
        seen.add(rec['id'])
        meetings.append(rec)
    meetings.sort(key=lambda x: (x['date'], int(x['id']) if x['id'].isdigit() else 0),
                  reverse=True)
    bodies_seen = sorted({m['body'] for m in meetings})
    return meetings, bodies_seen
