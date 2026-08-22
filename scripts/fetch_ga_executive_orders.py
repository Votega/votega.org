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

from lib.http import fetch_bytes
from html.parser import HTMLParser

BASE_URL   = "https://gov.georgia.gov"
OUTPUT_DIR = "assets/data"
YEAR       = datetime.now().year

_MAX_TITLE = 300   # titles longer than this are scraper noise, not real text

# Fields added later by enrich_ga_executive_orders.py (Layer 1). The scraper
# only ever produces the 5 base fields, so on a daily re-scrape it must carry
# these across rather than clobber them — otherwise every re-scrape would wipe
# the hash/size/archive data the enricher committed.
_ENRICH_FIELDS = ('sha256', 'bytes', 'fetchedAt', 'archiveUrl')


def _carry_enrichment(new_entry, old_entry):
    """Preserve Layer-1 enrichment fields when a re-scrape refreshes an entry.

    Only carry them when the download URL is unchanged — a new URL means a new
    PDF that must be re-hashed and re-archived, so dropping the stale fields is
    correct and lets the enricher redo them.
    """
    if old_entry.get('url') != new_entry.get('url'):
        return new_entry
    for fld in _ENRICH_FIELDS:
        if fld in old_entry and fld not in new_entry:
            new_entry[fld] = old_entry[fld]
    return new_entry


def governor_for_year(year):
    """Return the Georgia governor who held office for (most of) the given year.

    Nathan Deal served through 2018 and left office 14 Jan 2019; Brian P. Kemp
    took office that day. 2019 spans both, so it is labelled for both.
    """
    if year <= 2018:
        return "Nathan Deal"
    if year == 2019:
        return "Nathan Deal / Brian P. Kemp"
    return "Brian P. Kemp"


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

    The page is a two-column table:
      Document (PDF link with order number)  |  Description (title text)

    The Description cell follows the download link in DOM order, so the
    strategy is: when a download link closes, hold it as "pending" and
    collect subsequent text chunks. When the next download link opens (or
    parsing ends), finalise the pending entry using the accumulated text.
    PDF file-size strings like "(PDF, 98.59 KB)" are stripped from the text.
    """

    # The document-path segment is singular for 2023+ ("2026-executive-order")
    # but plural for the 2020–2022 pages ("2022-executive-orders"), so the `s`
    # is optional.
    _HREF_RE   = re.compile(
        r'/document/(\d{4})-executive-orders?/(\d{6,})(/download)?', re.IGNORECASE
    )
    _PDF_NOISE = re.compile(r'\(PDF[^)]*\)', re.IGNORECASE)

    def __init__(self, year):
        super().__init__()
        self.year   = year
        self.orders = {}

        self._in_link      = False
        self._pending_code = None   # code of the most-recently-closed EO link
        self._pending_href = None
        self._after_buf    = []     # text chunks collected after the link closes

    # ── helpers ──────────────────────────────────────────────────────────────

    def _flush_pending(self):
        """Finalise the pending EO entry using text collected after its link."""
        if not self._pending_code:
            return
        raw   = ' '.join(self._after_buf)
        title = self._PDF_NOISE.sub('', raw).strip()
        if title:
            entry = self._parse_entry(self._pending_code, title, self._pending_href)
            if entry:
                self.orders[entry['number']] = entry
        self._pending_code = None
        self._pending_href = None
        self._after_buf    = []

    def _parse_entry(self, code, title, url):
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

    # ── HTMLParser callbacks ──────────────────────────────────────────────────

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        m    = self._HREF_RE.search(href)
        if m and int(m.group(1)) == self.year:
            self._flush_pending()   # finalise the previous entry before starting a new one
            full = href if href.startswith('http') else BASE_URL + href
            self._in_link      = True
            self._pending_code = m.group(2)
            self._pending_href = full.split('?')[0]
            self._after_buf    = []

    def handle_data(self, data):
        text = ' '.join(data.split())
        if not text:
            return
        if self._in_link:
            return  # link text is the order number, not the title — ignore it
        if self._pending_code is not None:
            self._after_buf.append(text)

    def handle_endtag(self, tag):
        if tag == 'a' and self._in_link:
            self._in_link = False
        elif tag == 'tr' and self._pending_code:
            self._flush_pending()   # row end = description cell is done collecting

    def close(self):
        """Flush the last pending entry when parsing completes."""
        self._flush_pending()
        super().close()


# ── Network ───────────────────────────────────────────────────────────────────

def fetch_page(url, retries=3, delay=5):
    """Fetch an HTML listing page as text. Returns None on failure.

    Delegates to lib.http. This previously retried every status except 404 —
    including 4xx, which fail identically on retry. It now follows the
    documented 429/5xx-only policy. A 404 is an expected end-of-pagination
    signal here, so it stays unlogged.
    See CODEBASE-REVIEW-2026-08-18.md 2.4.
    """
    raw = fetch_bytes(
        url,
        headers={
            'User-Agent': 'votega.org/1.0 (executive-orders-updater)',
            'Accept':     'text/html,application/xhtml+xml',
        },
        retries=retries,
        backoff=delay,
        quiet_statuses=(404,),
        label=url,
    )
    return raw.decode('utf-8', errors='replace') if raw is not None else None


def candidate_bases(year):
    """Listing-page URL schemes the GA site has used, newest first.

    2022–present use the bare year; 2020–2021 (and any earlier Kemp-era year
    the site still hosts) 404 under that and need the '-executive-orders'
    suffix. We try both and take whichever actually yields orders.
    """
    return [
        f"{BASE_URL}/executive-action/executive-orders/{year}",
        f"{BASE_URL}/executive-action/executive-orders/{year}-executive-orders",
    ]


def _scrape_from_base(base_url, year):
    """Paginate one listing-URL scheme. Returns (orders_dict, reachable_bool).

    reachable is False only when page 0 itself could not be fetched (a 404
    under this scheme), so the caller can tell "wrong URL scheme" apart from
    "right page, no orders".
    """
    all_orders = {}
    page = 0
    reachable = False

    while True:
        url = base_url if page == 0 else f"{base_url}?page={page}"
        print(f"  Fetching page {page}: {url}")
        html = fetch_page(url)

        if not html:
            if page == 0:
                return {}, False
            break

        reachable = True
        parser = EOPageParser(year)
        parser.feed(html)
        parser.close()
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

    return all_orders, reachable


def scrape_all_pages(year):
    """Fetch all paginated listing pages and return a merged dict of orders.

    Tries each known URL scheme; returns the first that yields orders. Returns
    {} when a page was reachable but empty, or None when no scheme resolved at
    all — the caller distinguishes these for its strict/lenient exit handling.
    """
    any_reachable = False
    for base in candidate_bases(year):
        orders, reachable = _scrape_from_base(base, year)
        any_reachable = any_reachable or reachable
        if orders:
            return orders
    return {} if any_reachable else None


# ── JSON I/O ─────────────────────────────────────────────────────────────────

def load_existing(year):
    path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {'metadata': {'year': year, 'governor': governor_for_year(year), 'count': 0},
            'orders': []}


def save(year, data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_year(year, strict=True):
    """Fetch and merge one year. Returns True if the file was written.

    strict=True (the daily job) exits non-zero when a year returns nothing, so
    a broken page structure is caught loudly. strict=False (backfill over a
    range) treats an empty year as "nothing published / archived" and skips on,
    since not every year has a reachable listing page.
    """
    source_url = f"{BASE_URL}/executive-action/executive-orders/{year}"
    print(f"Fetching GA Executive Orders for {year}...")

    scraped = scrape_all_pages(year)
    if scraped is None:
        msg = f"could not fetch listing page for {year}"
        if strict:
            print(f"Error: {msg} — aborting")
            sys.exit(1)
        print(f"  Skipping {year}: {msg}")
        return False
    if not scraped:
        msg = f"no orders found for {year} — page structure may have changed or none published"
        if strict:
            print(f"Warning: {msg}")
            sys.exit(1)
        print(f"  Skipping {year}: {msg}")
        return False

    # Warn about any entries where the title is missing, too short, or suspiciously long
    bad = [n for n, e in scraped.items()
           if not (15 <= len(e.get('title', '')) <= _MAX_TITLE)]
    if bad:
        print(f"Warning: {len(bad)} order(s) have bad titles: {bad[:5]}")

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
        title_ok = 15 <= len(entry.get('title', '')) <= _MAX_TITLE

        if is_new:
            if title_ok:
                merged[num] = entry
                new_count += 1
            else:
                print(f"  Skipping new {num} — bad title ({len(entry.get('title',''))} chars): {entry.get('title','')[:80]!r}")
        else:
            if title_ok:
                merged[num] = _carry_enrichment(entry, existing[num])  # refresh, keep enrichment
            # else keep existing curated entry unchanged

    all_orders = sorted(merged.values(), key=lambda o: o['number'], reverse=True)

    if not new_count:
        print(f"  No new orders — skipping save (file unchanged)")
        return False

    data['_note']    = (f"Sourced from {source_url}. "
                        f"The current year is auto-updated daily; prior years are static.")
    data['metadata'] = {
        'year':      year,
        'governor':  governor_for_year(year),
        'updatedAt': datetime.now().strftime('%Y-%m-%d'),
        'source':    source_url,
        'count':     len(all_orders),
    }
    data['orders'] = all_orders

    path = save(year, data)
    print(f"Saved {len(all_orders)} orders -> {path} ({new_count} new)")
    return True


def parse_years(args):
    """Turn CLI args into a sorted, de-duplicated list of years.

    Accepts individual years ("2020") and inclusive ranges ("2016-2022").
    With no args, defaults to the current year (the daily-job behaviour).
    """
    if not args:
        return [YEAR]
    years = set()
    for a in args:
        if '-' in a:
            lo, hi = a.split('-', 1)
            years.update(range(int(lo), int(hi) + 1))
        else:
            years.add(int(a))
    return sorted(years)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    years = parse_years(argv)

    # A single implicit current-year run keeps the strict contract the daily
    # workflow relies on. An explicit multi-year backfill is lenient per year.
    strict = (argv == [] or argv is None) and len(years) == 1

    wrote_any = False
    for year in years:
        if fetch_year(year, strict=strict):
            wrote_any = True

    if len(years) > 1:
        print(f"\nBackfill complete for {years[0]}–{years[-1]}; "
              f"{'files written' if wrote_any else 'no files changed'}.")


if __name__ == '__main__':
    main()
