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
from lib.meeting_topics import (  # noqa: E402
    LAND_USE, classify, topic_flags, build_summary, flag_entry, write_flags_file,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')

_TAG = re.compile(r'<[^>]+>')
_DISTRICTS = re.compile(r'Commission District\(s\):\s*([^\n<]+)', re.I)


def _clean(s):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', s or '')).strip()


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

    date = (e.get('EventDate') or '')[:10]
    source_url = e.get('EventInSiteURL')
    # Meeting-level data-center list (title-per-item) — the shared rollup reads
    # this key from every enricher, so a Legistar and an OCR place produce the
    # same summary shape. Each entry links its source.
    dc_items = [{'title': it['title'], 'date': date, 'sourceUrl': source_url}
                for it in land_use_items if 'data-center' in it['tags']]

    return {
        'eventId': e.get('EventId'),
        'date': date,
        'body': e.get('EventBodyName'),
        'sourceUrl': source_url,
        'itemCount': len(items),
        'topics': topics,
        'flags': topic_flags(topics),
        'dataCenterItems': dc_items,
        'landUseItems': land_use_items,
    }


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

        # Guard like the other steps: never overwrite a good sidecar / good flags
        # with nothing. A zero-meeting result means the API was unreachable or the
        # window was empty, not that the place stopped flagging data centers.
        if not enriched:
            print('  WARNING: 0 meetings for %s — leaving existing enriched data intact' % slug)
            continue

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
        flag_updates[slug] = flag_entry(summary)
        print('  %s: flags=%s, %d data-center item(s)'
              % (slug, ','.join(summary['flags']) or '-', len(summary['dataCenterItems'])))

    if flag_updates:
        print('  Wrote %s' % write_flags_file(OUT_DIR, flag_updates))


if __name__ == '__main__':
    main()
