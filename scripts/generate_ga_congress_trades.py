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


def load_bioguide_by_last_name():
    """Maps last name (lowercase) -> bioguideId for GA's current federal delegation,
    so trade-data entries (which carry no bioguideId of their own) can link out to
    member.html. Last names are unique across the 15-member GA delegation, so this
    is a safe join key without needing full-name fuzzy matching."""
    if not os.path.exists(CURRENT_MEMBERS_FILE):
        print(f"Warning: {CURRENT_MEMBERS_FILE} not found, trade cards won't link to member profiles")
        return {}
    with open(CURRENT_MEMBERS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    result = {}
    for m in data.get('members', []):
        if m.get('state') != 'Georgia' or not m.get('lastName') or not m.get('bioguideId'):
            continue
        result[m['lastName'].strip().lower()] = m['bioguideId']
    return result


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

    bioguide_by_last_name = load_bioguide_by_last_name()

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

        last_name = name.split()[-1] if name.split() else ''
        bioguide_id = bioguide_by_last_name.get(last_name.lower())

        by_member[name] = {
            'filerId':      filer_id,
            'bioguideId':   bioguide_id,
            'party':        filer.get('party', ''),
            'chamber':      filer.get('chamber', ''),
            'office':       filer.get('office', ''),
            'state':        'GA',
            'photoUrl':     filer.get('photo_url', ''),
            'tradeCount':   filer.get('trade_count', len(trades)),
            'purchases':    filer.get('purchases', 0),
            'sales':        filer.get('sales', 0),
            'lateFilings':  filer.get('late_filings', 0),
            'estVolume':    filer.get('est_volume', 0),
            'trades':       trades,
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
            total_trades -= by_member.get(member_name, {}).get('tradeCount', 0)
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
                by_member[target_name]['tradeCount'] = len(by_member[target_name]['trades'])
                print(f"  Merged {member_name} ({len(extra_trades)} trades) into {target_name}")
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
