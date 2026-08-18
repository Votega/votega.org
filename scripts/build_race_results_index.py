#!/usr/bin/env python3
"""
Build assets/data/race-results-index.json — for each race in races.json, the
results of every election this cycle that has already produced votes.

This powers the "Earlier This Cycle" tab on race.html, so a race page can show
how its candidates actually performed in the primary/runoff leading up to the
election currently being fought.

Why a build-time index rather than a client-side join:
  * The results JSONs live in _data/, which Jekyll does not serve as static
    files — only the results *layout* can read them, via Liquid.
  * Matching a race to its contest is fuzzy at the edges (office-label drift,
    name-format drift). Doing it here means a failed match shows up in this
    script's output instead of silently rendering a race as though its
    candidates never ran.

Election metadata is read from the results page stubs' front matter (the same
files that drive /results/), so adding an election needs no change here.

Placeholder pages — every candidate at 0 votes, e.g. the pre-election general —
are skipped: a placeholder is not a result.

Usage:
    python scripts/build_race_results_index.py
"""

import glob
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, '..')
RESULTS_DIR = os.path.join(ROOT, '_data', 'election_results')
OUT_PATH = os.path.join(ROOT, 'assets', 'data', 'race-results-index.json')

FRONT_MATTER = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.S)


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def norm_name(s):
    """Match the normalization used by _layouts/election_results.html."""
    s = (s or '').lower()
    s = re.sub(r'["“”\'’]', '', s)
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\.?\b', ' ', s)
    s = re.sub(r'\b(dr|mr|mrs|ms)\.?\b', ' ', s)
    s = re.sub(r'\([^)]*\)', ' ', s)          # strip "(Dem)" suffixes
    s = re.sub(r'[^a-z\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def name_key(s):
    """Surname + first initial — tolerant of middle-name drift between sources."""
    t = norm_name(s).split()
    if not t:
        return None
    return (t[-1], t[0][0])


def discover_elections():
    """Read every results page stub's front matter; newest last."""
    elections = []
    for path in sorted(glob.glob(os.path.join(ROOT, '*.html'))):
        with open(path, encoding='utf-8') as f:
            head = f.read(4000)
        m = FRONT_MATTER.match(head)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if fm.get('layout') != 'election_results' or not fm.get('results_data'):
            continue
        data_path = os.path.join(RESULTS_DIR, fm['results_data'] + '.json')
        if not os.path.exists(data_path):
            print(f"  ! {os.path.basename(path)}: no data file for "
                  f"'{fm['results_data']}' — skipped")
            continue
        elections.append({
            'key': fm['results_data'],
            'label': fm.get('heading') or fm.get('title') or fm['results_data'],
            'subtitle': fm.get('subtitle'),
            'date': str(fm.get('election_date') or ''),
            'status': fm.get('status') or 'unofficial',
            'url': fm.get('permalink') or '',
            'sections': load_json(data_path),
        })
    elections.sort(key=lambda e: e['date'])
    return elections


def has_votes(sections):
    return any(c.get('totalVotes')
               for sec in sections for r in sec.get('races', []) for c in r.get('contests', []))


def index_contests(sections):
    """(section_id, office) -> contests, plus a name-key -> entries fallback."""
    by_office = {}
    by_name = {}
    by_office_norm = {}
    for sec in sections:
        for race in sec.get('races', []):
            entry = (sec['id'], race['office'], race['contests'])
            by_office[(sec['id'], race['office'])] = race['contests']
            by_office_norm.setdefault(
                (sec['id'], norm_office(race['office'])), []).append(race['contests'])
            for contest in race['contests']:
                for cand in contest.get('candidates', []):
                    k = name_key(cand.get('name'))
                    if k:
                        by_name.setdefault(k, []).append(entry)
    return by_office, by_name, by_office_norm


# ── race → results office label ────────────────────────────────────────────────
STATEWIDE_CHAMBER_MAP = {
    'U.S. Senate': ('statewide', 'US Senate'),
    'Governor': ('statewide', 'Governor'),
    'Lieutenant Governor': ('statewide', 'Lieutenant Governor'),
    'Secretary of State': ('statewide', 'Secretary of State'),
    'Attorney General': ('statewide', 'Attorney General'),
    'Commissioner of Agriculture': ('statewide', 'Commissioner of Agriculture'),
    'Insurance & Fire Safety Commissioner': ('statewide', 'Commissioner of Insurance'),
    'State School Superintendent': ('statewide', 'State School Superintendent'),
    'Labor Commissioner': ('statewide', 'Commissioner of Labor'),
}


def office_keys(race):
    """Candidate (section, office) pairs this race might be filed under."""
    chamber = race.get('chamber')
    district = race.get('district')
    seat = race.get('seat', '')
    if chamber in STATEWIDE_CHAMBER_MAP:
        return [STATEWIDE_CHAMBER_MAP[chamber]]
    if chamber == 'Public Service Commissioner':
        return [('statewide', f'PSC - District {district}')]
    if chamber == 'U.S. House':
        return [('us-house', f'District {district}')]
    if chamber == 'Georgia State Senate':
        return [('state-senate', f'District {district}')]
    if chamber == 'Georgia House of Representatives':
        return [('state-house', f'District {district}')]
    if chamber == 'Superior Court':
        return [('courts', f"Superior Court - {race.get('circuit', '')} ({seat})")]
    if chamber == 'Georgia Court of Appeals':
        return [('courts', f'Court of Appeals of Georgia ({seat})')]
    if chamber == 'Supreme Court of Georgia':
        return [('courts', f'Supreme Court of Georgia ({seat})')]
    return []


def race_name_keys(race):
    keys = set()
    for phase in (race.get('phases') or {}).values():
        groups = list((phase.get('ballots') or {}).values())
        if phase.get('candidates'):
            groups.append(phase['candidates'])
        for group in groups:
            for cand in group or []:
                k = name_key(cand.get('name'))
                if k:
                    keys.add(k)
    return keys


def norm_office(label):
    """Office label with punctuation and generational suffixes removed, so
    'Superior Court - Alapaha Judicial Circuit (Perryman, III)' and our
    '... (Perryman)' converge."""
    s = (label or '').lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b', ' ', s)
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def find_contests(race, by_office, by_name, by_office_norm):
    """Structural match first; fall back to candidate-name overlap."""
    for key in office_keys(race):
        if key in by_office:
            return by_office[key], 'office'

    # Same office, punctuation/suffix drift. Only accepted when exactly one
    # results office normalizes to this key, so near-identical judicial seats
    # never collapse into each other.
    for sec_id, office in office_keys(race):
        hits = by_office_norm.get((sec_id, norm_office(office)), [])
        if len(hits) == 1:
            return hits[0], 'office~'

    # Fallback: the office label drifted (e.g. judicial seat suffixes). Pick the
    # contest group sharing the most candidates with this race, requiring a real
    # overlap so unrelated races never borrow each other's numbers.
    my_keys = race_name_keys(race)
    if not my_keys:
        return None, None
    wanted_sections = {s for s, _ in office_keys(race)} or None
    best, best_score = None, 0
    seen = set()
    for k in my_keys:
        for sec_id, office, contests in by_name.get(k, []):
            if wanted_sections and sec_id not in wanted_sections:
                continue
            ident = (sec_id, office)
            if ident in seen:
                continue
            seen.add(ident)
            names = {name_key(c.get('name'))
                     for con in contests for c in con.get('candidates', [])}
            score = len(my_keys & names)
            if score > best_score:
                best, best_score = contests, score
    if best and best_score >= 2:
        return best, 'name'
    return None, None


def slim(contests):
    return [{
        'party': c.get('party', 'np'),
        'totalVotes': c.get('totalVotes', 0),
        'candidates': [{'name': cd['name'], 'votes': cd.get('votes', 0),
                        'incumbent': bool(cd.get('incumbent'))}
                       for cd in c.get('candidates', [])],
    } for c in contests if c.get('totalVotes')]


def main():
    races_data = load_json(os.path.join(ROOT, 'assets', 'data', 'races.json'))
    races = races_data.get('races', [])

    print('Discovering results pages...')
    elections = discover_elections()
    live = []
    for e in elections:
        if has_votes(e['sections']):
            live.append(e)
            print(f"  {e['date']}  {e['key']}  ({e['status']})")
        else:
            print(f"  {e['date']}  {e['key']}  — no votes yet, skipped")
    if not live:
        sys.exit('No elections with results found.')

    for e in live:
        e['by_office'], e['by_name'], e['by_office_norm'] = index_contests(e['sections'])

    # Two races can share an office label — GA-13's full-term seat and the
    # special election filling the remainder of the same seat both resolve to
    # ('us-house', 'District 13'). For those, an election only counts if the race
    # actually has a phase on that date, which is what separates the May primary
    # from the July special. The check is limited to shared keys on purpose:
    # 14 races reached the June runoff without carrying a `runoff` phase in
    # races.json, and requiring a date match everywhere would discard them.
    key_owners = {}
    for race in races:
        for key in office_keys(race):
            key_owners.setdefault(key, []).append(race['id'])
    contested_keys = {k for k, v in key_owners.items() if len(v) > 1}
    if contested_keys:
        print('\nShared office labels (date-disambiguated): '
              + ', '.join(f'{o}' for _, o in sorted(contested_keys)))

    index = {}
    stats = {'office': 0, 'office~': 0, 'name': 0}
    unmatched = []
    for race in races:
        ambiguous = any(k in contested_keys for k in office_keys(race))
        phase_dates = {str(p.get('electionDate') or '')
                       for p in (race.get('phases') or {}).values()}
        entries = []
        for e in live:
            if ambiguous and e['date'] not in phase_dates:
                continue
            contests, how = find_contests(race, e['by_office'], e['by_name'], e['by_office_norm'])
            if not contests:
                continue
            trimmed = slim(contests)
            if not trimmed:
                continue
            stats[how] += 1
            entries.append({
                'key': e['key'], 'label': e['label'], 'subtitle': e['subtitle'],
                'date': e['date'], 'status': e['status'], 'url': e['url'],
                'contests': trimmed,
            })
        if entries:
            index[race['id']] = entries
        elif race.get('cycle'):
            unmatched.append(race['id'])

    out = {
        'metadata': {
            'generatedAt': __import__('datetime').date.today().isoformat(),
            'source': 'Georgia Secretary of State results, joined to races.json',
            'elections': [{'key': e['key'], 'date': e['date'], 'status': e['status']} for e in live],
            'racesWithResults': len(index),
        },
        'races': index,
    }
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    print(f"\nMatched — exact office: {stats['office']}, "
          f"normalized office: {stats['office~']}, candidate names: {stats['name']}")
    print(f"Races with results: {len(index)} of {len(races)}")
    print(f"Races with none: {len(unmatched)}")
    for rid in unmatched[:15]:
        print(f"    {rid}")
    if len(unmatched) > 15:
        print(f"    ... and {len(unmatched) - 15} more")
    print(f"Wrote: {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes)")


if __name__ == '__main__':
    main()
