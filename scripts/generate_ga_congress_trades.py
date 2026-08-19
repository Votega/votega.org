#!/usr/bin/env python3
"""
Fetch congressional stock trade disclosures for Georgia federal members from the
kadoa-org/congress-trading-monitor GitHub dataset (House, Senate, both parties).
Writes assets/data/ga-congress-trades.json keyed by member name.

Data source: https://github.com/kadoa-org/congress-trading-monitor
No API key required.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

from lib.http import fetch_json as http_fetch_json

BASE_RAW        = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data"
FILERS_URL      = f"{BASE_RAW}/filers.json"
OUTPUT_FILE     = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-congress-trades.json"
OVERRIDES_FILE  = sys.argv[2] if len(sys.argv) > 2 else "assets/data/ga-congress-trades-overrides.json"
CURRENT_MEMBERS_FILE = os.path.join(os.path.dirname(OUTPUT_FILE), "current-members.json")


_SUFFIX_RE = re.compile(r'\b(jr|sr|ii|iii|iv)\b\.?$', re.IGNORECASE)
_DISTRICT_RE = re.compile(r'GA[-\s]?(\d+)', re.IGNORECASE)


def filer_surname(name):
    """Surname of a filer, ignoring a generational suffix.

    `name.split()[-1]` returns 'Jr' for 'Michael A. Collins Jr' — which is
    exactly the filer this file has to merge — so the surname join silently
    looked up a member named "jr".
    """
    cleaned = _SUFFIX_RE.sub('', (name or '').strip()).strip()
    parts = cleaned.split()
    return parts[-1].lower() if parts else ''


def filer_district(office):
    """District number from a filer's office string ('U.S. Representative — GA-12')."""
    m = _DISTRICT_RE.search(office or '')
    return int(m.group(1)) if m else None


def load_bioguide_index():
    """surname -> [(district, bioguideId), ...] for GA's federal delegation.

    Trade data carries no bioguideId, so the join is inferred from the name. The
    old map was surname -> bioguideId with last-write-wins, which is the bug
    generate_fec_data.py:227-234 documents having already fixed on the FEC side
    ("two Representatives named Scott… stamped one bioguide onto every Scott").
    Keeping every match instead lets an ambiguous surname be detected rather than
    silently resolved. See CODEBASE-REVIEW-2026-08-18.md finding 3.3.
    """
    if not os.path.exists(CURRENT_MEMBERS_FILE):
        print(f"Warning: {CURRENT_MEMBERS_FILE} not found, trade cards won't link to member profiles")
        return {}
    with open(CURRENT_MEMBERS_FILE, encoding='utf-8') as f:
        data = json.load(f)

    by_surname = {}
    for m in data.get('members', []):
        if m.get('state') != 'Georgia' or not m.get('bioguideId'):
            continue
        surname = (m.get('lastName') or '').strip().lower()
        if not surname:
            continue
        district = m.get('district')
        by_surname.setdefault(surname, []).append(
            (int(district) if district is not None else None, m['bioguideId']))
    return by_surname


def resolve_bioguide(name, office, by_surname):
    """bioguideId for a filer: surname first, district only to break a tie.

    District is deliberately *not* the primary key even though it looks like the
    stronger one. The upstream filer index is unreliable about office: it has
    listed Richard McCormick (GA-07) as "NY-01" and Michael Collins (GA-10) as
    "GA-08" — and GA-08 is Austin Scott, so trusting district first linked
    Collins' trades to Scott's profile. Surname cannot make that mistake: a wrong
    office can now only fail to disambiguate, never mis-resolve.
    """
    candidates = by_surname.get(filer_surname(name), [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]

    district = filer_district(office)
    narrowed = [b for d, b in candidates if district is not None and d == district]
    if len(narrowed) == 1:
        return narrowed[0]

    print(f"  Warning: surname '{filer_surname(name)}' matches {len(candidates)} GA "
          f"members and {office!r} does not disambiguate — no profile link for {name}")
    return None


def derive_counters(trades):
    """Counters describing exactly the trades this file publishes.

    The upstream filer record carries its own `purchases`/`sales`/`late_filings`/
    `est_volume`, but those describe *that filer*, and this script merges two
    filers for one member. Copying them across a merge left Michael Collins'
    card showing 42 trades beside a volume covering 23 of them.

    Deriving instead keeps every published number consistent with the published
    trade list. Verified against the four unmerged members: `purchases`,
    `lateFilings` and `estVolume` reproduce the upstream values exactly.
    `sales` does not — upstream reports 8 for Earl Carter against 14 actual sale
    transactions, and disagrees for two others — so that field is recomputed here
    rather than trusted. See CODEBASE-REVIEW-2026-08-18.md finding 3.3.
    """
    def midpoint(t):
        return ((t.get('amount_range_low') or 0) + (t.get('amount_range_high') or 0)) / 2

    return {
        'tradeCount':  len(trades),
        'purchases':   sum(1 for t in trades if t.get('transaction_type') == 'Purchase'),
        'sales':       sum(1 for t in trades
                           if str(t.get('transaction_type') or '').startswith('Sale')),
        'lateFilings': sum(1 for t in trades if t.get('is_late')),
        'estVolume':   sum(midpoint(t) for t in trades),
    }


def report_counter_drift(name, derived, filer):
    """Log where the upstream filer record disagrees with its own trade list."""
    upstream = {
        'tradeCount': filer.get('trade_count'), 'purchases': filer.get('purchases'),
        'sales': filer.get('sales'), 'lateFilings': filer.get('late_filings'),
        'estVolume': filer.get('est_volume'),
    }
    drift = [f"{k}: upstream {upstream[k]} vs {derived[k]} in trades"
             for k, v in upstream.items()
             if v is not None and abs((v or 0) - derived[k]) > 0.01]
    if drift:
        print(f"  Note: {name} — {'; '.join(drift)}")


def fetch_json(url):
    """Fetch JSON. Returns None on failure.

    Delegates to lib.http. This previously made a single attempt with no retry
    at all, so one transient 5xx produced a truncated trades file that the
    workflow then committed. See CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    return http_fetch_json(url)


def fetch_ticker_names(tickers):
    """Look up company short names from Yahoo Finance for a set of tickers.
    Returns a dict of {ticker: name}. Skips tickers that fail or return no name."""
    names = {}
    tickers = sorted(t for t in tickers if t)
    print(f"\nLooking up company names for {len(tickers)} unique tickers...")
    for ticker in tickers:
        url = (
            f"https://query1.finance.yahoo.com/v1/finance/search"
            f"?q={ticker}&quotesCount=1&newsCount=0&listsCount=0"
        )
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            quotes = data.get('quotes') or []
            if quotes:
                name = quotes[0].get('shortname') or quotes[0].get('longname') or ''
                if name:
                    names[ticker] = name
                    print(f"  {ticker} -> {name}")
                else:
                    print(f"  {ticker} -> (no name returned)")
            else:
                print(f"  {ticker} -> (no quotes)")
        except Exception as e:
            print(f"  {ticker} -> error: {e}")
        time.sleep(0.15)
    return names


def load_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        print(f"No overrides file found at {OVERRIDES_FILE}, skipping overrides")
        return {}
    with open(OVERRIDES_FILE, encoding='utf-8') as f:
        data = json.load(f)
    # Strip meta keys
    return {k: v for k, v in data.items() if not k.startswith('_')}


def main():
    overrides = load_overrides()
    print(f"Loaded {len(overrides)} override entries")

    print("Fetching filer index...")
    filers = fetch_json(FILERS_URL)
    if not filers:
        print("Error: could not fetch filers.json")
        sys.exit(1)

    ga_filers = [f for f in filers if f.get('state') == 'GA' and f.get('branch') == 'congress']
    print(f"Found {len(ga_filers)} GA congressional filers:")
    for f in ga_filers:
        print(f"  {f['full_name']} ({f['office']}) — {f['trade_count']} trades, ${f.get('est_volume', 0):,.2f} est. volume")

    bioguide_by_surname = load_bioguide_index()

    by_member = {}
    total_trades = 0

    for filer in ga_filers:
        filer_id = filer['id']
        name     = filer['full_name']
        print(f"\nFetching trades for {name}...")

        url  = f"{BASE_RAW}/filer/{filer_id}.json"
        data = fetch_json(url)
        if not data:
            print(f"  Warning: could not fetch data for {name}, skipping")
            continue

        trades_raw = data.get('trades', [])

        trades = []
        for t in trades_raw:
            trades.append({
                'transaction_date':   t.get('transaction_date', ''),
                'filing_date':        t.get('filing_date', ''),
                'days_to_file':       t.get('days_to_file'),
                'is_late':            bool(t.get('is_late')),
                'ticker':             t.get('ticker') or '',
                'asset_name':         t.get('asset_name', ''),
                'transaction_type':   t.get('transaction_type', ''),
                'amount_range_label': t.get('amount_range_label', ''),
                'amount_range_low':   t.get('amount_range_low'),
                'amount_range_high':  t.get('amount_range_high'),
                'owner':              t.get('owner', ''),
                'comment':            t.get('comment', ''),
                'doc_url':            t.get('doc_url', ''),
            })

        # Sort most-recent first
        trades.sort(key=lambda t: t.get('transaction_date', ''), reverse=True)

        bioguide_id = resolve_bioguide(name, filer.get('office', ''),
                                      bioguide_by_surname)

        counters = derive_counters(trades)
        report_counter_drift(name, counters, filer)

        by_member[name] = {
            'filerId':      filer_id,
            'bioguideId':   bioguide_id,
            'party':        filer.get('party', ''),
            'chamber':      filer.get('chamber', ''),
            'office':       filer.get('office', ''),
            'state':        'GA',
            'photoUrl':     filer.get('photo_url', ''),
            'trades':       trades,
            **counters,
        }
        total_trades += len(trades)
        print(f"  -> {len(trades)} trades loaded")

        time.sleep(0.2)

    # Apply overrides
    print("\nApplying overrides...")

    # Build a reverse lookup: name -> filerId for merge targets
    name_to_filer_id = {m['filerId']: name for name, m in by_member.items()}

    for filer_id, patch in overrides.items():
        # Find the member entry with this filerId
        member_name = name_to_filer_id.get(filer_id)
        if not member_name:
            print(f"  Override target {filer_id} not in fetched data, skipping")
            continue

        if patch.get('_exclude'):
            print(f"  Excluding {member_name}")
            del by_member[member_name]
            # No running-total bookkeeping here: `total_trades` is recomputed
            # from by_member after this loop. The subtraction that used to sit on
            # this line read the entry *after* deleting it, so it always
            # subtracted 0 -- dead code rather than an over-count, but confusing.
            continue

        merge_into_id = patch.get('_mergeInto')
        if merge_into_id:
            target_name = name_to_filer_id.get(merge_into_id)
            if target_name and target_name in by_member:
                extra_trades = by_member[member_name]['trades']
                by_member[target_name]['trades'].extend(extra_trades)
                by_member[target_name]['trades'].sort(
                    key=lambda t: t.get('transaction_date', ''), reverse=True
                )
                # Re-derive *all* counters, not just tradeCount: purchases,
                # sales, lateFilings and estVolume still described the target
                # filer alone, so the card showed the merged trade count beside
                # the unmerged volume.
                by_member[target_name].update(
                    derive_counters(by_member[target_name]['trades']))
                print(f"  Merged {member_name} ({len(extra_trades)} trades) into "
                      f"{target_name} -> {by_member[target_name]['tradeCount']} trades, "
                      f"${by_member[target_name]['estVolume']:,.2f} est. volume")
                del by_member[member_name]
            else:
                print(f"  Merge target {merge_into_id} not found, skipping merge of {member_name}")
            continue

        # Field-level patches (skip internal keys)
        applied = []
        for key, val in patch.items():
            if key.startswith('_'):
                continue
            by_member[member_name][key] = val
            applied.append(key)
        if applied:
            print(f"  Patched {member_name}: {', '.join(applied)}")

    # Recalculate total after merges/exclusions
    total_trades = sum(len(m['trades']) for m in by_member.values())

    # Look up company names for all unique tickers across all trades
    all_tickers = set()
    for m in by_member.values():
        for t in m['trades']:
            if t.get('ticker'):
                all_tickers.add(t['ticker'])
    ticker_names = fetch_ticker_names(all_tickers)

    output = {
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'source':      'kadoa-org/congress-trading-monitor (github.com/kadoa-org/congress-trading-monitor)',
            'totalTrades': total_trades,
            'gaMembers':   sorted(by_member.keys()),
            'disclaimer':  (
                'Stock trades are self-reported STOCK Act disclosures (Periodic Transaction Reports). '
                'Dollar amounts are ranges, not exact figures. Trades may be filed up to 45 days '
                'after the transaction. Data sourced from the House Clerk and Senate eFD systems '
                'via the kadoa-org/congress-trading-monitor open dataset.'
            ),
        },
        'tickerNames': ticker_names,
        'byMember': by_member,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {total_trades} trades for {len(by_member)} GA members -> {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
