#!/usr/bin/env python3
"""Assert validate_fec_data.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships broken data, and a
legitimate change that gates throws away a good week of it and leaves the site
stale. Each case below pins which side of the line a condition falls on.

Usage:
  python scripts/test_fec_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_fec_data as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def sound():
    """A small, self-consistent file in the shape generate_fec_data.py emits."""
    candidates = {
        "H4GA01039": {"candidateId": "H4GA01039", "name": "CARTER, EARL LEROY", "office": "H",
                      "committeeId": "C00543967", "committeeDesignation": "P",
                      "lastFileDate": "2024-11-18", "totalRaised": 7300242.83,
                      "coverageEndDate": "2026-06-30T00:00:00"},
        "S6GA00374": {"candidateId": "S6GA00374", "name": "CARTER, EARL LEROY", "office": "S",
                      "committeeId": "C00543967", "committeeDesignation": "P",
                      "lastFileDate": "2025-05-09", "totalRaised": 7300242.83,
                      "coverageEndDate": "2026-06-30T00:00:00"},
        "H6GA13062": {"candidateId": "H6GA13062", "name": "BLAIR, EVERTON", "office": "H",
                      "committeeId": "C00901157", "committeeDesignation": "U",
                      "lastFileDate": "2026-05-14", "totalRaised": 943154.08},
    }
    return {
        "metadata": {"totalCandidates": len(candidates), "cycle": 2026},
        "candidates": candidates,
        "byBioguideId": {"C001103": "S6GA00374", "B001328": "H6GA13062"},
        "byBioguideIdAll": {"C001103": ["H4GA01039", "S6GA00374"], "B001328": ["H6GA13062"]},
        "byNormalizedName": {"earl carter": "S6GA00374", "everton blair": "H6GA13062"},
        "byNormalizedNameAll": {"earl carter": ["H4GA01039", "S6GA00374"],
                                "everton blair": ["H6GA13062"]},
        "byDistrict": {"H01": ["H4GA01039"], "S": ["S6GA00374"], "H13": ["H6GA13062"]},
    }


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    # The regression this whole exercise is about: the published index saying one
    # thing and the rule that builds it saying another.
    d = sound()
    d["byBioguideId"]["C001103"] = "H4GA01039"
    errs = V.tier1(d)
    check("a published index disagreeing with preferred_filing() is tier 1",
          any("disagrees with the rule" in e for e in errs), True)

    d = sound()
    d["metadata"]["totalCandidates"] = 99
    check("a count that does not match what it counts is tier 1",
          any("totalCandidates" in e for e in V.tier1(d)), True)

    d = sound()
    d["byBioguideId"]["C001103"] = "H9GA99999"
    check("an index pointing outside candidates is tier 1",
          any("not in candidates" in e for e in V.tier1(d)), True)

    d = sound()
    d["candidates"]["H6GA13062"].pop("committeeId")
    check("totals with no committee behind them is tier 1",
          any("no committeeId" in e for e in V.tier1(d)), True)

    d = sound()
    d["byBioguideIdAll"].pop("B001328")
    check("the single and plural indexes covering different keys is tier 1",
          any("cover different keys" in e for e in V.tier1(d)), True)

    d = sound()
    d["candidates"] = {}
    check("an empty file is tier 1", V.tier1(d) != [], True)

    # Everything below is the world moving, and must NOT gate. Each is a real
    # thing the FEC can report, and the one that matters most is Blair's money
    # going away: that is the exact shape of the bug fixed in October 2026 AND
    # of his PAC winding down, so gating on it would block the truth half the
    # time. tier1() must stay silent on all of them.
    d = sound()
    d["candidates"]["H6GA13062"]["totalRaised"] = None
    d["candidates"]["H6GA13062"].pop("committeeId")
    d["candidates"]["H6GA13062"].pop("committeeDesignation")
    check("a member's money disappearing is NOT tier 1", V.tier1(d), [])

    d = sound()
    for cid in ("H4GA01039", "S6GA00374"):
        d["candidates"][cid]["totalRaised"] = 50.0
    check("totals collapsing to near nothing is NOT tier 1", V.tier1(d), [])

    d = sound()
    d["byBioguideId"].pop("B001328")
    d["byBioguideIdAll"].pop("B001328")
    check("losing an incumbent mapping (a vacancy) is NOT tier 1", V.tier1(d), [])

    # The old heredoc's floor was len(by_bio) < 12. A delegation with two mapped
    # incumbents is unusual, not self-contradictory.
    check("a small delegation is NOT tier 1 (the old floor's false positive)",
          V.tier1(sound()), [])


def tier2_cases():
    old = sound()

    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline -> nothing to report", V.tier2(sound(), None), [])

    new = copy.deepcopy(old)
    new["byBioguideId"]["C001103"] = "H4GA01039"
    heads = [h for h, _ in V.tier2(new, old)]
    check("a preferred-filing flip is reported", "Preferred filing changed" in heads, True)

    new = copy.deepcopy(old)
    new["candidates"]["H6GA13062"]["totalRaised"] = None
    heads = [h for h, _ in V.tier2(new, old)]
    check("money vanishing is reported",
          any("vanished" in h for h in heads), True)

    new = copy.deepcopy(old)
    new["candidates"]["H6GA13062"]["committeeId"] = "C00111111"
    new["candidates"]["H6GA13062"]["committeeDesignation"] = "P"
    heads = [h for h, _ in V.tier2(new, old)]
    check("a committee re-designation is reported", "Filing committee changed" in heads, True)

    # A quarter's fundraising should not fill the report with noise.
    new = copy.deepcopy(old)
    new["candidates"]["S6GA00374"]["totalRaised"] = old["candidates"]["S6GA00374"]["totalRaised"] * 1.1
    heads = [h for h, _ in V.tier2(new, old)]
    check("a 10% move is below the reporting threshold",
          any("moved" in h for h in heads), False)

    new = copy.deepcopy(old)
    new["candidates"]["S6GA00374"]["totalRaised"] = old["candidates"]["S6GA00374"]["totalRaised"] * 2
    heads = [h for h, _ in V.tier2(new, old)]
    check("a doubling is reported", any("moved" in h for h in heads), True)

    new = copy.deepcopy(old)
    new["candidates"]["H9GA99001"] = {"name": "NEWCOMER, A", "office": "H"}
    new["metadata"]["totalCandidates"] = len(new["candidates"])
    heads = [h for h, _ in V.tier2(new, old)]
    check("roster churn is reported", "Candidates added or removed" in heads, True)

    # A field that did not exist last week is not a change. Introducing
    # committeeDesignation made 209 of the first report's 226 committee lines
    # read `C00x [?] -> C00x [P]`, burying the 17 real ones.
    new = copy.deepcopy(old)
    for cid in new["candidates"]:
        new["candidates"][cid].pop("committeeDesignation", None)
    heads = [h for h, _ in V.tier2(old, new)]   # old is "new", new is "baseline"
    check("a newly populated designation on an unchanged committee is not a change",
          "Filing committee changed" in heads, False)

    # But a genuine re-designation, both sides present, still reports.
    new = copy.deepcopy(old)
    new["candidates"]["H6GA13062"]["committeeDesignation"] = "P"
    heads = [h for h, _ in V.tier2(new, old)]
    check("a real re-designation still reports", "Filing committee changed" in heads, True)

    # And a committee swap reports even when the designation is absent on one side.
    new = copy.deepcopy(old)
    new["candidates"]["H6GA13062"]["committeeId"] = "C00222222"
    new["candidates"]["H6GA13062"].pop("committeeDesignation")
    heads = [h for h, _ in V.tier2(new, old)]
    check("a committee swap reports whatever the designations are",
          "Filing committee changed" in heads, True)

    # The report is what a human reads; it must say the data shipped.
    body = V.render("ga-fec-data.json", V.tier2(new, old))
    check("the report states the data was committed anyway",
          "none of them blocked the update" in body, True)
    check("an empty report says so", "No material change this run" in
          V.render("ga-fec-data.json", []), True)


def collapse_cases():
    """The one baseline-reading gate: a shrink no week of politics can explain.

    The pair that matters is the last two. Within a cycle, a 99% drop is a
    half-failed fetch and must not commit. Across a cycle boundary the same
    99% drop is the FEC's list starting over, and gating on it would recreate
    the hand-pinned floor this validator replaced — the 2028 rollover would
    fail every run until someone edited the code.
    """
    old = sound()

    check("no baseline (first run) cannot collapse",
          V.collapse(sound(), None), [])

    check("an unchanged file does not collapse",
          V.collapse(sound(), old), [])

    grown = sound()
    grown["candidates"]["H8GA07000"] = {"candidateId": "H8GA07000", "name": "NEW, ONE",
                                        "office": "H", "committeeId": "C00999999",
                                        "totalRaised": 1000.0}
    check("growth does not collapse", V.collapse(grown, old), [])

    # One of three candidates leaving is a third of the file — real roster churn,
    # and tier 2's business.
    churned = sound()
    del churned["candidates"]["H6GA13062"]
    check("losing a third of the roster is reported, not gated",
          V.collapse(churned, old), [])

    gutted = sound()
    gutted["candidates"] = {"H4GA01039": old["candidates"]["H4GA01039"]}
    errs = V.collapse(gutted, old)
    # Two errors, not one: the candidates that went also carried the totals, so
    # both counts fall through the floor. Reporting both is the point — the pair
    # tells a reader the whole file thinned rather than the money alone.
    check("losing two thirds of the roster gates", len(errs), 2)
    check("the collapse error names the drop",
          bool(errs) and "3 -> 1" in errs[0] and "67% drop" in errs[0], True)
    check("the second error covers the totals that went with them",
          len(errs) > 1 and errs[1].startswith("candidates carrying totals"), True)

    # Totals vanishing wholesale while the roster survives is the exact shape of
    # a fetch that got the candidate list but lost the committee calls to 429s.
    no_money = sound()
    for c in no_money["candidates"].values():
        c["totalRaised"] = None
    errs = V.collapse(no_money, old)
    check("every total vanishing while the roster survives gates", len(errs), 1)
    check("that error is about totals, not the roster",
          bool(errs) and errs[0].startswith("candidates carrying totals"), True)

    rolled = sound()
    rolled["metadata"] = {**rolled["metadata"], "cycle": 2028}
    rolled["candidates"] = {"H4GA01039": old["candidates"]["H4GA01039"]}
    check("the same drop across a cycle rollover does not gate",
          V.collapse(rolled, old), [])


def main():
    print("tier 1 — gate on self-contradiction:")
    tier1_cases()
    print("\ntier 2 — report change, never gate:")
    tier2_cases()
    print("\ncollapse — gate only on a shrink the world cannot produce:")
    collapse_cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
