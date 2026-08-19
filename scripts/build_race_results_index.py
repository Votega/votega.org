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
    """(section_id, office) -> contests, plus name-key and surname fallbacks."""
    by_office = {}
    by_name = {}
    by_office_norm = {}
    by_surname = {}
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
                        # Surname alone, at contest granularity — the last resort
                        # when the first initial itself drifts.
                        by_surname.setdefault(k[0], []).append(
                            (sec['id'], race['office'], contest))
    return by_office, by_name, by_office_norm, by_surname


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


def contest_names(contest):
    return {name_key(c.get('name')) for c in contest.get('candidates', [])}


def narrow_group(contests, my_keys):
    """Drop contests in a group that share no candidate with this race.

    A group is normally the party primaries for a single seat, and a race's
    candidates appear across all of them, so nothing is dropped. Gwinnett files
    all five of its Superior Court seats under one office label with no seat
    suffix, though, so that 'group' is five unrelated judges. Without this,
    whichever race matched inherited the other four judges' vote totals — one
    Gwinnett race rendered 130,118 votes for Tracie Cason as its own.
    See CODEBASE-REVIEW-2026-08-18.md finding 3.1.
    """
    if not my_keys or len(contests) <= 1:
        return contests
    hits = [c for c in contests if my_keys & contest_names(c)]
    # No overlap at all: leave the group alone rather than emit nothing — the
    # race may legitimately have a different ballot than the contest recorded.
    return hits or contests


def find_contests(race, by_office, by_name, by_office_norm, by_surname, report=None):
    """Structural match first; fall back to candidate-name overlap."""
    my_keys = race_name_keys(race)

    # An exact office label identifies the seat, so its group is authoritative:
    # every contest in it belongs to this race even when a candidate's name
    # drifts between sources (races.json 'James E Lumsden' vs the state's
    # 'Eddie Lumsden'). Narrowing here would silently drop that party's result.
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

    # Fallback: the office label drifted (e.g. judicial seat suffixes, or a
    # circuit that files every seat under one heading). Score each candidate
    # group *after* narrowing it to the contests this race actually appears in,
    # so a five-seat group competes on the one seat that matches.
    if not my_keys:
        return None, None
    wanted_sections = {s for s, _ in office_keys(race)} or None
    scored, seen = [], set()
    for k in my_keys:
        for sec_id, office, contests in by_name.get(k, []):
            if wanted_sections and sec_id not in wanted_sections:
                continue
            ident = (sec_id, office)
            if ident in seen:
                continue
            seen.add(ident)
            narrowed = narrow_group(contests, my_keys)
            names = set().union(*(contest_names(c) for c in narrowed)) if narrowed else set()
            score = len(my_keys & names)
            if score:
                scored.append((score, ident, narrowed))

    if not scored:
        return find_by_surname(race, by_surname, report)

    scored.sort(key=lambda t: -t[0])
    top = scored[0][0]
    contenders = [s for s in scored if s[0] == top]

    # A tie means two offices fit this race equally well — (surname, initial) is
    # not unique across a section (courts has a Robert Lane and a Roger Lane).
    # Report it rather than taking whichever sorted first.
    if len(contenders) > 1:
        if report is not None:
            report.append((race['id'], 'ambiguous',
                           f"{top} name(s) matched {len(contenders)} offices equally: "
                           + ', '.join(o for _, (_, o), _ in contenders[:3])))
        return None, None

    # Accept a strong overlap, or a weak one that accounts for the race's whole
    # ballot — an uncontested judicial seat has exactly one name to match on, and
    # requiring two would leave every such race with no results at all.
    if top >= 2 or top == len(my_keys):
        return contenders[0][2], 'name'

    if report is not None:
        report.append((race['id'], 'weak',
                       f"best office '{contenders[0][1][1]}' matched {top} of "
                       f"{len(my_keys)} candidate(s) — below the bar"))
    return find_by_surname(race, by_surname, report)


def find_by_surname(race, by_surname, report=None):
    """Last resort: surname alone, for a one-candidate seat.

    `name_key` is surname plus first initial, which absorbs middle-name drift but
    not a different given name — Gwinnett's `Richard Timothy Hamil` is filed by
    the state as `Tim Hamil`, so the initials disagree (r vs t) and every tier
    above fails.

    Only attempted for a race with a single candidate surname, and only accepted
    when exactly one contest in the expected section carries that surname and
    that contest is itself uncontested. A section can hold two different people
    who share a surname (courts has a Robert Lane and a Roger Lane), so anything
    less strict would trade a missing result for a wrong one.
    """
    my_keys = race_name_keys(race)
    surnames = {k[0] for k in my_keys}
    if len(surnames) != 1:
        return None, None
    wanted_sections = {s for s, _ in office_keys(race)}
    if not wanted_sections:
        return None, None

    hits = [(sec_id, office, contest)
            for sec_id, office, contest in by_surname.get(next(iter(surnames)), [])
            if sec_id in wanted_sections]
    if len(hits) != 1:
        if hits and report is not None:
            report.append((race['id'], 'surname-ambiguous',
                           f"surname '{next(iter(surnames))}' appears in "
                           f"{len(hits)} contests — not attributable"))
        return None, None

    sec_id, office, contest = hits[0]
    if len(contest.get('candidates', [])) != 1:
        if report is not None:
            report.append((race['id'], 'surname-contested',
                           f"only a surname matched '{office}', which is contested "
                           f"— cannot tell which candidate"))
        return None, None
    return [contest], 'surname'


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
        (e['by_office'], e['by_name'],
         e['by_office_norm'], e['by_surname']) = index_contests(e['sections'])

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
    stats = {'office': 0, 'office~': 0, 'name': 0, 'surname': 0}
    unmatched = []
    near_misses = []
    for race in races:
        ambiguous = any(k in contested_keys for k in office_keys(race))
        phase_dates = {str(p.get('electionDate') or '')
                       for p in (race.get('phases') or {}).values()}
        entries = []
        for e in live:
            if ambiguous and e['date'] not in phase_dates:
                continue
            contests, how = find_contests(race, e['by_office'], e['by_name'],
                                          e['by_office_norm'], e['by_surname'],
                                          near_misses)
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
          f"normalized office: {stats['office~']}, candidate names: {stats['name']}, "
          f"surname only: {stats['surname']}")
    print(f"Races with results: {len(index)} of {len(races)}")
    if near_misses:
        # A rejected match is a decision worth seeing: it is the difference
        # between a race showing nothing and a race showing someone else's
        # numbers. See CODEBASE-REVIEW-2026-08-18.md finding 3.1.
        print(f"\nNear-misses rejected ({len(near_misses)}):")
        for rid, kind, detail in near_misses[:15]:
            print(f"    [{kind}] {rid}: {detail}")
        if len(near_misses) > 15:
            print(f"    ... and {len(near_misses) - 15} more")

    print(f"Races with none: {len(unmatched)}")
    for rid in unmatched[:15]:
        print(f"    {rid}")
    if len(unmatched) > 15:
        print(f"    ... and {len(unmatched) - 15} more")
    print(f"Wrote: {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes)")


if __name__ == '__main__':
    main()
