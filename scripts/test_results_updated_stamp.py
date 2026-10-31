#!/usr/bin/env python3
"""Pin the "Last updated" stamp that tells a reader how old an election-night count is.

The results page cannot be live. `_layouts/election_results.html` renders the
counts into the HTML at build time, and GitHub Pages serves that HTML with
`max-age=600` from its own CDN (measured 2026-10-30: Cloudflare returns
`cf-cache-status: DYNAMIC` for it, so it is NOT the cache in play and a
Cloudflare purge cannot clear it). A reader can therefore be looking at numbers
up to ~10 minutes old, with nothing on the page to say so.

So the page says when the numbers were built. `build_results_json.py` records it
because the thing that changes the numbers is the thing that should stamp them —
front matter would be an election-night step to remember at 9pm, and the stamp
was date-only precisely because nobody could have kept a time current by hand.

THE BUG THIS FILE EXISTS FOR. The stamp is stored as EPOCH SECONDS and the
layout must render `.epoch`. Liquid's `date` filter converts an integer through
the site `timezone` (America/New_York), but renders an ISO 8601 string in
whatever offset the string itself carries. Verified by building both forms on
2026-10-30: the same moment published as

    epoch 1793760000          -> "November 3, 2026 at ... PM ET"   (right day)
    "2026-11-04T02:40:00Z"    -> "November 4, 2026 at 2:40 AM ET"  (TOMORROW)

A 9:40pm Election Night build naming tomorrow's date is worse than the missing
time this replaced, because it reads as precise. `iso` is stored beside `epoch`
only so the file can be read by eye — rendering it is the regression.

The other checks:

  * The stamp is keyed by `data_key`, the same string a page's `results_data`
    front matter carries. Any other spelling silently yields no stamp at all.
  * Building one election does not erase another's stamp. The builder runs per
    page, so an overwrite would blank every other results page's stamp.
  * The time shows only while a page is `unofficial`. A certified page is a
    settled record that keeps its hand-set certification date, and an
    `upcoming` page holds nothing but zeros, where a precise build time implies
    counts that do not exist. That gate also keeps the stamp inside one DST
    period: a time is only ever shown in the days between poll close and
    certification, so it is never re-rendered across a clock change.

Usage:
  python scripts/test_results_updated_stamp.py

Exits 0 on success, 1 on any failure.
"""

import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_results_json as B  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(REPO, '_layouts', 'election_results.html')
SIDECAR = os.path.join(REPO, '_data', 'results_updated.json')

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def ok(label, cond, detail=''):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        failures.append(label)


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def builder_cases():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'results_updated.json')

        stamp = B.record_build_time('ga-general-2026-results', stamp_path=path)
        data = load(path)

        check("the stamp is keyed by data_key",
              sorted(data), ['ga-general-2026-results'])
        check("the returned stamp is the stored one",
              data['ga-general-2026-results'], stamp)
        check("the stamp carries epoch and iso",
              sorted(stamp), ['epoch', 'iso'])

        # Liquid converts an integer through the site timezone; it renders a
        # string in the string's own offset. The integer is the load-bearing one.
        ok("epoch is an int, not a string", isinstance(stamp['epoch'], int),
           f"{stamp['epoch']!r} would render through its own offset, not the site's")

        parsed = datetime.datetime.fromisoformat(stamp['iso'])
        ok("iso parses as ISO 8601", parsed is not None)
        ok("iso carries a UTC offset", parsed.utcoffset() is not None,
           f"{stamp['iso']!r} is naive, so it cannot be checked against epoch")
        ok("iso has no microseconds", parsed.microsecond == 0, stamp['iso'])
        check("epoch and iso are the same moment",
              int(parsed.timestamp()), stamp['epoch'])

        # A known moment, so the arithmetic itself is pinned rather than just
        # self-consistent: 02:40 UTC on 4 Nov 2026 is 9:40pm ET on election night.
        fixed = datetime.datetime(2026, 11, 4, 2, 40, tzinfo=datetime.timezone.utc)
        known = B.record_build_time('ga-general-2026-results', now=fixed,
                                    stamp_path=path)
        check("a known moment stamps the expected epoch", known['epoch'], 1793760000)
        check("a known moment stamps the expected iso",
              known['iso'], '2026-11-04T02:40:00+00:00')

        # A second page's build must not blank the first.
        B.record_build_time('ga-primary-results', stamp_path=path)
        data = load(path)
        check("building one page keeps the other's stamp",
              sorted(data), ['ga-general-2026-results', 'ga-primary-results'])
        check("the first page's stamp is untouched",
              data['ga-general-2026-results'], known)
        ok("a rebuild leaves the other page alone",
           data['ga-primary-results']['epoch'] != known['epoch'])

        # An unreadable sidecar must not cost us the results, which are already
        # written by the time the stamp is recorded.
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('{ this is not json')
        recovered = B.record_build_time('ga-general-2026-results', stamp_path=path)
        data = load(path)
        check("a corrupt sidecar is rebuilt rather than fatal",
              sorted(data), ['ga-general-2026-results'])
        check("the rebuilt sidecar holds the new stamp",
              data['ga-general-2026-results'], recovered)

        # A list is valid JSON but the wrong shape; treat it like corruption
        # rather than crashing when assigning into it.
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(['not', 'a', 'map'], fh)
        B.record_build_time('ga-primary-results', stamp_path=path)
        check("a wrong-shaped sidecar is replaced with a map",
              sorted(load(path)), ['ga-primary-results'])


def layout_cases():
    with open(LAYOUT, encoding='utf-8') as fh:
        src = fh.read()

    ok("the layout reads the sidecar",
       'site.data.results_updated[page.results_data]' in src,
       "the stamp must be looked up by the page's own results_data key")

    # The regression guard: `.epoch` renders through the site timezone, the bare
    # value renders in its own offset and can name the wrong day.
    ok("the layout renders pr_built.epoch", 'pr_built.epoch | date:' in src,
       "an ISO string renders in its own offset — a 9:40pm build printed 2:40 AM")
    ok("the layout never renders the bare stamp or its iso",
       'pr_built | date:' not in src and 'pr_built.iso' not in src,
       "iso is for reading the file by eye, not for rendering")

    ok("the time is gated on unofficial",
       "result_status == 'unofficial'" in src,
       "an upcoming page holds only zeros and a certified one keeps its date")

    ok("the rendered time is labelled ET",
       'ET' in src and '%-I:%M %p' in src,
       "a bare clock time is ambiguous to a reader outside Georgia")

    ok("a certified page still falls back to page.updated",
       'page.updated | date:' in src)


def sidecar_cases():
    """The committed sidecar must be the shape the layout indexes into."""
    if not os.path.exists(SIDECAR):
        # Not an error: the file appears on the first build, and the layout
        # treats a missing lookup as "no stamp" and falls back to page.updated.
        print("  ok   no committed sidecar yet (the layout falls back)")
        return
    data = load(SIDECAR)
    ok("the committed sidecar is a map", isinstance(data, dict), type(data).__name__)
    if not isinstance(data, dict):
        return

    results_dir = os.path.join(REPO, '_data', 'election_results')
    known = {f[:-5] for f in os.listdir(results_dir) if f.endswith('.json')}
    unknown = sorted(set(data) - known)
    ok("every stamped key is a real results data file", not unknown,
       f"no _data/election_results file for {unknown}")

    bad = []
    for key, value in data.items():
        try:
            if not isinstance(value['epoch'], int):
                bad.append(f"{key}: epoch is {type(value['epoch']).__name__}")
                continue
            parsed = datetime.datetime.fromisoformat(value['iso'])
            if parsed.utcoffset() is None:
                bad.append(f"{key}: iso is naive")
            elif int(parsed.timestamp()) != value['epoch']:
                bad.append(f"{key}: epoch and iso disagree")
        except (KeyError, TypeError, ValueError) as exc:
            bad.append(f"{key}: {exc}")
    ok("every committed stamp is a consistent epoch/iso pair", not bad, str(bad))


if __name__ == "__main__":
    print("results \"last updated\" stamp:")
    print(" builder:")
    builder_cases()
    print(" layout:")
    layout_cases()
    print(" committed sidecar:")
    sidecar_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
