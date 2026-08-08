#!/usr/bin/env python3
"""
Generate ga-member-votes.json from Open States API (Georgia).
Requires OPENSTATES_API_KEY environment variable.

Open States API flow:
  1. Paginate GET /bills?jurisdiction=GA&session=2025_26&include=votes
  2. For each bill, collect vote events where motion_classification == ['passage']
  3. Each vote event's votes[] has voter.id (OCD person ID) — no name matching needed
     since ga-members.json already uses OCD person IDs.

To update for a new session: change GA_SESSION below.

Data-soundness invariants (enforced on every run and available offline via
`--sanitize`):
  - No duplicate roll calls per member (Open States occasionally lists the same
    voter twice within one vote event).
  - A member's recorded votes come only from their own chamber. Some member IDs
    are erroneously attached to the other chamber's roll calls upstream; those
    cross-chamber entries are dropped for any member whose chamber is known from
    ga-members.json.

Usage:
  python generate_ga_votes_data.py                 # fetch + write (needs API key)
  python generate_ga_votes_data.py --sanitize      # re-clean the existing file
                                                   # in place, no API key needed
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

API_KEY      = os.environ.get('OPENSTATES_API_KEY')
BASE_URL     = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
GA_SESSION   = "2025_26"
SESSION_NAME = "2025-2026 Regular Session"
MEMBERS_FILE = "assets/data/ga-members.json"

SANITIZE_ONLY = '--sanitize' in sys.argv
_positional   = [a for a in sys.argv[1:] if not a.startswith('--')]
OUTPUT_FILE   = _positional[0] if _positional else "assets/data/ga-member-votes.json"

DELAY = 7  # Open States free tier: 10 req/min — 7s keeps safely under

VOTE_MAP = {
    'yes':        'Yea',
    'no':         'Nay',
    'not voting': 'Not Voting',
    'abstain':    'Present',
    'absent':     'Absent',
    'excused':    'Excused',
    'other':      'Other',
}

# Open States occasionally re-issues a person a new OCD id mid-session, leaving
# their earlier votes stranded under the old id (which then never appears in
# ga-members.json and shows up as an unattributed "ghost" voter). Map old -> new
# here to fold them back into the current id. Identified 2026-07-24 via LegiScan
# roll-call cross-reference: identical Yea/Nay/Other pattern across every roll
# call shared with the current id (both are Speaker Jon Burns; by House custom
# a presiding officer votes only to break ties, so both ids show ~100% "Other").
LEGACY_PERSON_ID_MAP = {
    'ocd-person/4161e949-6ea2-4df9-8248-cabcf40286ae': 'ocd-person/64012657-d026-411c-9525-3232524a5145',  # Jon Burns
}


def remap_legacy_ids(member_votes):
    """Fold any LEGACY_PERSON_ID_MAP entries into their current id in place."""
    for old_id, current_id in LEGACY_PERSON_ID_MAP.items():
        if old_id not in member_votes:
            continue
        member_votes.setdefault(current_id, []).extend(member_votes.pop(old_id))
    return member_votes


def event_chamber(motion_text, organization=None):
    """Which chamber held a roll call: 'Senate', 'House of Representatives', or None."""
    cls = (organization or {}).get('classification')
    if cls == 'upper':
        return 'Senate'
    if cls == 'lower':
        return 'House of Representatives'
    mt = motion_text or ''
    if 'Senate' in mt:
        return 'Senate'
    if 'House' in mt:
        return 'House of Representatives'
    return None


def load_member_chambers(path=MEMBERS_FILE):
    """Map OCD person ID -> chamber from ga-members.json (ground truth for the
    chamber-consistency check). Returns {} if the file is missing/unreadable."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return {m['id']: m.get('chamber') for m in data.get('members', []) if m.get('id')}


def sanitize_member_votes(member_votes, votes_meta, member_chambers):
    """Enforce the data-soundness invariants on a memberVotes mapping.

    - De-duplicates roll calls per member (keeps the first-seen entry for each
      vote ID).
    - Drops cross-chamber entries for any member whose chamber is known: a
      Georgia legislator only votes in their own chamber, so a vote recorded in
      the other chamber is upstream contamination.

    Members whose chamber is unknown (e.g. former members not in ga-members.json)
    are de-duplicated but not chamber-filtered, since there is no ground truth to
    check them against. Returns (clean_member_votes, stats)."""
    clean = {}
    dup_dropped = 0
    cross_dropped = 0
    for voter_id, entries in member_votes.items():
        known = member_chambers.get(voter_id)
        seen = set()
        kept = []
        for entry in entries:
            vote_id = entry.get('voteId')
            if not vote_id or vote_id in seen:
                dup_dropped += 1
                continue
            seen.add(vote_id)
            if known:
                ec = event_chamber((votes_meta.get(vote_id) or {}).get('motionText'))
                if ec and ec != known:
                    cross_dropped += 1
                    continue
            kept.append(entry)
        if kept:
            clean[voter_id] = kept
    return clean, {'duplicateVotesDropped': dup_dropped, 'crossChamberDropped': cross_dropped}


def sanitize_existing(path):
    """Re-apply the soundness invariants to an already-generated file in place,
    without hitting the API. Used by `--sanitize`."""
    if not os.path.exists(path):
        print(f"Error: {path} not found — nothing to sanitize.")
        sys.exit(1)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    votes_meta = data.get('votes', {})
    raw        = data.get('memberVotes', {})
    if not raw:
        print("Error: no memberVotes in file — refusing to write.")
        sys.exit(1)

    member_chambers = load_member_chambers()
    raw = remap_legacy_ids(raw)
    clean, stats = sanitize_member_votes(raw, votes_meta, member_chambers)

    data['memberVotes'] = clean
    meta = data.setdefault('metadata', {})
    meta['sanitizedAt']          = datetime.now().isoformat()
    meta['duplicateVotesDropped'] = stats['duplicateVotesDropped']
    meta['crossChamberDropped']   = stats['crossChamberDropped']

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'), ensure_ascii=False)

    print(f"Sanitized {path}: dropped {stats['duplicateVotesDropped']} duplicate "
          f"and {stats['crossChamberDropped']} cross-chamber entries; "
          f"{len(clean)} members remain.")


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={
        'X-API-Key': API_KEY or '',
        'Accept':    'application/json',
        'User-Agent': 'votega.org/1.0',
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            print(f"  HTTP {e.code}: {body[:200]}")
            if e.code == 429 or e.code >= 500:
                wait = DELAY * attempt * 2
                print(f"  Retrying in {wait}s ({attempt}/{retries})...")
                time.sleep(wait)
                continue
            return None
        except Exception as e:
            # Includes socket/read timeouts — treat like a 429/5xx (the API is
            # likely overloaded or degraded) rather than a quick flat-interval
            # retry, since a bare 7s wait wasn't enough to ride out the two
            # consecutive full-timeout outages seen in production.
            print(f"  Error: {e}")
            if attempt < retries:
                wait = DELAY * attempt * 2
                print(f"  Retrying in {wait}s ({attempt}/{retries})...")
                time.sleep(wait)
                continue
            return None
    return None


def main():
    if SANITIZE_ONLY:
        sanitize_existing(OUTPUT_FILE)
        return

    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    votes_meta   = {}
    member_votes = {}
    page         = 1
    total_pages  = None
    bills_seen   = 0

    print(f"Fetching GA bills for session {GA_SESSION} (passage votes only)...")

    while True:
        params = urllib.parse.urlencode([
            ('jurisdiction', GA_JURISDICTION),
            ('session',      GA_SESSION),
            ('include',      'votes'),
            ('include',      'sources'),
            ('per_page',     20),
            ('page',         page),
        ])
        data = fetch(f"{BASE_URL}/bills?{params}")
        if not data:
            if total_pages is not None and page < total_pages:
                print(f"  Warning: early termination on page {page}/{total_pages} — {bills_seen} bills fetched, ~{(total_pages - page) * 20} bills may be missing")
            else:
                print(f"  Failed on page {page}, stopping.")
            break

        results = data.get('results', [])
        if not results:
            break

        bills_seen += len(results)

        for bill in results:
            identifier = bill.get('identifier', '')
            title      = bill.get('title', '')
            # Prefer official legis.ga.gov bill page; fall back to Open States
            bill_url = next(
                (s['url'] for s in bill.get('sources', []) if 'legis.ga.gov' in s.get('url', '')),
                f"https://openstates.org/ga/bills/{GA_SESSION}/{identifier.replace(' ', '')}/"
            )

            passage_events = [
                ve for ve in bill.get('votes', [])
                if ve.get('motion_classification') == ['passage']
            ]

            for ve in passage_events:
                ve_id = ve.get('id', '')
                if not ve_id or ve_id in votes_meta:
                    continue

                counts = {c['option']: c['value'] for c in ve.get('counts', [])}
                yea    = counts.get('yes', 0)
                nay    = counts.get('no', 0)
                result = 'Pass' if str(ve.get('result', '')).lower() == 'pass' else 'Fail'

                votes_meta[ve_id] = {
                    'bill':       identifier,
                    'billUrl':    bill_url,
                    'title':      title,
                    'motionText': ve.get('motion_text', ''),
                    'date':       ve.get('start_date', ''),
                    'yea':        yea,
                    'nay':        nay,
                    'result':     result,
                }

                for pv in ve.get('votes', []):
                    voter    = pv.get('voter') or {}
                    voter_id = voter.get('id')
                    if not voter_id:
                        continue
                    option     = pv.get('option', '').lower()
                    vote_label = VOTE_MAP.get(option, 'Other')
                    member_votes.setdefault(voter_id, []).append({
                        'voteId': ve_id,
                        'vote':   vote_label,
                    })

        pagination  = data.get('pagination', {})
        total_pages = pagination.get('max_page', 1)
        print(f"  Page {page}/{total_pages} — {bills_seen} bills, {len(votes_meta)} passage votes, {len(member_votes)} members with votes")

        if page >= total_pages:
            break
        page += 1
        time.sleep(DELAY)

    # Refuse to write (and let the workflow commit) an empty dataset. A total
    # API failure on page 1 previously fell through silently — the script
    # would print "Done. 0 passage votes..." and exit 0, overwriting nothing
    # locally only because a separate validation step downstream happened to
    # catch it. That's a fragile safety net; fail here directly so this script
    # is correct on its own regardless of how it's invoked.
    if bills_seen == 0:
        print("Error: fetched zero bills — the Open States API may be down or "
              "unreachable. Refusing to write an empty output file.")
        sys.exit(1)

    # Enforce data-soundness invariants: fold deprecated OCD ids into their
    # current id, de-duplicate roll calls, and drop cross-chamber contamination
    # before writing.
    member_chambers = load_member_chambers()
    member_votes = remap_legacy_ids(member_votes)
    member_votes, sanitize_stats = sanitize_member_votes(member_votes, votes_meta, member_chambers)
    print(f"  Sanitized: dropped {sanitize_stats['duplicateVotesDropped']} duplicate "
          f"and {sanitize_stats['crossChamberDropped']} cross-chamber vote entries")

    # Fail here rather than writing an empty file and letting the workflow's validation
    # catch it later. A failed first page breaks out of the fetch loop above, and without
    # this guard the script exits 0 — so the job failed several steps downstream with the
    # actual HTTP error scrolled far off the top of the log.
    if not votes_meta:
        print(f"\nError: no passage votes collected for session {GA_SESSION} after "
              f"{bills_seen} bills. See the HTTP status printed above — a 401/403 means "
              f"the OPENSTATES_API_KEY secret, and a 400/404 usually means the session "
              f"identifier '{GA_SESSION}' is no longer accepted by /bills.", file=sys.stderr)
        sys.exit(1)

    if not member_votes:
        print(f"\nError: {len(votes_meta)} votes collected but no individual member votes. "
              f"Open States returned roll calls without per-legislator detail.", file=sys.stderr)
        sys.exit(1)

    output = {
        'metadata': {
            'generatedAt':          datetime.now().isoformat(),
            'session':              GA_SESSION,
            'sessionName':          SESSION_NAME,
            'source':               'Open States API',
            'totalVotes':           len(votes_meta),
            'totalBillsSeen':       bills_seen,
            'paginationComplete':   total_pages is None or page >= total_pages,
            'duplicateVotesDropped': sanitize_stats['duplicateVotesDropped'],
            'crossChamberDropped':   sanitize_stats['crossChamberDropped'],
        },
        'votes':       votes_meta,
        'memberVotes': member_votes,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(votes_meta)} passage votes · {len(member_votes)} members · {size_kb} KB -> {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
