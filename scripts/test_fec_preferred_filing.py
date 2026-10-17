#!/usr/bin/env python3
"""Assert the FEC record a candidate's money is read from is the right one.

Covers the two selection rules in generate_fec_data.py: preferred_filing(), which
picks between several candidate ids held by one person, and
get_candidate_committee(), which picks the committee those ids draw their totals
from. Both failed on real members of the Georgia delegation.

A sitting House member running for Senate holds two live FEC candidate ids in the
same cycle, both pointing at one principal committee. Because the totals are
fetched per committee, both ids carry identical money and identical coverage
dates, so every rule in preferred_filing() tied — and the pick fell through to
the candidate-id sort. That is alphabetical, so the House id won ("H4GA01039" <
"S6GA00374"), and /us-congress/earl-carter-ga-1/ linked to a filing FEC.gov
renders as "nothing filed" for 2026: every document of the cycle is filed under
the Senate candidacy. Same for Mike Collins (H4GA10071 vs S6GA00390).

lastFileDate breaks that tie. These cases pin the rule and the ordering of the
steps around it.

Usage:
  python scripts/test_fec_preferred_filing.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_fec_data as gen  # noqa: E402
from generate_fec_data import preferred_filing  # noqa: E402

FEC_FILE = "assets/data/ga-fec-data.json"

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def dual_filer_case():
    """The real shape: one committee, one set of totals, two candidate ids."""
    shared = {
        "totalRaised": 7300242.83,
        "coverageEndDate": "2026-06-30T00:00:00",
        "committeeId": "C00543967",
    }
    return {
        "H4GA01039": dict(shared, office="H", lastFileDate="2024-11-18"),
        "S6GA00374": dict(shared, office="S", lastFileDate="2025-05-09"),
    }


def committee_cases():
    """Which committees a candidacy's money comes from, and how they combine.

    Two rules replaced here over one night, both of which put other people's
    money on candidate pages: taking the best-ranked committee of any
    designation, then allowing one that had ever been designated P (that
    measured committee AGE -- it accepted seven PACs and refused three
    committees that really were the candidate's own). Only P and A qualify now,
    and ALL of them are summed, because FEC's candidate page does the same.
    """
    real_get = gen.fec_get

    def stub(results):
        gen.fec_get = lambda path, params=None, retries=3: {"results": list(results)}

    try:
        # The ordinary case: one principal committee, nothing else.
        stub([{"committee_id": "C00000001", "name": "CANDIDATE FOR CONGRESS",
               "designation": "P", "last_file_date": "2026-01-01"},
              {"committee_id": "C00000002", "name": "SOME JOINT FUNDRAISER",
               "designation": "J", "last_file_date": "2026-10-15"}])
        got = gen.get_candidate_committees("H0GA01000")
        check("a joint fundraiser is not the candidate's money",
              [a["id"] for a in got["authorized"]], ["C00000001"])
        check("and nothing is left over to point at", got["related"], None)

        # Mike Collins: principal + nominee fund. Reading the principal alone
        # under-reported him by $959,344.49 against his own FEC page.
        stub([{"committee_id": "C00544684", "name": "MIKE COLLINS FOR SENATE",
               "designation": "P", "last_file_date": "2026-10-15"},
              {"committee_id": "C00892000", "name": "COLLINS FOR GA SENATE REPUBLICAN NOMINEE FUND 2026",
               "designation": "A", "last_file_date": "2026-10-15"}])
        got = gen.get_candidate_committees("S6GA00390")
        check("an authorized nominee fund is collected, not dropped",
              [a["id"] for a in got["authorized"]], ["C00544684", "C00892000"])
        check("the principal sorts first, so it stays the headline identity",
              got["authorized"][0]["designation"], "P")

        stub([{"committee_id": "C00000003", "designation": "U", "last_file_date": "2026-10-15"},
              {"committee_id": "C00000002", "designation": "A", "last_file_date": "2026-02-01"}])
        got = gen.get_candidate_committees("H0GA01000")
        check("authorized is kept and unauthorized is not",
              [a["id"] for a in got["authorized"]], ["C00000002"])

        stub([{"committee_id": "C00000001", "designation": "A", "last_file_date": "2025-01-01"},
              {"committee_id": "C00000002", "designation": "A", "last_file_date": "2026-01-01"}])
        check("inside a tier the most recent filer leads",
              [a["id"] for a in gen.get_candidate_committees("H0GA01000")["authorized"]],
              ["C00000002", "C00000001"])

        # Dooley: a leadership PAC is never a source, only a pointer.
        stub([{"committee_id": "C00914531", "name": "LEADERSHIP MATTERS PAC",
               "designation": "U", "last_file_date": "2026-10-15"}])
        got = gen.get_candidate_committees("S6GA00408")
        check("an unauthorized committee yields no authorized set",
              got["authorized"], [])
        check("it becomes a pointer instead", got["related"]["id"], "C00914531")

        # Refusing one PAC must not promote the next: that fall-through put
        # MISSION DEMOCRACY PAC on a page after HOLD THE LINE was refused.
        stub([{"committee_id": "C00868976", "name": "HOLD THE LINE",
               "designation": "U", "last_file_date": "2026-10-15"},
              {"committee_id": "C00768101", "name": "MISSION DEMOCRACY PAC",
               "designation": "D", "last_file_date": "2026-09-01"}])
        got = gen.get_candidate_committees("H2GA14044")
        check("refusing one PAC does not promote the next", got["authorized"], [])
        check("the pointer is the best-ranked of them",
              got["related"]["id"], "C00868976")

        stub([])
        got = gen.get_candidate_committees("H0GA01000")
        check("no linked committee -> nothing either way",
              (got["authorized"], got["related"]), ([], None))
    finally:
        gen.fec_get = real_get


def summing_cases():
    """sum_committee_totals() against Mike Collins' published FEC page."""
    principal = {"receipts": 9290371.80, "disbursements": 8748014.35,
                 "last_cash_on_hand_end_period": 1138587.54,
                 "individual_itemized_contributions": 3551772.0,
                 "individual_unitemized_contributions": 2222710.0,
                 "transfers_from_other_authorized_committee": 2748507.0,
                 "coverage_end_date": "2026-06-30T00:00:00"}
    nominee = {"receipts": 959344.49,
               "individual_itemized_contributions": 224633.59,
               "individual_unitemized_contributions": 675868.82,
               "transfers_from_other_authorized_committee": 57205.44,
               "coverage_end_date": "2026-09-30T00:00:00"}

    m = gen.sum_committee_totals([principal, nominee])
    check("receipts match the FEC candidate page",
          round(m["receipts"], 2), 10249716.29)
    check("itemized individual money matches",
          round(m["individual_itemized_contributions"], 2), 3776405.59)
    check("unitemized individual money matches",
          round(m["individual_unitemized_contributions"], 2), 2898578.82)
    check("transfers are summed, not netted out (FEC does not net them either)",
          round(m["transfers_from_other_authorized_committee"], 2), 2805712.44)
    check("the later coverage date wins, since the figure runs through it",
          m["coverage_end_date"], "2026-09-30T00:00:00")
    check("a field only one committee reports still comes through",
          m["disbursements"], 8748014.35)

    # Nothing non-numeric gets summed: a response carries ids and flags too.
    noise = [{"receipts": 1.0, "cycle": 2026, "committee_id": "C1"},
             {"receipts": 2.0, "cycle": 2026, "committee_id": "C2"}]
    m = gen.sum_committee_totals(noise)
    check("receipts add", m["receipts"], 3.0)
    check("cycle is not added to itself", "cycle" in m, False)
    check("committee_id is not concatenated", "committee_id" in m, False)

    check("one committee is passed through untouched",
          gen.sum_committee_totals([principal]) is principal, True)
    check("no committees -> None", gen.sum_committee_totals([]), None)
    check("a failed totals fetch among several is skipped",
          gen.sum_committee_totals([principal, None])["receipts"], 9290371.80)
    check("all fetches failed -> None", gen.sum_committee_totals([None, None]), None)


def main():
    print("preferred_filing():")

    cands = dual_filer_case()
    ids = sorted(cands)
    check("dual filer -> the more recently filed candidacy",
          preferred_filing(ids, cands), "S6GA00374")
    check("dual filer -> same pick whatever order the ids arrive in",
          preferred_filing(list(reversed(ids)), cands), "S6GA00374")

    # A dormant registration must stay behind a live one even when it filed
    # paperwork more recently — activity is still the first test.
    mixed = {
        "H0GA01000": {"lastFileDate": "2026-09-01"},
        "S6GA00374": {"totalRaised": 1.0, "coverageEndDate": "2026-06-30T00:00:00",
                      "lastFileDate": "2025-05-09"},
    }
    check("activity outranks a newer filing date",
          preferred_filing(sorted(mixed), mixed), "S6GA00374")

    # An absent lastFileDate must sort last, not first: the empty string inverts
    # to the empty tuple, which would otherwise beat every real date.
    undated = {
        "H4GA01039": {"totalRaised": 1.0, "coverageEndDate": "2026-06-30T00:00:00"},
        "S6GA00374": {"totalRaised": 1.0, "coverageEndDate": "2026-06-30T00:00:00",
                      "lastFileDate": "2025-05-09"},
    }
    check("a filing with no date never outranks one that has a date",
          preferred_filing(sorted(undated), undated), "S6GA00374")

    # With no dates at all the rule has to degrade to what it did before, so data
    # generated ahead of the lastFileDate field keeps its published pick.
    nodates = {k: {"totalRaised": 1.0} for k in ("H4GA01039", "S6GA00374")}
    check("no dates anywhere -> deterministic id tiebreak, as before",
          preferred_filing(sorted(nodates), nodates), "H4GA01039")

    # A later coverage end date still beats an older one before dates are consulted.
    coverage = {
        "H4GA01039": {"totalRaised": 1.0, "coverageEndDate": "2026-06-30T00:00:00",
                      "lastFileDate": "2020-01-01"},
        "S6GA00374": {"totalRaised": 1.0, "coverageEndDate": "2024-06-30T00:00:00",
                      "lastFileDate": "2026-01-01"},
    }
    check("coverage end date is still tested before the filing date",
          preferred_filing(sorted(coverage), coverage), "H4GA01039")

    if not os.path.exists(FEC_FILE):
        print(f"\nSKIP live check: {FEC_FILE} not found (run from the repo root)")
    else:
        print(f"\nPublished indexes in {FEC_FILE}:")
        data = json.load(open(FEC_FILE, encoding="utf-8"))
        C = data["candidates"]
        multi = {b: ids for b, ids in data["byBioguideIdAll"].items() if len(ids) > 1}
        for bio, ids in sorted(multi.items()):
            check(f"byBioguideId[{bio}] matches the rule",
                  data["byBioguideId"][bio], preferred_filing(ids, C))
            # The pick is only useful if it is the one carrying the cycle's filings.
            dated = [i for i in ids if C.get(i, {}).get("lastFileDate")]
            if len(dated) == len(ids):
                newest = max(dated, key=lambda i: C[i]["lastFileDate"])
                check(f"byBioguideId[{bio}] is the newest-filed of {len(ids)}",
                      data["byBioguideId"][bio], newest)
        if not multi:
            print("  (no member currently holds more than one filing)")

    print("\nget_candidate_committees():")
    committee_cases()

    print("\nsum_committee_totals():")
    summing_cases()

    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
