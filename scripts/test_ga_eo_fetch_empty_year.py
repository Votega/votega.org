#!/usr/bin/env python3
"""Assert the GA executive-orders fetch tells an empty year from a broken scraper.

`fetch_year(strict=True)` is the daily job's path. It used to exit 1 whenever a
year returned nothing, which is a dated time bomb: gov.georgia.gov creates a
year's listing page only once it has content, so on 1 January the current year's
URL 404s under BOTH schemes, no scheme resolves, and the run died before the
validator ever saw the file. Measured 2026-10-17: /2026 returned 200 with 631 KB
of orders while /2027 and /2028 both 404'd.

Commit 6aa75c4e stopped the VALIDATOR failing on an empty year file. This covers
the other half — the fetch step, one stage earlier, where the job actually died.

The property under test is that all four cases are distinguished:

  * nothing this year + last year reads  -> an empty year, write it, exit 0
  * nothing this year + last year broken -> the scraper or scheme moved, exit 1
  * nothing this year + this year already has orders -> a failed scrape, exit 1
  * a normal year with orders            -> unchanged

Usage:
  python scripts/test_ga_eo_fetch_empty_year.py

Exits 0 on success, 1 on any failure. No network: every fetch is stubbed.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_ga_executive_orders as F  # noqa: E402

failures = []

THIS_YEAR = 2027
LAST_YEAR = 2026


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def listing_html(year):
    """Minimal markup the real page parser finds one order in.

    The page is a two-column table: the PDF link carries the order code in its
    href (`mmddyy` + sequence), and the title is the text that FOLLOWS the
    closing link, with any "(PDF, …)" size noise stripped.
    """
    code = f"0115{str(year)[2:]}01"
    return ('<html><body><table><tr>'
            f'<td><a href="/document/{year}-executive-orders/{code}/download">'
            f'{code} (PDF, 98.59 KB)</a></td>'
            '<td>A sufficiently long order title here</td>'
            '</tr></table></body></html>')


def parses_to_an_order():
    """Guard the fixture itself: scheme_alive is only meaningful if this parses."""
    return F.scheme_alive(LAST_YEAR, fetch=lambda url: listing_html(LAST_YEAR))


def run(this_year_result, last_year_reads, existing_orders):
    """Drive fetch_year in a temp OUTPUT_DIR. Returns the exit code, or None."""
    tmp = tempfile.mkdtemp()
    out_dir, scrape, alive = F.OUTPUT_DIR, F.scrape_all_pages, F.scheme_alive
    try:
        F.OUTPUT_DIR = tmp
        if existing_orders is not None:
            with open(os.path.join(tmp, f"ga-executive-orders-{THIS_YEAR}.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"metadata": {"year": THIS_YEAR,
                                        "count": len(existing_orders)},
                           "orders": existing_orders}, f)
        F.scrape_all_pages = lambda year: this_year_result
        F.scheme_alive = lambda year, fetch=None: last_year_reads
        try:
            F.fetch_year(THIS_YEAR, strict=True)
            code = 0
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
        written = None
        path = os.path.join(tmp, f"ga-executive-orders-{THIS_YEAR}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                written = json.load(f)
        return code, written
    finally:
        F.OUTPUT_DIR, F.scrape_all_pages, F.scheme_alive = out_dir, scrape, alive
        shutil.rmtree(tmp, ignore_errors=True)


def order(number="01.15.27.01"):
    return {"number": number, "title": "An order with a long enough title",
            "date": f"{THIS_YEAR}-01-15"}


def cases():
    check("the fixture markup really does parse into an order",
          parses_to_an_order(), True)

    # The January case, and the whole point. The year's page does not exist yet,
    # so NO scheme resolves and scrape_all_pages returns None — not an empty
    # dict. That is the branch the old code failed on.
    code, written = run(None, last_year_reads=True, existing_orders=None)
    check("a 404 year with last year reading does NOT exit 1 "
          "(the January time bomb)", code, 0)
    check("...and an empty file is written for the validator to report",
          (written or {}).get("orders"), [])
    check("...with metadata.count agreeing, so tier 1 stays happy",
          (written or {}).get("metadata", {}).get("count"), 0)

    # Same, for a year whose page exists but lists nothing yet.
    code, _ = run({}, last_year_reads=True, existing_orders=None)
    check("an empty-but-reachable year also does not exit 1", code, 0)

    # The condition `strict` exists for: the scheme or the parser moved.
    code, _ = run(None, last_year_reads=False, existing_orders=None)
    check("nothing this year AND last year unreadable exits 1", code, 1)
    code, _ = run({}, last_year_reads=False, existing_orders=None)
    check("an empty page with last year unreadable also exits 1", code, 1)

    # A year cannot lose its orders. Without this, a transient mid-year 404
    # would pass silently as a quiet day, since the unchanged file gives the
    # validator nothing to report.
    code, written = run(None, last_year_reads=True, existing_orders=[order()])
    check("a populated year going empty exits 1 even when last year reads",
          code, 1)
    check("...and the populated file is left alone",
          len((written or {}).get("orders", [])), 1)

    # Lenient mode (an explicit year, or a multi-year backfill) is unchanged:
    # it skips the year without consulting the previous one.
    tmp_alive = F.scheme_alive
    F.scheme_alive = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("lenient mode must not probe the previous year"))
    try:
        out_dir, scrape = F.OUTPUT_DIR, F.scrape_all_pages
        tmp = tempfile.mkdtemp()
        try:
            F.OUTPUT_DIR, F.scrape_all_pages = tmp, lambda year: None
            check("lenient mode skips an empty year without probing",
                  F.fetch_year(THIS_YEAR, strict=False), False)
        finally:
            F.OUTPUT_DIR, F.scrape_all_pages = out_dir, scrape
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        F.scheme_alive = tmp_alive

    # scheme_alive must not call a year "alive" on a page it cannot parse — that
    # is the exact signal it exists to provide.
    check("scheme_alive is False when the page does not fetch",
          F.scheme_alive(LAST_YEAR, fetch=lambda url: None), False)
    check("scheme_alive is False when the page fetches but parses to nothing",
          F.scheme_alive(LAST_YEAR, fetch=lambda url: "<html><body/></html>"), False)


def main():
    print("the fetch step's empty-year handling:")
    cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
