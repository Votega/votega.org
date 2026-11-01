#!/usr/bin/env python3
"""Top up a CivicPlus Agenda Center place from its RSS feed when the site itself is blocked.

Newton County's Cloudflare protection 403s `/AgendaCenter` and every agenda PDF, but
`/RSSFeed.aspx?ModID=65&CID=All-0` still answers. The feed is RECENT-ONLY (a couple of
items) and carries no minutes, so it can never replace the full scrape; what it can do is
tell us a new agenda was posted, between the human allowlist request and the day it works.

An item gives a title ("10/27/26 Planning Commission Agenda"), a post date and a link to
`/AgendaCenter/PreviousVersions/<id>`. The agenda's own address is rebuilt the way the
Agenda Center builds it, `/AgendaCenter/ViewFile/Agenda/_MMDDYYYY-<id>` (verified against
the committed records, e.g. id 1006 on 2026-09-29 -> `_09292026-1006`).

Nothing is guessed:
  * the MEETING DATE must be written in the title; an item without one is skipped (the
    post date is when it was uploaded, not when the body meets);
  * the BODY comes from the registry's `rss_bodies` rules (`match` substring -> label); an
    item matching no rule is skipped and reported;
  * a record already in the file is never touched (the full scrape's version wins).

Import from a generator in scripts/:
    from lib.civicplus_rss import supplement
"""

import re
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime

UA = 'Mozilla/5.0 (votega.org meeting-list)'
_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b')
_ID = re.compile(r'/PreviousVersions/(\d+)')


def parse_feed(xml_text):
    """[{title, link, id, posted}] from the RSS text; raises ValueError on a non-feed."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as e:
        raise ValueError('not an RSS feed: %s' % e)
    items = []
    for it in root.iter('item'):
        link = (it.findtext('link') or '').strip()
        m = _ID.search(link)
        posted = None
        try:
            posted = parsedate_to_datetime(it.findtext('pubDate') or '').date().isoformat()
        except (TypeError, ValueError):
            pass
        items.append({'title': (it.findtext('title') or '').strip(), 'link': link,
                      'id': m.group(1) if m else None, 'posted': posted})
    return items


def title_date(title):
    m = _DATE.search(title or '')
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def body_for(title, rules):
    t = (title or '').lower()
    for r in rules or []:
        if str(r['match']).lower() in t:
            return r['label']
    return None


def to_meeting(item, base_url, rules):
    """(meeting, None) or (None, reason)."""
    if not item['id']:
        return None, 'no agenda id in the link'
    d = title_date(item['title'])
    if not d:
        return None, 'no meeting date in the title'
    body = body_for(item['title'], rules)
    if not body:
        return None, 'no rss_bodies rule matches'
    return {
        'body': body, 'date': d.isoformat(), 'id': item['id'], 'title': item['title'],
        'agendaUrl': '%s/AgendaCenter/ViewFile/Agenda/_%s-%s' % (base_url.rstrip('/'),
                                                              d.strftime('%m%d%Y'), item['id']),
        'minutesUrl': None, 'videoUrl': None, 'hasPreviousVersions': False,
    }, None


def supplement(previous, feed_text, base_url, rules):
    """(meetings, added, skipped) - `previous` plus any feed item it does not already hold."""
    have = {str(m.get('id')) for m in previous}
    meetings, added, skipped = list(previous), [], []
    for item in parse_feed(feed_text):
        if item['id'] and item['id'] in have:
            continue
        m, why = to_meeting(item, base_url, rules)
        if m is None:
            skipped.append((item['title'], why))
            continue
        have.add(m['id'])
        meetings.append(m)
        added.append(m)
    meetings.sort(key=lambda m: (m['date'], m['id']), reverse=True)
    return meetings, added, skipped
