#!/usr/bin/env python3
"""
Fetch Georgia Governor's executive orders for the current year and merge
new entries into assets/data/ga-executive-orders-{year}.json.

Runs in GitHub Actions on a daily schedule. No third-party dependencies.

URL structure:  https://gov.georgia.gov/executive-action/executive-orders/YYYY
Download links: https://gov.georgia.gov/document/YYYY-executive-order/MMDDYYNN/download
Order numbers:  MM.DD.YY.NN
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from html.parser import HTMLParser

BASE_URL   = "https://gov.georgia.gov"
OUTPUT_DIR = "assets/data"
YEAR       = datetime.now().year
GOVERNOR   = "Brian P. Kemp"


# ── Categorisation (shared with generate_ga_executive_orders.py) ─────────────

def categorize(title):
    t = title.lower()
    if any(x in t for x in ['state of emergency', 'state emergency', 'renewing the state',
                              'extending the state', 'renewal of state', 'declaring a state']):
        return 'State of Emergency'
    if 'writ of election' in t:
        return 'Writ of Election'
    if t.startswith('suspend') or 'suspending' in t:
        return 'Suspension'
    if 'lower' in t and 'flag' in t:
        return 'Flag at Half-Staff'
    if t.startswith('authoriz') or 'authorizing' in t:
        return 'Authorization'
    if 'appoint' in t:
        return 'Appointment'
    return 'Other'


# ── HTML parser ───────────────────────────────────────────────────────────────

class EOLinkParser(HTMLParser):
    """
    Extracts executive order entries by finding all <a> links that point to
    /document/YYYY-executive-order/MMDDYYNN/download. The URL encodes the
    full date and sequence number, so we don't need to parse surrounding HTML.
    """
    _HREF_RE = re.compile(
        r'/document/(\d{4})-executive-order/(\d{6,})(/download)?', re.IGNORECASE
    )

    def __init__(self, year):
        super().__init__()
        self.year    = year
        self.orders  = {}   # number -> entry (auto-deduped)
        self._href   = None
        self._code   = None
        self._buf    = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        m    = self._HREF_RE.search(href)
        if m and int(m.group(1)) == self.year:
            self._href = href if href.startswith('http') else BASE_URL + href
            self._code = m.group(2)
            self._buf  = []

    def handle_data(self, data):
        if self._code is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._code is not None:
            title = ' '.join(''.join(self._buf).split()).strip()
            if title:
                entry = self._parse(self._code, title, self._href)
                if entry:
                    self.orders[entry['number']] = entry
            self._href = self._code = None
            self._buf  = []

    def _parse(self, code, title, url):
        # code = MMDDYY + sequence (2+ digits)
        if len(code) < 8:
            return None
        mm, dd, yy = code[:2], code[2:4], code[4:6]
        seq = code[6:].lstrip('0') or '0'
        try:
            full_date = f"20{yy}-{mm}-{dd}"
            datetime.strptime(full_date, '%Y-%m-%d')
        except ValueError:
            return None
        number = f"{mm}.{dd}.{yy}.{seq.zfill(2)}"
        return {
            'date':     full_date,
            'number':   number,
            'title':    title,
            'category': categorize(title),
            'url':      url.split('?')[0],  # strip query params if any
        }


# ── Network helpers ───────────────────────────────────────────────────────────

def fetch_page(url, retries=3, delay=5):
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'votega.org/1.0 (executive-orders-updater)',
                'Accept':     'text/html,application/xhtml+xml',
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} on {url}")
            if e.code == 404:
                return None
            if attempt < retries:
                time.sleep(delay)
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < retries:
                time.sleep(delay)
    return None


def scrape_all_pages(year):
    """Fetch all paginated listing pages and return a dict of all found orders."""
    all_orders = {}
    page = 0   # gov.georgia.gov uses ?page=0, ?page=1, ...

    while True:
        url = f"{BASE_URL}/executive-action/executive-orders/{year}"
        if page > 0:
            url += f"?page={page}"

        print(f"  Fetching page {page}: {url}")
        html = fetch_page(url)

        if not html:
            if page == 0:
                return None   # fatal — first page failed
            break             # later pages missing = we're done

        parser = EOLinkParser(year)
        parser.feed(html)
        found = parser.orders

        if not found:
            break   # no EO links on this page → end of pagination

        new_on_page = {k: v for k, v in found.items() if k not in all_orders}
        all_orders.update(found)
        print(f"    Found {len(found)} order(s), {len(new_on_page)} new")

        if not new_on_page:
            break   # page had links but all already seen → done paginating

        page += 1
        time.sleep(1)   # be polite

    return all_orders


# ── JSON I/O ─────────────────────────────────────────────────────────────────

def load_existing(year):
    path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {'metadata': {'year': year, 'governor': GOVERNOR, 'count': 0}, 'orders': []}


def save(year, data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    year = YEAR
    source_url = f"{BASE_URL}/executive-action/executive-orders/{year}"
    print(f"Fetching GA Executive Orders for {year}...")

    scraped = scrape_all_pages(year)
    if scraped is None:
        print("Error: could not fetch page — aborting")
        sys.exit(1)

    if not scraped:
        print("Warning: no orders found on any page — page structure may have changed")
        sys.exit(1)

    print(f"Scraped {len(scraped)} total order(s)")

    # Merge scraped into existing: existing acts as safety net for anything
    # the scraper might miss (e.g. orders removed from site); scraped takes
    # precedence so corrections on the live site are picked up.
    data     = load_existing(year)
    existing = {o['number']: o for o in data.get('orders', [])}
    merged   = {**existing, **scraped}

    new_count     = sum(1 for n in scraped if n not in existing)
    updated_count = sum(1 for n in scraped if n in existing
                        and scraped[n]['title'] != existing[n].get('title'))

    all_orders = sorted(merged.values(), key=lambda o: o['number'], reverse=True)

    data['_note']    = (f"Auto-updated daily from {source_url}. "
                        f"Older years (2023–2025) are static.")
    data['metadata'] = {
        'year':      year,
        'governor':  GOVERNOR,
        'updatedAt': datetime.now().strftime('%Y-%m-%d'),
        'source':    source_url,
        'count':     len(all_orders),
    }
    data['orders'] = all_orders

    path = save(year, data)
    print(f"Saved {len(all_orders)} orders → {path}")
    if new_count:
        print(f"  {new_count} new order(s) added")
    if updated_count:
        print(f"  {updated_count} order(s) updated")
    if not new_count and not updated_count:
        print("  No changes — already up to date")


if __name__ == '__main__':
    main()
