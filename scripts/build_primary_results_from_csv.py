#!/usr/bin/env python3
"""
Parse the official primary results CSV and update ga-primary-results.html
with official certified vote counts.

Usage: python scripts/build_primary_results_from_csv.py
"""

import csv
import json
import re
import sys
import os
from collections import OrderedDict

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'assets', 'data',
                        'Total Votes Results - OFFICIAL.csv')
HTML_PATH = os.path.join(os.path.dirname(__file__), '..', 'ga-primary-results.html')

# ──────────────────────────────────────────────
# Statewide race display names, in desired order
# ──────────────────────────────────────────────
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
    """Return section id for an office name."""
    on = office_name.lower()
    # Statewide executive/offices
    for key in STATEWIDE_MAP:
        if on.startswith(key):
            return 'statewide'
    if on.startswith('psc'):
        return 'statewide'
    # Legislative
    if 'us house of representatives' in on:
        return 'us-house'
    if 'state senate' in on or 'special state senate' in on:
        return 'state-senate'
    if 'state house of representatives' in on:
        return 'state-house'
    # Courts / DA
    if ('judge' in on or 'justice' in on or
            'court of appeals' in on or 'supreme court' in on or
            'district attorney' in on):
        return 'courts'
    # Party questions — skip
    return None


def base_display_name(office_name):
    """Canonical display name for an office (party suffix removed)."""
    # Strip bilingual suffix (everything after '/')
    name = re.sub(r'\s*/.*', '', office_name).strip()
    # Strip trailing ' - Rep' or ' - Dem'
    name = re.sub(r'\s*-\s*(Rep|Dem)\s*$', '', name, flags=re.IGNORECASE).strip()
    return name


def district_number(display_name):
    """Extract integer district number for sorting, or 0 if not found."""
    m = re.search(r'District\s+(\d+)', display_name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def statewide_display(office_name):
    """Map a statewide office name to its canonical display name."""
    on = office_name.lower()
    for key, display in STATEWIDE_MAP.items():
        if on.startswith(key):
            return display
    return base_display_name(office_name)


def courts_display(office_name):
    """Simplified display name for a court/DA race."""
    name = base_display_name(office_name)
    # Remove leading 'Judge - ' or 'Justice - '
    name = re.sub(r'^(Judge|Justice)\s*-\s*', '', name, flags=re.IGNORECASE).strip()
    return name


def parse_candidate_name(ballot_name):
    """Return (clean_name, is_incumbent). Handles (I), (Dem), (Rep) annotations."""
    incumbent = bool(re.search(r'\(I\)', ballot_name))
    # Remove (I) annotation
    name = re.sub(r'\s*\(I\)\s*', ' ', ballot_name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name, incumbent


def party_from_csv(party_str):
    p = (party_str or '').strip().upper()
    if p == 'REP':
        return 'rep'
    if p == 'DEM':
        return 'dem'
    return 'np'


# ──────────────────────────────────────────────
# Parse CSV
# ──────────────────────────────────────────────

def parse_csv(path):
    """
    Returns dict keyed by contest_id:
      { 'office_name': str, 'party': str, 'candidates': [...], 'totalVotes': int }
    Ordering preserves CSV row order.
    """
    contests = OrderedDict()

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 6:
                continue
            office_name = row[0].strip()
            contest_id  = row[1].strip()
            ballot_name = row[2].strip()
            party_str   = row[4].strip() if len(row) > 4 else ''
            total_str   = row[5].strip() if len(row) > 5 else ''
            total = int(total_str) if total_str else 0

            if ballot_name == 'Total Votes':
                if contest_id in contests:
                    contests[contest_id]['totalVotes'] = total
                continue

            party = party_from_csv(party_str)

            if contest_id not in contests:
                contests[contest_id] = {
                    'office_name': office_name,
                    'contest_id': contest_id,
                    'party': party,
                    'candidates': [],
                    'totalVotes': 0,
                }

            name, incumbent = parse_candidate_name(ballot_name)
            contests[contest_id]['candidates'].append({
                'name': name,
                'votes': total,
                'incumbent': incumbent,
            })

    # Sort candidates by votes descending within each contest
    for c in contests.values():
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)

    return contests


# ──────────────────────────────────────────────
# Build SECTIONS structure
# ──────────────────────────────────────────────

def build_sections(contests):
    # Bucket contests by section
    buckets = {
        'statewide':    OrderedDict(),  # display_name -> [contest, ...]
        'us-house':     OrderedDict(),
        'state-senate': OrderedDict(),
        'state-house':  OrderedDict(),
        'courts':       OrderedDict(),
    }

    for cid, contest in contests.items():
        section = classify(contest['office_name'])
        if section is None:
            continue  # skip party questions etc.

        bucket = buckets[section]
        on = contest['office_name']

        if section == 'statewide':
            display = statewide_display(on)
        elif section == 'courts':
            display = courts_display(on)
        else:
            # US House / State Senate / State House: use "District N"
            base = base_display_name(on)
            # For "Special State Senate", keep that prefix
            if 'special' in on.lower():
                display = base  # e.g. "Special State Senate - District 7"
            else:
                m = re.search(r'District\s+(\d+)', base, re.IGNORECASE)
                display = f"District {m.group(1)}" if m else base

        if display not in bucket:
            bucket[display] = []
        bucket[display].append(contest)

    # ── Statewide: enforce canonical order ──────────────────────────────
    statewide_races = []
    for name in STATEWIDE_ORDER:
        if name in buckets['statewide']:
            statewide_races.append({
                'office': name,
                'contests': _contests_for_office(buckets['statewide'][name]),
            })
    # Any statewide offices not in our known list (shouldn't happen)
    for name, conts in buckets['statewide'].items():
        if name not in STATEWIDE_ORDER:
            statewide_races.append({
                'office': name,
                'contests': _contests_for_office(conts),
            })

    # ── US House: sort by district number ───────────────────────────────
    ush_races = []
    for name in sorted(buckets['us-house'].keys(), key=district_number):
        ush_races.append({
            'office': name,
            'contests': _contests_for_office(buckets['us-house'][name]),
        })

    # ── State Senate: sort by district number; specials at end ──────────
    ss_regular = {k: v for k, v in buckets['state-senate'].items()
                  if 'special' not in k.lower()}
    ss_special  = {k: v for k, v in buckets['state-senate'].items()
                   if 'special' in k.lower()}
    ss_races = []
    for name in sorted(ss_regular.keys(), key=district_number):
        ss_races.append({
            'office': name,
            'contests': _contests_for_office(ss_regular[name]),
        })
    for name, conts in ss_special.items():
        ss_races.append({
            'office': name,
            'contests': _contests_for_office(conts),
        })

    # ── State House: sort by district number ────────────────────────────
    sh_races = []
    for name in sorted(buckets['state-house'].keys(), key=district_number):
        sh_races.append({
            'office': name,
            'contests': _contests_for_office(buckets['state-house'][name]),
        })

    # ── Courts: preserve CSV order ──────────────────────────────────────
    court_races = []
    for name, conts in buckets['courts'].items():
        court_races.append({
            'office': name,
            'contests': _contests_for_office(conts),
        })

    return [
        {'id': 'statewide',    'label': 'Executive / Statewide', 'races': statewide_races},
        {'id': 'us-house',     'label': 'U.S. House',            'races': ush_races},
        {'id': 'state-senate', 'label': 'GA State Senate',       'races': ss_races},
        {'id': 'state-house',  'label': 'GA State House',        'races': sh_races},
        {'id': 'courts',       'label': 'Courts',                'races': court_races},
    ]


def _contests_for_office(contest_list):
    """Convert a list of raw contests into the output format, Rep first."""
    # Sort: rep first, then dem, then np
    order = {'rep': 0, 'dem': 1, 'np': 2}
    contest_list = sorted(contest_list, key=lambda c: order.get(c['party'], 3))
    result = []
    for c in contest_list:
        result.append({
            'party': c['party'],
            'totalVotes': c['totalVotes'],
            'candidates': c['candidates'],
        })
    return result


# ──────────────────────────────────────────────
# Update HTML
# ──────────────────────────────────────────────

def update_html(html_path, sections):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace the SECTIONS data (single line)
    new_data = f'const SECTIONS={json.dumps(sections, separators=(",", ":"), ensure_ascii=False)};'
    content = re.sub(
        r'const SECTIONS=\[.*?\];',
        new_data,
        content,
        count=1,
        flags=re.DOTALL,
    )

    # Update metadata line: remove "Preliminary" flag, update timestamp
    content = content.replace(
        'Last updated: 8:00 AM ET &nbsp;&middot;&nbsp; Preliminary',
        'Last updated: June 6, 2026 &nbsp;&middot;&nbsp; Official Certified Results',
    )

    # Replace the preliminary notice with an official-results notice
    content = re.sub(
        r'<div class="pr-notice">.*?</div>',
        '<div class="pr-notice" style="background:#e8f8e8;border-color:#1e7e34;color:#1a5c2a;">'
        '&#10003; Official certified results from the Georgia Secretary of State.'
        '</div>',
        content,
        count=1,
        flags=re.DOTALL,
    )

    # Update status badge label for completed races (winner is definitive now)
    content = content.replace(
        "winner:      {cls:'winner',     text:'Leads >50%'},",
        "winner:      {cls:'winner',     text:'Advances'},",
    )
    content = content.replace(
        "runoff:      {cls:'runoff',     text:'Runoff Likely'},",
        "runoff:      {cls:'runoff',     text:'Runoff'},",
    )

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Updated: {html_path}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == '__main__':
    print(f"Parsing CSV: {CSV_PATH}")
    contests = parse_csv(CSV_PATH)
    print(f"  {len(contests)} contests parsed")

    sections = build_sections(contests)
    counts = {s['id']: len(s['races']) for s in sections}
    print(f"  Races per section: {counts}")

    update_html(HTML_PATH, sections)
    print("Done.")
