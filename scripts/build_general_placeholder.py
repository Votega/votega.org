#!/usr/bin/env python3
"""
Build a pre-election placeholder for the Nov 3, 2026 General Election results
page from races.json, so the page (and its ballot listing) exists and is
wired up before any votes are counted.

Every candidate is written with 0 votes; the shared results layout
(_layouts/election_results.html) treats a 0-vote contest as "Awaiting
Results" regardless of candidate count, so this is a safe pre-election
preview, not a projection.

Judicial races are left off the preview on purpose — see
PREVIEW_EXCLUDED_LEVELS — but still show their results once the SoS reports any.
The `courts` section is therefore the ten District Attorney races until then.

This is the placeholder generator, not the results builder. Once official
Nov 3 results are available as a Georgia SoS "Total Votes Results" CSV,
replace this file's output by running the real builder instead:
    python scripts/build_results_json.py <csv_path> ga-general-2026-results

Re-run it whenever races.json changes. It is a pure derivation of races.json,
so anything the two disagree about is this file being stale — and until a
`--check` existed, nothing said so. The published preview drifted 110 offices
away from races.json before anyone noticed, four of them showing the opponent
a candidate beat in the primary rather than the person actually on the ballot.
refresh-general-placeholder.yml now rebuilds it automatically.

Usage:
    python scripts/build_general_placeholder.py            # write
    python scripts/build_general_placeholder.py --check    # exit 1 if stale
"""

import json
from lib.atomic_io import write_json_atomic
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(__file__)

# Cycle to build the placeholder for — change at a rollover. See finding 5.9.
CYCLE = 2026
ROOT = os.path.join(HERE, '..')
OUT_DIR = os.path.join(ROOT, '_data', 'election_results')

STATEWIDE_ORDER = [
    'US Senate', 'Governor', 'Lieutenant Governor', 'Secretary of State',
    'Attorney General', 'Commissioner of Agriculture', 'Commissioner of Insurance',
    'State School Superintendent', 'Commissioner of Labor', 'PSC - District 3',
    'PSC - District 5',
]

STATEWIDE_CHAMBER_MAP = {
    'U.S. Senate': 'US Senate',
    'Governor': 'Governor',
    'Lieutenant Governor': 'Lieutenant Governor',
    'Secretary of State': 'Secretary of State',
    'Attorney General': 'Attorney General',
    'Commissioner of Agriculture': 'Commissioner of Agriculture',
    'Insurance & Fire Safety Commissioner': 'Commissioner of Insurance',
    'State School Superintendent': 'State School Superintendent',
    'Labor Commissioner': 'Commissioner of Labor',
}

PARTY_MAP = {
    'democrat': 'dem', 'democratic': 'dem',
    'republican': 'rep',
}


def party_code(label):
    return PARTY_MAP.get((label or '').strip().lower(), 'np')


def load(name):
    with open(os.path.join(ROOT, 'assets', 'data', name), encoding='utf-8') as f:
        return json.load(f)


def build_member_lookups():
    congress = load('current-members.json')
    ga = load('ga-members.json')
    congress_by_id = {}
    for m in congress.get('members', []):
        if m.get('bioguideId'):
            full = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
            congress_by_id[m['bioguideId']] = full or m.get('name')
    ga_by_id = {}
    for m in ga.get('members', []):
        if m.get('id'):
            ga_by_id[m['id']] = m.get('name')
    return congress_by_id, ga_by_id


def resolve_name(cand, congress_by_id, ga_by_id):
    if cand.get('name'):
        return cand['name']
    if cand.get('type') == 'incumbent':
        src = cand.get('memberSource', 'congress')
        mid = cand.get('memberId')
        if src == 'congress':
            return congress_by_id.get(mid)
        return ga_by_id.get(mid)
    return None


# Races the BALLOT PREVIEW leaves off on purpose, by `level`. Judicial races are
# nonpartisan and decided at the May general primary, so they are deliberately
# not advertised as "on the ballot" here — see the page's notice_upcoming.
#
# This is an exclusion from the PREVIEW ONLY, never from the results. Once polls
# close, the page is rebuilt from the Secretary of State's CSV by
# build_results_json.py, which buckets judicial contests into the same `courts`
# section this builder uses (ga-primary-results.json carries 88 of them). So
# judicial results appear of their own accord the moment the SoS reports any, and
# none appear if the SoS reports none. Nothing here has to be flipped on
# election night.
#
# It is keyed on the RACE, not the section, because `courts` also carries the ten
# District Attorney races, which are partisan, are on the November ballot, and
# must be listed. An earlier version excluded the whole section and took the DA
# races down with it.
PREVIEW_EXCLUDED_LEVELS = {'state-judicial'}


def classify(race):
    level = race.get('level')
    chamber = race.get('chamber')
    if level == 'federal' and chamber == 'U.S. House':
        return 'us-house'
    if chamber == 'Georgia State Senate':
        return 'state-senate'
    if chamber == 'Georgia House of Representatives':
        return 'state-house'
    if level == 'state-judicial':
        return 'courts'
    # A District Attorney is `level: "local"` in races.json, and `courts` is where
    # the SoS export puts one: build_results_json.classify() sends any office name
    # containing "district attorney" there. Matching it is the whole point — put
    # these anywhere else and all ten races jump to a different tab on election
    # night, when the CSV replaces this file.
    if level == 'local' and chamber == 'District Attorney':
        return 'courts'
    if level in ('federal', 'state-executive'):
        return 'statewide'
    return None


def office_name(race, section):
    chamber = race.get('chamber')
    if section == 'statewide':
        if chamber == 'Public Service Commissioner':
            return f"PSC - District {race.get('district')}"
        return STATEWIDE_CHAMBER_MAP.get(chamber, chamber)
    if section in ('us-house', 'state-senate', 'state-house'):
        return f"District {race.get('district')}"
    if section == 'courts':
        seat = race.get('seat', '')
        if chamber == 'District Attorney':
            # Spelled exactly as the SoS export spells it (ASCII hyphen, not the
            # em dash in races.json's displayTitle), so the office key is the
            # same string before and after the real results land.
            return f"District Attorney - {race.get('circuit', '')}"
        if chamber == 'Superior Court':
            return f"Superior Court - {race.get('circuit', '')} ({seat})"
        if chamber == 'Georgia Court of Appeals':
            return f"Court of Appeals of Georgia ({seat})"
        if chamber == 'Supreme Court of Georgia':
            return f"Supreme Court of Georgia ({seat})"
    return chamber


def build_contests(race, section, congress_by_id, ga_by_id):
    general = race.get('phases', {}).get('general', {})
    by_party = OrderedDict()  # party code -> [candidate dicts]

    def take(cand, code):
        name = resolve_name(cand, congress_by_id, ga_by_id)
        if not name:
            return
        by_party.setdefault(code, []).append({
            'name': name, 'votes': 0,
            'incumbent': bool(cand.get('isIncumbent') or cand.get('type') == 'incumbent'),
        })

    # Read whichever shape the phase uses, NOT whichever the section implies. A
    # nonpartisan race carries a flat `candidates` list and a partisan one carries
    # `ballots` keyed by party — and `courts` holds both: judicial races are
    # nonpartisan, District Attorney races are not. Keying this on the section
    # silently emitted zero contests for a DA race.
    ballots = general.get('ballots') or {}
    if ballots:
        for party_label, cands in ballots.items():
            code = party_code(party_label)
            for cand in cands or []:
                take(cand, code)
    else:
        for cand in general.get('candidates') or []:
            take(cand, 'np')

    order = {'rep': 0, 'dem': 1, 'np': 2}
    contests = []
    for code in sorted(by_party, key=lambda c: order.get(c, 3)):
        contests.append({'party': code, 'totalVotes': 0, 'candidates': by_party[code]})
    return contests


def district_number(name):
    m = re.search(r'District\s+(\d+)', name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def build_sections(races, congress_by_id, ga_by_id):
    buckets = {k: OrderedDict() for k in ('statewide', 'us-house', 'state-senate', 'state-house', 'courts')}

    for race in races:
        if race.get('cycle') != CYCLE or 'general' not in race.get('phases', {}):
            continue
        section = classify(race)
        if section is None or race.get('level') in PREVIEW_EXCLUDED_LEVELS:
            continue
        contests = build_contests(race, section, congress_by_id, ga_by_id)
        if not contests:
            continue
        name = office_name(race, section)
        buckets[section].setdefault(name, []).extend(contests)

    def races_from(bucket, keys):
        return [{'office': name, 'contests': bucket[name]} for name in keys]

    statewide_keys = [n for n in STATEWIDE_ORDER if n in buckets['statewide']]
    statewide_keys += [n for n in buckets['statewide'] if n not in STATEWIDE_ORDER]

    return [
        {'id': 'statewide', 'label': 'Executive / Statewide', 'races': races_from(buckets['statewide'], statewide_keys)},
        {'id': 'us-house', 'label': 'U.S. House', 'races': races_from(buckets['us-house'], sorted(buckets['us-house'], key=district_number))},
        {'id': 'state-senate', 'label': 'GA State Senate', 'races': races_from(buckets['state-senate'], sorted(buckets['state-senate'], key=district_number))},
        {'id': 'state-house', 'label': 'GA State House', 'races': races_from(buckets['state-house'], sorted(buckets['state-house'], key=district_number))},
        {'id': 'courts', 'label': 'Courts', 'races': races_from(buckets['courts'], sorted(buckets['courts']))},
    ]


def ballots(sections):
    """(section, office) -> the names on that ballot, for comparing two builds."""
    out = {}
    for sec in sections:
        for race in sec.get('races', []):
            out[(sec['id'], race['office'])] = [
                c['name'] for contest in race['contests'] for c in contest['candidates']
            ]
    return out


def counted_votes(path):
    """Votes in the committed preview; None when the file does not exist yet.

    None and 0 both mean "safe to write"; only a positive count refuses. They
    are distinguished because --check treats a missing file as an error while
    the writer treats it as the first run.

    This is what separates a placeholder from real results, so BOTH the write
    and --check gate on it. Keeping it in one place is the point: the guard
    used to live only inside --check, while the workflow's first step ran the
    writer with no flags — so a run on the morning after election night
    overwrote the real counts with zeros and committed them, and the --check
    in the following step then passed because the file it was handed had just
    been zeroed.
    """
    try:
        with open(path, encoding='utf-8') as f:
            committed = json.load(f)
    except FileNotFoundError:
        return None
    # Candidate tallies count too, not just the contest total. build_results_json
    # sets totalVotes only from a literal "Total Votes" row in the SoS export, so
    # an export without one yields contests whose candidates hold real votes while
    # totalVotes is 0 — and a guard reading only the total would wave that through
    # and zero it.
    return sum(max(c.get('totalVotes', 0) or 0,
                   sum(k.get('votes', 0) or 0 for k in c.get('candidates', [])))
               for sec in committed
               for race in sec.get('races', [])
               for c in race.get('contests', []))


def report_drift(committed, fresh):
    """Print how the committed preview differs from what races.json says now."""
    a, b = ballots(committed), ballots(fresh)
    added, removed = sorted(set(b) - set(a)), sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])

    for section, office in added:
        print(f"  + {section}/{office}: {b[(section, office)]}")
    for section, office in removed:
        print(f"  - {section}/{office}: {a[(section, office)]}")
    for key in changed:
        print(f"  ~ {key[0]}/{key[1]}")
        print(f"      published: {a[key]}")
        print(f"      races.json: {b[key]}")
    return len(added) + len(removed) + len(changed)


if __name__ == '__main__':
    check_only = '--check' in sys.argv

    races_data = load('races.json')
    congress_by_id, ga_by_id = build_member_lookups()
    sections = build_sections(races_data.get('races', []), congress_by_id, ga_by_id)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f'ga-general-{CYCLE}-results.json')

    counted = counted_votes(out_path)

    if check_only:
        # The preview is a pure derivation, so a difference can only mean the
        # committed copy predates a races.json edit. Votes are the one thing that
        # legitimately differ — once real results are loaded this file is no
        # longer a placeholder and the check retires itself rather than
        # proposing to overwrite them with zeros.
        if counted is None:
            sys.exit(f"STALE: {out_path} does not exist yet — run without --check.")

        if counted:
            print(f"{out_path} holds {counted:,} votes — real results, not a "
                  f"placeholder. Nothing to check.")
            sys.exit(0)

        with open(out_path, encoding='utf-8') as f:
            committed = json.load(f)
        drift = report_drift(committed, sections)
        if drift:
            sys.exit(f"\nSTALE: {drift} office(s) differ from races.json. "
                     f"Re-run without --check and commit.")
        print(f"Up to date with races.json ({len(ballots(sections))} offices).")
        sys.exit(0)

    # Refuse to replace real results with a zero-vote ballot preview. The
    # workflow runs this writer daily and on every races.json push, so without
    # this the first scheduled run after polls close reverts the page to
    # "Awaiting Results" and commits it.
    if counted:
        print(f"{out_path} holds {counted:,} votes — real results, not a "
              f"placeholder. Refusing to overwrite it with zeros.")
        sys.exit(0)

    write_json_atomic(out_path, sections, separators=(',', ':'))

    counts = {s['id']: len(s['races']) for s in sections}
    print(f"Races per section: {counts}")
    print(f"Wrote: {out_path}")
