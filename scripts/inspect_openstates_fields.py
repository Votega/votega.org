#!/usr/bin/env python3
"""
Diagnostic script — inspects raw Open States API response fields for GA members.
Checks: other_identifiers, extras, updated_at, and top-level email.
Run manually or via the inspect-openstates-fields workflow.
Requires OPENSTATES_API_KEY environment variable.
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
SAMPLE_SIZE = 10  # how many members to inspect


def fetch_url(url):
    req = urllib.request.Request(url, headers={
        'X-API-Key': API_KEY,
        'Accept': 'application/json',
        'User-Agent': 'votega.org/1.0',
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY not set")
        sys.exit(1)

    params = urllib.parse.urlencode([
        ('jurisdiction', GA_JURISDICTION),
        ('page',         1),
        ('per_page',     SAMPLE_SIZE),
        ('include',      'other_identifiers'),
        ('include',      'links'),
        ('include',      'offices'),
    ])
    url = f"{BASE_URL}/people?{params}"

    print(f"Fetching {SAMPLE_SIZE} GA members with other_identifiers...\n")
    data = fetch_url(url)

    if not data or 'results' not in data:
        print("Error: no results returned")
        sys.exit(1)

    for member in data['results']:
        name        = member.get('name', 'Unknown')
        role        = member.get('current_role') or {}
        chamber     = role.get('org_classification', '')
        district    = role.get('district', '')
        updated_at  = member.get('updated_at', '')
        extras      = member.get('extras', {})
        email       = member.get('email', '')
        identifiers = member.get('other_identifiers', [])
        links       = member.get('links', [])

        print(f"{'='*60}")
        print(f"  {name}  ({chamber} district {district})")
        print(f"  updated_at       : {updated_at}")
        print(f"  top-level email  : {email!r}")
        print(f"  extras           : {json.dumps(extras) if extras else '(empty)'}")

        if identifiers:
            print(f"  other_identifiers:")
            for ident in identifiers:
                print(f"    scheme={ident.get('scheme')!r}  id={ident.get('identifier')!r}")
        else:
            print(f"  other_identifiers: (none)")

        if links:
            print(f"  links:")
            for link in links:
                print(f"    {link.get('url')}")
        else:
            print(f"  links: (none)")

    print(f"\nDone. Inspected {len(data['results'])} members.")

    # ── Test 1: /organizations endpoint ────────────────────────────────────
    print("\n" + "="*60)
    print("Test 1: /organizations?classification=committee&include=memberships")

    org_params = urllib.parse.urlencode([
        ('jurisdiction',   GA_JURISDICTION),
        ('classification', 'committee'),
        ('page',           1),
        ('per_page',       2),
        ('include',        'memberships'),
    ])
    org_url = f"{BASE_URL}/organizations?{org_params}"
    print(f"URL: {org_url}\n")

    try:
        org_data = fetch_url(org_url)
        orgs = org_data.get('results', [])
        print(f"Returned {len(orgs)} org(s) on page 1 of {org_data.get('pagination', {}).get('max_page', '?')}")
        if orgs:
            print("First org keys:", list(orgs[0].keys()))
            print(json.dumps(orgs[0], indent=2)[:2000])
        else:
            print("No organizations returned.")
    except Exception as e:
        print(f"Error: {e}")

    # ── Test 2: /organizations without include ───────────────────────────────
    print("\n" + "="*60)
    print("Test 2: /organizations?classification=committee (no include)")

    org_params2 = urllib.parse.urlencode([
        ('jurisdiction',   GA_JURISDICTION),
        ('classification', 'committee'),
        ('page',           1),
        ('per_page',       1),
    ])
    try:
        org_data2 = fetch_url(f"{BASE_URL}/organizations?{org_params2}")
        orgs2 = org_data2.get('results', [])
        if orgs2:
            print("First org keys:", list(orgs2[0].keys()))
            print(json.dumps(orgs2[0], indent=2)[:2000])
        else:
            print("No organizations returned.")
    except Exception as e:
        print(f"Error: {e}")

    # ── Test 3: single person fetch with include=memberships ────────────────
    print("\n" + "="*60)
    first_person_id = data['results'][0].get('id', '')
    print(f"Test 3: /people/{{id}}?include=memberships  (id={first_person_id})")

    try:
        person_url = f"{BASE_URL}/people/{first_person_id}?include=memberships"
        print(f"URL: {person_url}\n")
        person_data = fetch_url(person_url)
        print("Person keys:", list(person_data.keys()))
        memberships = person_data.get('memberships', [])
        print(f"Memberships count: {len(memberships)}")
        if memberships:
            print("First membership:", json.dumps(memberships[0], indent=2))
        else:
            print("No memberships returned.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    main()
