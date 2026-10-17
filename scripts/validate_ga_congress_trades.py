#!/usr/bin/env python3
"""Validate ga-congress-trades.json: gate on self-consistency, report on change.

This replaces `validate_data_update.py --min trades=1 --min members=1` (plus
its default 20% shrink-vs-HEAD gate) in update-ga-congress-trades.yml.

Why those gates were wrong. `trades >= 1` and `members >= 1` are the world's
numbers: whether any member of Georgia's delegation has filed a periodic
transaction report is a fact about Congress, and a delegation that is
disclosure-free (or a quiet Congress) is a legitimate file. The 20% shrink
gate misfired both ways. On five members it tolerates losing one (5 -> 4 is
exactly -20%, which `< -20%` lets through) and trips on losing two, so it was
catching the failure by accident of arithmetic; and it trips on an upstream
dedupe that legitimately removes a few trades.

  Tier 1 — the file contradicts itself. metadata.totalTrades vs the trades it
  counts, gaMembers vs the byMember keys, a member's tradeCount / purchases /
  sales / lateFilings / estVolume vs the trades listed under them (recomputed by
  the generator's own derive_counters, the single implementation), more members
  than the delegation has seats, a member record missing the fields the page
  reads. Exit 1.

  Collapse — the one deliberate baseline gate, as in validate_fec_data.py. The
  failure it catches leaves every surviving record self-consistent: a per-filer
  fetch that fails is skipped (the generator's `could not fetch ... skipping`)
  and the member silently vanishes from the trades page. So: (a) a member the
  generator says it failed to fetch (metadata.fetchFailed, written for exactly
  this purpose) who had trades at HEAD, and (b) the trade total falling by more
  than COLLAPSE_DROP. The file is rebuilt whole each week from five small
  fetches, so refusing costs one week's wait, not a sweep.

  Tier 2 — reported, never gated: members added or removed (named), a member
  with no bioguideId (the generator refuses to guess one), a failed fetch for a
  member with no history, and a file with no trades at all.

Usage:
    python scripts/validate_ga_congress_trades.py assets/data/ga-congress-trades.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  tier 1 or the collapse check failed — the caller must not commit
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_ga_congress_trades import derive_counters  # noqa: E402

# Losing more than this share of last run's trades is not a week in Congress.
COLLAPSE_DROP = 0.5

MEMBER_FIELDS = ("filerId", "chamber", "trades", "tradeCount", "purchases",
                 "sales", "lateFilings", "estVolume")


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
    meta, by_member = d.get("metadata"), d.get("byMember")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(by_member, dict):
        return ["byMember is missing or not an object"]
    if not isinstance(d.get("tickerNames"), dict):
        return ["tickerNames is missing or not an object"]

    errors = []
    listed = 0
    for name, m in sorted(by_member.items()):
        gaps = [f for f in MEMBER_FIELDS if f not in m]
        if isinstance(m.get("trades"), list):
            listed += len(m["trades"])
        if gaps or not isinstance(m.get("trades"), list):
            errors.append(f"{name}: missing {', '.join(gaps) or 'a trades list'}")
            continue
        want = derive_counters(m["trades"])
        off = [f"{k} {m[k]!r} (trades say {want[k]!r})" for k in want
               if m[k] != want[k]]
        if off:
            errors.append(f"{name}: " + "; ".join(off))

    if meta.get("totalTrades") != listed:
        errors.append(f"metadata.totalTrades is {meta.get('totalTrades')!r} but "
                      f"{listed} trades are listed")
    if meta.get("gaMembers") != sorted(by_member):
        errors.append(f"metadata.gaMembers {meta.get('gaMembers')!r} disagrees with "
                      f"the byMember keys {sorted(by_member)!r}")
    size = meta.get("delegationSize")
    if isinstance(size, int) and len(by_member) > size:
        errors.append(f"{len(by_member)} members published but the delegation has "
                      f"only {size} seats")
    return errors


def total(d):
    return sum(len(m.get("trades") or []) for m in (d.get("byMember") or {}).values())


def collapse(new, old):
    """A self-consistent file that has lost members or most of its trades."""
    if not old:
        return []
    errors = []
    failed = (new.get("metadata") or {}).get("fetchFailed") or []
    lost = [n for n in failed
            if len(((old.get("byMember") or {}).get(n) or {}).get("trades") or []) > 0]
    if lost:
        errors.append("per-filer fetch failed for " + ", ".join(sorted(lost))
                      + " — they had trades at HEAD and would vanish from the page")
    o, n = total(old), total(new)
    if o > 0 and (o - n) / o > COLLAPSE_DROP:
        errors.append(f"trades fell {o} -> {n} ({(o - n) / o:.0%}); a drop this size "
                      f"is a half-failed fetch, not a quiet quarter")
    return errors


def tier2(new, old):
    """Things worth a human glance. Returns [(heading, [lines])]."""
    sections = []
    nm = new.get("byMember") or {}
    meta = new.get("metadata") or {}

    if not total(new):
        sections.append(("No trades in the file",
                         ["- No member of the delegation has a disclosed trade in "
                          "the source. Legitimate for a quiet delegation; check the "
                          "run log if that is not expected."]))

    unresolved = sorted(n for n, m in nm.items() if not m.get("bioguideId"))
    if unresolved:
        sections.append(("Members with no bioguideId", [
            f"- {n}: the generator refuses to guess, so their card cannot link "
            f"to a profile" for n in unresolved]))

    quiet_fail = [n for n in (meta.get("fetchFailed") or [])
                  if not old or n not in (old.get("byMember") or {})]
    if quiet_fail:
        sections.append(("Per-filer fetch failed (no prior record to lose)",
                         [f"- {n}" for n in sorted(quiet_fail)]))

    if old:
        om = old.get("byMember") or {}
        added, removed = sorted(set(nm) - set(om)), sorted(set(om) - set(nm))
        lines = []
        if added:
            lines.append("- added: " + ", ".join(
                f"{n} ({len(nm[n].get('trades') or [])} trades)" for n in added))
        if removed:
            lines.append("- removed: " + ", ".join(
                f"{n} ({len(om[n].get('trades') or [])} trades at HEAD)"
                for n in removed))
        if lines:
            sections.append(("Members added or removed", lines))
    return sections


def render(path, sections):
    out = [f"## GA congressional trades: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("None of these blocked the update — the data is committed.")
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
                    help="report a collapse instead of failing on it. For a human who "
                         "has inspected the rejected file and confirmed the drop is "
                         "real — never the default.")
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
        print("TIER 1 FAILED — the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in Congress. The rejected "
              "file is uploaded as a workflow artifact.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['byMember'])} members, "
          f"{new['metadata']['totalTrades']} trades, counters match the trades.")

    old = baseline(args.path, args.baseline_ref)
    shrink = collapse(new, old)
    if shrink:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nCOLLAPSE CHECK: the file is self-consistent but has lost data "
              "the committed one has:", file=stream)
        for e in shrink:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. The weekly run will retry; check the log "
                  "for fetch failures first. The rejected file is uploaded as a "
                  "workflow artifact.", file=stream)
            return 1
        print("\nallow_collapse was set, so this is a warning.", file=stream)

    sections = tier2(new, old)
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
