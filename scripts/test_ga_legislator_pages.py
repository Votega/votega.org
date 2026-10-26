#!/usr/bin/env python3
"""Drift test: roster `votegaUrl` must equal the permalink the real page builder emits.

lib/ga_legislator_pages.py restates two rules that live in other scripts (who gets a page:
generate_search_corpus; what the slug is: build_entity_pages). This runs BOTH real
implementations over the committed roster and compares, so a change to either one fails
here instead of publishing links that 404.

Usage: python scripts/test_ga_legislator_pages.py   (exit 0 ok, 1 on failure)
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import types  # noqa: E402

try:
    import yaml  # noqa: F401
except ImportError:
    # run-script-tests.yml installs no pip packages and build_entity_pages imports yaml at
    # module level; the GA-legislator path never calls it, so a stub is enough here.
    sys.modules["yaml"] = types.ModuleType("yaml")

import build_entity_pages as B  # noqa: E402
import generate_search_corpus as C  # noqa: E402
from lib import ga_legislator_pages as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def builder_urls(members_doc):
    """Run the real corpus filter and the real page builder over `members_doc`; return
    {roster id: permalink}. Nothing is written: page/card output is stubbed."""
    records, seen = [], set()
    real_load = C.load
    C.load = lambda name, *a, **k: members_doc if name == "ga-members.json" else real_load(name, *a, **k)
    try:
        C.build_ga_legislators(records, seen)
    finally:
        C.load = real_load
    saved = (B.load, B.write_page, B.add_card, B.resolve_lastmod)
    real_b_load = B.load
    B.load = lambda name: members_doc if name == "ga-members.json" else real_b_load(name)
    B.write_page = lambda *a, **k: None
    B.add_card = lambda *a, **k: None
    B.resolve_lastmod = lambda *a, **k: "2000-01-01"
    urls = {}
    try:
        B.build_ga_legislators(records, urls, {}, {})
    finally:
        B.load, B.write_page, B.add_card, B.resolve_lastmod = saved
    return urls.get("ga-legislator", {})


def main():
    with open(os.path.join(B.SRC_DIR, "ga-members.json"), encoding="utf-8") as f:
        doc = json.load(f)
    members = doc["members"]

    # 1. Real data: derived urls == what the builder emits; no page -> None.
    check("SITE_URL matches the builder", P.SITE_URL, B.SITE_URL)
    want = {k: B.SITE_URL + v for k, v in builder_urls(doc).items()}
    derived = copy.deepcopy(members)
    P.assign_votega_urls(derived)
    got = {m["id"]: m["votegaUrl"] for m in derived if m["votegaUrl"]}
    check("derived urls equal the page builder's permalinks", got, want)
    check("members without a page get null",
          all(m["votegaUrl"] is None for m in derived if m["id"] not in want), True)
    check("some members have pages", len(want) > 200, True)

    # 2. Collision rule, on a doctored roster (two members, same name/chamber/district).
    a = {"id": "ocd-person/aaaaaaaa-1111", "name": "Pat Doe", "chamber": "House of Representatives",
         "district": 5, "party": "Democratic", "status": None}
    b = dict(a, id="ocd-person/bbbbbbbb-2222")
    synth = {"metadata": doc.get("metadata", {}), "members": [a, b]}
    sd = copy.deepcopy(synth["members"])
    P.assign_votega_urls(sd)
    check("collision resolves like the builder",
          {m["id"]: m["votegaUrl"] for m in sd},
          {k: B.SITE_URL + v for k, v in builder_urls(synth).items()})

    # 3. The committed field, once the roster producer has written it, must agree.
    # (The field lands on the next update-ga-members run; absent until then.)
    if any("votegaUrl" in m for m in members):
        check("committed votegaUrl matches derived",
              {m["id"]: m.get("votegaUrl") for m in members},
              {m["id"]: m["votegaUrl"] for m in derived})
    else:
        print("  skip committed votegaUrl check: field not yet written by the roster producer")

    print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
