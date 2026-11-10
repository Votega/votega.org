#!/usr/bin/env python3
"""Invariants of local-officials term dates and seat identity (lib/local_terms.py)
and the validator rules built on them. No network, no third-party deps.
Run: python scripts/test_local_terms.py"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from lib import local_terms as T  # noqa: E402
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


def run_validator(fn, *args):
    V.errors.clear()
    V.warnings.clear()
    fn(*args)
    return list(V.errors), list(V.warnings)


JAN1 = date(2027, 1, 1)

print("is_active: half-open [takes_office, leaves_office)")
out = row(leaves_office=JAN1)
inc = row(name="C D", takes_office=JAN1)
check(T.is_active(out, date(2026, 12, 31)), "outgoing holds the seat on Dec 31")
check(not T.is_active(out, JAN1), "outgoing no longer holds it on the leaves_office date")
check(not T.is_active(inc, date(2026, 12, 31)), "incoming not active before takes_office")
check(T.is_active(inc, JAN1), "incoming active on takes_office")
check(T.is_active(row(), date(1999, 1, 1)), "undated row is always active")
check(T.is_active(row(takes_office="2027-01-01"), JAN1), "ISO string dates parse too")

print("seat_conflicts")
check(T.seat_conflicts([out, inc]) == [], "a handover on the same date is not an overlap")
check(len(T.seat_conflicts([row(), row(name="C D")])) == 1, "two undated holders of one seat conflict")
check(len(T.seat_conflicts([row(leaves_office=date(2027, 1, 2)), inc])) == 1,
      "a one-day overlap conflicts")
check(T.seat_conflicts([row(status="Suspended"), row(name="Interim")]) == [],
      "a Suspended holder does not conflict with the interim serving the seat")
check(T.seat_conflicts([row(), row(seat_id="district-2")]) == [], "different seats never conflict")

print("successor")
check(T.successor([out, inc], out) is inc, "finds the staged row for the same seat")
check(T.successor([out, row(name="X", seat_id="district-2", takes_office=JAN1)], out) is None,
      "ignores a staged row for another seat")
check(T.successor([row(), inc], row()) is None, "no successor for a row with no leaves_office")

print("suggest_seat_id")
check(T.suggest_seat_id({"seat": "Post 1 At-Large"}) == "post-1-at-large", "post + at-large")
check(T.suggest_seat_id({"seat": "At Large"}) == "at-large", "spelling variants collapse")
check(T.suggest_seat_id({"seat": "District 5 (At-Large)"}) == "district-5-at-large", "parenthetical")
check(T.suggest_seat_id({"seat": "At-Large", "role": "Chair", "title": "Mayor"}) == "mayor",
      "a mayor is `mayor`, not the at-large council seat")
check(T.suggest_seat_id({"seat": ""}) is None, "blank label -> None")

print("validator: term fields (tier 1 = the row contradicts itself)")
e, _ = run_validator(V.validate_term_fields, "x", row(takes_office=JAN1, leaves_office=JAN1))
check(any("must be after" in s for s in e), "leaves_office on/before takes_office is an error")
e, _ = run_validator(V.validate_term_fields, "x", row(takes_office="Jan 1 2027"))
check(any("ISO date" in s for s in e), "a non-ISO date is an error")
e, _ = run_validator(V.validate_term_fields, "x", row(seat_id=None))
check(any("seat_id is required" in s for s in e), "a labelled seat needs a seat_id")
e, _ = run_validator(V.validate_term_fields, "x", row(seat="", seat_id=None))
check(e == [], "a row with no seat label and no dates may omit seat_id (Palmetto)")
e, _ = run_validator(V.validate_term_fields, "x", row(seat_id="District 1"))
check(any("lowercase slug" in s for s in e), "seat_id must be a slug")
e, _ = run_validator(V.validate_term_fields, "x", row(leave_reason="quit"))
check(any("leave_reason must be one of" in s for s in e), "unknown leave_reason is an error")
check(any("leaves_office is blank" in s for s in e), "leave_reason without leaves_office is an error")
e, w = run_validator(V.validate_term_fields, "x", row(leaves_office=date(2020, 1, 1)))
check(e == [] and any("no leave_reason" in s for s in w),
      "a past departure with no reason is only reported")
e, w = run_validator(V.validate_term_fields, "x", row(leaves_office=date(2999, 1, 1)))
check(e == [] and w == [], "a FUTURE leaves_office is not flagged: nothing goes red on a date")

print("validator: seats")
e, _ = run_validator(V.validate_seats, "j", [row(), row(name="C D")])
check(any("overlapping dates" in s for s in e), "two people in one seat is an error")
e, w = run_validator(V.validate_seats, "j", [row(leaves_office=date(2020, 1, 1), leave_reason="resigned")])
check(e == [] and any("no current or incoming holder" in s for s in w),
      "an emptied seat is reported, not gated")
e, w = run_validator(V.validate_seats, "j", [row(leaves_office=date(2999, 1, 1)),
                                             row(name="C D", takes_office=date(2999, 1, 1))])
check(e == [] and w == [], "a staged handover is clean")

print("validator: At-Large spelling")
for bad in ("At-large", "At Large", "at large", "Post 1 At Large"):
    V.errors.clear()
    V.validate_member("x", 0, row(seat=bad, seat_id="at-large"), True)
    check(any("'At-Large'" in s for s in V.errors), f"{bad!r} is rejected")
for good in ("At-Large", "Post 1 At-Large", "District 5 (At-Large)"):
    V.errors.clear()
    V.validate_member("x", 0, row(seat=good, seat_id="at-large"), True)
    check(not any("'At-Large'" in s for s in V.errors), f"{good!r} is accepted")

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall passed")
