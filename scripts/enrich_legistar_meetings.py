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

sys.path.insert(0, os.path.dirname(__file__))
from lib.legistar import fetch_events, fetch_event_items, fetch_rollcalls  # noqa: E402
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.meeting_topics import (  # noqa: E402
    LAND_USE, classify, matched_terms, topic_flags, build_summary, flag_entry,
    topic_excerpts,
)
from lib.enrich_runner import (  # noqa: E402
    run_places, run_meetings, report, too_lossy, PlaceOutcome,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, '_data', 'places.yml')
OUT_DIR = os.path.join(ROOT, 'assets', 'data')

_TAG = re.compile(r'<[^>]+>')
_DISTRICTS = re.compile(r'Commission District\(s\):\s*([^\n<]+)', re.I)


def _clean(s):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', s or '')).strip()


def legistar_places(slug=None):
    """(place, client) for every visible Legistar place.

    `yaml` is imported HERE, not at module scope, and that placement is load-
    bearing: it is this module's only third-party dependency and the only place
    that needs it. scripts/test_enrich_*.py import this module, and
    run-script-tests.yml deliberately installs no pip packages — so a module-level
    `import yaml` made those suites fail with ModuleNotFoundError while the
    invariants they check were fine (see c01efecc for the same fix). Keep it local.
    """
    import yaml  # noqa: PLC0415 - see the docstring above
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
        client = cfg.get('client')
        if not client:
            # A legistar place with no `client` is mis-configured (or mid-onboarding);
            # skip it rather than crash the whole enrichment run.
            print('  skip %s: legistar platform but no `client` configured'
                  % p['slug'], file=sys.stderr)
            continue
        out.append((p, client))
    if slug and not out:
        sys.exit('%r is not a (visible) legistar place' % slug)
    return out


def enrich_event(client, e):
    items = fetch_event_items(client, e.get('EventId'))
    topics = {}
    terms = set()
    excerpts = {}          # {tag: {term, excerpt}} — first matching item per tag
    land_use_items = []
    for it in items:
        name = _clean(it.get('EventItemTitle') or it.get('EventItemMatterName') or '')
        blob = ' '.join(filter(None, [name, it.get('EventItemMatterType') or '']))
        tags = classify(blob)
        terms.update(matched_terms(blob))
        # Excerpt is the matching agenda item's own text (structured, so no OCR /
        # public-comment-roster noise). First item to hit a tag wins; a later item
        # with a stronger ALPR term (named vendor / spelled-out) is preferred.
        for tag, ex in topic_excerpts(blob, tags).items():
            # A Legistar EventItem IS an agenda item — there is no surrounding
            # agenda text for classify_context to read a section header from, so an
            # item with no explicit action verb comes back 'unknown'. Coerce that to
            # agenda-action (structured items are business, not public comment).
            if ex.get('context') == 'unknown':
                ex['context'] = 'agenda-action'
            cur = excerpts.get(tag)
            if cur is None:
                excerpts[tag] = ex
            elif tag == 'alpr' and cur['term'] == 'alpr' and ex['term'] != 'alpr':
                excerpts[tag] = ex
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
        'matchedTerms': sorted(terms),
        'topicExcerpts': excerpts,
        'flags': topic_flags(topics),
        'dataCenterItems': dc_items,
        'landUseItems': land_use_items,
    }


def load_cache(slug):
    """Prior enriched sidecar indexed by event id.

    Unlike the Granicus and OCR enrichers, this is NOT an incremental cache —
    the Legistar API is structured and cheap, so every event in the window is
    re-read on every run. It is read only as the per-meeting failure fallback:
    an event whose items or roll calls raise keeps the record an earlier run
    gave it rather than vanishing from the place page. See lib/enrich_runner.py.
    """
    path = os.path.join(OUT_DIR, 'local-%s-meetings-enriched.json' % slug)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            prior = json.load(f)
    except (ValueError, OSError):
        return {}
    return {m['eventId']: m for m in prior.get('meetings', []) if m.get('eventId')}


def enrich_place(place, client, since, limit):
    """Enrich one Legistar place: write its sidecar, return its flag entry.

    Returns None to leave the place's committed data untouched (nothing in the
    window) — or a PlaceOutcome when events inside the window were lost, so the
    run still fails even though the sidecar was written. Raising is reserved for
    the unexpected, which lib.enrich_runner contains to this one place.
    """
    slug = place['slug']
    print('Enriching %s (legistar %r) since %s ...' % (place['name'], client, since))
    events = [e for e in fetch_events(client, since) if e.get('EventAgendaFile')][:limit]
    print('  processing %d meeting(s)...' % len(events))
    # Per-MEETING boundary: one event whose items or roll calls raise costs that
    # event, not this place's whole window, and it falls back to its prior record.
    enriched, lost = run_meetings(
        slug, events, lambda e: enrich_event(client, e),
        meeting_id=lambda e: e.get('EventId'), cache=load_cache(slug))

    # Guard like the other steps: never overwrite a good sidecar / good flags
    # with nothing. A zero-meeting result means the API was unreachable or the
    # window was empty, not that the place stopped flagging data centers.
    if not enriched:
        print('  WARNING: 0 meetings for %s — leaving existing enriched data intact' % slug)
        return PlaceOutcome(None, lost)
    # ... nor with a window short of events we simply could not read.
    if too_lossy(slug, lost, len(events)):
        return PlaceOutcome(None, lost)

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
    write_json_atomic(os.path.join(OUT_DIR, 'local-%s-meetings-enriched.json' % slug),
                      out, indent=1)
    print('  %s: flags=%s, %d data-center item(s)'
          % (slug, ','.join(summary['flags']) or '-', len(summary['dataCenterItems'])))
    return PlaceOutcome(flag_entry(summary), lost)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slug', help='one place (default: all Legistar places)')
    ap.add_argument('--limit', type=int, default=25, help='recent meetings to enrich')
    ap.add_argument('--months', type=int, default=8, help='look-back window')
    args = ap.parse_args()

    since = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).strftime('%Y-%m-%d')
    os.makedirs(OUT_DIR, exist_ok=True)

    # One place's failure is contained to that place, and local-flags.json is
    # written as each place finishes — see lib/enrich_runner.py for the run this
    # cost us.
    done, failed = run_places(
        legistar_places(args.slug), OUT_DIR,
        lambda place, client: enrich_place(place, client, since, args.limit))
    sys.exit(report(done, failed, OUT_DIR))


if __name__ == '__main__':
    main()
