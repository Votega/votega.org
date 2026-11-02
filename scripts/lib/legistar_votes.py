#!/usr/bin/env python3
"""Recorded actions and named votes from a Legistar Web API client.

For each meeting, `Events/<id>/EventItems` lists the agenda items; one with an
`EventItemActionName` ("Approved", "adopt", "Tabled") was acted on, carrying the
mover, seconder and a Pass/Fail flag. `EventItems/<id>/Votes` then names how each
member voted. (`RollCalls`, which lib.legistar uses, is attendance only.)

Maps onto the shared record in lib.meeting_votes, one motion per acted item.
An acted item with no vote rows (a voice vote) is kept with empty lists: the
action happened, only the names were not recorded.

Cost is one request per acted item, 20-90 a meeting, so reads are incremental
and bounded: a meeting already read and older than RECHECK_DAYS is carried
forward, and a first run looks back `months` only.
"""

import datetime as dt
import re
from urllib.parse import quote

from lib.http import fetch_json
from lib.legistar import api_base
from lib.meeting_votes import bucket, clean_text, result_from_flag

RECHECK_DAYS = 60
# An acted item with no names and no Pass/Fail is usually clerical bookkeeping
# ("Accepted to the BOC agenda and assigned", "Read into the record": 900 of
# DeKalb's 2,800). Kept only when the action is a decision a voter would care
# about, even if the source recorded no names for it.
_DECISION_RE = re.compile(
    r'^(approv|adopt|den|pass|fail|defer|hold|held|table|withdr|reject|postpone|continu)',
    re.I)
_DISTRICT_RE = re.compile(r'^\s*Commission District\(s\):\s*([^\r\n]*)[\r\n]+(.*)$', re.S)


def split_title(title):
    """DeKalb prefixes titles with "Commission District(s): 3 & 7" on its own
    line. -> (district or None, title without it)."""
    m = _DISTRICT_RE.match(title or '')
    if m:
        return clean_text(m.group(1)), clean_text(m.group(2))
    return None, clean_text(title)


def motion_from(item, votes):
    """EventItem + its Votes rows -> motion dict."""
    cols = {'yes': [], 'no': [], 'abstain': [], 'absent': []}
    for v in votes or []:
        key = bucket(v.get('VoteValueName'))
        who = clean_text(v.get('VotePersonName'))
        if key and who:
            cols[key].append(who)
    return {
        'motion': clean_text(item.get('EventItemActionName')),
        'movedBy': clean_text(item.get('EventItemMover')),
        'secondedBy': clean_text(item.get('EventItemSeconder')),
        'result': result_from_flag(item.get('EventItemPassedFlagName')),
        'yes': cols['yes'], 'no': cols['no'],
        'abstain': cols['abstain'], 'absent': cols['absent'],
    }


def read_event(client, event, fetch=fetch_json, timeout=40):
    """-> list of item records for one meeting, or None if any read failed
    (a partial meeting is never published as complete)."""
    base = api_base(client)
    items = fetch('%s/Events/%s/EventItems' % (base, event['EventId']),
                  timeout=timeout, label='%s event %s items' % (client, event['EventId']))
    if not isinstance(items, list):
        return None
    out = []
    for it in items:
        if not clean_text(it.get('EventItemActionName')):
            continue
        votes = fetch('%s/EventItems/%s/Votes' % (base, it['EventItemId']),
                      timeout=timeout, label='%s item %s votes' % (client, it['EventItemId']))
        if not isinstance(votes, list):
            return None
        motion = motion_from(it, votes)
        if not (motion['result'] or motion['yes'] or motion['no'] or motion['abstain']
                or _DECISION_RE.match(motion['motion'] or '')):
            continue
        district, name = split_title(it.get('EventItemTitle'))
        out.append({
            'outline': clean_text(it.get('EventItemAgendaNumber')),
            'name': name,
            'reference': clean_text(it.get('EventItemMatterFile')),
            'district': district,
            'motions': [motion],
        })
    return out


def fetch_votes(client, previous=None, months=12, today=None, fetch=fetch_json,
                timeout=40):
    """Meeting vote records for a Legistar client, or None if the event listing
    failed. Same carry-forward rules as lib.civicclerk_votes.fetch_votes."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=int(months * 30.5))).isoformat()
    url = '%s/Events?%%24orderby=%s&%%24filter=%s' % (
        api_base(client), quote('EventDate desc'),
        quote("EventDate ge datetime'%s' and EventDate lt datetime'%s'"
              % (since, (today + dt.timedelta(days=1)).isoformat())))
    events = fetch(url, timeout=timeout, label='%s events' % client)
    if not isinstance(events, list):
        return None
    prev = {m['id']: m for m in (previous or [])}
    out = []
    for e in events:
        eid, date = str(e['EventId']), (e.get('EventDate') or '')[:10]
        if not date:
            continue
        old = prev.get(eid)
        if old is not None and (today - dt.date.fromisoformat(date)).days > RECHECK_DAYS:
            out.append(old)
            continue
        items = read_event(client, e, fetch=fetch, timeout=timeout)
        if items is None:
            if old is not None:
                out.append(old)
            continue
        out.append({'id': eid, 'date': date,
                    'body': clean_text(e.get('EventBodyName')) or 'Meeting',
                    'title': clean_text(e.get('EventComment')),
                    'items': items})
    return out
