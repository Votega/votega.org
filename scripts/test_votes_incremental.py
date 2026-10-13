#!/usr/bin/env python3
"""Invariants the incremental GA votes fetch depends on (lib/votes_schema.py).

generate_ga_votes_soap.py fetches only ACTIVE_SESSION and carries the closed sessions
forward from the existing ga-member-votes.json. That is only safe if the compact index
is append-only and the per-member merge keeps every member — including the ones who are
absent from the active session entirely. These tests pin both.

Run: python scripts/test_votes_incremental.py        (no network, no writes)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.votes_schema import (encode_member_votes, member_votes_map, merge_member_votes,
                              preserved_layer)

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "assets", "data", "ga-member-votes.json")

failures = []


def check(label, cond, detail=""):
    if cond:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        failures.append(label)


def fixture():
    """Two sessions, four members: one in both, one closed-only (the departed member
    whose history a naive merge drops), one active-only (a new arrival), one with a
    single closed vote. Index order is closed-first, mirroring a real file."""
    votes = {
        "1-10": {"session": "closed_a", "bill": "HB 1"},
        "1-11": {"session": "closed_a", "bill": "HB 2"},
        "2-12": {"session": "closed_a", "bill": "HB 3"},
        "9-90": {"session": "active_b", "bill": "HB 9"},
    }
    legacy = {
        "p/both":   [{"voteId": "1-10", "vote": "Yea"}, {"voteId": "9-90", "vote": "Nay"}],
        "p/left":   [{"voteId": "1-11", "vote": "Nay"}, {"voteId": "2-12", "vote": "Yea"}],
        "p/arrived": [{"voteId": "9-90", "vote": "Yea"}],
        "p/one":    [{"voteId": "2-12", "vote": "Excused"}],
    }
    compact, ids = encode_member_votes(legacy, list(votes.keys()))
    return {"voteIds": ids, "votes": votes, "memberVotes": compact}


def test_fixture_layer_and_merge():
    print("fixture: preserved layer + merge")
    data = fixture()
    pv, pmv = preserved_layer(data, ["closed_a"])

    check("preserved votes are the closed session only", list(pv) == ["1-10", "1-11", "2-12"])
    check("preserved keeps file key order", list(pv) == [k for k in data["voteIds"] if k in pv])
    check("active-only member excluded from preserved layer", "p/arrived" not in pmv)
    check("closed-only member present in preserved layer", "p/left" in pmv)
    check("both-sessions member keeps only closed rows in the layer",
          [e["voteId"] for e in pmv["p/both"]] == ["1-10"])

    # the active session, as a fresh fetch would hand it over
    fetched_votes = {"9-90": {"session": "active_b", "bill": "HB 9"}}
    fetched_mv = {
        "p/both":    [{"voteId": "9-90", "vote": "Nay"}],
        "p/arrived": [{"voteId": "9-90", "vote": "Yea"}],
    }
    merged_votes = {**pv, **fetched_votes}
    merged_mv = merge_member_votes(pmv, fetched_mv)

    check("THE HAZARD: closed-only member survives the merge", "p/left" in merged_mv)
    check("closed-only member keeps every row",
          [e["voteId"] for e in merged_mv["p/left"]] == ["1-11", "2-12"])
    check("member set is the union, not the fetch", set(merged_mv) == set(
        ["p/both", "p/left", "p/arrived", "p/one"]))
    check("both-sessions member gets closed + active",
          [e["voteId"] for e in merged_mv["p/both"]] == ["1-10", "9-90"])

    compact, ids = encode_member_votes(merged_mv, list(merged_votes.keys()))
    check("merged index equals the original", ids == data["voteIds"])
    check("merged memberVotes equals the original",
          json.dumps(compact, sort_keys=True) == json.dumps(data["memberVotes"], sort_keys=True))

    # preserved indices must not move
    pc, pids = encode_member_votes(pmv, list(pv.keys()))
    check("preserved indices keep their original positions",
          all(pids[i] == data["voteIds"][i] for i in range(len(pids))))


def test_no_duplicate_on_refetch():
    print("re-fetching the active session corrects, never duplicates")
    data = fixture()
    pv, pmv = preserved_layer(data, ["closed_a"])
    # same vote fetched twice, second time with a corrected option
    merged = merge_member_votes(pmv, {"p/both": [{"voteId": "9-90", "vote": "Nay"}]})
    merged = merge_member_votes(merged, {"p/both": [{"voteId": "9-90", "vote": "Yea"}]})
    ids = [e["voteId"] for e in merged["p/both"]]
    check("no duplicate row for the re-fetched vote", ids == ["1-10", "9-90"], ids)
    check("the later fetch wins",
          [e["vote"] for e in merged["p/both"] if e["voteId"] == "9-90"] == ["Yea"])


def test_legacy_schema_refused():
    print("a legacy-schema file is refused rather than merged")
    legacy_file = {"votes": {"a": {"session": "x"}},
                   "memberVotes": {"p/1": [{"voteId": "a", "vote": "Yea"}]}}
    try:
        preserved_layer(legacy_file, ["x"])
        check("raises ValueError", False, "(no raise)")
    except ValueError:
        check("raises ValueError", True)


def test_against_live_file():
    print("live ga-member-votes.json")
    if not os.path.exists(DATA):
        print("  skip (file absent)")
        return
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    active = (data.get("metadata") or {}).get("activeSession")
    closed = sorted({(r or {}).get("session") for r in data["votes"].values()} - {active, None})
    if not closed:
        print("  skip (single-session file — nothing to preserve)")
        return

    # 1. the codec is lossless on the real file
    compact, ids = encode_member_votes(member_votes_map(data), list(data["votes"].keys()))
    check("round-trip reproduces voteIds", ids == data["voteIds"])
    check("round-trip reproduces memberVotes byte-for-byte",
          json.dumps(compact, separators=(",", ":"))
          == json.dumps(data["memberVotes"], separators=(",", ":")))

    # 2. closed sessions occupy the LEADING indices — what makes preservation an append
    seq = [data["votes"][v]["session"] for v in data["voteIds"]]
    boundary = seq.index(active) if active in seq else len(seq)
    check("closed sessions occupy the leading indices",
          set(seq[:boundary]) <= set(closed) and active not in seq[:boundary],
          "(boundary at %d)" % boundary)

    # 3. partitioning leaves preserved rows untouched
    pv, pmv = preserved_layer(data, closed)
    pc, pids = encode_member_votes(pmv, list(pv.keys()))
    check("preserved voteIds keep their index positions",
          all(pids[i] == data["voteIds"][i] for i in range(len(pids))))
    stable = sum(1 for p in pc
                 if pc[p] == {k: v for k, v in data["memberVotes"][p].items()
                              if int(k) < len(pids)})
    check("every preserved member row is byte-stable",
          stable == len(pc), "(%d/%d)" % (stable, len(pc)))

    # 4. the hazard, on real data: members with no active-session votes
    closed_only = [p for p, row in data["memberVotes"].items()
                   if all(int(i) < boundary for i in row)]
    merged = merge_member_votes(pmv, {})
    check("members with only closed-session votes survive an empty active fetch",
          all(p in merged for p in closed_only),
          "(%d such members)" % len(closed_only))
    print("       (%d of %d members have no active-session votes)"
          % (len(closed_only), len(data["memberVotes"])))


if __name__ == "__main__":
    for t in (test_fixture_layer_and_merge, test_no_duplicate_on_refetch,
              test_legacy_schema_refused, test_against_live_file):
        t()
    print()
    if failures:
        print("FAILED: %d" % len(failures))
        for f in failures:
            print("  - %s" % f)
        sys.exit(1)
    print("All votes-incremental invariants hold.")
