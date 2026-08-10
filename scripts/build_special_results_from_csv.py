#!/usr/bin/env python3
"""
Build a special-election results page from an official SoS
"Total Votes Results" CSV export.

Same SECTIONS format and page structure as build_primary_results_from_csv.py /
build_primary_runoff_results_from_csv.py, but for standalone special elections
(e.g. the July 28, 2026 U.S. House District 13 special, and its Aug 25 runoff).

Usage:
    python scripts/build_special_results_from_csv.py            # July 28 special
    python scripts/build_special_results_from_csv.py <csv> <html>

The CSV uses the SoS export columns: Office Name, Contest ID, Ballot Name,
Choice ID, Party, Total. Special-election contests are jungle/nonpartisan, so
leave the Party column blank and keep the "(Dem)"/"(Rep)" suffix in the ballot
name — the contest renders as a single non-partisan card with party labels on
each candidate, matching how prior special contests were shown.
"""

import csv
import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(__file__)
DEFAULT_CSV = os.path.join(HERE, '..', 'assets', 'data', 'ga-special-2026-results.csv')
DEFAULT_HTML = os.path.join(HERE, '..', 'ga-special-2026-results.html')


def classify(office_name):
    on = office_name.lower()
    if 'us house of representatives' in on:
        return 'us-house'
    if 'us senate' in on:
        return 'statewide'
    if 'state senate' in on:
        return 'state-senate'
    if 'state house of representatives' in on:
        return 'state-house'
    if any(k in on for k in ('judge', 'justice', 'court of appeals',
                             'supreme court', 'district attorney')):
        return 'courts'
    return 'statewide'


def display_name(office_name):
    """'US House of Representatives - District 13' -> 'District 13'."""
    m = re.search(r'District\s+(\d+)', office_name, re.IGNORECASE)
    if m:
        return f"District {m.group(1)}"
    return re.sub(r'\s*-\s*(Rep|Dem)\s*$', '', office_name, flags=re.IGNORECASE).strip()


def parse_candidate_name(ballot_name):
    incumbent = bool(re.search(r'\(I\)', ballot_name))
    name = re.sub(r'\s*\(I\)\s*', ' ', ballot_name)
    return re.sub(r'\s+', ' ', name).strip(), incumbent


def party_from_csv(party_str):
    p = (party_str or '').strip().upper()
    return {'REP': 'rep', 'DEM': 'dem'}.get(p, 'np')


def parse_csv(path):
    contests = OrderedDict()
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
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
                    'office_name': office_name,
                    'party': party_from_csv(party_str),
                    'candidates': [],
                    'totalVotes': 0,
                }
            name, incumbent = parse_candidate_name(ballot_name)
            contests[contest_id]['candidates'].append(
                {'name': name, 'votes': total, 'incumbent': incumbent})

    for c in contests.values():
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)
    return contests


def build_sections(contests):
    section_defs = [
        ('statewide', 'Executive / Statewide'),
        ('us-house', 'U.S. House'),
        ('state-senate', 'GA State Senate'),
        ('state-house', 'GA State House'),
        ('courts', 'Courts'),
    ]
    buckets = {sid: OrderedDict() for sid, _ in section_defs}
    for c in contests.values():
        sid = classify(c['office_name'])
        buckets[sid].setdefault(display_name(c['office_name']), []).append(c)

    def district_num(name):
        m = re.search(r'District\s+(\d+)', name, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    sections = []
    for sid, label in section_defs:
        races = []
        for office in sorted(buckets[sid].keys(), key=district_num):
            races.append({
                'office': office,
                'contests': [
                    {'party': c['party'], 'totalVotes': c['totalVotes'],
                     'candidates': c['candidates']}
                    for c in buckets[sid][office]
                ],
            })
        sections.append({'id': sid, 'label': label, 'races': races})
    return sections


def update_html(html_path, sections):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_data = f'const SECTIONS={json.dumps(sections, separators=(",", ":"), ensure_ascii=False)};'
    content, n = re.subn(r'const SECTIONS=\[.*?\];', new_data, content, count=1, flags=re.DOTALL)
    if n != 1:
        sys.exit(f"ERROR: could not find 'const SECTIONS=[...]' in {html_path}")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Updated: {html_path}")


if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    html_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_HTML
    print(f"Parsing CSV: {csv_path}")
    contests = parse_csv(csv_path)
    print(f"  {len(contests)} contest(s) parsed")
    sections = build_sections(contests)
    update_html(html_path, sections)
    print("Done.")
