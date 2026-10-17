#!/usr/bin/env python3
"""Validate ga-campaign-finance.json (Georgia state, PeachFile): gate on
self-consistency, report on change.

This is the STATE finance file. The federal FEC file is validate_fec_data.py's;
the two share nothing but the pattern.

  Tier 1 — the file contradicts itself. A `metadata.count` that is not the number
  of filers, a filer missing a field the member pages read, a seat/office index
  naming a filer the file does not hold, a legislative filer that its own seat
  index forgot. No fact about the Ethics Commission can make any of these true,
  so they mean the generator is broken and the file must not be committed.

  Tier 2 — the file disagrees with last week's, or with full coverage. A seat
  with no filer, a seat that had one last week, an office that thinned out, an
  override pointing at a committee that has since terminated. Each is something
  the Commission or a candidate can legitimately do, so they are REPORTED, never
  gated, and the data is committed.

What the inline heredoc this replaces gated on, and why that discarded good data:

  len(by_seat) < 150 and len(legislative) < 400 — floors on what the source
  returns. They were pinned to the 2026 general's shape (233 seats, 560
  legislative filers) and would fire on any cycle with fewer contested seats, or
  on the first weeks of a new cycle when few have filed (the 2028 rollover is a
  date those numbers cannot survive). The failure they were groping at is real —
  the workflow's own comment says it: a partial pull (a dropped page, a WAF
  rejection) "shows up as a collapse in seat coverage". But a global count is a
  poor proxy for it. A seat count of 149 and a seat count of 151 are the same
  week of politics; one seat that had a filer last week and has none now is a
  fact with a name. So the replacement is per-seat: Georgia has 180 House and 56
  Senate seats, the file says which it covers, and the report NAMES the seats
  that lost coverage (and, with no baseline, the seats that have none), the
  offices that thinned, and — straight from the generator, which is the only
  thing that knows — the offices whose pagination stopped on a failed page.

  n == 0 is the judgement call, and it stays tier 1. The usual argument for
  tier 2 is that gating discards a good run; an empty run has no good data in it
  to discard, and the committed file is untouched either way. The generator
  already refuses to write it (and says whether the API returned nothing or
  returned only another cycle's rows, e.g. races.json moving a cycle ahead of
  PeachFile), so this is the same condition seen from the file.

  Missing `totalRaised` / `office` stay tier 1: the member pages read both, and
  the generator always writes both (None is a value; an absent KEY is a bug).

What this CANNOT see, said plainly: byOffice and bySeat are tallied from records,
so a seat or office with zero filers has no key — nothing absolute can iterate
over what is missing. Hence the seat check enumerates the seats that EXIST
(1-180, 1-56) and diffs against the baseline's covered set, and the office check
iterates the union of the two files' offices. The fetch-completeness warning
(metadata.incompleteOffices) is the only direct evidence of a dropped page; a
file from before that field existed reports nothing from it.

Usage:
    python scripts/validate_ga_campaign_finance.py assets/data/ga-campaign-finance.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  a tier-1 check failed — the caller must not commit
"""

import argparse
import json
import os
import subprocess
import sys

# The seats that EXIST. A seat with no filer is ordinary (nobody filed yet, or
# the incumbent runs for something else — Josh McLaurin sits in Senate 14 and
# filed for Lieutenant Governor); a seat that LOST its filer since last week is
# what a dropped page looks like.
CHAMBERS = {"House of Representatives": 180, "Senate": 56}

# filer.office -> the chamber its bySeat key is built from
LEGISLATIVE = {"State Representative": "House of Representatives",
               "State Senator": "Senate"}

REQUIRED_FIELDS = ("totalRaised", "office")

# An office losing more than this share of its filers in a week is reported.
# Reporting only: a committee terminating is a thing that happens, a quarter of
# an office terminating is a thing a human should look at.
OFFICE_DROP = 0.25
OFFICE_DROP_MIN_OLD = 4    # below this, one filer is already 25%


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, text=True, check=True).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    filers = d.get("filers") or {}
    meta = d.get("metadata") or {}

    if not filers:
        errors.append("no filers in the file")
        return errors   # nothing below can say anything useful

    n = meta.get("count")
    if n != len(filers):
        errors.append(f"metadata.count ({n}) != len(filers) ({len(filers)})")

    missing = [k for k, f in filers.items()
               if any(field not in f for field in REQUIRED_FIELDS)]
    if missing:
        errors.append(f"filers missing a required field "
                      f"({'/'.join(REQUIRED_FIELDS)}): {sorted(missing)[:5]}")

    for index_name in ("bySeat", "byOffice"):
        for key, ids in (d.get(index_name) or {}).items():
            for fid in ids:
                if fid not in filers:
                    errors.append(f"{index_name}[{key}] names {fid}, which is not in filers")
    for key, fid in (d.get("byNormalizedName") or {}).items():
        if fid not in filers:
            errors.append(f"byNormalizedName[{key}] -> {fid}, which is not in filers")

    # The generator puts every legislative filer with a district into bySeat. One
    # that is missing, or filed under another seat, was dropped by a broken join.
    in_seat = {}
    for key, ids in (d.get("bySeat") or {}).items():
        for fid in ids:
            in_seat.setdefault(fid, set()).add(key)
    orphans = []
    for fid, f in filers.items():
        chamber = LEGISLATIVE.get(f.get("office"))
        if not chamber or not f.get("district"):
            continue
        if f"{chamber}-{f['district']}" not in in_seat.get(fid, ()):
            orphans.append(fid)
    if orphans:
        errors.append(f"legislative filer(s) absent from their own bySeat bucket: "
                      f"{sorted(orphans)[:5]}")

    return errors


# ── tier 2: coverage, and the file against last week's ─────────────────────────

def covered(d):
    """Seats ('House of Representatives-13') that have at least one filer."""
    return {k for k, ids in (d.get("bySeat") or {}).items() if ids}


def all_seats():
    return [f"{chamber}-{n}" for chamber, top in CHAMBERS.items()
            for n in range(1, top + 1)]


def name_seats(seats):
    """['House 75, 102, 129', 'Senate 4'] -- grouped, numerically ordered."""
    out = []
    for chamber in CHAMBERS:
        nums = sorted(int(s.rsplit("-", 1)[1]) for s in seats
                      if s.startswith(chamber + "-") and s.rsplit("-", 1)[1].isdigit())
        if nums:
            short = "House" if chamber.startswith("House") else "Senate"
            out.append(f"{short} " + ", ".join(str(n) for n in nums))
    return out


def office_counts(d):
    counts = {}
    for f in (d.get("filers") or {}).values():
        counts[f.get("office")] = counts.get(f.get("office"), 0) + 1
    return counts


def tier2(new, old):
    """Coverage facts and changes, as (heading, [lines]) sections."""
    sections = []
    meta = new.get("metadata") or {}

    # The generator's own account of a dropped page. Written by the producer, the
    # only thing that can know; absent from files that predate the field.
    if meta.get("incompleteOffices"):
        sections.append(("Fetch stopped on a failed page", [
            f"- {o}: the list is a prefix of the office, so filers are missing "
            f"until the next run" for o in meta["incompleteOffices"]]))

    if meta.get("droppedOverrides"):
        sections.append(("Overrides dropped: the filer no longer exists", [
            f"- {u}" for u in meta["droppedOverrides"]] + [
            "- These candidates fell back to the automatic join. A committee "
            "terminating does this; re-resolve each with "
            "`scripts/report_ga_finance_matches.py` and the overrides editor."]))

    now = covered(new)
    uncovered = [s for s in all_seats() if s not in now]

    if not old:
        if uncovered:
            sections.append(("Seats with no filer", [
                f"- {len(uncovered)} of {len(all_seats())}: " + "; ".join(name_seats(uncovered))]))
        return sections

    before = covered(old)
    lost = sorted(before - now)
    gained = sorted(now - before)
    if lost:
        sections.append(("Seats that lost coverage — check these first", [
            f"- {len(lost)} seat(s) had a filer last run and have none now: "
            + "; ".join(name_seats(lost)),
            "- A candidate withdrawing or a committee terminating does this. So does a "
            "dropped page: if many seats appear here, check the run log first."]))
    if gained:
        sections.append(("Seats that gained coverage", [
            f"- {len(gained)} seat(s): " + "; ".join(name_seats(gained))]))
    if (lost or gained) and uncovered:
        sections[-1][1].append(f"- Currently with no filer ({len(uncovered)}): "
                               + "; ".join(name_seats(uncovered)))

    nc, oc = office_counts(new), office_counts(old)
    thinned = []
    for office in sorted(set(nc) | set(oc), key=str):
        was, is_ = oc.get(office, 0), nc.get(office, 0)
        if was >= OFFICE_DROP_MIN_OLD and is_ < was * (1 - OFFICE_DROP):
            thinned.append(f"- **{office}**: {was} → {is_} filers")
    if thinned:
        sections.append((f"Offices that lost more than {OFFICE_DROP:.0%} of their filers",
                         thinned))

    o_cycle, n_cycle = (old.get("metadata") or {}).get("cycle"), meta.get("cycle")
    if o_cycle != n_cycle:
        sections.append(("Cycle changed", [f"- {o_cycle} → {n_cycle}"]))

    return sections


def render(path, sections):
    out = [f"## GA state campaign finance: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something the Ethics Commission or a candidate can "
                   "legitimately do, so none of them blocked the update — the data is "
                   "committed. They are here because they change what a reader sees on "
                   "a member's or a race's page.")
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
        print("\nThis is a generator bug, not a change in the data. The rejected file "
              "is uploaded as a workflow artifact so it can be inspected.", file=sys.stderr)
        return 1
    filers = new["filers"]
    legislative = sum(1 for f in filers.values() if f.get("office") in LEGISLATIVE)
    print(f"Tier 1 passed: {len(filers)} filers ({legislative} legislative), "
          f"{len(covered(new))} seats covered, indexes agree with filers.")

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} reported item(s) — reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
