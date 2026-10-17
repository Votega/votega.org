#!/usr/bin/env python3
"""Validate the general-election ballot placeholder: gate on self-contradiction, report on change.

_data/election_results/ga-general-<cycle>-results.json is a pure derivation of
races.json: every candidate at 0 votes, listing who is on the ballot.

  Tier 1 - the file contradicts itself. A placeholder carrying votes (it is
  defined as the file with none), a contest whose totalVotes is not the sum of
  its candidates, a candidate with no name, two sections or two offices with
  one id. No fact about the ballot makes any of these true.

  Tier 2 - the ballot is not the shape we expected, or differs from yesterday's.
  A missing section, an empty section, fewer offices than the committed file,
  a candidate added or removed. All of these are things races.json can
  legitimately say (a withdrawal, a race not yet curated) and the preview
  should publish them.

This replaces the inline heredoc in refresh-general-placeholder.yml, whose
`len(d) == 5`, `offices >= 300` and `cands >= 400` were floors on numbers
races.json controls. Floors also could not name anything: "suspiciously few
offices" does not say WHICH section lost its races, so this reports per
section. The generator has no world-gate of its own; its only exits are in
--check, which rebuilds and compares the file with races.json.

Usage:
    python scripts/validate_general_placeholder.py \
        _data/election_results/ga-general-2026-results.json \
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

# The sections build_sections() emits. Structural, not a count of anything the
# world controls, but a missing one is still the world (or races.json) talking,
# so it is reported rather than gated.
EXPECTED_SECTIONS = ["statewide", "us-house", "state-senate", "state-house", "courts"]

# Cap on named lines per heading; the first run after a races.json edit can
# touch a hundred offices.
MAX_LINES = 25


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, check=True).stdout
        return json.loads(blob.decode("utf-8"))   # bytes: text=True decodes with the locale codec
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def contests_of(race):
    return race.get("contests") or []


# -- tier 1: the file against itself -------------------------------------------

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    if not isinstance(d, list):
        return [f"top level is {type(d).__name__}, not a list of sections"]
    errors = []

    ids = [s.get("id") for s in d]
    dupes = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dupes:
        errors.append(f"section id(s) used more than once: {dupes}")

    for sec in d:
        sid = sec.get("id")
        if not sid:
            errors.append("a section has no id")
        offices = [r.get("office") for r in sec.get("races") or []]
        odupes = sorted({o for o in offices if offices.count(o) > 1}, key=str)
        if odupes:
            errors.append(f"{sid}: office(s) listed more than once: {odupes[:5]}")
        for race in sec.get("races") or []:
            office = race.get("office")
            if not office:
                errors.append(f"{sid}: a race has no office name")
            for contest in contests_of(race):
                cands = contest.get("candidates") or []
                summed = sum(c.get("votes", 0) for c in cands)
                if contest.get("totalVotes", 0) != summed:
                    errors.append(f"{sid}/{office} [{contest.get('party')}]: totalVotes "
                                  f"({contest.get('totalVotes')}) != sum of candidates ({summed})")
                if contest.get("totalVotes", 0) or summed:
                    errors.append(f"{sid}/{office} [{contest.get('party')}]: placeholder "
                                  f"carries {max(contest.get('totalVotes', 0), summed)} votes")
                for c in cands:
                    if not c.get("name"):
                        errors.append(f"{sid}/{office} [{contest.get('party')}]: "
                                      f"a candidate has no name")
    return errors


# -- tier 2: the ballot against what we expect and against yesterday's ----------

def tallies(d):
    """section id -> (offices, candidates)."""
    out = {}
    for sec in d:
        races = sec.get("races") or []
        out[sec.get("id")] = (len(races),
                              sum(len(c.get("candidates") or [])
                                  for r in races for c in contests_of(r)))
    return out


def ballots(d):
    """(section, office) -> sorted names on that ballot."""
    out = {}
    for sec in d:
        for race in sec.get("races") or []:
            out[(sec.get("id"), race.get("office"))] = sorted(
                c.get("name") for contest in contests_of(race)
                for c in contest.get("candidates") or [])
    return out


def capped(lines):
    if len(lines) <= MAX_LINES:
        return lines
    return lines[:MAX_LINES] + [f"- ... and {len(lines) - MAX_LINES} more"]


def tier2(new, old):
    """Things races.json can legitimately say, as (heading, [lines]) sections."""
    sections = []
    now = tallies(new)

    missing = [s for s in EXPECTED_SECTIONS if s not in now]
    extra = [s for s in now if s not in EXPECTED_SECTIONS]
    lines = ([f"- missing: `{s}`" for s in missing] +
             [f"- unexpected: `{s}`" for s in extra])
    if lines:
        sections.append(("Sections differ from the expected five", lines))

    empty = [f"- `{s}` has no offices" for s in EXPECTED_SECTIONS if s in now and now[s][0] == 0]
    if empty:
        sections.append(("Empty sections", empty))

    if not old or not isinstance(old, list):
        return sections

    before = tallies(old)
    moved = []
    for s in sorted(set(now) | set(before), key=str):
        (no, nc), (oo, oc) = now.get(s, (0, 0)), before.get(s, (0, 0))
        if (no, nc) != (oo, oc):
            moved.append(f"- `{s}`: {oo} offices / {oc} candidates -> {no} / {nc}")
    if moved:
        sections.append(("Offices and candidates per section", moved))

    a, b = ballots(old), ballots(new)
    added = [f"- {k[0]}/{k[1]}: {', '.join(b[k]) or 'no candidates'}"
             for k in sorted(set(b) - set(a), key=str)]
    removed = [f"- {k[0]}/{k[1]}" for k in sorted(set(a) - set(b), key=str)]
    changed = []
    for k in sorted(set(a) & set(b), key=str):
        if a[k] != b[k]:
            gone, came = sorted(set(a[k]) - set(b[k])), sorted(set(b[k]) - set(a[k]))
            changed.append(f"- {k[0]}/{k[1]}: " +
                           "; ".join(x for x in (f"off: {', '.join(gone)}" if gone else "",
                                                 f"on: {', '.join(came)}" if came else "") if x))
    if added:
        sections.append(("Offices added to the ballot", capped(added)))
    if removed:
        sections.append(("Offices removed from the ballot", capped(removed)))
    if changed:
        sections.append(("Candidates changed on an existing ballot", capped(changed)))
    return sections


def render(path, sections):
    out = [f"## General-election preview: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something races.json can legitimately say, so none "
                   "of them blocked the update - the preview is committed. They are "
                   "here because they change who a reader sees on the ballot.")
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
        for e in errors[:MAX_LINES]:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in races.json. The rejected "
              "file is uploaded as a workflow artifact so it can be inspected.",
              file=sys.stderr)
        return 1
    t = tallies(new)
    print(f"Tier 1 passed: {sum(o for o, _ in t.values())} offices, "
          f"{sum(c for _, c in t.values())} candidates, 0 votes.")

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
