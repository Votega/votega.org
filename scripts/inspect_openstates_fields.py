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


if __name__ == '__main__':
    main()
