#!/usr/bin/env python3
"""Recorded votes from a CivicClerk portal's meeting records.

`lib.civicclerk` lists a portal's meetings and their file links. The same API
also serves each meeting's agenda tree at `/v1/Meetings/<agendaId>`; once a
clerk has finished the minutes, an item carries `minutesItemVotes`, one entry
per motion:

    {motionName, initiatedBy, secondedBy, passFail, yesVotes[], noVotes[],
     abstainVotes[]}

with the voters named. That is the record voters actually want (who moved, who
voted which way), and the portal's PDF minutes do not expose it in any
machine-readable form.

This module is pure parsing plus a fetch loop with an injectable fetcher, so
tests need no network. Output keeps ONLY items that carry a recorded motion:
the full agenda tree is hundreds of items per meeting, mostly headings.

Which places publish votes varies (a survey of 12 portals found them on Carroll,
Forsyth, Douglas, Coweta, Bibb, Lumpkin and Walker; Henry, Cobb, Butts, Columbia
and Oconee had none), so an empty result is normal, never an error.
"""

import datetime as dt
from urllib.parse import quote

from lib.civicclerk import api_base
from lib.http import fetch_json
from lib.meeting_votes import clean_text, names, result_from_tally

# A meeting this recent is re-read every run: minutes (and so votes) land days
# after the meeting. An older meeting that came back with none is not re-read.
RECHECK_DAYS = 60


def _motion(v):
    """One `minutesItemVotes` entry -> motion dict, or None if it carries neither
    a motion nor any voter. CivicClerk's own passFail is deliberately not used
    (see lib.meeting_votes)."""
    yes, no = names(v.get('yesVotes')), names(v.get('noVotes'))
    abstain = names(v.get('abstainVotes'))
    name = clean_text(v.get('motionName'))
    if not (name or yes or no or abstain):
        return None
    return {
        'motion': name,
        'movedBy': clean_text(v.get('initiatedBy')),
        'secondedBy': clean_text(v.get('secondedBy')),
        'result': result_from_tally(yes, no),
        'yes': yes,
        'no': no,
        'abstain': abstain,
        'absent': [],
    }


def extract_items(items, out=None):
    """Walk the agenda tree, returning one record per item that has a motion."""
    out = [] if out is None else out
    for it in items or []:
        motions = [m for m in (_motion(v) for v in it.get('minutesItemVotes') or [])
                   if m]
        if motions:
            ref = it.get('ordinanceNumber') or it.get('resolutionNumber')
            out.append({
                'outline': clean_text(it.get('agendaObjectItemOutlineNumber')),
                'name': clean_text(it.get('agendaObjectItemName')),
                # 0 is the API's "none".
                'reference': str(ref) if ref else None,
                'district': None,
                'motions': motions,
            })
        extract_items(it.get('childItems'), out)
    return out


def list_agenda_events(subdomain, years, fetch=fetch_json, timeout=30, max_pages=80):
    """[(eventId, agendaId, date, body, title)] for events that have an agenda
    record, newest first. Returns None if the first page cannot be read."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=365 * years)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cap = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = '%s/v1/Events?%%24orderby=%s&%%24filter=%s' % (
        api_base(subdomain), quote('startDateTime desc'),
        quote('startDateTime lt %s' % cap))
    events, pages = [], 0
    while url and pages < max_pages:
        data = fetch(url, timeout=timeout, label='%s civicclerk events' % subdomain)
        if data is None:
            return None if pages == 0 else events
        pages += 1
        stop = False
        for e in data.get('value', []):
            sdt = e.get('startDateTime') or ''
            if sdt and sdt < cutoff:
                stop = True
                continue
            if e.get('agendaId') and sdt:
                events.append((str(e.get('id')), e['agendaId'], sdt[:10],
                               (e.get('categoryName') or '').strip() or 'Meeting',
                               (e.get('eventName') or '').strip() or None))
        if stop:
            break
        url = data.get('@odata.nextLink')
    return events


def fetch_votes(subdomain, previous=None, years=2, today=None,
                fetch=fetch_json, timeout=30):
    """Return a list of meeting vote records, or None if the listing failed.

    `previous` is the last published list. A meeting already checked and older
    than RECHECK_DAYS is carried forward untouched (its record is final); a
    recent one, or one never checked, is read. A meeting whose record cannot be
    fetched keeps its previous entry, or is left out to be retried next run -
    a failed read is never published as "no votes"."""
    today = today or dt.date.today()
    events = list_agenda_events(subdomain, years, fetch=fetch, timeout=timeout)
    if events is None:
        return None
    prev = {m['id']: m for m in (previous or [])}
    out = []
    for eid, agenda_id, date, body, title in events:
        old = prev.get(eid)
        age = (today - dt.date.fromisoformat(date)).days
        if old is not None and age > RECHECK_DAYS:
            out.append(old)
            continue
        rec = fetch('%s/v1/Meetings/%s' % (api_base(subdomain), agenda_id),
                    timeout=timeout, label='%s civicclerk meeting %s' % (subdomain, agenda_id))
        if rec is None:
            if old is not None:
                out.append(old)
            continue
        out.append({'id': eid, 'date': date, 'body': body, 'title': title,
                    'items': extract_items(rec.get('items'))})
    return out
