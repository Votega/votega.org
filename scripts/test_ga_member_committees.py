#!/usr/bin/env python3
"""Committee memberships on the roster (generate_ga_members_soap.build_record).

Pins: an ended membership (DateVacated) is dropped when the member has current ones, so
a chair handed over mid-biennium is not listed twice (Harbin, Senate Government
Oversight, 2026-01-13); a member whose every membership ended keeps them; committeeRoles
carries the committee id the bills producer joins chairs on.

Usage: python scripts/test_ga_member_committees.py     (no network)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_members_soap as M  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def record(committees):
    listing = {"id": 5, "first": "Marty", "last": "Harbin", "chamber": "Senate", "party": "Republican",
               "district": 16}
    detail = {"sessions": [{"sessionId": 1033, "description": "2025-2026 Regular Session",
                            "committees": committees}]}
    return M.build_record(listing, detail, 1033, {}, None)


def com(cid, name, role, vacated=None):
    return {"id": cid, "code": None, "name": name, "type": "Senate", "role": role, "dateVacated": vacated}


r = record([com(130, "Government Oversight", "Chairman", "2026-01-13T00:00:00"),
            com(78, "Insurance and Labor", "Vice Chairman", "2026-01-13T00:00:00"),
            com(130, "Government Oversight", "Member"),
            com(78, "Insurance and Labor", "Chairman")])
check("ended memberships dropped", sorted((c["id"], c["role"]) for c in r["committeeRoles"]),
      [(78, "Chairman"), (130, "Member")])
check("names follow", r["committees"], ["Government Oversight", "Insurance and Labor"])
r = record([com(82, "Retirement", "Member", "2026-01-13T00:00:00")])
check("a departed member keeps what they served on", [c["id"] for c in r["committeeRoles"]], [82])

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
