#!/usr/bin/env python3
"""Assert validate_curated_ga_bills.py gates on self-contradiction and only reports change.

A check in the wrong tier is the bug. Each case pins which side of the line a
condition falls on.

Usage:
  python scripts/test_curated_ga_bills_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_curated_ga_bills as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def chamber_vote(n=4):
    members = {f"ocd-person/{i}": ("yes" if i % 2 else "no") for i in range(n)}
    return {"rollNumber": 1, "memberVotes": members,
            "partyTally": {"Democratic": {"yea": n // 2, "nay": 0, "other": 0},
                           "Republican": {"yea": 0, "nay": n - n // 2, "other": 0}}}


def bill(ident, session="2025_26"):
    return {"legislationId": 1, "session": session, "identifier": ident, "title": ident,
            "billUrl": "https://x", "votes": {"house": chamber_vote(), "senate": chamber_vote()}}


def sound():
    bills = [bill("HB 1"), bill("SB 2"), bill("HB 3")]
    return {"metadata": {"count": 3, "fromLocalRecord": 2, "fromSoapFetch": 1,
                         "sittingLegislators": 235, "legislatorsWithVotes": 235,
                         "voterResolution": {"unresolved": 0}, "unresolvedVoterRows": 0},
            "bills": bills}


def heads(sections):
    return [h for h, _ in sections]


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound()
    d["metadata"]["count"] = 9
    check("a count that does not match the bills is tier 1",
          any("metadata.count" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["fromLocalRecord"] = 3
    d["metadata"]["fromSoapFetch"] = 3
    check("a source breakdown larger than the whole is tier 1",
          any("exceed" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["legislatorsWithVotes"] = 300
    check("more legislators with votes than are sitting is tier 1",
          any("exceeds sittingLegislators" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["unresolvedVoterRows"] = 5
    check("two unresolved counters disagreeing is tier 1",
          any("unresolvedVoterRows" in e for e in V.tier1(d)), True)

    # The old inline assert, kept: arithmetic, not politics.
    d = sound()
    d["bills"][0]["votes"]["house"]["partyTally"]["Democratic"]["yea"] = 50
    check("a party tally exceeding its roster is tier 1",
          any("double-counting" in e for e in V.tier1(d)), True)

    d = sound()
    del d["bills"][0]["votes"]["house"]["partyTally"]["Democratic"]["nay"]
    check("a tally row without yea/nay/other is tier 1",
          any("partyTally row" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"][0]["votes"]["house"].pop("memberVotes")
    check("a chamber vote without memberVotes is tier 1",
          any("missing or not a map" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"][1]["votes"]["joint"] = chamber_vote()
    check("an unknown chamber key is tier 1",
          any("unknown chamber" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"][0].pop("identifier")
    check("a bill missing identifier is tier 1",
          any("missing required" in e for e in V.tier1(d)), True)

    d = sound()
    d["bills"].append(copy.deepcopy(d["bills"][0]))
    d["metadata"]["count"] = 4
    check("the same bill twice is tier 1",
          any("more than once" in e for e in V.tier1(d)), True)

    check("a file with no bills list is tier 1", V.tier1({"metadata": {}}) != [], True)

    # Everything below is the world, or the editor, moving. Must NOT gate.

    # Old: --min bills=1. An emptied curated list is an editorial choice, and
    # the producer already exits 1 when every listed bill failed to source.
    d = sound()
    d["bills"] = []
    d["metadata"].update(count=0, fromLocalRecord=0, fromSoapFetch=0)
    check("an emptied curated list is NOT tier 1 (the old --min bills=1 false positive)",
          V.tier1(d), [])

    # Old: the 20% shrink on bills/coverage. Nine bills means one edit is >11%;
    # a vacancy or a rollover moves legislatorsWithVotes legitimately.
    d = sound()
    d["metadata"].update(sittingLegislators=120, legislatorsWithVotes=30)
    check("coverage collapsing (rollover, vacancies) is NOT tier 1 "
          "(the old coverage-delta gate's false positive)", V.tier1(d), [])

    # Old: the ghosts/unresolved block printed a warning. The producer drops
    # these rows by design and counts them in metadata.
    d = sound()
    d["metadata"]["voterResolution"] = {"unresolved": 78}
    d["metadata"]["unresolvedVoterRows"] = 78
    check("unresolved voter rows are NOT tier 1 (a designed-for degraded state)",
          V.tier1(d), [])

    # The producer retains a prior record when a bill cannot be re-sourced.
    d = sound()
    d["metadata"].update(fromLocalRecord=1, fromSoapFetch=1)
    check("retained prior records (local+soap < count) are NOT tier 1", V.tier1(d), [])

    d = sound()
    d["bills"][0]["votes"] = {"house": chamber_vote()}
    check("a bill with only one chamber's vote is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()
    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline, clean file -> nothing to report", V.tier2(sound(), None), [])

    new = sound()
    new["metadata"].update(unresolvedVoterRows=78)
    check("unresolved voter rows are reported",
          "Roll-call rows that could not be attributed" in heads(V.tier2(new, old)), True)

    new = sound()
    new["metadata"]["legislatorsWithVotes"] = 230
    h = heads(V.tier2(new, old))
    check("sitting legislators with no key vote are reported",
          "Sitting legislators with no key vote" in h, True)
    check("a coverage change against last run is reported", "Key-vote coverage changed" in h, True)

    new = sound()
    new["metadata"].update(fromLocalRecord=1, fromSoapFetch=1)
    check("retained prior records are reported",
          "Records kept from the previous run" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"].append(bill("HB 9"))
    new["metadata"].update(count=4, fromLocalRecord=3)
    check("a bill added to the curated list is reported",
          "Curated bills added or removed" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"] = new["bills"][1:]
    new["metadata"].update(count=2, fromLocalRecord=1)
    check("a bill removed from the curated list is reported",
          "Curated bills added or removed" in heads(V.tier2(new, old)), True)

    new = sound()
    del new["bills"][0]["votes"]["senate"]
    check("a bill losing a chamber vote is reported",
          "A bill lost a chamber vote" in heads(V.tier2(new, old)), True)

    new = sound()
    new["bills"] = []
    new["metadata"].update(count=0, fromLocalRecord=0, fromSoapFetch=0)
    check("an empty list is reported",
          "The curated list is empty" in heads(V.tier2(new, old)), True)

    check("an empty report says so",
          "No material change this run" in V.render("c.json", []), True)
    check("the report states the data was committed anyway",
          "none of them blocked the update" in V.render("c.json", V.tier2(new, old)), True)


def main():
    print("tier 1 — gate on self-contradiction:")
    tier1_cases()
    print("\ntier 2 — report change, never gate:")
    tier2_cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
