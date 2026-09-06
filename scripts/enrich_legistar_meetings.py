#!/usr/bin/env python3
"""PROTOTYPE: mine Legistar meetings for subject areas + per-member votes.

Demonstrates the "rich dataset" on the Legistar counties (Fulton, DeKalb) using
STRUCTURED API data only — no OCR. For recent meetings it pulls the structured
agenda items (`EventItems`), tags each by subject with keyword rules (land use,
rezoning, data center, millage, …), and for the voted land-use items pulls the
per-member roll call (`EventItems/{id}/RollCalls`). Output is a sidecar
`assets/data/local-<slug>-meetings-enriched.json` plus a console demo of a
flagged, sourced example.

This is a proof of signal, not a production pipeline: scope is bounded to a recent
window, and it only roll-calls the land-use items (where the civic interest is).

Usage:
    python scripts/enrich_legistar_meetings.py --slug dekalb [--limit 20] [--months 8]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.legistar import fetch_events, fetch_event_items, fetch_rollcalls  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')

# Subject taxonomy — keyword rules over the item title + matter name/type.
TOPIC_RULES = {
    'data-center':        ['data center', 'data centre', 'hyperscale', 'data-center'],
    'rezoning':           ['rezon'],
    'special-land-use':   ['special land use', 'special-use', 'slup', 'conditional use',
                           'land use permit'],
    'variance':           ['variance'],
    'annexation':         ['annex'],
    'development':        ['apartment', 'subdivision', 'warehouse', 'mixed use',
                           'mixed-use', 'townhome', 'multifamily', 'multi-family'],
    'comprehensive-plan': ['comprehensive plan', 'future land use', 'land use plan'],
    'millage-budget':     ['millage', 'ad valorem', 'tax rate', 'budget', 'fiscal year'],
    'contract':           ['contract', 'procurement', 'task order', 'award of', 'purchase order'],
    'appointment':        ['appoint', 'reappoint'],
}
# Subjects that make an item "land use" (drives the card flag).
LAND_USE = {'data-center', 'rezoning', 'special-land-use', 'variance',
            'annexation', 'development', 'comprehensive-plan'}

_TAG = re.compile(r'<[^>]+>')
_DISTRICTS = re.compile(r'Commission District\(s\):\s*([^\n<]+)', re.I)


def _clean(s):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', s or '')).strip()


def classify(text):
    t = text.lower()
    return [tag for tag, kws in TOPIC_RULES.items() if any(k in t for k in kws)]


def legistar_places(slug=None):
    with open(REGISTRY, encoding='utf-8') as f:
        places = (yaml.safe_load(f) or {}).get('places', [])
    out = []
    for p in places:
        if p.get('hidden'):
            continue
        cfg = (p.get('domains') or {}).get('meetings') or {}
        if cfg.get('platform') != 'legistar':
            continue
        if slug and p['slug'] != slug:
            continue
        out.append((p, cfg['client']))
    if slug and not out:
        sys.exit('%r is not a (visible) legistar place' % slug)
    return out


def enrich_event(client, e):
    items = fetch_event_items(client, e.get('EventId'))
    topics = {}
    land_use_items = []
    for it in items:
        name = _clean(it.get('EventItemTitle') or it.get('EventItemMatterName') or '')
        blob = ' '.join(filter(None, [name, it.get('EventItemMatterType') or '']))
        tags = classify(blob)
        for tg in tags:
            topics[tg] = topics.get(tg, 0) + 1
        if set(tags) & LAND_USE:
            rec = {
                'title': name[:180],
                'matterFile': it.get('EventItemMatterFile'),
                'matterType': it.get('EventItemMatterType'),
                'tags': tags,
                'passed': it.get('EventItemPassedFlagName'),
                'action': it.get('EventItemActionName'),
                'mover': it.get('EventItemMover'),
            }
            m = _DISTRICTS.search(name)
            if m:
                rec['districts'] = m.group(1).strip().rstrip('.')
            if it.get('EventItemPassedFlagName') and it.get('EventItemRollCallFlag'):
                votes = fetch_rollcalls(client, it.get('EventItemId'))
                rec['votes'] = {_clean(v.get('RollCallPersonName')): v.get('RollCallValueName')
                                for v in votes if v.get('RollCallPersonName')}
            land_use_items.append(rec)

    flags = []
    if any(t in topics for t in LAND_USE):
        flags.append('land-use')
    if 'data-center' in topics:
        flags.append('data-center')
    if 'millage-budget' in topics:
        flags.append('millage-budget')

    return {
        'eventId': e.get('EventId'),
        'date': (e.get('EventDate') or '')[:10],
        'body': e.get('EventBodyName'),
        'sourceUrl': e.get('EventInSiteURL'),
        'itemCount': len(items),
        'topics': topics,
        'flags': flags,
        'landUseItems': land_use_items,
    }


def build_summary(enriched):
    """Roll per-meeting enrichment up into a place-level summary for the UI."""
    topic_totals = {}
    dc_items = {}
    flags = set()
    last = None
    for m in enriched:
        flags.update(m['flags'])
        if m['date'] and (last is None or m['date'] > last):
            last = m['date']
        for tg, n in m['topics'].items():
            topic_totals[tg] = topic_totals.get(tg, 0) + n
        for it in m['landUseItems']:
            if 'data-center' in it['tags']:
                dc_items.setdefault(it['title'], {'title': it['title'],
                                                  'date': m['date'], 'sourceUrl': m['sourceUrl']})
    return {
        'flags': sorted(flags),
        'lastActivity': last,
        'topicTotals': topic_totals,
        'dataCenterItems': list(dc_items.values()),
        'landUseMeetings': sum(1 for m in enriched if 'land-use' in m['flags']),
    }


def write_flags_file(updates):
    """Merge per-place flag summaries into the single hub file local-flags.json."""
    path = os.path.join(OUT_DIR, 'local-flags.json')
    doc = {'metadata': {}, 'places': {}}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except (ValueError, OSError):
            pass
    doc.setdefault('places', {}).update(updates)
    doc['metadata'] = {'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print('  Wrote %s' % path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='one place (default: all Legistar places)')
    ap.add_argument('--limit', type=int, default=25, help='recent meetings to enrich')
    ap.add_argument('--months', type=int, default=8, help='look-back window')
    args = ap.parse_args()

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')
    os.makedirs(OUT_DIR, exist_ok=True)
    flag_updates = {}

    for place, client in legistar_places(args.slug):
        slug = place['slug']
        print('Enriching %s (legistar %r) since %s ...' % (place['name'], client, since))
        events = [e for e in fetch_events(client, since) if e.get('EventAgendaFile')][:args.limit]
        print('  processing %d meeting(s)...' % len(events))
        enriched = [enrich_event(client, e) for e in events]
        summary = build_summary(enriched)

        out = {
            'metadata': {
                'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'source': '%s (Legistar structured API)' % place['name'],
                'place': place['name'],
                'count': len(enriched),
            },
            'summary': summary,
            'meetings': enriched,
        }
        with open(os.path.join(OUT_DIR, 'local-%s-meetings-enriched.json' % slug),
                  'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        flag_updates[slug] = {
            'flags': summary['flags'],
            'dataCenterCount': len(summary['dataCenterItems']),
            'lastActivity': summary['lastActivity'],
        }
        print('  %s: flags=%s, %d data-center item(s)'
              % (slug, ','.join(summary['flags']) or '-', len(summary['dataCenterItems'])))

    write_flags_file(flag_updates)


if __name__ == '__main__':
    main()


if __name__ == '__main__':
    main()
