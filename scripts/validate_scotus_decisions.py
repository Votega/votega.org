#!/usr/bin/env python3
"""Validate scotus-decisions.json: gate on self-consistency and lost rulings.

This replaces `validate_data_update.py --min decisions=1 --scope-key
metadata.terms` (plus its default 20% shrink-vs-HEAD gate) in
update-scotus-decisions.yml.

`decisions >= 1` is the world's number: the Court issues nothing between a
term's start in October and its first opinions, and TERMS is edited by hand
each October, so a freshly added term is legitimately empty for weeks. The
`--scope-key` was a patch for the other half of that problem (a TERMS edit
resets the corpus).

  Tier 1 — the file contradicts itself. metadata.count vs the cases it counts,
  a case whose term is not in metadata.terms, the same term/docket twice, a
  case missing a field the page reads, cases not in decided-date order (the
  generator's own contract). Exit 1.

  Loss — the one deliberate baseline gate, as in validate_fec_data.py and
  validate_ga_congress_trades.py. A decided case never legitimately leaves the
  record, but the generator skips a case whose Oyez detail fetch fails and a
  term whose case list fails, and either leaves every surviving case perfectly
  self-consistent. The generator now publishes what it failed to get
  (metadata.detailFetchFailed, metadata.emptyTerms), so the gate is precise
  rather than a percentage: a failed case that was in HEAD, or a term that had
  cases at HEAD and has none now, refuses the commit. Cases of a term no longer
  in metadata.terms are exempt (dropping a term from TERMS is a deliberate
  edit — this is what --scope-key was approximating). A bare >50% fall also
  refuses. The job is weekly and cheap to retry; the rejected file is uploaded.

  Tier 2 — reported, never gated: cases added (named, the new rulings), cases
  removed without a recorded failure (Oyez retracted them — a human should
  look), a failed fetch with no prior record, and a stale TERMS: once a new
  term has begun (October 1) and TERMS does not include it, new decisions are
  not being collected. That edit is manual (see the TERMS comment in the
  generator and RECURRING-TASKS.md), so the report is the only reminder.

Usage:
    python scripts/validate_scotus_decisions.py assets/data/scotus-decisions.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  tier 1 or the loss check failed — the caller must not commit
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

# More than this share of last run's cases gone is a half-failed sweep.
COLLAPSE_DROP = 0.5

CASE_FIELDS = ("name", "docketNumber", "term", "decidedDate")


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


def key(case):
    """The generator's own identity for a case: the same `term/docket` string it
    records in metadata.detailFetchFailed."""
    return f"{case.get('term')}/{case.get('docketNumber')}"


def tier1(d):
    """Contradictions inside the file. Returns a list of strings."""
    meta, cases = d.get("metadata"), d.get("cases")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(cases, list):
        return ["cases is missing or not a list"]
    errors = []
    if meta.get("count") != len(cases):
        errors.append(f"metadata.count is {meta.get('count')!r} but the file holds "
                      f"{len(cases)} cases")
    terms = set(meta.get("terms") or [])
    seen, dupes, off_term, gappy = set(), set(), set(), []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            errors.append(f"cases[{i}] is not an object")
            continue
        gaps = [f for f in CASE_FIELDS if not c.get(f)]
        if gaps:
            gappy.append(f"cases[{i}] ({c.get('name')!r}) lacks {', '.join(gaps)}")
        k = key(c)
        if k in seen:
            dupes.add(k)
        seen.add(k)
        if c.get("term") not in terms:
            off_term.add(c.get("term"))
    if gappy:
        errors.append(f"{len(gappy)} case(s) missing a required field, e.g. {gappy[0]}")
    if dupes:
        errors.append(f"duplicate term/docket: {sorted(dupes)[:5]}")
    if off_term:
        errors.append(f"case term(s) not in metadata.terms {sorted(terms)}: "
                      f"{sorted(map(str, off_term))}")
    dates = [c.get("decidedDate") or "" for c in cases if isinstance(c, dict)]
    if dates != sorted(dates, reverse=True):
        errors.append("cases are not in decided-date order (the generator sorts them)")
    return errors


def collapse(new, old):
    """A self-consistent file that has lost rulings the committed one has."""
    if not old:
        return []
    meta = new.get("metadata") or {}
    terms = set(meta.get("terms") or [])
    # Only cases whose term is still collected can be "lost"; dropping a term
    # from TERMS is a deliberate edit.
    held = {key(c): c for c in old.get("cases") or [] if c.get("term") in terms}
    errors = []
    lost = sorted(k for k in meta.get("detailFetchFailed") or [] if k in held)
    if lost:
        errors.append(f"Oyez detail fetch failed for {len(lost)} case(s) already "
                      f"published: {', '.join(lost[:6])}"
                      + (" ..." if len(lost) > 6 else ""))
    for t in sorted(meta.get("emptyTerms") or []):
        n = sum(1 for c in held.values() if c.get("term") == t)
        if n:
            errors.append(f"the {t} term returned no cases but {n} are published")
    if held:
        have = {key(c) for c in new.get("cases") or []}
        gone = sum(1 for k in held if k not in have)
        if gone / len(held) > COLLAPSE_DROP:
            errors.append(f"{gone} of {len(held)} published cases are gone "
                          f"({gone / len(held):.0%})")
    return errors


def tier2(new, old, today=None):
    """Things worth a human glance. Returns [(heading, [lines])]."""
    sections = []
    meta = new.get("metadata") or {}
    cases = new.get("cases") or []
    today = today or datetime.date.today()

    terms = [t for t in meta.get("terms") or [] if str(t).isdigit()]
    if terms and today >= datetime.date(today.year, 10, 1) and max(map(int, terms)) < today.year:
        sections.append(("TERMS is missing the current term", [
            f"- The {today.year} term began October 1 but metadata.terms stops at "
            f"{max(map(int, terms))}, so its decisions are not being collected. "
            f"Add \"{today.year}\" to TERMS in scripts/generate_scotus_decisions.py."]))

    failed = [k for k in meta.get("detailFetchFailed") or []
              if not old or k not in {key(c) for c in old.get("cases") or []}]
    if failed:
        sections.append(("Detail fetch failed (no prior record to lose)",
                         [f"- {k}" for k in sorted(failed)]))

    if old:
        old_by = {key(c): c for c in old.get("cases") or []}
        new_by = {key(c): c for c in cases}
        added = sorted(set(new_by) - set(old_by), key=lambda k: new_by[k].get("decidedDate") or "",
                       reverse=True)
        known_fail = set(meta.get("detailFetchFailed") or [])
        removed = sorted(k for k in set(old_by) - set(new_by)
                         if k not in known_fail
                         and old_by[k].get("term") in (meta.get("terms") or []))
        if added:
            sections.append((f"{len(added)} new decision(s)", [
                f"- {new_by[k].get('name')} ({k}), decided {new_by[k].get('decidedDate')}"
                for k in added[:15]] + (["- ..."] if len(added) > 15 else [])))
        if removed:
            sections.append(("Cases removed with no recorded fetch failure", [
                f"- {old_by[k].get('name')} ({k})" for k in removed]))
    return sections


def render(path, sections):
    out = [f"## SCOTUS decisions: what changed in `{os.path.basename(path)}`", ""]
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
                    help="report lost cases instead of failing on them. For a human "
                         "who has inspected the rejected file — never the default.")
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
        print("\nThis is a generator bug, not a change in the Court. The rejected "
              "file is uploaded as a workflow artifact.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['cases'])} cases across terms "
          f"{new['metadata'].get('terms')}.")

    old = baseline(args.path, args.baseline_ref)
    lost = collapse(new, old)
    if lost:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nLOSS CHECK: the file is self-consistent but is missing rulings "
              "the committed one has:", file=stream)
        for e in lost:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. The weekly run will retry; check the log "
                  "for Oyez fetch failures first. The rejected file is uploaded as "
                  "a workflow artifact.", file=stream)
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
