#!/usr/bin/env python3
"""Invariants of the optional `election_rules` block in _data/local_officials.yml
and the validator rules for it. No network, no third-party deps.
Run: python scripts/test_local_election_rules.py"""

import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))
import validate_local_officials as V  # noqa: E402

failures = []


def check(cond, msg):
    print("  %s  %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def row(**kw):
    m = {"name": "A B", "role": "Commissioner", "seat": "District 1", "seat_id": "district-1",
         "party": "Republican", "last_elected": 2024, "next_election": 2028, "voting": True}
    m.update(kw)
    return m


ITEM = {"topic": "terms", "text": "Four years.", "cite": "Charter § 1",
        "url": "https://example.org/1"}


def errs(block):
    V.errors.clear()
    V.validate_election_rules("x", block)
    return list(V.errors)


def block(**kw):
    b = {"checked": date(2026, 11, 26), "text_as_of": "2026-10-21", "items": [dict(ITEM)]}
    b.update(kw)
    return b


print("election_rules: the block")
check(V.ELECTION_TOPICS == ("schedule", "terms", "winning", "districts",
      "vacancies", "eligibility", "term_limits"), "topic order")
check(errs(None) == [], "absent block is valid")
check(errs(block()) == [], "date object and ISO string both accepted")
check(errs([]), "block must be a mapping")
check(errs(block(extra=1)), "unknown block key")
for k in ("checked", "text_as_of"):
    check(errs(block(**{k: None})), f"missing {k}")
    check(errs(block(**{k: "11/26/2026"})), f"malformed {k}")
    check(errs(block(**{k: "2026-1-5"})), f"unpadded {k}")
    check(errs(block(**{k: "2026-02-30"})), f"impossible {k}")
    check(errs(block(**{k: datetime(2026, 11, 26, 9, 0)})), f"timestamp {k}")
    check(errs({a: v for a, v in block().items() if a != k}), f"absent {k}")

print("election_rules: the items")
check(errs(block(items=[])), "empty items")
check(errs(block(items="terms")), "items must be a list")
check(errs(block(items=["terms"])), "item must be a mapping")
check(errs(block(items=[ITEM, ITEM])), "repeated topic")
check(errs(block(items=[{**ITEM, "topic": "term"}])), "unknown topic")
check(errs(block(items=[{**ITEM, "topic": ["terms"]}])), "a list as topic is reported, not a crash")
check(errs(block(items=[{**ITEM, "ur1": "x"}])), "unknown item key")
for k in ("topic", "text", "cite", "url"):
    check(errs(block(items=[{**ITEM, k: "  "}])), f"blank {k}")
    check(errs(block(items=[{a: v for a, v in ITEM.items() if a != k}])), f"missing {k}")
check(errs(block(items=[{**ITEM, "url": "http://example.org"}])), "non-https url")
check(errs(block(items=[{**ITEM, "topic": t} for t in V.ELECTION_TOPICS])) == [],
      "every topic once is valid")
check(all(e.startswith("  [x.election_rules] ") for e in errs(block(items=[{**ITEM, "ur1": "x"}]))),
      "errors name the jurisdiction and block")

print("election_rules: wired into the jurisdiction pass")
V.errors.clear()
V.validate_jurisdiction(0, {"id": "x", "name": "X", "type": "city", "body": "Council",
    "partisan": False, "members": [row()], "election_rules": []}, set())
check(any("election_rules" in e for e in V.errors), "validate_jurisdiction checks the block")

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall passed")
