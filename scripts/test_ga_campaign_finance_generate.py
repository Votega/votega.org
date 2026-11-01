#!/usr/bin/env python3
"""vanished_offices: an office that had filers and now has none must be caught."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], os.devnull]   # the module reads argv[1] at import
import generate_ga_campaign_finance as G


def f(office, n):
    return {f"{office}{i}": {"office": office} for i in range(n)}


fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f" (got {got!r}, want {want!r})"))


prev = {**f("Attorney General", 3), **f("Governor", 20)}
check("an office that vanished is named",
      G.vanished_offices(prev, f("Governor", 20)), ["Attorney General"])
check("an office that merely shrank is not",
      G.vanished_offices(prev, {**f("Attorney General", 1), **f("Governor", 5)}), [])
check("a tiny office going empty is not a fault",
      G.vanished_offices(f("Commissioner of Labor", 2), {}), [])
check("no previous file means nothing to compare", G.vanished_offices(None, f("Governor", 1)), [])
sys.exit(1 if fails else 0)
