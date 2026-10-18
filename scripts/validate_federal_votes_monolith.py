#!/usr/bin/env python3
"""Validate federal-member-votes.json: gate on self-consistency and lost rolls.

This replaces `validate_data_update.py --metric rollcalls/members/house/senate
--min members=15 --scope-key metadata.congress` in update-federal-votes.yml.
(validate_federal_votes.py, which runs after it, checks the SHAPE of the roll
calls and the slice alignment; this checks the monolith's own totals and what
the committed file already held.)

`members >= 15` is the world's number. Georgia's delegation is 16 seats; a
vacancy leaves 15, two leave 14, and a new Congress starts every member at zero
votes -- each a legitimate file that the floor would reject. The 20% shrink gate
was approximating a sharper fact, which is what the loss check below states.

  Tier 1 -- the file contradicts itself. metadata.totalVotes / houseVotes /
  senateVotes / billLessVotes / memberCount vs the records they count, a vote id
  whose H/S prefix disagrees with its chamber, a memberVotes entry naming a roll
  call that is not in `votes` (or naming one twice), and the generator's own
  reconciliation (memberCount = sittingMembersWithVotes + staleVoteRecords).
  Exit 1.

  Loss -- the one deliberate baseline gate, as in validate_fec_data.py and
  validate_ga_congress_trades.py. A roll call is immutable once a chamber
  publishes it and the run is incremental (it reuses every committed record), so
  within one Congress the set of roll-call ids only grows. A committed id that is
  gone means a chamber index failed to parse or the reuse layer broke -- the
  Senate menu returns [] on a ParseError and the House walk stops after a streak
  of failed fetches, and either leaves every surviving record self-consistent. So:
  a roll call at HEAD that is missing now (same Congress only; a new Congress
  legitimately starts empty), or a sitting member who had votes at HEAD and has
  none now, refuses the commit. This is a set difference, not a percentage.

  Tier 2 -- reported, never gated: sitting delegation members with no votes
  (named -- a vacancy, a newly seated member, or a Congress that has just
  begun), and a monolith with no roll calls yet.

Usage:
    python scripts/validate_federal_votes_monolith.py \
        assets/data/federal-member-votes.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  tier 1 or the loss check failed -- the caller must not commit
"""

import argparse
import json
import os
import subprocess
import sys

PREFIX_CHAMBER = {"H": "House", "S": "Senate"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, check=True).stdout
        return json.loads(blob.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def tier1(d):
    """Contradictions inside the file. Returns a list of strings."""
    meta, votes, mv = d.get("metadata"), d.get("votes"), d.get("memberVotes")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(votes, dict) or not isinstance(mv, dict):
        return ["votes / memberVotes is missing or not an object"]
    errors = []

    by_chamber, bill_less, wrong_prefix = {}, 0, []
    for vid, v in votes.items():
        ch = v.get("chamber") if isinstance(v, dict) else None
        by_chamber[ch] = by_chamber.get(ch, 0) + 1
        if isinstance(v, dict) and not v.get("bill"):
            bill_less += 1
        want = PREFIX_CHAMBER.get(str(vid)[:1])
        if want and ch != want:
            wrong_prefix.append(vid)

    for key, got in (("totalVotes", len(votes)),
                     ("houseVotes", by_chamber.get("House", 0)),
                     ("senateVotes", by_chamber.get("Senate", 0)),
                     ("billLessVotes", bill_less),
                     ("memberCount", len(mv))):
        if meta.get(key) != got:
            errors.append(f"metadata.{key} is {meta.get(key)!r} but the file holds {got}")
    if wrong_prefix:
        errors.append(f"{len(wrong_prefix)} vote id(s) whose H/S prefix disagrees with "
                      f"their chamber, e.g. {wrong_prefix[:3]}")

    orphan, dupes = set(), []
    for bio, entries in mv.items():
        seen = set()
        for e in entries or []:
            vid = e.get("voteId") if isinstance(e, dict) else None
            if vid not in votes:
                orphan.add(vid)
            if vid in seen:
                dupes.append(f"{bio}:{vid}")
            seen.add(vid)
    if orphan:
        errors.append(f"memberVotes names {len(orphan)} roll call(s) absent from votes, "
                      f"e.g. {sorted(map(str, orphan))[:3]}")
    if dupes:
        errors.append(f"{len(dupes)} member/roll-call pair(s) recorded twice, e.g. {dupes[:3]}")

    sw, stale = meta.get("sittingMembersWithVotes"), meta.get("staleVoteRecords")
    if isinstance(sw, int) and isinstance(stale, int) and sw + stale != len(mv):
        errors.append(f"memberCount {len(mv)} != sittingMembersWithVotes {sw} + "
                      f"staleVoteRecords {stale}")
    sit = meta.get("sittingDelegation")
    if isinstance(sit, int) and isinstance(sw, int) and sw > sit:
        errors.append(f"sittingMembersWithVotes {sw} exceeds sittingDelegation {sit}")
    return errors


def collapse(new, old):
    """A self-consistent file that has lost roll calls the committed one holds."""
    if not old:
        return []
    nm, om = new.get("metadata") or {}, old.get("metadata") or {}
    if nm.get("congress") != om.get("congress"):
        return []          # a new Congress legitimately starts from nothing
    errors = []
    gone = sorted(set(old.get("votes") or {}) - set(new.get("votes") or {}))
    if gone:
        errors.append(f"{len(gone)} roll call(s) at HEAD are missing now, e.g. "
                      f"{', '.join(gone[:5])} -- committed roll calls are immutable "
                      "and reused, so a chamber index failed or the reuse layer broke")
    had = {b for b, e in (old.get("memberVotes") or {}).items() if e}
    lost = sorted(b for b in nm.get("sittingMembersMissingVotes") or [] if b in had)
    if lost:
        errors.append(f"sitting member(s) with votes at HEAD have none now: "
                      f"{', '.join(lost)}")
    return errors


def tier2(new, old):
    """Things worth a human glance. Returns [(heading, [lines])]."""
    sections = []
    meta = new.get("metadata") or {}
    if not new.get("votes"):
        sections.append(("No roll calls yet", [
            f"- The {meta.get('congress')}th Congress has no recorded roll call in "
            "this file. Expected in the first days of a Congress; check the "
            "run log if not."]))
    missing = meta.get("sittingMembersMissingVotes") or []
    if missing:
        sections.append(("Sitting delegation members with no votes", [
            f"- `{b}`" for b in missing] + [
            "", "A vacancy filled mid-Congress, a newly seated member, or a "
            "Congress that has just begun are all normal; a member with a long "
            "record is not -- the loss check would have refused that."]))
    return sections


def render(path, sections):
    out = [f"## Federal votes: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("None of these blocked the update -- the data is committed.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--baseline-ref", default="HEAD",
                    help="git ref to diff the new file against (default HEAD)")
    ap.add_argument("--report-out", help="write the tier-2 markdown report here")
    ap.add_argument("--allow-collapse", action="store_true",
                    help="report lost roll calls instead of failing on them. For a "
                         "human who has inspected the rejected file -- never the default.")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"FAIL: {args.path} was not generated", file=sys.stderr)
        return 1
    try:
        new = load(args.path)
    except json.JSONDecodeError as exc:
        print(f"FAIL: {args.path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    errors = tier1(new)
    if errors:
        print("TIER 1 FAILED -- the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in Congress. The rejected "
              "file is uploaded as a workflow artifact.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['votes'])} roll calls, "
          f"{len(new['memberVotes'])} members, totals agree.")

    lost = collapse(new, baseline(args.path, args.baseline_ref))
    if lost:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nLOSS CHECK: the file is self-consistent but is missing data the "
              "committed one has:", file=stream)
        for e in lost:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. The weekly run will retry; check the log "
                  "for chamber-index or fetch failures first. The rejected file is "
                  "uploaded as a workflow artifact.", file=stream)
            return 1
        print("\nallow_collapse was set, so this is a warning.", file=stream)

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
