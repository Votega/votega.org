#!/usr/bin/env python3
"""Validate vp-tie-votes.json: gate on self-consistency and lost votes.

This replaces `validate_data_update.py --metric votes/records --scope-key
metadata.congress` (default 20% shrink-vs-HEAD) in update-vp-tie-votes.yml.

There was never an absolute floor, so nothing here was the world's number, and
the --scope-key handled the Congress rollover correctly (a new Congress starts
with no tie-breaking votes). What was wrong is that a 20% shrink gate is blunt
at this size: the file holds 8 votes, so losing one is -12.5% and sails through,
and the generator skips a vote whose detail XML fails to fetch (`if not raw:
continue`) while its Senate menu returns [] on a parse error. Either publishes a
file missing a tie-breaking vote -- every surviving record intact -- and the
weekly run is the only thing that would restore it.

  Tier 1 -- the file contradicts itself. metadata.count vs the votes it counts,
  a record whose tally is not a tie (yeas != nays is the DEFINITION of the file,
  and the generator only keeps a vote where the Senate recorded a tie-breaker),
  a vpVote that is not Yea/Nay, a vote from a different Congress than
  metadata.congress, the same congress/session/voteNumber twice, a record
  missing a field the page renders, votes not in date order. Exit 1.

  Loss -- the one deliberate baseline gate, as in the other migrated validators.
  A recorded vote is immutable and the file is rebuilt whole, so within one
  Congress the set of (session, voteNumber) only grows: one at HEAD that is gone
  now refuses the commit. A set difference rather than a percentage, so it fires
  on the first lost vote. A new Congress is exempt (it legitimately starts empty).

  Tier 2 -- reported, never gated: votes added (named).

Usage:
    python scripts/validate_vp_tie_votes.py assets/data/vp-tie-votes.json \
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

REQUIRED = ("voteNumber", "congress", "session", "date", "vpVote", "yeas", "nays")


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


def key(v):
    return f"{v.get('congress')}-{v.get('session')}-{v.get('voteNumber')}"


def tier1(d):
    """Contradictions inside the file. Returns a list of strings."""
    meta, votes = d.get("metadata"), d.get("votes")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(votes, list):
        return ["votes is missing or not a list"]
    errors = []
    if meta.get("count") != len(votes):
        errors.append(f"metadata.count is {meta.get('count')!r} but the file holds "
                      f"{len(votes)} votes")
    seen, dupes, gappy, not_tie, bad_vp, wrong_cong = set(), set(), [], [], [], []
    for i, v in enumerate(votes):
        if not isinstance(v, dict):
            errors.append(f"votes[{i}] is not an object")
            continue
        gaps = [f for f in REQUIRED if v.get(f) in (None, "")]
        if gaps:
            gappy.append(f"votes[{i}] lacks {', '.join(gaps)}")
        if key(v) in seen:
            dupes.add(key(v))
        seen.add(key(v))
        if v.get("yeas") != v.get("nays"):
            not_tie.append(key(v))
        if v.get("vpVote") not in ("Yea", "Nay"):
            bad_vp.append(f"{key(v)}={v.get('vpVote')!r}")
        if v.get("congress") != meta.get("congress"):
            wrong_cong.append(key(v))
    if gappy:
        errors.append(f"{len(gappy)} vote(s) missing a required field, e.g. {gappy[0]}")
    if dupes:
        errors.append(f"duplicate vote(s): {sorted(dupes)[:5]}")
    if not_tie:
        errors.append(f"{len(not_tie)} vote(s) whose tally is not a tie, e.g. {not_tie[:3]}")
    if bad_vp:
        errors.append(f"vpVote is not Yea/Nay: {bad_vp[:3]}")
    if wrong_cong:
        errors.append(f"{len(wrong_cong)} vote(s) from a Congress other than "
                      f"metadata.congress {meta.get('congress')}: {wrong_cong[:3]}")
    dates = [v.get("date") or "" for v in votes if isinstance(v, dict)]
    if dates != sorted(dates):
        errors.append("votes are not in date order (the generator sorts them)")
    return errors


def collapse(new, old):
    """A self-consistent file that has lost votes the committed one holds."""
    if not old:
        return []
    if (new.get("metadata") or {}).get("congress") != (old.get("metadata") or {}).get("congress"):
        return []          # a new Congress legitimately starts empty
    gone = sorted(set(map(key, old.get("votes") or [])) - set(map(key, new.get("votes") or [])))
    if not gone:
        return []
    return [f"{len(gone)} recorded tie-breaking vote(s) at HEAD are missing now: "
            f"{', '.join(gone[:5])} -- recorded votes are immutable, so a vote detail "
            "fetch failed or the Senate menu did not parse"]


def tier2(new, old):
    """Things worth a human glance. Returns [(heading, [lines])]."""
    if not old:
        return []
    have = set(map(key, old.get("votes") or []))
    added = [v for v in new.get("votes") or [] if key(v) not in have]
    if not added or (new.get("metadata") or {}).get("congress") != (old.get("metadata") or {}).get("congress"):
        return []
    return [(f"{len(added)} new tie-breaking vote(s)", [
        f"- {v.get('date')}: VP voted {v.get('vpVote')} -- {v.get('title') or v.get('question')}"
        for v in added])]


def render(path, sections):
    out = [f"## VP tie-breaking votes: what changed in `{os.path.basename(path)}`", ""]
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
                    help="report lost votes instead of failing on them. For a human who "
                         "has inspected the rejected file -- never the default.")
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
        print("\nThis is a generator bug, not a quiet Senate. The rejected file is "
              "uploaded as a workflow artifact.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['votes'])} tie-breaking vote(s), "
          f"{new['metadata'].get('congress')}th Congress.")

    old = baseline(args.path, args.baseline_ref)
    lost = collapse(new, old)
    if lost:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nLOSS CHECK: the file is self-consistent but is missing votes the "
              "committed one has:", file=stream)
        for e in lost:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. The weekly run will retry; check the log "
                  "for fetch failures first. The rejected file is uploaded as a "
                  "workflow artifact.", file=stream)
            return 1
        print("\nallow_collapse was set, so this is a warning.", file=stream)

    report = render(args.path, tier2(new, old))
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
