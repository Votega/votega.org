#!/usr/bin/env python3
"""
Generate ga-bills.json from the Open States API (Georgia General Assembly).
Requires OPENSTATES_API_KEY environment variable.

Replaces the one-time process_ga_bills.py transform of a static bulk export
(GA_2025_26_bills.json, May 2026) with a live paginated fetch of
GET /bills?jurisdiction=GA&session=<active>&include=... .

Multi-session (biennium) model: Georgia's General Assembly sits for a two-year
biennium made up of a regular session plus any special sessions. Each bill is tagged
with its `session` id. This generator fetches only the ACTIVE session live and PRESERVES
the (frozen) bills of the closed sessions already on file, so the combined ga-bills.json
covers the whole biennium. See scripts/lib/ga_sessions.py — update session config there,
not here. Every session is added and pointed-at in that one module.

Usage:
  python scripts/generate_ga_bills_data.py                       # writes assets/data/ga-bills.json
  python scripts/generate_ga_bills_data.py /path/to/output.json
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

from lib.http import fetch_json
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             session_name, tag_session)

API_KEY  = os.environ.get('OPENSTATES_API_KEY')
BASE_URL = "https://v3.openstates.org"
GA_JURISDICTION = "ocd-jurisdiction/country:us/state:ga/government"
# The session fetched live. Closed sessions are preserved from the existing file.
GA_SESSION      = ACTIVE_SESSION
SESSION_NAME    = session_name(ACTIVE_SESSION)

OUTPUT_FILE     = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-bills.json"
OVERRIDES_FILE  = os.path.join(os.path.dirname(OUTPUT_FILE), 'ga-bills-subjects.json')
REVIEW_CSV_FILE = os.path.join('scripts', 'ga-bills-review.csv')

ABSTRACT_MAX = 500  # chars — keeps abstract useful without bloating file size
PER_PAGE     = 20   # /bills max per_page when using multiple `include`s
DELAY        = 7    # Open States free tier: 10 req/min — 7s keeps safely under

# Open States also enforces a 250 request/day cap. A full 2025-26 pull is ~274
# pages, so an unfiltered fetch can never finish; runs are incremental by default
# and re-fetch only bills changed since the last run. Set FULL_REFRESH=1 to force
# a complete rebuild (expect it to need more than one day's quota).
FULL_REFRESH  = os.environ.get('FULL_REFRESH', '').strip().lower() in ('1', 'true', 'yes')
OVERLAP_DAYS  = 3   # re-window a few days each run to absorb clock skew / late indexing

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

# Regex matching any GA county name as a whole word. Sorted longest-first so
# multi-word names ("Ben Hill") match before their components ("Hill").
_COUNTY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(GA_COUNTIES, key=len, reverse=True)) + r')\b'
)

# When a GA county name appears in the first title segment alongside one of
# these keywords, the bill is local/municipal (e.g. "Brooks County Development
# Authority", "Pickens County Airport Authority", "Cobb Judicial Circuit").
_LOCAL_ENTITY_KW = {
    'Authority', 'Airport', 'Commission', 'Development', 'School',
    'Water', 'Recreation', 'Library', 'Housing', 'Transit',
    'Utility', 'Utilities', 'Circuit',
}

_ACT_NUMBER_RE = re.compile(r'^Act (\d+)$')


# ---------------------------------------------------------------------------
# Open States fetch
# ---------------------------------------------------------------------------

def fetch(url, retries=3):
    """Fetch JSON from Open States. Returns None on failure.

    Delegates to lib.http; this was already policy-compliant, so the move is
    about having one implementation rather than five. backoff=DELAY*2 keeps the
    original 14s/28s/42s ramp. See CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    return fetch_json(url, headers={
        'X-API-Key': API_KEY or '',
        'Accept':    'application/json',
    }, retries=retries, backoff=DELAY * 2, timeout=60, redact=API_KEY)


def get_all_bills(updated_since=None):
    """Paginate GET /bills for the configured GA session, with the relation
    includes slim_bill() needs (abstracts, actions, sponsorships, sources,
    votes, versions). subject/classification/identifier/title/chamber are
    core fields returned without an include.

    `updated_since` limits the pull to bills changed on or after that date. A full
    session is ~274 pages and the Open States free tier allows 250 requests/day, so
    an unfiltered pull cannot complete — see main() for how the incremental path is
    chosen.
    """
    all_bills   = []
    page        = 1
    total_pages = None

    while True:
        query = [
            ('jurisdiction', GA_JURISDICTION),
            ('session',      GA_SESSION),
            ('per_page',     PER_PAGE),
            ('page',         page),
            ('include',      'abstracts'),
            ('include',      'actions'),
            ('include',      'sponsorships'),
            ('include',      'sources'),
            ('include',      'versions'),
            ('include',      'votes'),
        ]
        if updated_since:
            query.append(('updated_since', updated_since))
        params = urllib.parse.urlencode(query)
        data = fetch(f"{BASE_URL}/bills?{params}")

        if not data:
            if total_pages is not None and page < total_pages:
                print(f"  Warning: early termination on page {page}/{total_pages} — "
                      f"{len(all_bills)} bills fetched, ~{(total_pages - page) * PER_PAGE} may be missing")
            else:
                print(f"  Failed on page {page}, stopping.")
            break

        results = data.get('results', [])
        all_bills.extend(results)

        pagination  = data.get('pagination', {})
        total_pages = pagination.get('max_page', 1)
        print(f"  Page {page}/{total_pages}: {len(results)} bills (total: {len(all_bills)})")

        if page >= total_pages:
            break
        page += 1
        time.sleep(DELAY)

    return all_bills, (total_pages is None or page >= total_pages)


# ---------------------------------------------------------------------------
# Helpers (subject inference, overrides, bill-record shaping)
# ---------------------------------------------------------------------------

def infer_local_subject(title):
    """
    Return ['Local / Municipal'] if the bill title identifies a GA locality,
    otherwise return [].  Only applied to bills with no Open States subject tags.

    GA bill titles follow the convention 'Subject; detail; verb phrase', so the
    first semicolon-delimited segment reliably identifies the subject area.
    """
    if ';' not in title:
        return []
    first_seg = title.split(';')[0].strip().strip('"\'')

    if first_seg.startswith(('City of ', 'Town of ', 'County of ')):
        return ['Local / Municipal']

    for suffix in (', City of', ', Town of'):
        if first_seg.endswith(suffix):
            return ['Local / Municipal']

    for suffix in (', County', ' County'):
        if first_seg.endswith(suffix):
            return ['Local / Municipal']

    if _COUNTY_RE.search(first_seg) and any(kw in first_seg for kw in _LOCAL_ENTITY_KW):
        return ['Local / Municipal']

    if first_seg in GA_COUNTIES:
        return ['Local / Municipal']

    return []


def load_subjects_overrides(path):
    """
    Load manual subject-tag overrides from ga-bills-subjects.json.
    Keys are bill identifiers (e.g. 'HB 739'); values are subject lists.
    Keys beginning with '_' are metadata and are ignored.
    Returns an empty dict if the file doesn't exist.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith('_') and v}


def get_bill_url(sources):
    """Prefer legis.ga.gov; fall back to first source URL."""
    for s in sources:
        if 'legis.ga.gov' in s.get('url', ''):
            return s['url']
    return sources[0]['url'] if sources else ''


def get_text_url(versions):
    """
    Pick a full-text PDF URL from versions[]. Prefers an "As Passed" version
    (note contains '/AP'); falls back to the most recent version with a PDF
    link. Mirrors generate_curated_ga_bills.py's pick_full_text_url — the
    live API exposes full text via versions[], unlike the bulk export's
    raw_text_url convenience field.
    """
    if not versions:
        return ''
    for v in versions:
        if '/AP' in v.get('note', ''):
            for link in v.get('links', []):
                if link.get('media_type') == 'application/pdf':
                    return link['url']
    for v in reversed(versions):
        for link in v.get('links', []):
            if link.get('media_type') == 'application/pdf':
                return link['url']
    return ''


def get_chamber(identifier):
    """
    Derive 'lower' (House) or 'upper' (Senate) from a GA bill identifier
    (HB/HR = House, SB/SR = Senate) rather than relying on an unconfirmed
    top-level API field — the identifier prefix is a fixed GA convention.
    """
    return 'lower' if identifier.strip().upper().startswith('H') else 'upper'


def get_governor_action(actions):
    """
    Derive the Governor's disposition of a bill from its action history.

    legis.ga.gov (via Open States) tags actions with 'executive-receipt'
    (sent to the Governor), 'executive-signature' (signed — this also fires
    on the 'Act NNN' action that assigns the act number), and
    'executive-veto'. A vetoed bill's transmittal record still carries an
    'executive-signature'-tagged "Date Signed by Governor" action dated the
    same day as the veto — an upstream labeling quirk, not a real signature —
    so veto is treated as decisive whenever both are present.

    Returns None if the bill has not been sent to the Governor, otherwise:
      { status: 'Signed' | 'Vetoed' | 'Sent to Governor',
        sentDate, decisionDate (None if still pending), actNumber (Signed only) }
    """
    sent_date  = None
    veto_date  = None
    sign_date  = None
    act_number = None

    for a in sorted(actions, key=lambda x: x.get('order', 0)):
        classes = a.get('classification') or []
        date    = a.get('date')
        desc    = a.get('description', '')

        if 'executive-receipt' in classes and sent_date is None:
            sent_date = date
        if 'executive-veto' in classes and veto_date is None:
            veto_date = date
        if 'executive-signature' in classes:
            if sign_date is None:
                sign_date = date
            m = _ACT_NUMBER_RE.match(desc)
            if m and act_number is None:
                act_number = int(m.group(1))

    if veto_date:
        return {'status': 'Vetoed', 'sentDate': sent_date, 'decisionDate': veto_date, 'actNumber': None}
    if sign_date:
        return {'status': 'Signed', 'sentDate': sent_date, 'decisionDate': sign_date, 'actNumber': act_number}
    if sent_date:
        return {'status': 'Sent to Governor', 'sentDate': sent_date, 'decisionDate': None, 'actNumber': None}
    return None


def get_passage_votes(votes):
    """
    Return passage vote counts per chamber.
    Drops individual voter arrays — ga-member-votes.json already carries
    per-member roll calls, joined separately by enrich_bills_with_party_votes.py.
    """
    result = []
    for v in votes:
        if 'passage' not in (v.get('motion_classification') or []):
            continue
        counts = {c['option']: c['value'] for c in v.get('counts', [])}
        result.append({
            'chamber':    (v.get('organization') or {}).get('classification', ''),
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

    actions[] is intentionally omitted from the output — governorAction below
    is derived from it. status/statusDate (from the last action) plus billUrl
    cover the list-view need.
    """
    actions     = sorted(b.get('actions', []), key=lambda a: a.get('order', 0))
    last_action = actions[-1] if actions else {}
    abstract    = (b.get('abstracts') or [{}])[0].get('abstract', '')
    identifier  = b.get('identifier', '')

    return {
        'id':          b['id'],
        'identifier':  identifier,
        'session':     GA_SESSION,   # only the active session is fetched/slimmed here
        'billType':    (b.get('classification') or ['bill'])[0],
        'chamber':     get_chamber(identifier),
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
            for s in b.get('sponsorships', [])
        ],
        'billUrl':     get_bill_url(b.get('sources', [])),
        'textUrl':     get_text_url(b.get('versions', [])),
        'passageVotes': get_passage_votes(b.get('votes', [])),
        'governorAction': get_governor_action(actions),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_existing(path):
    """Previously published bills, as a merge baseline. Returns (bills, metadata)."""
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d.get('bills') or [], d.get('metadata') or {}
    except Exception as e:
        print(f"  Could not read existing {path}: {e}")
        return [], {}


def incremental_since(meta):
    """Date to pass as updated_since, with a few days of overlap.

    Re-fetching a small window that was already covered is cheap and guards against
    clock skew and bills indexed by Open States after our run. Returns None when the
    baseline is unusable, which forces a full pull.
    """
    if not meta.get('generatedAt'):
        return None
    # Only take the incremental path if the ACTIVE session was already being tracked.
    # When a session first becomes active (e.g. a newly convened special session), the
    # file has no active-session baseline yet, so a full pull of it is required — and
    # it's cheap, since a session opens with a handful of bills. The closed sessions in
    # the file are preserved separately in main(), never re-fetched.
    if meta.get('activeSession') != GA_SESSION:
        print(f"  Active session {GA_SESSION} not yet in the baseline "
              f"(was {meta.get('activeSession') or meta.get('session')}) "
              f"— starting a fresh full fetch of it.")
        return None
    # Only build on a baseline that was itself complete.
    if meta.get('paginationComplete') is False:
        return None
    try:
        ts = meta['generatedAt'].replace('Z', '+00:00')
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - timedelta(days=OVERLAP_DAYS)).date().isoformat()
    except Exception:
        return None


def main():
    if not API_KEY:
        print("Error: OPENSTATES_API_KEY environment variable not set")
        sys.exit(1)

    existing_bills, existing_meta = load_existing(OUTPUT_FILE)

    # Migrate + partition the baseline by session: closed sessions are PRESERVED
    # untouched (they never change), only the active session is (re)fetched. Records
    # written before multi-session support carried no `session` tag and belong to
    # UNTAGGED_SESSION (folded in by tag_session).
    for b in existing_bills:
        b['session'] = tag_session(b.get('session'))
    preserved     = [b for b in existing_bills if b['session'] != GA_SESSION]
    active_prior  = [b for b in existing_bills if b['session'] == GA_SESSION]

    since = None if FULL_REFRESH else incremental_since(existing_meta)

    if FULL_REFRESH:
        print(f"Full refresh requested — fetching every bill for the active session {GA_SESSION}.")
    elif since and active_prior:
        print(f"Incremental update: {len(active_prior):,} active-session bills on file; "
              f"fetching only those updated since {since}.")
    else:
        print(f"No active-session baseline — full fetch of the active session {GA_SESSION}.")
    if preserved:
        print(f"  Preserving {len(preserved):,} bill(s) from closed session(s) "
              f"{sorted(set(b['session'] for b in preserved))} — not re-fetched.")

    raw_bills, pagination_complete = get_all_bills(updated_since=since)

    # Slim + tag this run's active-session fetch, then union over the active baseline
    # (keyed by OCD bill id). Preserved closed-session bills are added back untouched.
    fetched = {b['id']: b for b in (slim_bill(x) for x in raw_bills) if b.get('id')}
    active_merged = {b['id']: b for b in active_prior if b.get('id')}
    added = len(set(fetched) - set(active_merged))
    active_merged.update(fetched)
    bills = preserved + list(active_merged.values())

    if since and active_prior:
        print(f"  Merged {len(fetched)} changed active-session bill(s) ({added} new) into "
              f"{len(active_prior):,} existing -> {len(active_merged):,} active, "
              f"{len(bills):,} total incl. preserved")
    else:
        print(f"  Active session: {len(active_merged):,} bill(s); {len(bills):,} total incl. preserved")

    if not bills:
        print("Error: no bills at all (no active-session fetch and nothing preserved)")
        sys.exit(1)

    overrides = load_subjects_overrides(OVERRIDES_FILE)
    if overrides:
        print(f'Loaded {len(overrides)} manual subject override(s) from {OVERRIDES_FILE}')

    # Keep a stable order so a merge doesn't reshuffle the file and produce a
    # misleadingly large diff on every run. Group by session first so each session's
    # bills stay contiguous in the file.
    bills.sort(key=lambda b: (b.get('session') or '', b.get('chamber') or '', b.get('identifier') or ''))

    override_count = 0
    for bill in bills:
        if bill['identifier'] in overrides:
            bill['subjects'] = overrides[bill['identifier']]
            override_count += 1

    bills_only    = [b for b in bills if b['billType'] == 'bill']
    with_subjects = sum(1 for b in bills if b['subjects'])
    bills_tagged  = sum(1 for b in bills_only if b['subjects'])
    with_votes    = sum(1 for b in bills if b['passageVotes'])
    signed        = sum(1 for b in bills if (b['governorAction'] or {}).get('status') == 'Signed')
    vetoed        = sum(1 for b in bills if (b['governorAction'] or {}).get('status') == 'Vetoed')
    pending_gov   = sum(1 for b in bills if (b['governorAction'] or {}).get('status') == 'Sent to Governor')
    chambers      = {}
    for b in bills:
        chambers[b['chamber']] = chambers.get(b['chamber'], 0) + 1

    was_incremental = bool(since and active_prior)
    # This run only fetched the active session; the preserved sessions are complete by
    # definition (frozen). So the cumulative dataset is complete iff the active fetch
    # finished AND (on an incremental run) the active baseline was already complete.
    active_complete = pagination_complete and (existing_meta.get('paginationComplete', True)
                                               if was_incremental else True)
    by_session = {}
    for b in bills:
        by_session[b['session']] = by_session.get(b['session'], 0) + 1
    output = {
        'metadata': {
            'generatedAt':        datetime.now(timezone.utc).isoformat(),
            'biennium':           BIENNIUM,
            # Every session in the biennium, with its bill count. Preserved sessions are
            # frozen; only activeSession is fetched live.
            'sessions':           [{'id': sid, 'name': session_name(sid),
                                    'billCount': by_session.get(sid, 0)}
                                   for sid in all_session_ids()],
            'activeSession':      GA_SESSION,
            'activeSessionName':  SESSION_NAME,
            # Legacy single-session fields, kept pointing at the active session so any
            # older reader still resolves. Prefer `biennium` / `sessions` going forward.
            'session':            GA_SESSION,
            'sessionName':        SESSION_NAME,
            'source':             'Open States API',
            'totalBills':         len(bills),
            'paginationComplete': active_complete,
            'updateMode':         'incremental' if was_incremental else 'full',
            # Provenance of the underlying baseline: incremental runs build on it and
            # never re-verify the untouched bills, so it's worth knowing how old it is.
            'lastFullRefresh':    (existing_meta.get('lastFullRefresh')
                                   if was_incremental
                                   else datetime.now(timezone.utc).isoformat()),
        },
        'bills': bills,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    print(f'Writing {OUTPUT_FILE} ...')
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

    # Write review CSV for any remaining untagged actual bills
    untagged_bills = [b for b in bills_only if not b['subjects']]
    if untagged_bills:
        os.makedirs(os.path.dirname(REVIEW_CSV_FILE) or '.', exist_ok=True)
        with open(REVIEW_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['identifier', 'chamber', 'title', 'status'])
            for b in untagged_bills:
                chamber = 'House' if b['chamber'] == 'lower' else 'Senate'
                w.writerow([b['identifier'], chamber, b['title'], b['status']])
        print(f'\n  WARNING: {len(untagged_bills)} bill(s) still lack subject tags.')
        print(f'     Review CSV written to: {REVIEW_CSV_FILE}')
        print(f'     Add overrides to:      {OVERRIDES_FILE}')

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f'\nDone.')
    print(f'  Bills:              {len(bills):,}')
    print(f'  House/lower:        {chambers.get("lower", 0):,}')
    print(f'  Senate/upper:       {chambers.get("upper", 0):,}')
    print(f'  Tagged (all):       {with_subjects:,} ({with_subjects/len(bills)*100:.0f}%)')
    print(f'  Tagged (HB/SB):     {bills_tagged:,} / {len(bills_only):,} ({bills_tagged/len(bills_only)*100:.1f}%)')
    print(f'  Manual overrides:   {override_count}')
    print(f'  With votes:         {with_votes:,} ({with_votes/len(bills)*100:.0f}%)')
    print(f'  Signed by Governor: {signed:,}')
    print(f'  Vetoed by Governor: {vetoed:,}')
    print(f'  Pending w/ Governor:{pending_gov:,}')
    print(f'  Update mode:        {"incremental" if was_incremental else "full"}')
    print(f'  Pagination complete:{pagination_complete}')
    print(f'  Last full refresh:  {output["metadata"]["lastFullRefresh"] or "unknown"}')
    print(f'  Output size:        {size_mb:.1f} MB')

    if not pagination_complete:
        if was_incremental:
            # A half-applied update is worse than none: generatedAt would advance past
            # changes we never fetched, and the next run's updated_since window would
            # start after them, so they'd be skipped permanently.
            print('\nERROR: incremental fetch did not finish (likely the 250/day quota). '
                  'Not publishing a partially applied update.')
        else:
            print('\nERROR: pagination did not complete — refusing to treat this as a full dataset.')
        sys.exit(1)


if __name__ == '__main__':
    main()
