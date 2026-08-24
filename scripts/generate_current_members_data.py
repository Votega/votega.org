#!/usr/bin/env python3
"""
Generate current-members.json from Congress.gov API
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import quote
import yaml
from datetime import datetime

from lib.http import fetch_bytes, fetch_json

# Configuration
API_KEY = os.environ.get('CONGRESS_API_KEY')
BASE_URL = "https://api.congress.gov/v3"
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/current-members.json"
LEGISLATORS_BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"

def fetch_url(url, retries=3, backoff=5):
    """Fetch data from Congress.gov API with error handling.
    Retries on 429/5xx only — 4xx errors are non-retryable client errors.

    The retry logic that used to live here is now lib.http.fetch_json, which
    was promoted from this function: it was the one implementation in the repo
    that already matched the policy in CLAUDE.md. See
    CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    if 'api_key=' not in url:
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}api_key={API_KEY}"

    safe_url = url.replace(API_KEY, "***") if API_KEY else url
    print(f"Fetching: {safe_url[:100]}...")

    return fetch_json(url, headers={'Accept': 'application/json'},
                      retries=retries, backoff=backoff,
                      redact=API_KEY, label=safe_url)

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
            # Only include positions explicitly marked as current
            if position.get('current') is True:
                current_leadership.append({
                    'title': position.get('type', position.get('title', 'Unknown')),
                    'congress': position.get('congress', ''),
                    'current': position.get('current', True)
                })
    
    return current_leadership

def fetch_yaml(url):
    """Fetch and parse a YAML file from a URL (no API key needed).

    Now retries via lib.http; previously a single transient failure fetching
    the congress-legislators YAML silently dropped that enrichment source.
    """
    print(f"Fetching YAML: {url}...")
    raw = fetch_bytes(url, label=url)
    if raw is None:
        return None
    try:
        return yaml.safe_load(raw.decode('utf-8'))
    except Exception as e:
        print(f"Error parsing YAML {url}: {e}")
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
        title     = bill.get('title') or ''
        if not bill_type or not bill_num or not title:
            continue
        slug = BILL_TYPE_SLUG.get(bill_type, bill_type.lower())
        bill_url = f"https://www.congress.gov/bill/{current_congress}th-congress/{slug}/{bill_num}"
        result.append({
            'type':           bill_type,
            'number':         bill_num,
            'title':          title,
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


def build_profile_enrichment():
    """Fetch congress-legislators id/bio + social-media YAML, keyed by bioguide.

    Returns {bioguide: {birthday, gender, externalLinks[], socialLinks[]}}, where
    each *Links entry is {"label", "url"} ready to render. congress-legislators
    is the canonical, public-domain (CC0) crosswalk of a member's identifiers
    across reference sites; the Congress.gov API carries none of these. Two
    separate YAML files:
      - legislators-current.yaml       id.{wikipedia,ballotpedia,opensecrets,
                                       govtrack}, bio.{birthday,gender}
      - legislators-social-media.yaml  social.{twitter,facebook,instagram,youtube*}

    Missing/failed fetches degrade to {} so the build never breaks on this
    optional enrichment; the caller only overwrites fields it actually got.
    """
    result = {}

    leg = fetch_yaml(f"{LEGISLATORS_BASE}/legislators-current.yaml")
    if leg:
        for person in leg:
            ids = person.get('id') or {}
            bio = person.get('bio') or {}
            bioguide = ids.get('bioguide')
            if not bioguide:
                continue
            links = []
            if ids.get('wikipedia'):
                slug = quote(ids['wikipedia'].replace(' ', '_'), safe='_()')
                links.append({'label': 'Wikipedia', 'url': f"https://en.wikipedia.org/wiki/{slug}"})
            if ids.get('ballotpedia'):
                slug = quote(ids['ballotpedia'].replace(' ', '_'), safe='_()')
                links.append({'label': 'Ballotpedia', 'url': f"https://ballotpedia.org/{slug}"})
            if ids.get('opensecrets'):
                links.append({'label': 'OpenSecrets',
                              'url': f"https://www.opensecrets.org/members-of-congress/summary?cid={ids['opensecrets']}"})
            if ids.get('govtrack'):
                links.append({'label': 'GovTrack',
                              'url': f"https://www.govtrack.us/congress/members/{ids['govtrack']}"})
            result[bioguide] = {
                'birthday': bio.get('birthday') or None,
                'gender': bio.get('gender') or None,
                'externalLinks': links,
            }
    else:
        print("Warning: legislators-current.yaml unavailable — profile links skipped")

    social = fetch_yaml(f"{LEGISLATORS_BASE}/legislators-social-media.yaml")
    if social:
        for person in social:
            ids = person.get('id') or {}
            bioguide = ids.get('bioguide')
            s = person.get('social') or {}
            if not bioguide:
                continue
            slinks = []
            if s.get('twitter'):
                slinks.append({'label': 'X (Twitter)', 'url': f"https://x.com/{s['twitter']}"})
            if s.get('facebook'):
                slinks.append({'label': 'Facebook', 'url': f"https://www.facebook.com/{s['facebook']}"})
            if s.get('instagram'):
                slinks.append({'label': 'Instagram', 'url': f"https://www.instagram.com/{s['instagram']}"})
            # Prefer the stable channel ID over the legacy /user/ vanity name.
            if s.get('youtube_id'):
                slinks.append({'label': 'YouTube', 'url': f"https://www.youtube.com/channel/{s['youtube_id']}"})
            elif s.get('youtube'):
                slinks.append({'label': 'YouTube', 'url': f"https://www.youtube.com/user/{s['youtube']}"})
            if slinks:
                result.setdefault(bioguide, {})['socialLinks'] = slinks
    else:
        print("Warning: legislators-social-media.yaml unavailable — social links skipped")

    return result


def enrich_member_data(bioguideId, basic_member):
    """Fetch and enrich member data. Returns (member, success)."""
    member_details = get_member_details(bioguideId)

    if not member_details:
        print(f"Warning: Could not fetch details for {bioguideId}, using basic data")
        basic_member['leadership'] = []
        basic_member['contactInfo'] = {}
        basic_member['officialWebsiteUrl'] = None
        basic_member['birthYear'] = None
        basic_member['currentMember'] = None
        basic_member['firstName'] = None
        basic_member['lastName'] = None
        basic_member['dataUpdatedAt'] = datetime.now().isoformat()
        return basic_member, False

    basic_member['leadership'] = extract_leadership(member_details)
    basic_member['contactInfo'] = member_details.get('addressInformation', {})
    basic_member['officialWebsiteUrl'] = member_details.get('officialWebsiteUrl') or None
    basic_member['birthYear'] = member_details.get('birthYear') or None
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

    return basic_member, True

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
    enrichment_failures = 0
    for i, member in enumerate(members):
        bioguideId = member.get('bioguideId', '')
        print(f"  Processing {i+1}/{len(members)}: {member.get('name', 'Unknown')} ({bioguideId})")
        enriched_member, ok = enrich_member_data(bioguideId, member)
        enriched_members.append(enriched_member)
        if not ok:
            enrichment_failures += 1

        if (i + 1) % 5 == 0:
            print(f"  Progress: {i+1}/{len(members)} members processed")

    if enrichment_failures:
        print(f"Warning: {enrichment_failures}/{len(members)} member(s) failed detail enrichment (missing name/currentMember data)")
        failure_rate = enrichment_failures / len(members)
        if enrichment_failures > 5 and failure_rate > 0.05:
            print(f"Error: enrichment failure rate too high ({enrichment_failures}/{len(members)}, {failure_rate:.1%}) — likely an API outage. Not committing.")
            sys.exit(1)

    # Drop members Congress.gov reports as no longer serving.
    #
    # get_current_members() filters on term endYear >= current year, which correctly
    # keeps everyone whose term runs through this year but cannot catch a seat vacated
    # mid-term by death, resignation, or expulsion — those members keep an endYear of
    # the current year and were being published as sitting members.
    #
    # Only `is False` is dropped: enrich_member_data() sets currentMember to None when
    # the detail lookup fails, and an API hiccup must not silently delete a member.
    departed = [m for m in enriched_members if m.get('currentMember') is False]
    if departed:
        print(f"Removing {len(departed)} member(s) Congress.gov reports as no longer serving:")
        for m in departed:
            print(f"  - {m.get('name', 'Unknown')} ({m.get('state')}, {m.get('bioguideId')})")
        # A large jump means the flag or the API changed, not that Congress emptied out.
        if len(departed) > 25:
            print(f"Error: {len(departed)} members flagged as departed — implausible. Not committing.")
            sys.exit(1)
        enriched_members = [m for m in enriched_members if m.get('currentMember') is not False]

    print("Fetching committee memberships...")
    committee_lookup = get_committee_memberships()
    for member in enriched_members:
        member['committees'] = committee_lookup.get(member.get('bioguideId', ''), [])
    committees_count = sum(1 for m in enriched_members if m.get('committees'))
    print(f"Members with committee data: {committees_count}")

    # Enrich with congress-legislators reference links + biographical detail
    # (Wikipedia/Ballotpedia/OpenSecrets/GovTrack, full birthday, gender, socials).
    # Additive and optional: only fields actually returned are written, so a
    # failed fetch leaves members exactly as Congress.gov provided them.
    print("Enriching with congress-legislators profile links & bio...")
    profile_lookup = build_profile_enrichment()
    profile_matched = 0
    for member in enriched_members:
        e = profile_lookup.get(member.get('bioguideId', ''))
        if not e:
            continue
        profile_matched += 1
        if e.get('birthday'):
            member['birthday'] = e['birthday']
        if e.get('gender'):
            member['gender'] = e['gender']
        if e.get('externalLinks'):
            member['externalLinks'] = e['externalLinks']
        if e.get('socialLinks'):
            member['socialLinks'] = e['socialLinks']
    print(f"Members enriched with profile data: {profile_matched}/{len(enriched_members)}")

    # Create output structure
    output_data = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source': 'Congress.gov API',
            'count': len(enriched_members),
            'apiVersion': 'v3',
            'enrichmentFailures': enrichment_failures
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
