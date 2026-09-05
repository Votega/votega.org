#!/usr/bin/env python3
"""Probe the feeds in _data/news_sources.yml (and any URLs passed as args) and
report which return valid RSS/Atom, how many items, and -- for entity-bound
official feeds -- who each item would be tagged to.

This is the companion to the "confirm the URL, then uncomment it" workflow for
the staged press-release feeds in news_sources.yml: run it from an environment
with outbound access to *.house.gov / *.georgia.gov (the daily build has this;
the web-session sandbox does not), paste a candidate URL, and enable the feed
once it shows OK with items.

Usage:
    python scripts/verify_news_feeds.py                 # all configured feeds
    python scripts/verify_news_feeds.py https://x/feed/ # ad-hoc URL(s) too
"""
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from lib.http import fetch_bytes
import generate_ga_news as g  # reuse parse_feed + entity resolution

SOURCES = os.path.join(REPO, "_data", "news_sources.yml")
CROSSWALK = os.path.join(REPO, "assets", "data", "id-crosswalk.json")


def main():
    cfg = yaml.safe_load(open(SOURCES, encoding="utf-8"))
    feeds = list(cfg.get("feeds") or [])
    for url in sys.argv[1:]:
        feeds.append({"name": url, "url": url, "type": "ad-hoc"})

    people = json.load(open(CROSSWALK, encoding="utf-8"))["people"]
    id_index = g.build_id_index(people)
    person_by_vgid = {p.get("vgId"): p for p in people if p.get("vgId")}

    ok = bad = 0
    for feed in feeds:
        name, url = feed["name"], feed["url"]
        bound_vgid = g.resolve_feed_entity(feed, id_index)
        bound = ""
        if bound_vgid:
            p = person_by_vgid.get(bound_vgid) or {}
            bound = f"  -> tags {(p.get('name') or {}).get('full')}"
        raw = fetch_bytes(url, label=name, retries=1, verbose=False)
        if raw is None:
            print(f"  FAIL  {name}  ({url})")
            bad += 1
            continue
        items = g.parse_feed(raw, name)
        if items:
            print(f"  OK    {name}: {len(items)} items{bound}")
            print(f"        e.g. {items[0]['title'][:70]}")
            ok += 1
        else:
            print(f"  EMPTY {name}  ({url}) -- fetched but no <item>/<entry>")
            bad += 1

    print(f"\n{ok} OK, {bad} failed/empty of {len(feeds)} feeds")
    sys.exit(1 if bad and not sys.argv[1:] else 0)


if __name__ == "__main__":
    main()
