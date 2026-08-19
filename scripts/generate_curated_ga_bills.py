#!/usr/bin/env python3
"""
Generate curated-ga-bill-votes.json from Open States API.
Reads assets/data/curated-ga-bills.json (maintainer-controlled list) and fetches
vote data, party tallies, and bill metadata for each entry.
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
from lib.ga_voters import (VOTING_CHAMBERS, MemberIndex, event_chamber, new_stats,
                           resolve_voter, summarize)

API_KEY = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"

CURATED_BILLS_FILE = "assets/data/curated-ga-bills.json"
GA_MEMBERS_FILE    = "assets/data/ga-members.json"
OUTPUT_FILE        = sys.argv[1] if len(sys.argv) > 1 else "assets/data/curated-ga-bill-votes.json"


def fetch_url(url, retries=3, backoff=5):
    """Fetch JSON from Open States. Returns None on failure.

    Delegates to lib.http so the 429/5xx retry policy lives in one place. This
    function previously retried 5xx only — and since Open States signals quota
    exhaustion with 429, the one status it refused to retry was the one this
    daily job was most likely to hit. See CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    print(f"  GET {url[:120]}")
    return fetch_json(url, headers={
        'X-API-Key': API_KEY or '',
        'Accept': 'application/json',
    }, retries=retries, backoff=backoff, redact=API_KEY)


def build_party_lookup():
    """Return {ocd-person-id: party} from ga-members.json."""
    with open(GA_MEMBERS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    lookup = {m['id']: m['party'] for m in data.get('members', []) if m.get('id')}
    print(f"  Loaded party data for {len(lookup)} members")
    return lookup


def extract_roll_number(motion_text):
    """Parse roll number from 'House Vote #56 - ...' motion text."""
    if not motion_text:
        return None
    m = re.search(r'#(\d+)', motion_text)
    return int(m.group(1)) if m else None


def select_passage_vote(votes, chamber_classification, override_roll=None):
    """
    Select the final passage vote for a chamber from a list of vote events.
    Uses highest roll number to pick the latest passage vote (handles substitute votes).
    override_roll pins to a specific roll number from curated-ga-bills.json voteOverride.
    """
    chamber_votes = [
        v for v in votes
        if (v.get('organization') or {}).get('classification') == chamber_classification
        and v.get('motion_classification') == ['passage']
    ]
    if not chamber_votes:
        return None

    if override_roll is not None:
        for v in chamber_votes:
            if extract_roll_number(v.get('motion_text')) == override_roll:
                return v
        print(f"  WARNING: voteOverride #{override_roll} not found — falling back to auto-detect")

    return max(chamber_votes, key=lambda v: extract_roll_number(v.get('motion_text')) or -1)


def pick_full_text_url(versions):
    """
    Select the As Passed bill text PDF from versions[].
    Prefers a version whose note contains '/AP' (As Passed).
    Falls back to the last version with any PDF link.
    """
    if not versions:
        return ''
    for v in versions:
        note = v.get('note', '')
        if '/AP' in note:
            for link in v.get('links', []):
                if link.get('media_type') == 'application/pdf':
                    return link['url']
    for v in reversed(versions):
        for link in v.get('links', []):
            if link.get('media_type') == 'application/pdf':
                return link['url']
    return ''


def build_vote_record(vote_event, party_lookup, member_index=None, stats=None):
    """
    Build the standardized vote record for one chamber from a raw Open States vote event.

    Each roll-call row is resolved to a member id via lib.ga_voters.resolve_voter,
    which validates `voter.id` against ga-members.json and falls back to matching
    (chamber, name) when the id is missing *or* unresolvable. Keying on the raw
    `voter.id` with no validation is what let 21 deprecated ids orphan 38 sitting
    legislators from every key vote. See CODEBASE-REVIEW-2026-08-18.md 1.5.
    """
    member_votes = {}
    chamber = event_chamber(vote_event.get('motion_text'),
                            vote_event.get('organization'))

    for pv in vote_event.get('votes', []):
        voter  = pv.get('voter') or {}
        option = pv.get('option', '')  # 'yes', 'no', 'abstain', 'other'

        member_id, how = resolve_voter(
            voter.get('id'),
            pv.get('voter_name') or voter.get('name'),
            chamber,
            member_index,
        )
        if stats is not None:
            stats[how] += 1
        if member_id:
            member_votes[member_id] = option

    # Tally from the de-duplicated roster, not per row. Open States occasionally
    # lists the same voter twice in one event, and `member_votes` collapses that
    # while a per-row counter did not — every one of the 9 curated Senate roll
    # calls published `sum(partyTally) == roster + 1`. Resolving ghost ids onto
    # members who are already present makes counting per row wrong in a second
    # way, so this has to be derived from the final mapping either way.
    # See CODEBASE-REVIEW-2026-08-18.md 3.5.
    party_tally = {
        'Democratic':  {'yea': 0, 'nay': 0, 'other': 0},
        'Republican':  {'yea': 0, 'nay': 0, 'other': 0},
        'Independent': {'yea': 0, 'nay': 0, 'other': 0},
    }
    for member_id, option in member_votes.items():
        party = party_lookup.get(member_id)
        if party and party in party_tally:
            bucket = 'yea' if option == 'yes' else ('nay' if option == 'no' else 'other')
            party_tally[party][bucket] += 1

    return {
        'rollNumber':  extract_roll_number(vote_event.get('motion_text')),
        'date':        vote_event.get('start_date', ''),
        'motionText':  vote_event.get('motion_text', ''),
        'result':      vote_event.get('result', ''),
        'partyTally':  party_tally,
        'memberVotes': member_votes,
    }


def fetch_bill(entry, party_lookup, member_index=None, stats=None):
    """Fetch and process one curated bill entry. Returns a bill record dict or None."""
    session    = entry['session']
    identifier = entry['identifier']

    params = urllib.parse.urlencode([
        ('jurisdiction', GA_JURISDICTION),
        ('session',      session),
        ('identifier',   identifier),
        ('include',      'votes'),
        ('include',      'abstracts'),
        ('include',      'versions'),
    ])
    data = fetch_url(f"{BASE_URL}/bills?{params}")

    if not data or not data.get('results'):
        print(f"  WARNING: Not found — session={session!r} identifier={identifier!r}")
        print(f"           Verify the session string matches Open States exactly.")
        return None

    bill = data['results'][0]
    all_votes = bill.get('votes', [])
    overrides = entry.get('voteOverride') or {}

    house_event  = select_passage_vote(all_votes, 'lower', overrides.get('house'))
    senate_event = select_passage_vote(all_votes, 'upper', overrides.get('senate'))

    votes = {}
    if house_event:
        votes['house']  = build_vote_record(house_event,  party_lookup, member_index, stats)
    if senate_event:
        votes['senate'] = build_vote_record(senate_event, party_lookup, member_index, stats)

    if not votes:
        print(f"  WARNING: No passage votes found for {identifier} ({session})")

    abstracts = bill.get('abstracts', [])
    summary   = entry.get('summaryOverride') or (abstracts[0].get('abstract', '') if abstracts else '')

    # Construct openstatesUrl from bill identifier (strip spaces for URL)
    openstates_url = f"https://openstates.org/ga/bills/{session}/{identifier.replace(' ', '')}/"

    print(f"  OK — {len(votes)} chamber vote(s)  |  summary: {'override' if entry.get('summaryOverride') else 'API'}")

    return {
        'id':           bill.get('id', ''),
        'session':      session,
        'identifier':   identifier,
        'title':        bill.get('title', ''),
        'summary':      summary,
        'status':       bill.get('latest_action_description', ''),
        'statusDate':   bill.get('latest_action_date', ''),
        'openstatesUrl': openstates_url,
        'fullTextUrl':  pick_full_text_url(bill.get('versions', [])),
        'votes':        votes,
    }


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    with open(CURATED_BILLS_FILE, encoding='utf-8') as f:
        curated = json.load(f)
    bill_list = curated.get('ga', [])
    print(f"Processing {len(bill_list)} curated bills...\n")

    print("Loading member party data...")
    party_lookup = build_party_lookup()

    # Prior records, so a bill that times out keeps its last-known data instead of
    # vanishing from the site. Keyed by (session, identifier) because the curated list
    # spans sessions and identifiers repeat across them (e.g. "SB 233" in 2023_24).
    prior = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding='utf-8') as f:
                for b in json.load(f).get('bills', []):
                    prior[(b.get('session'), b.get('identifier'))] = b
            print(f"Loaded {len(prior)} previously published record(s) as fallback.")
        except Exception as e:
            print(f"  Could not read existing {OUTPUT_FILE}: {e}")

    member_index = MemberIndex(GA_MEMBERS_FILE)
    print(f"  Loaded {len(member_index)} members for voter-id validation")
    voter_stats = new_stats()

    results  = []
    failed   = []
    retained = []
    for entry in bill_list:
        label = entry.get('_name') or entry['identifier']
        print(f"\n--- {label} ({entry['identifier']}, {entry['session']}) ---")
        record = fetch_bill(entry, party_lookup, member_index, voter_stats)
        if record:
            results.append(record)
        else:
            fallback = prior.get((entry.get('session'), entry['identifier']))
            if fallback:
                results.append(fallback)
                retained.append(entry['identifier'])
                print(f"  Kept previously published record for {entry['identifier']}")
            else:
                failed.append(entry['identifier'])
        time.sleep(7)  # Open States rate limit is 10 req/min — 7s keeps well under it

    # Coverage is the metric that actually matters to a reader: a legislator with
    # no key votes looks like someone who never voted. Recording it in metadata
    # lets validate_data_update.py catch a regression as a delta, instead of
    # needing a hardcoded floor that goes stale every session.
    voted = {mid for rec in results for v in rec.get('votes', {}).values()
             for mid in (v.get('memberVotes') or {})}
    sitting = [m for m in member_index.by_id.values()
               if not m.get('status') and m.get('chamber') in VOTING_CHAMBERS]
    silent = sorted(m['name'] for m in sitting if m['id'] not in voted)

    output = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source':      'Open States API',
            'count':       len(results),
            'sittingLegislators':    len(sitting),
            'legislatorsWithVotes':  len(sitting) - len(silent),
            # Voter-resolution outcomes, so a regression is visible in the data
            # rather than showing up as legislators quietly missing key votes.
            # ghostVoterIds > 0 means an id was present, absent from
            # ga-members.json, and not recoverable by name — those votes are
            # dropped. See CODEBASE-REVIEW-2026-08-18.md 1.5.
            'voterResolution':     dict(voter_stats),
            'ghostVoterIds':       voter_stats['ghost'],
            'unresolvedVoterRows': voter_stats['unresolved'],
            'nameFallbackResolved': voter_stats['name'],
        },
        'bills': results,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(results)} bill records to {OUTPUT_FILE}")
    print(f"Voter resolution: {summarize(voter_stats)}")
    print(f"Coverage: {len(sitting) - len(silent)}/{len(sitting)} sitting legislators "
          f"have at least one curated vote")
    if silent:
        print(f"  {len(silent)} with none: {', '.join(silent[:10])}"
              + (' ...' if len(silent) > 10 else ''))

    if voter_stats['ghost'] or voter_stats['unresolved']:
        print(f"WARNING: {voter_stats['ghost']} row(s) carried an OCD person id that is not "
              f"in {GA_MEMBERS_FILE} and could not be matched by name, and "
              f"{voter_stats['unresolved']} row(s) had no usable id or name. "
              f"Those votes are omitted, so the affected legislators will show no key "
              f"votes.\n"
              f"  Fix by adding the member to ga-members.json (or an alias to "
              f"LEGACY_PERSON_ID_MAP in scripts/lib/ga_voters.py) and re-running.")

    # Tolerate the odd transient miss, fail on a real outage.
    #
    # Open States read timeouts are frequent enough that failing the whole daily job
    # over one slow request threw away the other bills' fresh data too. A bill that
    # times out now keeps its previously published record, so the site never loses a
    # curated bill — but a run that can't fetch most of the list still fails, so stale
    # data is never quietly presented as current.
    if retained:
        print(f"NOTE: {len(retained)} bill(s) served from previously published data: "
              f"{', '.join(retained)}")
        print("  If the same bill is retained run after run, check that its session and "
              "identifier in curated-ga-bills.json still match Open States.")

    if failed:
        print(f"WARNING: {len(failed)} of {len(bill_list)} bill(s) could not be fetched "
              f"and have no previous record: {', '.join(failed)}")
        sys.exit(1)

    if len(retained) > len(bill_list) // 2:
        print(f"\nERROR: more than half the curated list ({len(retained)}/{len(bill_list)}) "
              f"came from cache — treating this as an API outage rather than publishing "
              f"a mostly-stale file.")
        sys.exit(1)


if __name__ == '__main__':
    main()
