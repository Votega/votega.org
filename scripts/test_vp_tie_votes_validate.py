#!/usr/bin/env python3
"""Assert validate_vp_tie_votes.py gates on self-contradiction and a lost vote,
and only reports additions.

The old gate was a 20% shrink (with --scope-key metadata.congress). On an
8-vote file, losing one is -12.5% and passed. Stdlib only.

Usage:
  python scripts/test_vp_tie_votes_validate.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_vp_tie_votes as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def vote(n, congress=119, session=1, vp="Yea", date=None):
    return {"voteNumber": f"{n:05d}", "congress": congress, "session": session,
            "date": date or f"2025-0{1 + n % 9}-01", "vpVote": vp, "yeas": 50, "nays": 50,
            "title": f"Vote {n}"}


def sound(n=8, congress=119):
    votes = sorted((vote(i, congress) for i in range(1, n + 1)), key=lambda v: v["date"])
    return {"metadata": {"congress": congress, "count": len(votes)}, "votes": votes}


def t1(fn):
    d = sound()
    fn(d)
    return len(V.tier1(d))


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    check("a new Congress with no tie-breakers is NOT tier 1", V.tier1(sound(0, congress=120)), [])
    check("count mismatch", t1(lambda d: d["metadata"].update(count=99)), 1)
    check("not a tie", t1(lambda d: d["votes"][0].update(yeas=51)), 1)
    check("vpVote not Yea/Nay", t1(lambda d: d["votes"][0].update(vpVote="Present")), 1)
    check("other Congress", t1(lambda d: d["votes"][0].update(congress=118)), 1)
    check("duplicate vote", t1(lambda d: d["votes"][1].update(
        voteNumber=d["votes"][0]["voteNumber"], session=d["votes"][0]["session"])), 1)
    check("missing field", t1(lambda d: d["votes"][2].update(date=None)), 2)
    check("not in date order", t1(lambda d: d["votes"].reverse()), 1)


def loss_cases():
    print("loss (the one baseline gate)")
    old = sound()
    check("no baseline -> nothing", V.collapse(sound(), None), [])
    check("unchanged -> nothing", V.collapse(sound(), old), [])
    check("growth -> nothing", V.collapse(sound(9), old), [])
    check("ONE lost vote of 8 (-12.5%, passed the old 20% gate) -> refuse",
          len(V.collapse(sound(7), old)), 1)
    check("new Congress starts empty -> not a loss", V.collapse(sound(0, congress=120), old), [])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    old = sound(7)
    check("unchanged -> nothing", V.tier2(sound(7), old), [])
    check("new vote named", [h for h, _ in V.tier2(sound(8), old)], ["1 new tie-breaking vote(s)"])
    check("new Congress -> nothing", V.tier2(sound(1, congress=120), old), [])
    check("render with no sections says no material change",
          "No material change" in V.render("x.json", []), True)


def main():
    tier1_cases()
    loss_cases()
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
