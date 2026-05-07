#!/usr/bin/env python3
"""
Generate current-members.json from Congress.gov API
"""

import json
import os
import sys
import urllib.request
import urllib.error
import yaml
from datetime import datetime

# Configuration
API_KEY = os.environ.get('CONGRESS_API_KEY')
BASE_URL = "https://api.congress.gov/v3"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/current-members.json"
LEGISLATORS_BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"

def fetch_url(url):
    """Fetch data from Congress.gov API with error handling"""
    try:
        # Add API key as query parameter (required by Congress.gov API)
        if 'api_key=' not in url:
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}api_key={API_KEY}"
        
        safe_url = url.replace(API_KEY, "***") if API_KEY else url
        print(f"Fetching: {safe_url[:100]}...")
        
        req = urllib.request.Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'votega.org/1.0',
        })
        
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"Error fetching {url[:100]}: {e}")
        return None

def get_member_details(bioguideId):
    """Fetch detailed member data"""
    url = f"{BASE_URL}/member/{bioguideId}?format=json"
    data = fetch_url(url)
    if data and 'member' in data:
        return data['member']
    return None

def extract_leadership(member_data):
    """Extract leadership positions"""
    leadership = member_data.get('leadership', [])
    
    # Handle both list and dict with 'item' key
    if isinstance(leadership, dict):
        leadership = leadership.get('item', [])
    
    if not isinstance(leadership, list):
        leadership = [leadership] if leadership else []
    
    # Extract current leadership positions
    current_leadership = []
    for position in leadership:
        if isinstance(position, dict):
            # Include if marked as current OR if no 'current' field (assume current)
            if position.get('current') == True or 'current' not in position:
                current_leadership.append({
                    'title': position.get('type', position.get('title', 'Unknown')),
                    'congress': position.get('congress', ''),
                    'current': position.get('current', True)
                })
    
    return current_leadership

def fetch_yaml(url):
    """Fetch and parse a YAML file from a URL (no API key needed)."""
    try:
        print(f"Fetching YAML: {url}...")
        req = urllib.request.Request(url, headers={'User-Agent': 'votega.org/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return yaml.safe_load(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching YAML {url}: {e}")
        return None

BILL_TYPE_SLUG = {
    'HR':      'house-bill',
    'S':       'senate-bill',
    'HRES':    'house-resolution',
    'SRES':    'senate-resolution',
    'HJRES':   'house-joint-resolution',
    'SJRES':   'senate-joint-resolution',
    'HCONRES': 'house-concurrent-resolution',
    'SCONRES': 'senate-concurrent-resolution',
}

def get_sponsored_legislation(bioguideId, current_congress=119, limit=20):
    """Fetch first page of sponsored legislation for a member, filtered to current Congress."""
    url = f"{BASE_URL}/member/{bioguideId}/sponsored-legislation?limit={limit}&format=json"
    data = fetch_url(url)
    if not data:
        return []

    bills = data.get('sponsoredLegislation', [])
    if not isinstance(bills, list):
        bills = []

    result = []
    for bill in bills:
        if bill.get('congress') != current_congress:
            continue
        bill_type = bill.get('type') or ''
        bill_num  = bill.get('number') or ''
        slug = BILL_TYPE_SLUG.get(bill_type, bill_type.lower())
        bill_url = f"https://www.congress.gov/bill/{current_congress}th-congress/{slug}/{bill_num}"
        result.append({
            'type':           bill_type,
            'number':         bill_num,
            'title':          bill.get('title', ''),
            'introducedDate': bill.get('introducedDate', ''),
            'latestAction':   bill.get('latestAction') or {},
            'policyArea':     (bill.get('policyArea') or {}).get('name') or None,
            'billUrl':        bill_url,
        })

    return result

def get_committee_memberships():
    """Fetch committee memberships from unitedstates/congress-legislators.
    Returns a dict keyed by bioguideId -> list of full committee names."""

    # Build committee code -> name lookup (full committees only, not subcommittees)
    committees_data = fetch_yaml(f"{LEGISLATORS_BASE}/committees-current.yaml")
    if not committees_data:
        print("Warning: Could not fetch committees data, skipping committee enrichment")
        return {}

    committees_lookup = {}
    for committee in committees_data:
        thomas_id = committee.get('thomas_id', '')
        name = committee.get('name', '')
        if thomas_id and name:
            committees_lookup[thomas_id] = name
    print(f"Loaded {len(committees_lookup)} committees")

    # Fetch membership: { committee_code: [ {bioguide, name, ...}, ... ] }
    membership_data = fetch_yaml(f"{LEGISLATORS_BASE}/committee-membership-current.yaml")
    if not membership_data:
        print("Warning: Could not fetch committee membership data, skipping committee enrichment")
        return {}

    # Invert to bioguide -> [committee names]
    lookup = {}
    for code, members in membership_data.items():
        committee_name = committees_lookup.get(code)
        if not committee_name or not isinstance(members, list):
            continue
        for member in members:
            bioguide = member.get('bioguide', '')
            if not bioguide:
                continue
            if bioguide not in lookup:
                lookup[bioguide] = []
            if committee_name not in lookup[bioguide]:
                lookup[bioguide].append(committee_name)

    print(f"Built committee lookup for {len(lookup)} members")
    return lookup


def enrich_member_data(bioguideId, basic_member):
    """Fetch and enrich member data"""
    member_details = get_member_details(bioguideId)
    
    if not member_details:
        print(f"Warning: Could not fetch details for {bioguideId}, using basic data")
        basic_member['leadership'] = []
        basic_member['contactInfo'] = {}
        basic_member['officialWebsiteUrl'] = ''
        basic_member['birthYear'] = ''
        basic_member['dataUpdatedAt'] = datetime.now().isoformat()
        return basic_member
    
    basic_member['leadership'] = extract_leadership(member_details)
    basic_member['contactInfo'] = member_details.get('addressInformation', {})
    basic_member['officialWebsiteUrl'] = member_details.get('officialWebsiteUrl', '')
    basic_member['birthYear'] = member_details.get('birthYear', '')
    basic_member['currentMember'] = member_details.get('currentMember', False)
    basic_member['honorificName'] = member_details.get('honorificName', '')
    basic_member['firstName'] = member_details.get('firstName', '')
    basic_member['lastName'] = member_details.get('lastName', '')
    basic_member['sponsoredLegislation'] = member_details.get('sponsoredLegislation', {})
    basic_member['cosponsoredLegislation'] = member_details.get('cosponsoredLegislation', {})
    basic_member['dataUpdatedAt'] = datetime.now().isoformat()

    # Fetch recent sponsored bills only for GA delegation (avoids 500+ extra API calls)
    if basic_member.get('state') == 'Georgia':
        basic_member['recentSponsored'] = get_sponsored_legislation(bioguideId)

    return basic_member

def get_current_members():
    """Fetch all current members of Congress using pagination (max limit=250)"""
    all_members = []
    url = f"{BASE_URL}/member?limit=250&offset=0&format=json"

    while url:
        data = fetch_url(url)

        if not data or 'members' not in data:
            print("Error: Could not fetch member list")
            return []

        members_data = data['members']
        if isinstance(members_data, list):
            page_members = members_data
        elif isinstance(members_data, dict):
            page_members = members_data.get('member', [])
            if not isinstance(page_members, list):
                page_members = [page_members] if page_members else []
        else:
            page_members = []

        all_members.extend(page_members)
        print(f"Fetched {len(page_members)} members (total so far: {len(all_members)})")

        # Follow pagination next link
        next_url = data.get('pagination', {}).get('next', '')
        if not next_url and isinstance(members_data, dict):
            next_url = members_data.get('next', '')
        url = next_url or None

    print(f"Found {len(all_members)} members total")

    # Filter to only current members
    current_year = datetime.now().year
    current_members = []
    for member in all_members:
        terms = member.get('terms', {}).get('item', [])
        if terms:
            has_current_term = any(
                term.get('endYear') is None or term.get('endYear', 0) >= current_year
                for term in terms
            )
            if has_current_term:
                current_members.append(member)

    print(f"Filtered to {len(current_members)} current members")
    return current_members

def main():
    if not API_KEY:
        print("Error: CONGRESS_API_KEY environment variable not set")
        sys.exit(1)
    
    print("Fetching current Congress members...")
    members = get_current_members()
    
    if not members:
        print("Error: No members fetched")
        sys.exit(1)
    
    print("Enriching member data with leadership positions...")
    enriched_members = []
    for i, member in enumerate(members):
        bioguideId = member.get('bioguideId', '')
        print(f"  Processing {i+1}/{len(members)}: {member.get('name', 'Unknown')} ({bioguideId})")
        enriched_member = enrich_member_data(bioguideId, member)
        enriched_members.append(enriched_member)

        if (i + 1) % 5 == 0:
            print(f"  Progress: {i+1}/{len(members)} members processed")

    print("Fetching committee memberships...")
    committee_lookup = get_committee_memberships()
    for member in enriched_members:
        member['committees'] = committee_lookup.get(member.get('bioguideId', ''), [])
    committees_count = sum(1 for m in enriched_members if m.get('committees'))
    print(f"Members with committee data: {committees_count}")

    # Create output structure
    output_data = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source': 'Congress.gov API',
            'count': len(enriched_members),
            'apiVersion': 'v3'
        },
        'members': enriched_members
    }
    
    # Ensure output directory exists (simple approach)
    try:
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        print(f"Directory check passed for {OUTPUT_FILE}")
    except Exception as e:
        print(f"Directory creation error: {e}")
        sys.exit(1)
    
    # Write to file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"Successfully wrote {len(enriched_members)} members to {OUTPUT_FILE}")
    except Exception as e:
        print(f"Error writing file: {e}")
        sys.exit(1)
    
    # Print summary
    leadership_count = sum(1 for m in enriched_members if m.get('leadership'))
    print(f"Members with leadership positions: {leadership_count}")
    print(f"Members with committee data: {committees_count}")

if __name__ == '__main__':
    main()
