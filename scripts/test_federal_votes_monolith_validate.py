#!/usr/bin/env python3
"""Assert validate_federal_votes_monolith.py gates on self-contradiction and lost
roll calls, and only reports a vacancy or a Congress that has just begun.

The old gate was `members >= 15`, a 20% shrink on four counters, and a
--scope-key on metadata.congress. Stdlib only.

Usage:
  python scripts/test_federal_votes_monolith_validate.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_federal_votes_monolith as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def sound(n_house=3, n_senate=2, members=("A", "B"), congress=119, stale=0):
    votes = {}
    for i in range(1, n_house + 1):
        votes[f"H2025_{i:04d}"] = {"chamber": "House", "bill": "H.R. 1" if i % 2 else None}
    for i in range(1, n_senate + 1):
        votes[f"S{congress}_1_{i:05d}"] = {"chamber": "Senate", "bill": None}
    mv = {m: [{"voteId": v, "vote": "Yea"} for v in votes] for m in members}
    for k in range(stale):
        mv[f"X{k}"] = [{"voteId": next(iter(votes)), "vote": "Yea"}]
    return {"metadata": {
        "congress": congress, "totalVotes": len(votes), "houseVotes": n_house,
        "senateVotes": n_senate,
        "billLessVotes": sum(1 for v in votes.values() if not v["bill"]),
        "memberCount": len(mv), "sittingDelegation": len(members),
        "sittingMembersWithVotes": len(members), "staleVoteRecords": stale},
        "votes": votes, "memberVotes": mv}


def t1(fn, **kw):
    d = sound(**kw)
    fn(d)
    return len(V.tier1(d))


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    check("with stale (departed) records passes", V.tier1(sound(stale=2)), [])
    check("14 members is NOT tier 1 (old floor was members>=15)",
          V.tier1(sound(members=tuple("ABCDEFGHIJKLMN"))), [])
    check("no roll calls yet is NOT tier 1 (a Congress starts at zero)",
          V.tier1(sound(n_house=0, n_senate=0, members=())), [])
    check("totalVotes mismatch", t1(lambda d: d["metadata"].update(totalVotes=99)), 1)
    check("houseVotes mismatch", t1(lambda d: d["metadata"].update(houseVotes=9)), 1)
    check("billLessVotes mismatch", t1(lambda d: d["metadata"].update(billLessVotes=0)), 1)
    check("memberCount mismatch", t1(lambda d: d["metadata"].update(memberCount=1)), 1)
    check("prefix disagrees with chamber",
          t1(lambda d: d["votes"]["H2025_0001"].update(chamber="Senate")), 3)
    check("memberVotes names an unknown roll call",
          t1(lambda d: d["memberVotes"]["A"].append({"voteId": "H2025_9999", "vote": "Yea"})), 1)
    check("a roll call recorded twice for one member",
          t1(lambda d: d["memberVotes"]["A"].append(dict(d["memberVotes"]["A"][0]))), 1)
    check("sitting + stale != memberCount",
          t1(lambda d: d["metadata"].update(staleVoteRecords=3)), 1)


def loss_cases():
    print("loss (the one baseline gate)")
    old = sound()
    check("no baseline -> nothing", V.collapse(sound(), None), [])
    check("unchanged -> nothing", V.collapse(sound(), old), [])
    check("growth -> nothing", V.collapse(sound(n_house=5), old), [])
    check("one HEAD roll call gone -> refuse (a set difference, not a percentage)",
          len(V.collapse(sound(n_house=2), old)), 1)
    check("Senate index failed (all Senate rolls gone) -> refuse",
          len(V.collapse(sound(n_senate=0), old)), 1)
    reset = sound(n_house=0, n_senate=0, congress=120, members=())
    check("a new Congress starts empty -> not a loss", V.collapse(reset, old), [])
    lost_member = sound(members=("A",))
    lost_member["metadata"]["sittingMembersMissingVotes"] = ["B"]
    check("sitting member with HEAD votes now has none -> refuse",
          len(V.collapse(lost_member, old)), 1)
    new_member = sound(members=("A",))
    new_member["metadata"]["sittingMembersMissingVotes"] = ["Z"]
    check("sitting member who never had votes (newly seated) -> not a loss",
          V.collapse(new_member, old), [])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    check("healthy -> nothing", V.tier2(sound(), sound()), [])
    vac = sound()
    vac["metadata"]["sittingMembersMissingVotes"] = ["Z000001"]
    check("sitting member with no votes named", [h for h, _ in V.tier2(vac, sound())],
          ["Sitting delegation members with no votes"])
    empty = sound(n_house=0, n_senate=0, members=())
    check("no roll calls yet reported", [h for h, _ in V.tier2(empty, None)], ["No roll calls yet"])
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
