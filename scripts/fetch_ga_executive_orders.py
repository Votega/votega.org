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

# Text values that appear as download link labels — not real titles
_LINK_LABELS = {'download', 'pdf', 'view', 'download pdf', 'view pdf', 'open', 'click here'}


# ── Categorisation ────────────────────────────────────────────────────────────

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

class EOPageParser(HTMLParser):
    """
    Parses the GA governor EO listing page.

    Strategy: track <tr> / <li> row boundaries. Within each row, collect all
    text chunks and find any EO download links. When the row closes, the title
    is the longest text chunk that isn't a generic download label. The date and
    order number are derived from the download link URL, which encodes MMDDYYNN.
    """

    _HREF_RE = re.compile(
        r'/document/(\d{4})-executive-order/(\d{6,})(/download)?', re.IGNORECASE
    )

    def __init__(self, year):
        super().__init__()
        self.year   = year
        self.orders = {}   # number -> entry

        # Row state
        self._stack     = []   # open tag stack
        self._row_depth = None # stack length when the current row opened
        self._texts     = []   # text chunks collected in current row
        self._links     = []   # (code, full_href) for EO download links in row

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_row(tag):
        return tag in ('tr', 'li')

    def _parse_entry(self, code, title, url):
        """Convert a URL code segment (MMDDYYNN) into a structured entry."""
        if len(code) < 8:
            return None
        mm, dd, yy = code[:2], code[2:4], code[4:6]
        seq = code[6:]
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
            'url':      url,
        }

    def _flush_row(self):
        """Process the accumulated row state and reset."""
        if self._links:
            # Title = longest text chunk that isn't a generic label and is > 10 chars
            real_texts = [t for t in self._texts
                          if t.lower() not in _LINK_LABELS and len(t) > 10]
            title = max(real_texts, key=len, default='').strip()

            for code, href in self._links:
                entry = self._parse_entry(code, title, href)
                if entry and entry['title']:
                    self.orders[entry['number']] = entry

        self._row_depth = None
        self._texts     = []
        self._links     = []

    # ── HTMLParser callbacks ──────────────────────────────────────────────────

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag)
        attrs_d = dict(attrs)

        # Start a new row context if we're not already in one
        if self._is_row(tag) and self._row_depth is None:
            self._row_depth = len(self._stack)
            self._texts     = []
            self._links     = []

        # Detect EO download links
        if tag == 'a':
            href = attrs_d.get('href', '')
            m    = self._HREF_RE.search(href)
            if m and int(m.group(1)) == self.year:
                full = href if href.startswith('http') else BASE_URL + href
                self._links.append((m.group(2), full.split('?')[0]))

    def handle_data(self, data):
        if self._row_depth is not None:
            text = ' '.join(data.split())   # normalise whitespace
            if text:
                self._texts.append(text)

    def handle_endtag(self, tag):
        # Close the row context when we return to the depth it opened at
        if (self._is_row(tag)
                and self._row_depth is not None
                and len(self._stack) <= self._row_depth):
            self._flush_row()

        if self._stack and self._stack[-1] == tag:
            self._stack.pop()


# ── Network ───────────────────────────────────────────────────────────────────

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
    """Fetch all paginated listing pages and return a merged dict of orders."""
    all_orders = {}
    page = 0

    while True:
        url = f"{BASE_URL}/executive-action/executive-orders/{year}"
        if page > 0:
            url += f"?page={page}"

        print(f"  Fetching page {page}: {url}")
        html = fetch_page(url)

        if not html:
            if page == 0:
                return None
            break

        parser = EOPageParser(year)
        parser.feed(html)
        found = parser.orders

        if not found:
            print(f"    No EO links found — end of pagination")
            break

        new_on_page = {k: v for k, v in found.items() if k not in all_orders}
        all_orders.update(found)
        print(f"    Found {len(found)} order(s), {len(new_on_page)} new")

        if not new_on_page:
            break   # all entries already seen — no more pages

        page += 1
        time.sleep(1)

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
    year       = YEAR
    source_url = f"{BASE_URL}/executive-action/executive-orders/{year}"
    print(f"Fetching GA Executive Orders for {year}...")

    scraped = scrape_all_pages(year)
    if scraped is None:
        print("Error: could not fetch page — aborting")
        sys.exit(1)
    if not scraped:
        print("Warning: no orders found — page structure may have changed")
        sys.exit(1)

    # Warn about any entries where the title is still empty/bad
    bad = [n for n, e in scraped.items() if len(e.get('title', '')) < 15]
    if bad:
        print(f"Warning: {len(bad)} order(s) have suspiciously short titles: {bad[:5]}")

    print(f"Scraped {len(scraped)} total order(s)")

    data     = load_existing(year)
    existing = {o['number']: o for o in data.get('orders', [])}

    # Merge: scraped takes precedence for new/updated entries.
    # If a scraped title is clearly wrong (empty / too short), fall back to
    # the existing curated title so we don't overwrite good data with noise.
    merged = dict(existing)
    new_count = 0
    for num, entry in scraped.items():
        is_new = num not in existing
        title_ok = len(entry.get('title', '')) >= 15

        if is_new:
            if title_ok:
                merged[num] = entry
                new_count += 1
            else:
                print(f"  Skipping new {num} — title too short: {entry.get('title')!r}")
        else:
            if title_ok:
                merged[num] = entry   # update with fresh data
            # else keep existing curated entry unchanged

    all_orders = sorted(merged.values(), key=lambda o: o['number'], reverse=True)

    data['_note']    = (f"Auto-updated daily from {source_url}. "
                        f"Years 2023–2025 are static.")
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
    else:
        print("  No new orders")


if __name__ == '__main__':
    main()
