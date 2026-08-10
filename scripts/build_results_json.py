#!/usr/bin/env python3
"""
Parse an official Georgia SoS "Total Votes Results" CSV export into the
`SECTIONS` JSON structure consumed by the shared election-results layout
(_layouts/election_results.html).

This is the single builder for every results page (primary, runoff, special,
general). Presentation — status labels, unofficial/certified, notice text — is
declared per page in front matter, NOT here; this script only shapes the data.

Usage:
    python scripts/build_results_json.py <csv_path> <data_key>

    <data_key> is the base name written to _data/election_results/<data_key>.json
    and referenced by a page's `results_data:` front matter.

Examples:
    python scripts/build_results_json.py "assets/data/Total Votes Results - OFFICIAL.csv" ga-primary-results
    python scripts/build_results_json.py assets/data/ga-primary-runoff-results.csv    ga-primary-runoff-results
    python scripts/build_results_json.py assets/data/ga-special-2026-results.csv       ga-special-2026-results

CSV columns: Office Name, Contest ID, Ballot Name, Choice ID, Party, Total.
Jungle/nonpartisan special contests: leave the Party column blank and keep the
"(Dem)"/"(Rep)" suffix in the ballot name — the contest renders as one
non-partisan card with party labels on each candidate.
"""

import csv
import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, '..', '_data', 'election_results')

# Statewide race display names, in desired order
STATEWIDE_ORDER = [
    'US Senate', 'Governor', 'Lieutenant Governor', 'Secretary of State',
    'Attorney General', 'Commissioner of Agriculture', 'Commissioner of Insurance',
    'State School Superintendent', 'Commissioner of Labor', 'PSC - District 3',
    'PSC - District 5',
]
STATEWIDE_MAP = {
    'us senate': 'US Senate', 'governor': 'Governor',
    'lieutenant governor': 'Lieutenant Governor', 'secretary of state': 'Secretary of State',
    'attorney general': 'Attorney General', 'commissioner of agriculture': 'Commissioner of Agriculture',
    'commissioner of insurance': 'Commissioner of Insurance',
    'state school superintendent': 'State School Superintendent',
    'commissioner of labor': 'Commissioner of Labor',
    'psc - district 3': 'PSC - District 3', 'psc - district 5': 'PSC - District 5',
}


def classify(office_name):
    on = office_name.lower()
    for key in STATEWIDE_MAP:
        if on.startswith(key):
            return 'statewide'
    if on.startswith('psc'):
        return 'statewide'
    if 'us house of representatives' in on:
        return 'us-house'
    if 'state senate' in on:
        return 'state-senate'
    if 'state house of representatives' in on:
        return 'state-house'
    if ('judge' in on or 'justice' in on or 'court of appeals' in on or
            'supreme court' in on or 'district attorney' in on):
        return 'courts'
    return None  # party questions etc. — skip


def base_display_name(office_name):
    name = re.sub(r'\s*/.*', '', office_name).strip()
    return re.sub(r'\s*-\s*(Rep|Dem)\s*$', '', name, flags=re.IGNORECASE).strip()


def district_number(display_name):
    m = re.search(r'District\s+(\d+)', display_name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def statewide_display(office_name):
    on = office_name.lower()
    for key, display in STATEWIDE_MAP.items():
        if on.startswith(key):
            return display
    return base_display_name(office_name)


def courts_display(office_name):
    name = base_display_name(office_name)
    return re.sub(r'^(Judge|Justice)\s*-\s*', '', name, flags=re.IGNORECASE).strip()


def parse_candidate_name(ballot_name):
    incumbent = bool(re.search(r'\(I\)', ballot_name))
    name = re.sub(r'\s*\(I\)\s*', ' ', ballot_name)
    return re.sub(r'\s+', ' ', name).strip(), incumbent


def party_from_csv(party_str):
    p = (party_str or '').strip().upper()
    return {'REP': 'rep', 'DEM': 'dem'}.get(p, 'np')


def detect_delimiter(path):
    """Sniff delimiter — handles both tab-separated exports and comma CSV."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096)
    return '\t' if sample.count('\t') > sample.count(',') else ','


def parse_csv(path):
    contests = OrderedDict()
    delimiter = detect_delimiter(path)
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader)  # header
        for row in reader:
            if len(row) < 6:
                continue
            office_name, contest_id, ballot_name = row[0].strip(), row[1].strip(), row[2].strip()
            party_str, total_str = row[4].strip(), row[5].strip()
            total = int(total_str) if total_str else 0

            if ballot_name.lower() == 'total votes':
                if contest_id in contests:
                    contests[contest_id]['totalVotes'] = total
                continue

            if contest_id not in contests:
                contests[contest_id] = {
                    'office_name': office_name, 'party': party_from_csv(party_str),
                    'candidates': [], 'totalVotes': 0,
                }
            name, incumbent = parse_candidate_name(ballot_name)
            contests[contest_id]['candidates'].append(
                {'name': name, 'votes': total, 'incumbent': incumbent})

    for c in contests.values():
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)
    return contests


def _contests_for_office(contest_list):
    order = {'rep': 0, 'dem': 1, 'np': 2}
    contest_list = sorted(contest_list, key=lambda c: order.get(c['party'], 3))
    return [{'party': c['party'], 'totalVotes': c['totalVotes'], 'candidates': c['candidates']}
            for c in contest_list]


def build_sections(contests):
    buckets = {k: OrderedDict() for k in
               ('statewide', 'us-house', 'state-senate', 'state-house', 'courts')}
    for contest in contests.values():
        section = classify(contest['office_name'])
        if section is None:
            continue
        on = contest['office_name']
        if section == 'statewide':
            display = statewide_display(on)
        elif section == 'courts':
            display = courts_display(on)
        else:
            base = base_display_name(on)
            if 'special' in on.lower():
                display = base  # keep "Special ..." prefix
            else:
                m = re.search(r'District\s+(\d+)', base, re.IGNORECASE)
                display = f"District {m.group(1)}" if m else base
        buckets[section].setdefault(display, []).append(contest)

    def races_from(bucket, keys):
        return [{'office': name, 'contests': _contests_for_office(bucket[name])} for name in keys]

    # Statewide: canonical order, then any stragglers
    statewide_keys = [n for n in STATEWIDE_ORDER if n in buckets['statewide']]
    statewide_keys += [n for n in buckets['statewide'] if n not in STATEWIDE_ORDER]

    # Legislative: by district number; specials sorted to the end
    def split_specials(bucket):
        regular = sorted((k for k in bucket if 'special' not in k.lower()), key=district_number)
        specials = [k for k in bucket if 'special' in k.lower()]
        return regular + specials

    return [
        {'id': 'statewide',    'label': 'Executive / Statewide', 'races': races_from(buckets['statewide'], statewide_keys)},
        {'id': 'us-house',     'label': 'U.S. House',            'races': races_from(buckets['us-house'], sorted(buckets['us-house'], key=district_number))},
        {'id': 'state-senate', 'label': 'GA State Senate',       'races': races_from(buckets['state-senate'], split_specials(buckets['state-senate']))},
        {'id': 'state-house',  'label': 'GA State House',        'races': races_from(buckets['state-house'], sorted(buckets['state-house'], key=district_number))},
        {'id': 'courts',       'label': 'Courts',                'races': races_from(buckets['courts'], list(buckets['courts']))},
    ]


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit("Usage: python scripts/build_results_json.py <csv_path> <data_key>")
    csv_path, data_key = sys.argv[1], sys.argv[2]
    print(f"Parsing CSV: {csv_path}")
    contests = parse_csv(csv_path)
    print(f"  {len(contests)} contest(s) parsed")
    sections = build_sections(contests)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{data_key}.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(sections, f, ensure_ascii=False, separators=(',', ':'))
    counts = {s['id']: len(s['races']) for s in sections}
    print(f"  Races per section: {counts}")
    print(f"Wrote: {out_path}")
