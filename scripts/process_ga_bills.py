#!/usr/bin/env python3
"""
process_ga_bills.py
One-time transform: GA_2025_26_bills.json → assets/data/ga-bills.json

Output schema is intentionally identical to what generate_ga_bills_data.py
will produce when the live API workflow is built, so the frontend never needs
to change when that swap happens.

Usage:
  python scripts/process_ga_bills.py
  python scripts/process_ga_bills.py /path/to/GA_2025_26_bills.json
  python scripts/process_ga_bills.py /path/to/input.json /path/to/output.json
"""

import json
import os
import sys
from datetime import datetime, timezone

# --- Defaults (relative to repo root) ---
REPO_ROOT   = os.path.join(os.path.dirname(__file__), '..')
INPUT_FILE  = os.path.join(REPO_ROOT, 'GA_2025_26_bills.json')
OUTPUT_FILE = os.path.join(REPO_ROOT, 'assets', 'data', 'ga-bills.json')

SESSION      = '2025_26'
SESSION_NAME = '2025-2026 Regular Session'
ABSTRACT_MAX = 500  # chars — keeps abstract useful without bloating file size

# All 159 Georgia counties (source: GA General Assembly reapportionment data,
# mirrored in assets/scripts/ga-districts.js).
GA_COUNTIES = {
    'Appling','Atkinson','Bacon','Baker','Baldwin','Banks','Barrow','Bartow',
    'Ben Hill','Berrien','Bibb','Bleckley','Brantley','Brooks','Bryan','Bulloch',
    'Burke','Butts','Calhoun','Camden','Candler','Carroll','Catoosa','Charlton',
    'Chatham','Chattahoochee','Chattooga','Cherokee','Clarke','Clay','Clayton',
    'Clinch','Cobb','Coffee','Colquitt','Columbia','Cook','Coweta','Crawford',
    'Crisp','Dade','Dawson','Decatur','DeKalb','Dodge','Dooly','Dougherty',
    'Douglas','Early','Echols','Effingham','Elbert','Emanuel','Evans','Fannin',
    'Fayette','Floyd','Forsyth','Franklin','Fulton','Gilmer','Glascock','Glynn',
    'Gordon','Grady','Greene','Gwinnett','Habersham','Hall','Hancock','Haralson',
    'Harris','Hart','Heard','Henry','Houston','Irwin','Jackson','Jasper',
    'Jeff Davis','Jefferson','Jenkins','Johnson','Jones','Lamar','Lanier',
    'Laurens','Lee','Liberty','Lincoln','Long','Lowndes','Lumpkin','Macon',
    'Madison','Marion','McDuffie','McIntosh','Meriwether','Miller','Mitchell',
    'Monroe','Montgomery','Morgan','Murray','Muscogee','Newton','Oconee',
    'Oglethorpe','Paulding','Peach','Pickens','Pierce','Pike','Polk','Pulaski',
    'Putnam','Quitman','Rabun','Randolph','Richmond','Rockdale','Schley',
    'Screven','Seminole','Spalding','Stephens','Stewart','Sumter','Talbot',
    'Taliaferro','Tattnall','Taylor','Telfair','Terrell','Thomas','Tift','Toombs',
    'Towns','Treutlen','Troup','Turner','Twiggs','Union','Upson','Walker',
    'Walton','Ware','Warren','Washington','Wayne','Webster','Wheeler','White',
    'Whitfield','Wilcox','Wilkes','Wilkinson','Worth',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def infer_local_subject(title):
    """
    Return ['Local / Municipal'] if the bill title starts with a GA county or
    major city name, otherwise return [].  Only applied to bills with no Open
    States subject tags.

    GA bill titles follow the convention 'Subject; detail; verb phrase', so the
    first semicolon-delimited segment reliably identifies the subject area.
    """
    if ';' not in title:
        return []
    first_seg = title.split(';')[0].strip()
    # Strip common suffixes like ", City of" / ", Town of" / ", County"
    # so "Fulton County" and "Savannah, City of" both reduce to the place name.
    for suffix in (', City of', ', Town of', ', County', ' County'):
        if first_seg.endswith(suffix):
            first_seg = first_seg[: -len(suffix)].strip()
            break
    if first_seg in GA_COUNTIES:
        return ['Local / Municipal']
    return []


def get_bill_url(sources):
    """Prefer legis.ga.gov; fall back to first source URL."""
    for s in sources:
        if 'legis.ga.gov' in s.get('url', ''):
            return s['url']
    return sources[0]['url'] if sources else ''


def get_passage_votes(votes):
    """
    Return passage vote counts per chamber.
    Drops individual voter arrays — those stay in GA_2025_26_bills.json
    if ever needed for a deeper feature.
    """
    result = []
    for v in votes:
        if 'passage' not in v.get('motion_classification', []):
            continue
        counts = {c['option']: c['value'] for c in v.get('counts', [])}
        result.append({
            'chamber':    v.get('organization__classification', ''),
            'date':       v.get('start_date', ''),
            'result':     v.get('result', ''),
            'motionText': v.get('motion_text', ''),
            'yea':        counts.get('yes', 0),
            'nay':        counts.get('no', 0),
            'other':      counts.get('other', 0),
        })
    return result


def slim_bill(b):
    """Map one raw Open States bill object to the target schema.

    actions[] is intentionally omitted — the full history is in GA_2025_26_bills.json.
    status/statusDate (derived from the last action) plus billUrl cover the list-view need.
    """
    actions     = sorted(b.get('actions', []), key=lambda a: a.get('order', 0))
    last_action = actions[-1] if actions else {}
    abstract    = (b.get('abstracts') or [{}])[0].get('abstract', '')

    return {
        'id':          b['id'],
        'identifier':  b['identifier'],
        'billType':    (b.get('classification') or ['bill'])[0],
        'chamber':     b.get('chamber', ''),
        'title':       b.get('title', ''),
        'abstract':    abstract[:ABSTRACT_MAX] if abstract else '',
        'status':      last_action.get('description', ''),
        'statusDate':  last_action.get('date', ''),
        'subjects':    b.get('subject', []) or infer_local_subject(b.get('title', '')),
        'sponsors': [
            {
                'name':    s['name'],
                'primary': s.get('primary', False),
            }
            for s in b.get('sponsors', [])
        ],
        'billUrl':     get_bill_url(b.get('sources', [])),
        'textUrl':     b.get('raw_text_url', ''),
        'passageVotes': get_passage_votes(b.get('votes', [])),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    input_path  = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    output_path = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE

    if not os.path.exists(input_path):
        print(f'ERROR: Input file not found: {input_path}')
        print('Pass the path explicitly: python scripts/process_ga_bills.py /path/to/GA_2025_26_bills.json')
        sys.exit(1)

    print(f'Reading {input_path} ...')
    with open(input_path, encoding='utf-8') as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        print('ERROR: Expected a JSON array at the top level.')
        sys.exit(1)

    print(f'Processing {len(raw):,} bills ...')
    bills = [slim_bill(b) for b in raw]

    # Basic sanity stats
    with_subjects = sum(1 for b in bills if b['subjects'])
    with_votes    = sum(1 for b in bills if b['passageVotes'])
    chambers      = {}
    for b in bills:
        chambers[b['chamber']] = chambers.get(b['chamber'], 0) + 1

    output = {
        'metadata': {
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'session':     SESSION,
            'sessionName': SESSION_NAME,
            'source':      'Open States (bulk export — May 2026)',
            'note':        'Generated by process_ga_bills.py. Swap for generate_ga_bills_data.py when live API workflow is ready.',
            'totalBills':  len(bills),
        },
        'bills': bills,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f'Writing {output_path} ...')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f'\nDone.')
    print(f'  Bills:        {len(bills):,}')
    print(f'  House/lower:  {chambers.get("lower", 0):,}')
    print(f'  Senate/upper: {chambers.get("upper", 0):,}')
    print(f'  With subjects: {with_subjects:,} ({with_subjects/len(bills)*100:.0f}%)')
    print(f'  With votes:    {with_votes:,} ({with_votes/len(bills)*100:.0f}%)')
    print(f'  Output size:  {size_mb:.1f} MB')


if __name__ == '__main__':
    main()
