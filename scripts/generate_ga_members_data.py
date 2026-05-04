#!/usr/bin/env python3
"""
Generate ga-members.json from Open States API (Georgia General Assembly).
Requires OPENSTATES_API_KEY environment variable.
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-members.json"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"


def fetch_url(url):
    try:
        print(f"Fetching: {url[:120]}...")
        req = urllib.request.Request(url, headers={
            'X-API-Key': API_KEY,
            'Accept': 'application/json',
            'User-Agent': 'votega.org/1.0',
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"HTTP Error {e.code}: {e.reason} — {body[:300]}")
        return None
    except Exception as e:
        print(f"Error fetching: {e}")
        return None


def get_all_members():
    all_members = []
    page = 1
    per_page = 50

    while True:
        params = urllib.parse.urlencode([
            ('jurisdiction', GA_JURISDICTION),
            ('page',         page),
            ('per_page',     per_page),
            ('include',      'links'),
            ('include',      'offices'),
        ])
        url = f"{BASE_URL}/people?{params}"
        data = fetch_url(url)

        if not data or 'results' not in data:
            print("Error: Could not fetch member list")
            break

        results = data['results']
        all_members.extend(results)

        pagination = data.get('pagination', {})
        max_page = pagination.get('max_page', 1)
        print(f"  Page {page}/{max_page}: {len(results)} members (total: {len(all_members)})")

        if page >= max_page:
            break
        page += 1

    return all_members


def normalize_member(raw):
    role = raw.get('current_role') or {}
    org = role.get('org_classification', '')

    if org == 'upper':
        chamber = 'Senate'
        chamber_slug = 'senate'
    elif org == 'lower':
        chamber = 'House of Representatives'
        chamber_slug = 'house'
    else:
        chamber = org
        chamber_slug = org.lower()

    offices = raw.get('offices', [])
    phone   = next((o.get('voice', '')   for o in offices if o.get('voice')),   '')
    address = next((o.get('address', '') for o in offices if o.get('address')), '')
    # Use offices email first; fall back to top-level email field
    email   = next((o.get('email', '')   for o in offices if o.get('email')), '') or raw.get('email', '') or ''

    # Construct URL from extras.georgia_id — most reliable source, available on every member
    extras     = raw.get('extras', {})
    georgia_id = extras.get('georgia_id')
    if georgia_id and chamber_slug in ('house', 'senate'):
        website = f"https://www.legis.ga.gov/members/{chamber_slug}/{georgia_id}"
    else:
        # Fall back to links: prefer legis.ga.gov, discard stale house/senate.ga.gov URLs
        links = raw.get('links', [])
        website = ''
        for link in links:
            url = link.get('url', '')
            if 'legis.ga.gov' in url:
                website = url.split('?')[0]
                break
        if not website:
            for link in links:
                url = link.get('url', '')
                if 'house.ga.gov' not in url and 'senate.ga.gov' not in url and url:
                    website = url
                    break

    birth_date = raw.get('birth_date', '') or ''
    birth_year = int(birth_date[:4]) if len(birth_date) >= 4 else None

    term_start     = role.get('start_date', '') or ''
    term_start_year = int(term_start[:4]) if len(term_start) >= 4 else None

    district_str = role.get('district', '')
    try:
        district = int(district_str)
    except (ValueError, TypeError):
        district = district_str

    return {
        'id':               raw.get('id', ''),
        'name':             raw.get('name', ''),
        'firstName':        raw.get('given_name', ''),
        'lastName':         raw.get('family_name', ''),
        'party':            raw.get('party', ''),
        'chamber':          chamber,
        'district':         district,
        'title':            role.get('title', ''),
        'imageUrl':         raw.get('image') or '',
        'phone':            phone,
        'address':          address,
        'email':            email,
        'officialWebsiteUrl': website,
        'birthDate':        birth_date,
        'birthYear':        birth_year,
        'termStart':        term_start,
        'termStartYear':    term_start_year,
    }


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    print("Fetching Georgia General Assembly members from Open States API...")
    raw_members = get_all_members()

    if not raw_members:
        print("Error: No members fetched")
        sys.exit(1)

    print(f"Normalizing {len(raw_members)} members...")
    members = [normalize_member(m) for m in raw_members]

    # Apply manual overrides (keyed by OCD member ID)
    overrides_file = os.path.join(os.path.dirname(OUTPUT_FILE), 'ga-members-overrides.json')
    if os.path.exists(overrides_file):
        with open(overrides_file, encoding='utf-8') as f:
            overrides = json.load(f)
        applied = 0
        for member in members:
            patch = overrides.get(member['id'])
            if patch:
                member.update({k: v for k, v in patch.items() if not k.startswith('_')})
                applied += 1
        print(f"  Applied overrides to {applied} member(s)")

    senate = [m for m in members if m['chamber'] == 'Senate']
    house  = [m for m in members if m['chamber'] == 'House of Representatives']
    print(f"  Senate: {len(senate)}  |  House: {len(house)}  |  Total: {len(members)}")

    output_data = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source':      'Open States API',
            'jurisdiction': 'Georgia',
            'count':       len(members),
        },
        'members': members,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully wrote {len(members)} GA members to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
