#!/usr/bin/env python3
"""Submit new/changed URLs to IndexNow so Bing (and other participating engines)
discover them within minutes instead of waiting for a scheduled crawl.

Run after each Pages deploy (see .github/workflows/indexnow.yml). IndexNow asks
callers to submit only added or changed URLs, not the whole sitemap every day, so:

  * On the first run (no previous URL list cached) we submit everything once —
    the expected bulk adoption submission.
  * On later runs we submit URLs newly present in the sitemap since the last run
    (new entity pages, new posts) plus a small curated set of pages we know change
    every day (the homepage, the feed, and the data hub pages). Routine re-crawls
    of already-known pages are left to the engines.

sitemap.xml uses a uniform build-time lastmod (no jekyll-last-modified-at plugin),
so we intentionally diff on the URL set, not on lastmod — a lastmod diff would
flag every page every day. If real per-page lastmod is added later, switch the
`added` computation to compare lastmod too.

Environment:
  INDEXNOW_KEY           the IndexNow key (also hosted at KEY_LOCATION)
  INDEXNOW_KEY_LOCATION  public URL of the key file
  SITEMAP_URL            sitemap to read (default https://www.votega.org/sitemap.xml)
  HOST                   bare host (default www.votega.org)
  PREV_LOCS              path to previous run's URL list (may not exist)
  OUT_LOCS               path to write this run's URL list (for the next run)
  DRY_RUN                if set, print what would be submitted and skip the POST
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error

HOST = os.environ.get("HOST", "www.votega.org")
SITEMAP_URL = os.environ.get("SITEMAP_URL", f"https://{HOST}/sitemap.xml")
KEY = os.environ.get("INDEXNOW_KEY", "")
KEY_LOCATION = os.environ.get("INDEXNOW_KEY_LOCATION", f"https://{HOST}/{KEY}.txt")
PREV_LOCS = os.environ.get("PREV_LOCS", "previous_locs.txt")
OUT_LOCS = os.environ.get("OUT_LOCS", "current_locs.txt")
ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URLS = 10000  # IndexNow per-request limit

# Pages whose content is regenerated on essentially every deploy.
CURATED_PATHS = [
    "/", "/feed.xml",
    "/ga-bills.html", "/ga-congress-trades.html", "/ga-executive-orders.html",
    "/ga-party-unity.html", "/ga-majority-tracker.html", "/ga-voter-access.html",
    "/supreme-court.html", "/elections/candidates/", "/open-data",
]


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "votega-indexnow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def sitemap_entries(xml):
    """Return {loc: lastmod-or-empty} from the sitemap, dependency-free."""
    import re
    out = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        if not loc:
            continue
        lm = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        out[loc.group(1).strip()] = lm.group(1).strip() if lm else ""
    return out


def load_prev(path):
    """Prior {loc: lastmod}. Tolerates the older newline-list format (lastmod unknown)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text:
            return {}
        if text[0] == "{":
            return json.loads(text)
        return {ln.strip(): "" for ln in text.splitlines() if ln.strip()}
    except (ValueError, OSError):
        return {}


def main():
    if not KEY:
        print("INDEXNOW_KEY not set; skipping", file=sys.stderr)
        return 0
    try:
        current = sitemap_entries(fetch(SITEMAP_URL))
    except Exception as exc:
        print(f"could not fetch sitemap ({exc}); skipping", file=sys.stderr)
        return 0
    if not current:
        print("sitemap had no URLs; skipping", file=sys.stderr)
        return 0

    prev = load_prev(PREV_LOCS)
    curated = {f"https://{HOST}{p}" for p in CURATED_PATHS} & set(current)
    if prev is not None:
        # New URLs, plus any whose lastmod advanced since last run. Pages with no
        # lastmod in the sitemap (some hubs) can't be diffed this way, so the
        # curated daily set is the backstop for those.
        changed = {loc for loc, lm in current.items()
                   if loc not in prev or prev.get(loc, "") != lm}
        submit = sorted(changed | curated)
        reason = f"{len(changed - curated)} new/changed + {len(curated)} daily"
    else:
        submit = sorted(current)  # first run: bulk adoption
        reason = "first run (bulk)"

    # Always record the current {loc: lastmod} for the next run's diff.
    os.makedirs(os.path.dirname(OUT_LOCS) or ".", exist_ok=True)
    with open(OUT_LOCS, "w", encoding="utf-8") as fh:
        json.dump(current, fh, separators=(",", ":"))

    if not submit:
        print("nothing new to submit")
        return 0
    submit = submit[:MAX_URLS]
    print(f"submitting {len(submit)} URLs to IndexNow ({reason})")

    if os.environ.get("DRY_RUN"):
        for u in submit[:20]:
            print("  ", u)
        if len(submit) > 20:
            print(f"   … +{len(submit) - 20} more")
        return 0

    payload = json.dumps({
        "host": HOST, "key": KEY, "keyLocation": KEY_LOCATION, "urlList": submit,
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "votega-indexnow/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow responded {r.status}")
    except urllib.error.HTTPError as exc:
        # 4xx/5xx are non-fatal: never fail the pipeline over a submission ping.
        print(f"IndexNow HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}",
              file=sys.stderr)
    except Exception as exc:
        print(f"IndexNow submission failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
