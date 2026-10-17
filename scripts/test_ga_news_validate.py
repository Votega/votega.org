#!/usr/bin/env python3
"""Assert validate_ga_news.py gates on self-contradiction and only reports a thin run.

The property under test is the tier split. The old gate (`items >= 20`) was a
world-controlled floor: a Cloudflare-blocked feed or a quiet window aborted a
job that runs every three hours. Each case pins which side of the line a
condition falls on. Stdlib only (run-script-tests.yml installs no packages).

Usage:
  python scripts/test_ga_news_validate.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_news as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def item(n, source="A", entity=None, topics=()):
    return {"id": f"id{n}", "title": f"t{n}", "url": f"https://x/{n}", "source": source,
            "entityIds": [entity] if entity else [], "topics": list(topics)}


def sound(n=30):
    items = [item(i, "A" if i % 2 else "B", "vg-1" if i == 0 else None,
                  ["elections"] if i < 3 else []) for i in range(n)]
    return {
        "metadata": {"count": n, "entityTagged": 1, "sources": ["A", "B", "C"],
                     "topicCounts": {"elections": 3}},
        "entities": {"vg-1": {"name": "X", "url": None}},
        "items": items,
    }


def mutate(fn, n=30):
    d = sound(n)
    fn(d)
    return d


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    check("small quiet file is NOT a tier-1 failure (old floor was 20)",
          V.tier1(mutate(lambda d: (d["items"].__delitem__(slice(3, None)),
                                    d["metadata"].update(count=3)))), [])
    check("count != items", len(V.tier1(mutate(lambda d: d["metadata"].update(count=99)))), 1)
    check("entityTagged != tagged items",
          len(V.tier1(mutate(lambda d: d["metadata"].update(entityTagged=5)))), 1)
    check("topicCounts != tally",
          len(V.tier1(mutate(lambda d: d["metadata"].update(topicCounts={"elections": 9})))), 1)
    check("duplicate id",
          len(V.tier1(mutate(lambda d: d["items"][1].update(id="id0")))), 1)
    check("missing required field",
          len(V.tier1(mutate(lambda d: d["items"][2].update(url=None)))), 1)
    check("source not in metadata.sources",
          len(V.tier1(mutate(lambda d: d["items"][2].update(source="Z")))), 1)
    check("orphan entity",
          len(V.tier1(mutate(lambda d: d["entities"].update({"vg-9": {}})))), 1)
    check("items not a list", V.tier1({"metadata": {}, "items": {}, "entities": {}}),
          ["items is missing or not a list"])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    old = sound(30)
    check("no baseline -> nothing", V.tier2(sound(), None), [])
    check("unchanged -> nothing", V.tier2(sound(), old), [])
    check("modest dip -> nothing", V.tier2(sound(25), old), [])
    thin = sound(30)
    thin["items"] = [i for i in thin["items"] if i["source"] != "B"]
    sec = V.tier2(thin, old)
    check("big drop reports", [h for h, _ in sec], ["Thin run"])
    check("big drop names the silent source", any("B" in l for l in sec[0][1][1:]), True)
    check("tier 2 never raises tier-1 errors on a thin but sound file",
          V.tier1(mutate(lambda d: (d["items"].__delitem__(slice(5, None)),
                                    d["metadata"].update(count=5)))), [])
    check("render with no sections says no material change",
          "No material change" in V.render("ga-news.json", []), True)


def main():
    tier1_cases()
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
