#!/usr/bin/env python3
"""Seat-label invariants of generate_local_officials.classify(). No network, no deps.

Two real SoS label shapes used to merge or lose seats:
  * "County Commissioner 4" (Harris) has the bare number after 'commissioner', not
    'commission', so it fell through to "At-Large" and two seats collided.
  * "Post 1" (Glynn) was relabelled "District 1", colliding with Glynn's real
    District 1. A Post stays a Post.

Run: python scripts/test_generate_local_officials_seats.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_local_officials as G  # noqa: E402

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


def seat(office):
    c = G.classify(office)
    return c[2] if c else None


check("bare number after 'commissioner'", seat("County Commissioner 4"), "District 4")
check("bare number after 'commission'", seat("County Commission 1"), "District 1")
check("district stays a district", seat("County Commission - District 2"), "District 2")
check("post stays a post", seat("County Commissioner - Post 1"), "Post 1")
check("at-large post", seat("County Commissioner - At Large - Post 2"), "Post 2 (At-Large)")
check("post and district are different seats",
      seat("County Commissioner - Post 1") != seat("County Commissioner - District 1"), True)
check("chair is a chair", (G.classify("County Commission Chairman") or [None])[0], "Chair")
check("tax commissioner is not a seat", G.classify("Tax Commissioner"), None)
check("statewide commissioner is not a seat", G.classify("Commissioner of Agriculture"), None)

if fails:
    print("FAIL")
    print("\n".join("  " + f for f in fails))
    sys.exit(1)
print("OK - generate_local_officials seat labels")
