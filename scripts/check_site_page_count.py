#!/usr/bin/env python3
"""Deploy gate: refuse to publish a built site that lost a large share of its pages.

Run by deploy-pages.yml after the Jekyll build and BEFORE the artifact upload, so a
failure stops `deploy` (and therefore the `indexnow` ping, which only follows a
successful run). A generator failure that merely degrades is tolerated elsewhere;
what must never ship is a site that silently went missing hundreds of pages.

Two checks on the number of built HTML pages in _site:
  * absolute floor (MIN_PAGES): the site had 1,484 pages on 2026-11-02 (1,411 of
    them generated entity pages). 1,200 is ~81% of that: well below normal
    churn, well above what a broken build_entity_pages.py leaves (~70 hand-written
    pages plus posts).
  * relative drop (MAX_DROP): more than 10% below the previous deploy's count,
    the same tolerance build_entity_pages.py uses for its own entity count.
    The prior count lives in a one-line state file the workflow caches.
    A missing state file (first run / evicted cache) skips only this check.

On success the new count is written to the state file. On failure it is NOT, so
a bad run cannot lower the baseline the next run is compared with.

Usage: check_site_page_count.py [--site _site] [--state .deploy-page-count.json]
Exit 0 ok, 1 gate tripped. Stdlib only.
"""
import argparse
import json
import os
import sys

MIN_PAGES = 1200
MAX_DROP = 0.10


def count_pages(site):
    n = 0
    for _root, _dirs, files in os.walk(site):
        n += sum(1 for f in files if f.endswith(".html"))
    return n


def evaluate(count, prior, min_pages=MIN_PAGES, max_drop=MAX_DROP):
    """Return a list of human-readable problems (empty = pass)."""
    problems = []
    if count < min_pages:
        problems.append(f"{count} pages built, below the floor of {min_pages}")
    if prior and prior > 0 and count < prior * (1 - max_drop):
        problems.append(
            f"{count} pages built, more than {int(max_drop * 100)}% below the "
            f"previous deploy's {prior}")
    return problems


def load_prior(path):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f).get("pages")
        return v if isinstance(v, int) and v > 0 else None
    except (OSError, ValueError, AttributeError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="_site")
    ap.add_argument("--state", default=".deploy-page-count.json")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.site):
        print(f"check_site_page_count: {args.site} does not exist", file=sys.stderr)
        return 1
    count = count_pages(args.site)
    prior = load_prior(args.state)
    problems = evaluate(count, prior)
    print(f"SITE_PAGE_COUNT pages={count} prior={prior if prior else 'none'} "
          f"status={'FAIL' if problems else 'ok'}")
    if problems:
        for p in problems:
            print(f"check_site_page_count: {p}", file=sys.stderr)
        return 1
    with open(args.state, "w", encoding="utf-8") as f:
        json.dump({"pages": count}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
