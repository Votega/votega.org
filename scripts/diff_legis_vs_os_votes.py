#!/usr/bin/env python3
"""Diff the legis.ga.gov vote file against the Open States file — the cutover
go/no-go (design §7).

Both files share the compact v2 schema (lib/votes_schema.py), so this decodes
each with `member_votes_map`, then compares roll calls.

Why tally-aware pairing
-----------------------
A bill can have SEVERAL roll calls on the same day (passage, reconsider, a second
chamber), so pairing legis<->OS by `(bill, date)` ALONE mis-pairs them and
invents disagreement (the 2026-10-03 ad-hoc diff's inflated 7%). Instead, within
each `(bill, date)` group we pair the legis and OS roll calls by BEST per-member
agreement (the two roll calls whose members voted most alike are the same vote),
then compare only matched pairs. Leftover roll calls on either side are reported
as source-only, not as disagreements.

Usage:
  python diff_legis_vs_os_votes.py [--session 2025_26]
      [--legis assets/data/ga-member-votes.legis.json]
      [--os assets/data/ga-member-votes.json]
      [--examples 20]
"""

import argparse
import json
from collections import defaultdict

from lib.ga_passage import normalize_bill
from lib.votes_schema import member_votes_map

LEGIS_FILE = "assets/data/ga-member-votes.legis.json"
OS_FILE = "assets/data/ga-member-votes.json"

#: Only Yea/Nay are comparable across sources (OS lumps the rest as "Other").
_AXIS = {"Yea": "Y", "Nay": "N"}


def _axis(vote):
    return _AXIS.get(vote, "O")


def by_vote_members(data):
    """voteId -> {ocdPersonId: 'Y'|'N'|'O'} from either schema."""
    out = defaultdict(dict)
    for ocd, entries in member_votes_map(data).items():
        for e in entries:
            out[str(e["voteId"])][ocd] = _axis(e["vote"])
    return out


def index_by_key(data, session=None):
    """key (normalize_bill, 'YYYY-MM-DD') -> [voteId, ...] for a source, limited to
    `session` when given. Also returns voteId -> meta."""
    groups = defaultdict(list)
    meta = {}
    for vid, m in (data.get("votes") or {}).items():
        if session is not None and m.get("session") != session:
            continue
        key = (normalize_bill(m.get("bill")), (m.get("date") or "")[:10])
        groups[key].append(str(vid))
        meta[str(vid)] = m
    return groups, meta


def _agreement(a, b):
    """Count of members present in BOTH roll calls who cast the same Yea/Nay axis
    (the pairing score — higher means more likely the same roll call)."""
    shared = a.keys() & b.keys()
    return sum(1 for ocd in shared if a[ocd] == b[ocd])


def pair_rollcalls(legis_vids, os_vids, members):
    """Greedy best-agreement pairing within one (bill, date) group. Returns
    (pairs, legis_only, os_only) where pairs is [(legis_vid, os_vid)]."""
    cand = sorted(
        ((_agreement(members[l], members.get(o, {})), l, o)
         for l in legis_vids for o in os_vids),
        key=lambda t: -t[0])
    pairs, used_l, used_o = [], set(), set()
    for _score, l, o in cand:
        if l in used_l or o in used_o:
            continue
        used_l.add(l)
        used_o.add(o)
        pairs.append((l, o))
    legis_only = [l for l in legis_vids if l not in used_l]
    os_only = [o for o in os_vids if o not in used_o]
    return pairs, legis_only, os_only


def diff(legis, os_data, session, examples=20):
    lg_members = by_vote_members(legis)
    os_members = by_vote_members(os_data)
    members = {**os_members, **lg_members}  # voteId -> member map (ids are disjoint)

    lg_groups, lg_meta = index_by_key(legis, session)
    os_groups, os_meta = index_by_key(os_data, session)

    all_pairs = []
    legis_only, os_only = [], []
    for key in set(lg_groups) | set(os_groups):
        lv, ov = lg_groups.get(key, []), os_groups.get(key, [])
        if lv and ov:
            pairs, lo, oo = pair_rollcalls(lv, ov, members)
            all_pairs += [(key, l, o) for l, o in pairs]
            legis_only += [(key, l) for l in lo]
            os_only += [(key, o) for o in oo]
        elif lv:
            legis_only += [(key, l) for l in lv]
        else:
            os_only += [(key, o) for o in ov]

    tally_agree = tally_differ = 0
    tally_examples = []
    mv_agree = mv_differ = 0
    mv_examples = []
    for key, l, o in all_pairs:
        lm, om = lg_meta[l], os_meta[o]
        # tally agreement on Yea/Nay
        if (lm.get("yea"), lm.get("nay")) == (om.get("yea"), om.get("nay")):
            tally_agree += 1
        else:
            tally_differ += 1
            if len(tally_examples) < examples:
                tally_examples.append(
                    "%s %s: legis %s/%s vs OS %s/%s"
                    % (lm.get("bill"), key[1], lm.get("yea"), lm.get("nay"),
                       om.get("yea"), om.get("nay")))
        # per-member agreement among shared members
        a, b = members[l], members.get(o, {})
        for ocd in a.keys() & b.keys():
            if a[ocd] == b[ocd]:
                mv_agree += 1
            else:
                mv_differ += 1
                if len(mv_examples) < examples:
                    mv_examples.append("%s %s member %s: legis %s vs OS %s"
                                       % (lm.get("bill"), key[1], ocd[-12:],
                                          a[ocd], b[ocd]))

    print("=== LEGIS vs OS DIFF (%s, tally-aware pairing) ===" % (session or "all"))
    print("legis passage roll calls: %d | OS roll calls: %d"
          % (len(lg_meta), len(os_meta)))
    print("paired roll calls:        %d" % len(all_pairs))
    print("  tally agree: %d   tally differ: %d  (%.1f%% agree)"
          % (tally_agree, tally_differ,
             100.0 * tally_agree / max(1, tally_agree + tally_differ)))
    print("legis-only roll calls:    %d  (in legis, no OS pair)" % len(legis_only))
    print("OS-only roll calls:       %d  (in OS, no legis pair)" % len(os_only))
    print("\nper-member Yea/Nay comparisons on paired roll calls:")
    print("  agree: %d   differ: %d  (%.3f%% agree)"
          % (mv_agree, mv_differ, 100.0 * mv_agree / max(1, mv_agree + mv_differ)))
    if tally_examples:
        print("\nsample tally differences:")
        for e in tally_examples:
            print("  " + e)
    if mv_examples:
        print("\nsample per-member disagreements:")
        for e in mv_examples:
            print("  " + e)
    if os_only:
        print("\nsample OS-only roll calls (legis missing these — OS gaps or match misses):")
        for key, o in os_only[:examples]:
            m = os_meta[o]
            print("  %s %s  %s/%s  %s"
                  % (m.get("bill"), key[1], m.get("yea"), m.get("nay"), m.get("result")))
    if legis_only:
        print("\nsample legis-only roll calls (legis kept, OS didn't):")
        for key, l in legis_only[:examples]:
            m = lg_meta[l]
            print("  %s %s  %s/%s  %s"
                  % (m.get("bill"), key[1], m.get("yea"), m.get("nay"),
                     m.get("motionText")))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Diff legis vs Open States vote files.")
    p.add_argument("--session", default="2025_26",
                   help="session tag to compare (default: %(default)s)")
    p.add_argument("--legis", default=LEGIS_FILE)
    p.add_argument("--os", dest="os_file", default=OS_FILE)
    p.add_argument("--examples", type=int, default=20)
    return p.parse_args(argv)


def main():
    args = parse_args()
    with open(args.legis, encoding="utf-8") as f:
        legis = json.load(f)
    with open(args.os_file, encoding="utf-8") as f:
        os_data = json.load(f)
    diff(legis, os_data, args.session, examples=args.examples)


if __name__ == "__main__":
    main()
