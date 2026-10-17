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
    """Only an authorized committee is a source of totals; the rest are pointers.

    Two earlier rules put other people's money on candidate pages — taking the
    best-ranked committee of any designation, then allowing one that had ever
    been designated P. The second measured committee age, not ownership: it
    accepted seven PACs and refused three committees that really were the
    candidate's own. These cases pin the rule that replaced both.
    """
    real_get = gen.fec_get

    def stub(results):
        gen.fec_get = lambda path, params=None, retries=3: {"results": list(results)}

    try:
        # A principal committee is the ordinary case and must not change.
        stub([
            {"committee_id": "C00000002", "name": "SOME JOINT FUNDRAISER",
             "designation": "J", "last_file_date": "2026-10-15"},
            {"committee_id": "C00000001", "name": "CANDIDATE FOR CONGRESS",
             "designation": "P", "last_file_date": "2026-01-01"},
        ])
        got = gen.get_candidate_committee("H0GA01000")
        check("principal beats every other designation", got["id"], "C00000001")
        check("a usable committee is returned as a source, not a pointer",
              "related" in got, False)

        stub([
            {"committee_id": "C00000003", "designation": "U", "last_file_date": "2026-10-15"},
            {"committee_id": "C00000002", "designation": "A", "last_file_date": "2026-02-01"},
        ])
        check("authorized beats unauthorized",
              gen.get_candidate_committee("H0GA01000")["id"], "C00000002")

        stub([
            {"committee_id": "C00000001", "designation": "A", "last_file_date": "2025-01-01"},
            {"committee_id": "C00000002", "designation": "A", "last_file_date": "2026-01-01"},
        ])
        check("inside a tier the most recent filer wins",
              gen.get_candidate_committee("H0GA01000")["id"], "C00000002")

        # Dooley: a leadership PAC is never a source. $4.7M of LEADERSHIP MATTERS
        # PAC reached a live Senate candidate's page when it was.
        stub([{"committee_id": "C00914531", "name": "LEADERSHIP MATTERS PAC",
               "designation": "U", "last_file_date": "2026-10-15"}])
        got = gen.get_candidate_committee("S6GA00408")
        check("an unauthorized committee is a pointer, never a source",
              "related" in got, True)
        check("the pointer still names the committee",
              got["related"]["id"], "C00914531")

        stub([{"committee_id": "C00708289", "name": "PUTTING PEOPLE BEFORE POLITICIANS INC",
               "designation": "D", "last_file_date": "2026-10-15"}])
        check("a leadership PAC is a pointer too",
              "related" in gen.get_candidate_committee("H0GA06192"), True)

        # Blair: his own campaign committee, re-designated. Still not a source —
        # it files as a PAC now, which is why FEC publishes no totals for him.
        stub([{"committee_id": "C00901157",
               "name": "BUILDING LASTING ALLIANCES FOR IMPACT AND RESULTS PAC",
               "designation": "U", "last_file_date": "2026-10-15"}])
        got = gen.get_candidate_committee("H6GA13062")
        check("a re-designated campaign committee is a pointer, not a source",
              "related" in got, True)

        # The fall-through that made the old rule worse: refusing HOLD THE LINE
        # promoted MISSION DEMOCRACY PAC behind it. Ranking picks one; a
        # non-authorized winner ends the search instead of walking the list.
        stub([{"committee_id": "C00868976", "name": "HOLD THE LINE",
               "designation": "U", "last_file_date": "2026-10-15"},
              {"committee_id": "C00768101", "name": "MISSION DEMOCRACY PAC",
               "designation": "D", "last_file_date": "2026-09-01"}])
        got = gen.get_candidate_committee("H2GA14044")
        check("refusing one PAC does not promote the next one",
              "related" in got, True)
        check("the pointer is the best-ranked, not whichever survived a walk",
              got["related"]["id"], "C00868976")

        stub([])
        check("no linked committee -> None",
              gen.get_candidate_committee("H0GA01000"), None)
    finally:
        gen.fec_get = real_get


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

    print("\nget_candidate_committee():")
    committee_cases()

    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
