#!/usr/bin/env python3
"""Validate _data/ga_unopposed_seats.json: gate on self-contradiction, report on change.

The file is a pure derivation of races.json, so what can go wrong splits cleanly.

  Tier 1 - the file contradicts itself. A chamber total that does not sum, a
  seat list that is not as long as the unopposed count, a chamber holding MORE
  seats than the constitution creates (180 House, 56 Senate), two entries for
  one seat. No fact about Georgia makes any of these true, so they mean the
  derivation is broken and the file must not be committed.

  Tier 2 - the file differs from yesterday's, or from a full General Assembly.
  A race missing from races.json, a seat newly contested after a candidate
  withdrew, a total below 236: all of them are things races.json can
  legitimately say, and the page should publish the answer it gives.

This replaces the inline heredoc in refresh-unopposed-count.yml, whose
`150 <= total <= 260` window was a floor on a number the world controls. A
total of 149 is a data-entry gap in races.json worth NAMING, not a reason to
discard the day's refresh. See docs/audits/2026-10-13-data-pipeline-audit.md
2.6. The generator has no world-gate of its own: its only exits are in --check,
which compares the file with itself rebuilt.

Usage:
    python scripts/validate_unopposed_seats.py _data/ga_unopposed_seats.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  a tier-1 check failed - the caller must not commit
"""

import argparse
import json
import os
import subprocess
import sys

# Seats the constitution creates. A quantity ABOVE these is a contradiction;
# below them is a seat missing from races.json, which is tier 2.
FULL_STRENGTH = {"house": 180, "senate": 56}
CHAMBER_LABEL = {"house": "House", "senate": "Senate"}


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


# -- tier 1: the file against itself -------------------------------------------

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    by = d.get("byChamber") or {}
    for key in FULL_STRENGTH:
        if key not in by:
            errors.append(f"byChamber has no {key!r} entry")
    if errors:
        return errors   # nothing below can say anything useful

    def num(label, v):
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append(f"{label} is {v!r}, not an integer")
            return 0
        return v

    total, unopposed, contested = (num(k, d.get(k)) for k in ("total", "unopposed", "contested"))
    h, s = by["house"], by["senate"]
    if total != num("house.total", h.get("total")) + num("senate.total", s.get("total")):
        errors.append("chamber totals do not sum to total")
    if unopposed != num("house.unopposed", h.get("unopposed")) + num("senate.unopposed", s.get("unopposed")):
        errors.append("chamber unopposed counts do not sum to unopposed")
    if unopposed + contested != total:
        errors.append(f"unopposed ({unopposed}) + contested ({contested}) != total ({total})")

    for key, cap in FULL_STRENGTH.items():
        c = by[key]
        if num(f"{key}.total", c.get("total")) > cap:
            errors.append(f"{key} lists {c['total']} seats; the chamber has {cap}")
        if c.get("unopposed", 0) > c.get("total", 0):
            errors.append(f"{key}: {c['unopposed']} unopposed of only {c['total']} seats")
        safe = c.get("republicanSafe", 0) + c.get("democraticSafe", 0)
        if safe > c.get("unopposed", 0):
            errors.append(f"{key}: {safe} safe seats exceeds its {c['unopposed']} unopposed")

    seats = d.get("seats")
    if not isinstance(seats, list):
        errors.append("seats is not a list")
        return errors
    if len(seats) != unopposed:
        errors.append(f"seat list length ({len(seats)}) != unopposed count ({unopposed})")
    ids = [x.get("id") for x in seats]
    dupes = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dupes:
        errors.append(f"seat(s) listed more than once: {dupes[:5]}")
    for key in FULL_STRENGTH:
        listed = sum(1 for x in seats if x.get("chamber") == key)
        if listed != by[key].get("unopposed"):
            errors.append(f"{key}: {listed} seats listed but byChamber says "
                          f"{by[key].get('unopposed')} unopposed")
    stray = sorted({str(x.get("chamber")) for x in seats} - set(FULL_STRENGTH))
    if stray:
        errors.append(f"seat(s) in unknown chamber(s): {stray}")

    if total and d.get("unopposedPct") != round(unopposed / total * 100, 1):
        errors.append(f"unopposedPct ({d.get('unopposedPct')}) != unopposed/total "
                      f"({round(unopposed / total * 100, 1)})")
    return errors


# -- tier 2: the file against full strength and against yesterday's -------------

def seat_label(s):
    return f"{CHAMBER_LABEL.get(s.get('chamber'), s.get('chamber'))} district {s.get('district')}"


def seat_line(s):
    return (f"- {seat_label(s)} ({s.get('party') or 'no major party'}, "
            f"{s.get('candidate') or 'candidate unknown'})")


def tier2(new, old):
    """Things races.json can legitimately say, as (heading, [lines]) sections."""
    sections = []
    by = new.get("byChamber") or {}

    short = [f"- **{CHAMBER_LABEL[k]}**: races.json holds {by[k].get('total')} of "
             f"{cap} seats ({cap - by[k].get('total', 0)} missing)"
             for k, cap in FULL_STRENGTH.items()
             if k in by and by[k].get("total", 0) < cap]
    if short:
        sections.append(("A chamber is below full strength in races.json", short))

    if not old:
        return sections

    n = {x.get("id"): x for x in new.get("seats") or []}
    o = {x.get("id"): x for x in old.get("seats") or []}
    gained = [seat_line(n[i]) for i in sorted(set(n) - set(o), key=str)]
    lost = [seat_line(o[i]) for i in sorted(set(o) - set(n), key=str)]
    if gained:
        sections.append(("Seats that became unopposed", gained))
    if lost:
        sections.append(("Seats that are now contested (or left races.json)", lost))

    moved = []
    for k in ("total", "unopposed", "contested", "republicanSafe", "democraticSafe"):
        if new.get(k) != old.get(k):
            moved.append(f"- {k}: {old.get(k)} -> {new.get(k)}")
    if moved:
        sections.append(("Headline numbers", moved))
    return sections


def render(path, sections):
    out = [f"## Unopposed seats: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something races.json can legitimately say, so none "
                   "of them blocked the update - the data is committed. They are "
                   "here because they change the headline number on the Majority Tracker.")
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
        print("TIER 1 FAILED - the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in races.json. The rejected "
              "file is uploaded as a workflow artifact so it can be inspected.",
              file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {new['unopposed']} of {new['total']} seats unopposed, "
          f"sums and seat list agree.")

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} material change(s) - reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
