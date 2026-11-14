#!/usr/bin/env python3
"""Tests for lib/ga_former.py. Stdlib only. Usage: python scripts/test_ga_former.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_former as F  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def mem(gid, status=None, **kw):
    m = {"id": f"ocd-person/{gid}", "legisGaGovId": gid, "name": f"Member {gid}",
         "chamber": "House of Representatives", "district": 63, "party": "Democratic",
         "status": status, "statusDate": None}
    m.update(kw)
    return m


def test_live_resigned_is_former_with_current_tag():
    live = [mem(1), mem(2, "Resigned", statusDate="2026-01-05")]
    got = F.former_records(live, {})
    check("live resigned -> (live record, 'current')", [(r["legisGaGovId"], t) for r, t in got], [(2, "current")])
    check("is_former live departed", F.is_former(live[1], True), True)
    check("is_former live sitting", F.is_former(live[0], True), False)
    check("is_former frozen-only", F.is_former(live[0], False), True)
    check("suspended is not former", F.is_former(mem(3, "Suspended"), True), False)


def test_frozen_only_member_uses_newest_frozen_record():
    old, new = mem(9, name="Old Name"), mem(9, name="New Name")
    frozen = {"2023_24": {"9": old}, "2025_26": {"9": new, "1": mem(1)}}
    got = F.former_records([mem(1)], frozen)
    check("frozen-only newest record", [(r["name"], t) for r, t in got], [("New Name", "2025_26")])


def test_bienniums_dedupe_live_session():
    frozen = {"2025_26": {"1": mem(1)}}
    check("dedupe", F.bienniums_for("1", "2025_26", frozen), ["current"])


def test_bienniums_after_rollover():
    frozen = {"2025_26": {"1": mem(1)}, "2023_24": {"1": mem(1)}, "2021_22": {"2": mem(2)}}
    check("after rollover", F.bienniums_for("1", "2027_28", frozen), ["current", "2025_26", "2023_24"])
    check("frozen-only", F.bienniums_for("2", None, frozen), ["2021_22"])


def test_departure_sentence_resigned():
    m = mem(1, "Resigned", statusDate="2026-01-05")
    check("resigned", F.departure_sentence(m, "2025_26"),
          "Served in the Georgia House, District 63, in the 2025–2026 General Assembly. Resigned January 5, 2026.")
    check("removed", F.departure_sentence(mem(1, "Removed", statusDate="2026-02-10"), "2025_26").endswith(
        "Removed from office February 10, 2026."), True)
    check("deceased", F.departure_sentence(mem(1, "Deceased", statusDate="2026-03-01", chamber="Senate"), "2025_26"),
          "Served in the Georgia Senate, District 63, in the 2025–2026 General Assembly. Died March 1, 2026.")


def test_departure_sentence_no_status():
    check("no status", F.departure_sentence(mem(1), "2023_24"),
          "Served in the Georgia House, District 63, in the 2023–2024 General Assembly.")
    check("status without date", F.departure_sentence(mem(1, "Resigned"), "2023_24").endswith("Assembly."), True)


def test_job_title():
    check("former rep", F.job_title(mem(1), True), "Former State Representative")
    check("former sen", F.job_title(mem(1, chamber="Senate"), True), "Former State Senator")
    check("sitting", F.job_title(mem(1, chamber="Senate"), False), "State Senator")


for t in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    t()
print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed.")
sys.exit(1 if failures else 0)
