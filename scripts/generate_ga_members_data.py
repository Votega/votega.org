#!/usr/bin/env python3
"""
Generate ga-members.json from Open States API (Georgia General Assembly).
Requires OPENSTATES_API_KEY environment variable.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

from lib.http import fetch_json

OCD_ID_RE = re.compile(r'^ocd-person/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-members.json"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"


def fetch_url(url, retries=3, backoff=5):
    """Fetch JSON from Open States. Returns None on failure.

    Delegates to lib.http. Like generate_curated_ga_bills.py, this retried 5xx
    only — so the daily members job would give up immediately on the HTTP 429
    that Open States returns when the shared 250 req/day quota is exhausted.
    See CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    print(f"Fetching: {url[:120]}...")
    return fetch_json(url, headers={
        'X-API-Key': API_KEY or '',
        'Accept': 'application/json',
    }, retries=retries, backoff=backoff, redact=API_KEY)


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


def get_committee_memberships():
    """
    Fetch all GA legislative committees and return a mapping of
    OCD person ID -> sorted list of committee names.
    Uses GET /v3/committees (memberships included by default).
    """
    by_person = {}
    page = 1
    per_page = 20  # /committees endpoint max is 20

    while True:
        params = urllib.parse.urlencode([
            ('jurisdiction', GA_JURISDICTION),
            ('page',         page),
            ('per_page',     per_page),
            ('include',      'memberships'),
        ])
        url = f"{BASE_URL}/committees?{params}"
        data = fetch_url(url)

        if not data or 'results' not in data:
            print("  Warning: could not fetch committee data — committees will be empty")
            return None  # signals failure to caller

        for committee in data['results']:
            name = committee.get('name', '')
            memberships = committee.get('memberships', [])
            for m in memberships:
                pid = (m.get('person') or {}).get('id', '')
                if pid:
                    by_person.setdefault(pid, []).append(name)

        pagination = data.get('pagination', {})
        if page >= pagination.get('max_page', 1):
            break
        page += 1

    return {pid: sorted(names) for pid, names in by_person.items()}


def normalize_member(raw, committees_by_id=None):
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
    phone   = next((o.get('voice')   for o in offices if o.get('voice')),   None)
    address = next((o.get('address') for o in offices if o.get('address')), None)
    # Use offices email first; fall back to top-level email field
    email   = next((o.get('email')   for o in offices if o.get('email')), None) or raw.get('email') or None

    # Construct URL from extras.georgia_id — most reliable source, available on every member
    extras     = raw.get('extras', {})
    georgia_id = extras.get('georgia_id')
    if georgia_id and chamber_slug in ('house', 'senate'):
        website = f"https://www.legis.ga.gov/members/{chamber_slug}/{georgia_id}"
    else:
        # Fall back to links: prefer legis.ga.gov, discard stale house/senate.ga.gov URLs
        links = raw.get('links', [])
        website = None
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

    birth_date = raw.get('birth_date') or None
    birth_year = int(birth_date[:4]) if birth_date and len(birth_date) >= 4 else None

    term_start      = role.get('start_date') or None
    term_start_year = int(term_start[:4]) if term_start and len(term_start) >= 4 else None

    district_str = role.get('district', '')
    try:
        district = int(district_str)
    except (ValueError, TypeError):
        district = district_str or None  # empty string → None

    return {
        'id':               raw.get('id', ''),
        'name':             raw.get('name', ''),
        'firstName':        raw.get('given_name', ''),
        'lastName':         raw.get('family_name', ''),
        'party':            raw.get('party') or None,  # empty string → None
        'chamber':          chamber,
        'district':         district,
        'title':            role.get('title', ''),
        'imageUrl':         raw.get('image') or None,
        'phone':            phone,
        'address':          address,
        'email':            email,
        'officialWebsiteUrl': website,
        'birthDate':        birth_date,
        'birthYear':        birth_year,
        'termStart':        term_start,
        'termStartYear':    term_start_year,
        'committees':       (committees_by_id or {}).get(raw.get('id', ''), []),
        # Numeric ID used only to construct officialWebsiteUrl (legis.ga.gov member
        # page). NOT a vote-join key — votes join on the OCD person `id` instead.
        'legisGaGovId':     georgia_id,
        # Departure status — set via overrides only; None means active
        'status':           None,
        'statusDate':       None,
        'statusNote':       None,
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

    print("Fetching committee memberships...")
    committees_by_id = get_committee_memberships()
    committees_available = committees_by_id is not None
    if not committees_available:
        committees_by_id = {}
    print(f"  Committee data found for {len(committees_by_id)} members")

    print(f"Normalizing {len(raw_members)} members...")
    members = [normalize_member(m, committees_by_id) for m in raw_members]

    # Apply manual overrides (keyed by OCD member ID or full member name)
    overrides_file = os.path.join(os.path.dirname(OUTPUT_FILE), 'ga-members-overrides.json')
    if os.path.exists(overrides_file):
        with open(overrides_file, encoding='utf-8') as f:
            overrides = json.load(f)

        # Split into ID-keyed (ocd-person/...) and name-keyed entries
        id_overrides   = {k: v for k, v in overrides.items() if k.startswith('ocd-person/')}
        name_overrides = {k.lower().strip(): v for k, v in overrides.items()
                          if not k.startswith('ocd-person/') and not k.startswith('_')}

        applied = 0
        for member in members:
            patch = id_overrides.get(member['id']) or name_overrides.get(member['name'].lower().strip())
            if patch:
                member.update({k: v for k, v in patch.items() if not k.startswith('_')})
                applied += 1
        print(f"  Applied overrides to {applied} member(s)")

        # Inject entirely new entries (e.g. vacant seats not tracked by Open States)
        injected = overrides.get('_inject', [])
        existing_ids = {m['id'] for m in members}
        for entry in injected:
            if entry.get('id') and entry['id'] not in existing_ids:
                clean_entry = {k: v for k, v in entry.items() if not k.startswith('_')}
                members.append(clean_entry)
                existing_ids.add(entry['id'])
        if injected:
            print(f"  Injected {len(injected)} new member(s) from _inject")

    senate = [m for m in members if m['chamber'] == 'Senate']
    house  = [m for m in members if m['chamber'] == 'House of Representatives']
    print(f"  Senate: {len(senate)}  |  House: {len(house)}  |  Total: {len(members)}")

    non_ocd = [m['id'] for m in members if m['id'] and not OCD_ID_RE.match(m['id'])]
    if non_ocd:
        print(f"  Note: {len(non_ocd)} member(s) have non-standard IDs (injected entries): {non_ocd[:5]}")

    output_data = {
        'metadata': {
            'generatedAt':        datetime.now().isoformat(),
            'source':             'Open States API',
            'jurisdiction':       'Georgia',
            'count':              len(members),
            'committeesAvailable': committees_available,
        },
        'members': members,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully wrote {len(members)} GA members to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
