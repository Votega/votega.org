#!/usr/bin/env python3
"""Pin the suspension signals: fabricated roster, orders and votes, plus the committed
executive orders for the one real legislator suspension (Rep. Sharon Henderson, 2026).
No network.

Usage:
  python scripts/test_ga_suspension_signals.py

Exits 0 on success, 1 on any failure.
"""

import copy
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from lib import ga_suspension_signals as S  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


H = "House of Representatives"
ROSTER = [
    {"id": "a", "name": "Sharon Henderson", "chamber": H, "district": 113, "status": None},
    {"id": "b", "name": "Pat Doe", "chamber": H, "district": 20, "status": None},
    {"id": "c", "name": "Lee Roe", "chamber": "Senate", "district": 7, "status": None},
]
SUSPEND = {"number": "01.22.26.02", "date": "2026-01-22", "category": "Suspension",
           "title": "Suspending Representative Sharon Henderson from office as the District 113 "
                    "Representative in the Georgia House of Representatives"}


def with_status(roster, mid, **fields):
    r = copy.deepcopy(roster)
    for m in r:
        if m["id"] == mid:
            m.update(fields)
    return r


print("suspension_without_status")
check("flags a suspended legislator the roster calls sitting",
      len(S.suspension_without_status(ROSTER, [SUSPEND])), 1)
check("quiet once the roster says Suspended",
      S.suspension_without_status(with_status(ROSTER, "a", status="Suspended"), [SUSPEND]), [])
check("quiet when the member has since left",
      S.suspension_without_status(with_status(ROSTER, "a", status="Resigned"), [SUSPEND]), [])
check("quiet when the EO number is acknowledged in statusNote",
      S.suspension_without_status(with_status(ROSTER, "a", statusNote="Reinstated; see EO 01.22.26.02"),
                                  [SUSPEND]), [])
check("ignores a sheriff or county commissioner",
      S.suspension_without_status(ROSTER, [{"number": "x", "date": "2026-01-01", "title":
          "Suspending Sheriff Kenneth Henderson from the Office of Sheriff of Towns County"}]), [])
check("says so when no member with that surname holds the seat",
      "no member with that surname" in S.suspension_without_status(
          [m for m in ROSTER if m["id"] != "a"] + [{"id": "z", "name": "Someone Else", "chamber": H,
                                                    "district": 113}], [SUSPEND])[0], True)
senator = {"number": "s1", "date": "2026-02-01", "title":
           "Suspending Senator Lee Roe from office as the District 7 Senator in the Georgia Senate"}
check("handles a Senator", len(S.suspension_without_status(ROSTER, [senator])), 1)

print("review_commission_pending")
COMMISSION = {"number": "01.08.26.01", "date": "2026-01-08", "category": "Appointment",
              "title": "Appointing the Review Commission to review the indictment of Ms. Sharon "
                       "Henderson, District 113 Representative in the Georgia House of Representatives"}
check("flags a recent commission on a sitting legislator",
      len(S.review_commission_pending(ROSTER, [COMMISSION], today=date(2026, 2, 1))), 1)
check("quiet once the commission is older than the window",
      S.review_commission_pending(ROSTER, [COMMISSION], today=date(2026, 9, 1)), [])
check("quiet once the member is Suspended",
      S.review_commission_pending(with_status(ROSTER, "a", status="Suspended"), [COMMISSION],
                                  today=date(2026, 2, 1)), [])
check("ignores a commission on a non-legislator",
      S.review_commission_pending(ROSTER, [{"number": "y", "date": "2026-01-08", "title":
          "Appointing the Review Commission to examine the indictment of Kenneth Henderson "
          "Sheriff of Towns County"}], today=date(2026, 2, 1)), [])

print("suspended_but_voting")
VOTES = {"voteIds": ["v0", "v1", "v2"],
         "votes": {"v0": {"date": "2026-01-10"}, "v1": {"date": "2026-03-01"},
                   "v2": {"date": "2026-03-02"}},
         "memberVotes": {"a": {"0": "Y", "1": "E", "2": "NV"}}}
suspended = with_status(ROSTER, "a", status="Suspended", statusDate="2026-01-22")
check("excused and not-voting after the date are not votes cast",
      S.suspended_but_voting(suspended, VOTES), [])
VOTES["memberVotes"]["a"]["1"] = "Y"
got = S.suspended_but_voting(suspended, VOTES)
check("a Yea after the suspension date is flagged", len(got), 1)
check("it reports the latest date", "2026-03-01" in got[0], True)
check("a vote before the date is not flagged",
      S.suspended_but_voting(with_status(ROSTER, "a", status="Suspended", statusDate="2026-04-01"),
                             VOTES), [])
check("no votes file means no signal", S.suspended_but_voting(suspended, None), [])

print("committed data")
orders = S.load_orders(os.path.join(ROOT, "assets", "data", "ga-executive-orders-*.json"))
check("loads executive orders", len(orders) > 100, True)
sec = S.suspension_without_status(ROSTER, orders)
check("the real Henderson order is recognised", any("01.22.26.02" in l for l in sec), True)
members = json.load(open(os.path.join(ROOT, "assets", "data", "ga-members.json")))["members"]
check("no unresolved legislator suspension in the committed roster",
      S.signal_sections(members, orders, S.load_member_votes(
          os.path.join(ROOT, "assets", "data", "ga-member-votes.json")), today=date(2026, 10, 23)), [])

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all passed")
