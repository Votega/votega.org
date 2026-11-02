#!/usr/bin/env python3
"""Bake the per-place millage views into _data/millage.json for server rendering.

    python scripts/build_millage_places.py --input assets/data/ga-millage.json

Phase 1b of docs/LOCAL-EXPANSION-SCOPE.md. Reads the statewide dataset that
generate_ga_millage.py (phase 1a) produces, reduces it to the handful of levy
lines each /local/<slug>/ page shows, and writes one small file keyed by place
slug. _includes/entity/place.html renders it through site.data.millage.

WHY _data AND NOT assets/data
-----------------------------
Jekyll exposes _data/*.json to Liquid, so the table is SERVER-RENDERED into the
page like the officials section, rather than fetched like meetings. Property tax
is the highest-search-intent topic in this section, so the figures should be in
the HTML a crawler sees, and the whole statewide reduction is tens of KB.
(_data already holds generated files — executive.json, featured_races.json,
results_updated.json — so this is an established shape, not a new one.)

lib/millage.py itself imports nothing outside the standard library, so
scripts/test_millage_view.py runs in CI; this builder uses pyyaml like every
other builder in scripts/.

WHY THE STATEWIDE FILE IS NOT COMMITTED
---------------------------------------
ga-millage.json is ~1.8MB and belongs in the ga-local-government open-data repo
(scope doc, decision 1). Only this reduction lives in the site repo.

HIDDEN PLACES ARE SKIPPED, like every other consumer of places.yml.
"""

import argparse
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import millage as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES = os.path.join(ROOT, '_data', 'places.yml')
OUT = os.path.join(ROOT, '_data', 'millage.json')


def load_places(path=PLACES):
    """The place registry. Uses pyyaml, like build_entity_pages.py does.

    Only scripts/test_*.py must be import-free (run-script-tests.yml installs no
    packages); lib/millage.py is therefore dependency-free and testable, while
    this build script may use the same yaml every other builder here uses.
    """
    with open(path, encoding='utf-8') as fh:
        return (yaml.safe_load(fh) or {}).get('places', []) or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=os.path.join(ROOT, 'assets', 'data', 'ga-millage.json'))
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--places', default=PLACES)
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit('ERROR: %s not found. Run scripts/generate_ga_millage.py '
                         'first (phase 1a).' % args.input)

    rows, meta = M.load(args.input)
    places = load_places(args.places)
    by_slug = {p['slug']: p for p in places}
    visible = [p for p in places if not p.get('hidden')]
    if not visible:
        raise SystemExit('ERROR: no visible places parsed from %s' % args.places)

    out, missing = {}, []
    for p in visible:
        try:
            view = M.place_view(rows, p, by_slug)
        except M.MillageError as exc:
            raise SystemExit('ERROR: %s\nNothing was written.' % exc)
        if not view:
            missing.append(p['slug'])
            continue
        out[p['slug']] = view

    payload = {
        'metadata': {
            'source': meta.get('source'),
            'sourceIndex': meta.get('sourceIndex'),
            'generatedAt': meta.get('generatedAt'),
            'years': meta.get('years'),
            'places': len(out),
            'note': ('Per-place reduction of the statewide millage dataset. '
                     'M&O rates only. The combined rate is the sum of the lines '
                     'shown and excludes special districts, which depend on the '
                     'parcel. The state rate has been zero throughout.'),
        },
        'places': out,
    }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write('\n')

    full = sum(1 for v in out.values() if len(v['combined']) == len(v['years']))
    print('%d of %d visible places have a millage view' % (len(out), len(visible)))
    print('  %d show a combined rate for every year' % full)
    nocomb = [s for s, v in out.items() if not v['combined']]
    if nocomb:
        print('  no combined rate (reason is carried on the view): %s' % ', '.join(nocomb))
    if missing:
        print('  WARNING: no millage rows joined for: %s' % ', '.join(missing))
    print('wrote %s (%.1f KB)' % (args.out, os.path.getsize(args.out) / 1024.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
