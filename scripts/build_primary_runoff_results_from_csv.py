#!/usr/bin/env python3
"""
Parse the primary runoff results CSV and inject data into ga-primary-runoff-results.html.

CSV format: tab-separated, columns:
  Office Name | Contest ID | Ballot Name | Choice ID | Party | Total

Usage:
  python scripts/build_primary_runoff_results_from_csv.py
  python scripts/build_primary_runoff_results_from_csv.py path/to/results.csv
"""

import csv
import json
import re
import sys
import os
from collections import OrderedDict

CSV_PATH  = os.path.join(os.path.dirname(__file__), '..', 'assets', 'data',
                         'ga-primary-runoff-results.csv')
HTML_PATH = os.path.join(os.path.dirname(__file__), '..', 'ga-primary-runoff-results.html')

STATEWIDE_ORDER = [
    'US Senate',
    'Governor',
    'Lieutenant Governor',
    'Secretary of State',
    'Attorney General',
    'Commissioner of Agriculture',
    'Commissioner of Insurance',
    'State School Superintendent',
    'Commissioner of Labor',
    'PSC - District 3',
    'PSC - District 5',
]

STATEWIDE_MAP = {
    'us senate':                     'US Senate',
    'governor':                      'Governor',
    'lieutenant governor':           'Lieutenant Governor',
    'secretary of state':            'Secretary of State',
    'attorney general':              'Attorney General',
    'commissioner of agriculture':   'Commissioner of Agriculture',
    'commissioner of insurance':     'Commissioner of Insurance',
    'state school superintendent':   'State School Superintendent',
    'commissioner of labor':         'Commissioner of Labor',
    'psc - district 3':              'PSC - District 3',
    'psc - district 5':              'PSC - District 5',
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
    if 'state senate' in on or 'special state senate' in on:
        return 'state-senate'
    if 'state house of representatives' in on:
        return 'state-house'
    if ('judge' in on or 'justice' in on or
            'court of appeals' in on or 'supreme court' in on or
            'district attorney' in on):
        return 'courts'
    return None


def base_display_name(office_name):
    name = re.sub(r'\s*/.*', '', office_name).strip()
    name = re.sub(r'\s*-\s*(Rep|Dem)\s*$', '', name, flags=re.IGNORECASE).strip()
    return name


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
    name = re.sub(r'^(Judge|Justice)\s*-\s*', '', name, flags=re.IGNORECASE).strip()
    return name


def parse_candidate_name(ballot_name):
    incumbent = bool(re.search(r'\(I\)', ballot_name))
    name = re.sub(r'\s*\(I\)\s*', ' ', ballot_name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name, incumbent


def party_from_csv(party_str):
    p = (party_str or '').strip().upper()
    if p == 'REP': return 'rep'
    if p == 'DEM': return 'dem'
    return 'np'


def detect_delimiter(path):
    """Sniff delimiter — handles both tab-separated exports and comma CSV."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096)
    return '\t' if sample.count('\t') > sample.count(',') else ','


def parse_csv(path):
    delimiter = detect_delimiter(path)
    contests = OrderedDict()

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 6:
                continue
            office_name = row[0].strip()
            contest_id  = row[1].strip()
            ballot_name = row[2].strip()
            party_str   = row[4].strip() if len(row) > 4 else ''
            total_str   = row[5].strip() if len(row) > 5 else ''
            total = int(total_str.replace(',', '')) if total_str else 0

            if ballot_name == 'Total Votes':
                if contest_id in contests:
                    contests[contest_id]['totalVotes'] = total
                continue

            party = party_from_csv(party_str)

            if contest_id not in contests:
                contests[contest_id] = {
                    'office_name': office_name,
                    'contest_id':  contest_id,
                    'party':       party,
                    'candidates':  [],
                    'totalVotes':  0,
                }

            name, incumbent = parse_candidate_name(ballot_name)
            contests[contest_id]['candidates'].append({
                'name':      name,
                'votes':     total,
                'incumbent': incumbent,
            })

    for c in contests.values():
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)

    return contests


def build_sections(contests):
    buckets = {
        'statewide':    OrderedDict(),
        'us-house':     OrderedDict(),
        'state-senate': OrderedDict(),
        'state-house':  OrderedDict(),
        'courts':       OrderedDict(),
    }

    for cid, contest in contests.items():
        section = classify(contest['office_name'])
        if section is None:
            continue

        bucket = buckets[section]
        on = contest['office_name']

        if section == 'statewide':
            display = statewide_display(on)
        elif section == 'courts':
            display = courts_display(on)
        else:
            base = base_display_name(on)
            if 'special' in on.lower():
                display = base
            else:
                m = re.search(r'District\s+(\d+)', base, re.IGNORECASE)
                display = f"District {m.group(1)}" if m else base

        if display not in bucket:
            bucket[display] = []
        bucket[display].append(contest)

    # Statewide: canonical order
    statewide_races = []
    for name in STATEWIDE_ORDER:
        if name in buckets['statewide']:
            statewide_races.append({
                'office':   name,
                'contests': _contests_for_office(buckets['statewide'][name]),
            })
    for name, conts in buckets['statewide'].items():
        if name not in STATEWIDE_ORDER:
            statewide_races.append({
                'office':   name,
                'contests': _contests_for_office(conts),
            })

    # US House: sort by district
    ush_races = [
        {'office': name, 'contests': _contests_for_office(buckets['us-house'][name])}
        for name in sorted(buckets['us-house'].keys(), key=district_number)
    ]

    # State Senate: regular then specials
    ss_regular = {k: v for k, v in buckets['state-senate'].items() if 'special' not in k.lower()}
    ss_special  = {k: v for k, v in buckets['state-senate'].items() if 'special' in k.lower()}
    ss_races = (
        [{'office': n, 'contests': _contests_for_office(v)} for n, v in sorted(ss_regular.items(), key=lambda x: district_number(x[0]))] +
        [{'office': n, 'contests': _contests_for_office(v)} for n, v in ss_special.items()]
    )

    # State House: sort by district
    sh_races = [
        {'office': name, 'contests': _contests_for_office(buckets['state-house'][name])}
        for name in sorted(buckets['state-house'].keys(), key=district_number)
    ]

    # Courts: preserve CSV order
    court_races = [
        {'office': name, 'contests': _contests_for_office(conts)}
        for name, conts in buckets['courts'].items()
    ]

    return [
        {'id': 'statewide',    'label': 'Executive / Statewide', 'races': statewide_races},
        {'id': 'us-house',     'label': 'U.S. House',            'races': ush_races},
        {'id': 'state-senate', 'label': 'GA State Senate',       'races': ss_races},
        {'id': 'state-house',  'label': 'GA State House',        'races': sh_races},
        {'id': 'courts',       'label': 'Courts',                'races': court_races},
    ]


def _contests_for_office(contest_list):
    order = {'rep': 0, 'dem': 1, 'np': 2}
    contest_list = sorted(contest_list, key=lambda c: order.get(c['party'], 3))
    return [
        {
            'party':      c['party'],
            'totalVotes': c['totalVotes'],
            'candidates': c['candidates'],
        }
        for c in contest_list
    ]


def update_html(html_path, sections):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_data = f'const SECTIONS={json.dumps(sections, separators=(",", ":"), ensure_ascii=False)};'
    content = re.sub(
        r'const SECTIONS=\[.*?\];',
        new_data,
        content,
        count=1,
        flags=re.DOTALL,
    )

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Updated: {html_path}")


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV_PATH

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        print("Usage: python scripts/build_primary_runoff_results_from_csv.py [path/to/results.csv]")
        sys.exit(1)

    print(f"Parsing: {csv_path}")
    contests = parse_csv(csv_path)
    print(f"  {len(contests)} contests parsed")

    sections = build_sections(contests)
    counts = {s['id']: len(s['races']) for s in sections}
    print(f"  Races per section: {counts}")

    update_html(HTML_PATH, sections)
    print("Done.")
