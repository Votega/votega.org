#!/usr/bin/env python3
"""
Generate ga-member-votes.json from Open States API (Georgia).
Requires OPENSTATES_API_KEY environment variable.

Open States API flow:
  1. Paginate GET /bills?jurisdiction=GA&session=2025_26&include=votes
  2. For each bill, collect vote events where motion_classification == ['passage']
  3. Each vote event's votes[] normally has voter.id (an OCD person ID matching
     ga-members.json directly). Open States sometimes fails to resolve it —
     most often on a surname shared by several members — in which case
     voter_name (the raw name string) is matched against ga-members.json
     instead, scoped to the roll call's own chamber. See
     normalize_voter_name()/build_member_name_index(). A row with neither a
     usable id nor a resolvable name is dropped and counted in
     metadata.unresolvedVoterRows.

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
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

API_KEY      = os.environ.get('OPENSTATES_API_KEY')
BASE_URL     = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
GA_SESSION   = "2025_26"
SESSION_NAME = "2025-2026 Regular Session"
MEMBERS_FILE = "assets/data/ga-members.json"

SANITIZE_ONLY = '--sanitize' in sys.argv
_positional   = [a for a in sys.argv[1:] if not a.startswith('--')]
OUTPUT_FILE   = _positional[0] if _positional else "assets/data/ga-member-votes.json"

# This paginates the same /bills endpoint as generate_ga_bills_data.py — ~274 pages
# for a full session, against an Open States cap of 250 requests/day shared by every
# job using the key. Runs are therefore incremental by default. FULL_REFRESH=1 forces
# a complete rebuild (needs more than one day's quota; run it on a day nothing else does).
FULL_REFRESH = os.environ.get('FULL_REFRESH', '').strip().lower() in ('1', 'true', 'yes')
OVERLAP_DAYS = 3

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


_TITLE_PREFIX_RE = re.compile(
    r'^(rep(resentative)?|sen(ator)?|mr|mrs|ms|dr)\.?\s+', re.IGNORECASE
)


def normalize_voter_name(name):
    """Fold a name to a loose comparison key: strip a leading title, reorder a
    "Last, First" string to "First Last", drop punctuation and extra
    whitespace, lowercase the rest. Open States' voter_name is a raw string
    from the legislature's site and its convention isn't guaranteed to match
    ga-members.json's "First Last" (no title, no comma)."""
    if not name:
        return ''
    name = _TITLE_PREFIX_RE.sub('', name.strip())
    if ',' in name:
        last, _, first = name.partition(',')
        name = f'{first.strip()} {last.strip()}'
    name = re.sub(r"[.,]", '', name)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name


def build_member_name_index(path=MEMBERS_FILE):
    """Map (chamber, normalized name) -> OCD person id, for the voter_name
    fallback used when Open States fails to resolve voter.id (the surname-
    collision case: Open States can disambiguate the vote's chamber and the
    name string, but not always which same-surnamed member cast it via id).

    A (chamber, name) pair that matches more than one member is mapped to
    None rather than guessed — an ambiguous name isn't safe to attribute
    either way, so it's counted as unresolved like a missing id would be.
    """
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    index = {}
    for m in data.get('members', []):
        chamber = m.get('chamber')
        mid = m.get('id')
        name = normalize_voter_name(m.get('name'))
        if not chamber or not mid or not name:
            continue
        key = (chamber, name)
        index[key] = None if key in index else mid
    return index


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


def load_existing(path):
    """Previously published votes, as a merge baseline."""
    if not os.path.exists(path):
        return {}, {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d.get('votes') or {}, d.get('memberVotes') or {}, d.get('metadata') or {}
    except Exception as e:
        print(f"  Could not read existing {path}: {e}")
        return {}, {}, {}


def incremental_since(meta):
    """Date for updated_since, with overlap. None forces a full pull.

    Deliberately does NOT require the baseline to be complete. The published file is
    a partial pull (the session is ~274 pages against a 250/day quota), and refusing
    to build on it would force a full fetch that cannot finish — leaving the data
    frozen forever. An incremental run only adds and updates, so a partial baseline
    still gets strictly fresher; the incompleteness is carried forward honestly in
    metadata.paginationComplete rather than used to block the run.
    """
    if not meta.get('generatedAt'):
        return None
    # A baseline from a different session is not a baseline — see the matching guard
    # in generate_ga_bills_data.py. Forces a full pull at the biennium changeover so
    # two sessions never end up merged into one file.
    if meta.get('session') and meta['session'] != GA_SESSION:
        print(f"  Baseline is session {meta['session']}, now building {GA_SESSION} "
              f"— starting a fresh full fetch.")
        return None
    try:
        ts = meta['generatedAt'].replace('Z', '+00:00')
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - timedelta(days=OVERLAP_DAYS)).date().isoformat()
    except Exception:
        return None


def merge_votes(prior_votes, prior_member_votes, new_votes, new_member_votes):
    """Layer this run's votes over the baseline.

    Member entries are keyed by voteId, so a re-fetched roll call must *replace* the
    old entry rather than append beside it — otherwise a corrected vote would leave
    the legislator recorded twice for the same roll call, and the sanitize pass would
    have to guess which is current.
    """
    votes = dict(prior_votes)
    votes.update(new_votes)

    refetched = set(new_votes)
    members = {}
    for pid, entries in prior_member_votes.items():
        members[pid] = [e for e in entries if e.get('voteId') not in refetched]
    for pid, entries in new_member_votes.items():
        members.setdefault(pid, []).extend(entries)

    # Drop anyone left with no votes at all after the filter.
    members = {p: e for p, e in members.items() if e}
    return votes, members


def main():
    if SANITIZE_ONLY:
        sanitize_existing(OUTPUT_FILE)
        return

    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    prior_votes, prior_member_votes, prior_meta = load_existing(OUTPUT_FILE)
    since = None if FULL_REFRESH else incremental_since(prior_meta)

    if FULL_REFRESH:
        print("Full refresh requested — paginating the whole session.")
    elif since and prior_votes:
        print(f"Incremental update: {len(prior_votes)} votes already on file; "
              f"fetching only bills updated since {since}.")
    else:
        print("No usable baseline — falling back to a full fetch.")

    member_name_index    = build_member_name_index()
    unresolved_voter_rows = 0
    name_fallback_resolved = 0

    votes_meta   = {}
    member_votes = {}
    page         = 1
    total_pages  = None
    bills_seen   = 0

    print(f"Fetching GA bills for session {GA_SESSION} (passage votes only)...")

    while True:
        query = [
            ('jurisdiction', GA_JURISDICTION),
            ('session',      GA_SESSION),
            ('include',      'votes'),
            ('include',      'sources'),
            ('per_page',     20),
            ('page',         page),
        ]
        if since:
            query.append(('updated_since', since))
        params = urllib.parse.urlencode(query)
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
                (s['url'] for s in bill.get('sources', []) if 'www.legis.ga.gov/legislation/' in s.get('url', '')),
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

                ve_chamber = event_chamber(ve.get('motion_text'), ve.get('organization'))

                for pv in ve.get('votes', []):
                    voter    = pv.get('voter') or {}
                    voter_id = voter.get('id')
                    if not voter_id:
                        # Open States most often fails to resolve voter.id on a
                        # surname collision (e.g. one of 5 Joneses); voter_name
                        # is still the raw name string, so fall back to matching
                        # it against ga-members.json within the roll call's own
                        # chamber. A miss (no chamber, no name, or an ambiguous
                        # match) is counted rather than silently dropped.
                        fallback_key = (ve_chamber, normalize_voter_name(pv.get('voter_name')))
                        voter_id = member_name_index.get(fallback_key) if ve_chamber else None
                        if not voter_id:
                            unresolved_voter_rows += 1
                            continue
                        name_fallback_resolved += 1
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

    # Did *this* run's pagination finish? Separate from whether the accumulated
    # dataset is complete — a run can succeed fully while the baseline stays partial.
    fetch_complete = total_pages is None or page >= total_pages

    was_incremental = bool(since and prior_votes)
    if was_incremental:
        fetched_votes, fetched_members = len(votes_meta), len(member_votes)
        votes_meta, member_votes = merge_votes(
            prior_votes, prior_member_votes, votes_meta, member_votes
        )
        print(f"  Merged {fetched_votes} refetched vote(s) across {fetched_members} member(s) "
              f"into {len(prior_votes)} existing -> {len(votes_meta)} votes, "
              f"{len(member_votes)} members")

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

    # A half-applied incremental update is worse than none: generatedAt would advance
    # past changes we never fetched, so the next run's updated_since window would start
    # after them and they'd be skipped permanently.
    if was_incremental and not fetch_complete:
        print(f"\nError: incremental fetch stopped on page {page} of {total_pages} "
              f"(likely the Open States 250/day quota). Not publishing a partially "
              f"applied update — the next run would silently skip the missed window.",
              file=sys.stderr)
        sys.exit(1)

    output = {
        'metadata': {
            'generatedAt':          datetime.now().isoformat(),
            'session':              GA_SESSION,
            'sessionName':          SESSION_NAME,
            'source':               'Open States API',
            'totalVotes':           len(votes_meta),
            'totalBillsSeen':       bills_seen,
            # Whether the CUMULATIVE dataset is complete. An incremental run inherits
            # the baseline's gaps, so it can't claim completeness the baseline lacked.
            # Distinct from fetch_complete below, which is about this run only.
            'paginationComplete':   fetch_complete and (prior_meta.get('paginationComplete', True)
                                                        if was_incremental else True),
            'fetchComplete':        fetch_complete,
            'updateMode':           'incremental' if was_incremental else 'full',
            'lastFullRefresh':      (prior_meta.get('lastFullRefresh')
                                     if was_incremental
                                     else datetime.now().isoformat()),
            'duplicateVotesDropped': sanitize_stats['duplicateVotesDropped'],
            'crossChamberDropped':   sanitize_stats['crossChamberDropped'],
            # This run's fetch only — like duplicateVotesDropped/crossChamberDropped
            # above, an incremental run doesn't re-derive these for bills it didn't
            # refetch. nameFallbackResolved is how many of those unresolved rows the
            # voter_name fallback recovered; unresolvedVoterRows is what's left after
            # it — no id, no usable name match, or an ambiguous chamber+name pair.
            'nameFallbackResolved':  name_fallback_resolved,
            'unresolvedVoterRows':   unresolved_voter_rows,
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
