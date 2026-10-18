#!/usr/bin/env python3
"""Validate ga-campaign-finance-donors.json (per-candidate donor summaries from
PeachFile): gate on self-consistency, report on everything the world controls.

Sidecar to ga-campaign-finance.json; written by generate_ga_donor_summaries.py. The
page treats it as optional, so the question this answers is "is the file we are about
to commit well formed?" (tier 1) and "is the donor panel quietly falling behind the
headline totals?" (tier 2).

  Tier 1 — the file contradicts itself. A `metadata.count` that is not the number of
  filers, an entry missing a key the page reads (an absent KEY is a bug; None is a
  value), a wrong-typed field, a duplicate contributor category within one filer, a
  `largest` list longer than the cap the generator itself applies, a non-positive
  amount where the generator drops those. No fact about the Ethics Commission makes
  any of these true, so they mean the generator is broken and the file must not be
  committed.

  Tier 2 — coverage, staleness and change. Reported, never gated, data committed:
    * filers the generator could not fetch (`metadata.failedFilers`, named);
    * entries whose `raised` no longer equals the finance file's `totalRaised` — the
      sharpest evidence the donor panel is behind the headline totals, because both
      come from the same API in the same run;
    * filers with money but no entry at all;
    * entries for a filer the finance file no longer holds;
    * a cycle that differs from the finance file's;
    * filers that had an entry at the baseline and have none now.

What is deliberately NOT checked, and why:

  * An empty `filers` map is not tier 1. In the first weeks of a new cycle nobody has
    raised money, so an empty file is the calendar, not a bug (the same dated time
    bomb the other floors were removed for). It is reported instead.
  * `sum(byType) <= raised` is not asserted. Measured 2026-10-18: 6 of 558 filers
    exceed it (the API's itemized categories and the committee's cumulative total are
    different cuts), so it would fail real data. A report that fires every week on the
    same six is also noise people learn to ignore, so it is not reported either.
  * A floor on the number of filers. See above; the generator's own refusal to
    publish a mostly-failed pull is the sharp version of that condition.

Usage:
    python scripts/validate_ga_donor_summaries.py assets/data/ga-campaign-finance-donors.json \
        --finance assets/data/ga-campaign-finance.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  a tier-1 check failed — the caller must not commit

Standard library only: run-script-tests.yml installs no pip packages.
"""

import argparse
import json
import os
import subprocess
import sys

# The cap generate_ga_donor_summaries.py applies to `largest` (its TOP_N). Duplicated
# as a literal on purpose: importing the generator would pull its API client into a
# validator; scripts/test_ga_donor_summaries.py pins the two together.
LARGEST_CAP = 10

REQUIRED_FIELDS = ("raised", "largest", "byType", "inState", "outOfState", "unitemized")
NAMED_LIMIT = 10     # how many filer names a report line spells out


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


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ── tier 1: the file against itself ────────────────────────────────────────────

def entry_errors(fid, e):
    """Contradictions inside one filer's entry."""
    errs = []
    if not isinstance(e, dict):
        return [f"{fid}: entry is not an object"]
    for field in REQUIRED_FIELDS:
        if field not in e:
            errs.append(f"{fid}: missing {field}")
    if errs:
        return errs   # the type checks below would only repeat the same fact

    if not is_num(e["raised"]) or e["raised"] <= 0:
        errs.append(f"{fid}: raised must be a positive number (the generator writes "
                    f"no entry for a filer with no money), got {e['raised']!r}")

    largest = e["largest"]
    if not isinstance(largest, list):
        errs.append(f"{fid}: largest is not a list")
    else:
        if len(largest) > LARGEST_CAP:
            errs.append(f"{fid}: largest has {len(largest)} rows, over the cap of {LARGEST_CAP}")
        for row in largest:
            if not (isinstance(row, dict) and isinstance(row.get("name"), str)
                    and row["name"].strip() and is_num(row.get("amount")) and row["amount"] > 0):
                errs.append(f"{fid}: a largest row lacks a name or a positive amount: {row!r}")
                break

    by_type = e["byType"]
    if not isinstance(by_type, list):
        errs.append(f"{fid}: byType is not a list")
    else:
        codes = [t.get("code") if isinstance(t, dict) else None for t in by_type]
        if len(codes) != len(set(codes)):
            errs.append(f"{fid}: byType repeats a contributor category")
        for t in by_type:
            if not (isinstance(t, dict) and is_num(t.get("amount")) and t["amount"] > 0):
                errs.append(f"{fid}: a byType row lacks a positive amount: {t!r}")
                break

    for geo in ("inState", "outOfState", "unitemized"):
        v = e[geo]
        if v is not None and (not is_num(v) or v < 0):
            errs.append(f"{fid}: {geo} must be null or a non-negative number, got {v!r}")
    return errs


def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    filers = d.get("filers")
    meta = d.get("metadata")
    if not isinstance(filers, dict):
        return ["filers is missing or not an object"]
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]

    if meta.get("count") != len(filers):
        errors.append(f"metadata.count ({meta.get('count')}) != len(filers) ({len(filers)})")
    if not meta.get("generatedAt"):
        errors.append("metadata.generatedAt is missing")
    failed = meta.get("failedFilers")
    if not isinstance(failed, list):
        errors.append("metadata.failedFilers is missing or not a list")

    bad = []
    for fid, e in filers.items():
        bad += entry_errors(fid, e)
    errors += bad[:10]
    if len(bad) > 10:
        errors.append(f"...and {len(bad) - 10} more entry problem(s)")
    return errors


# ── tier 2: coverage, staleness and change ─────────────────────────────────────

def label(fid, finance_filers):
    """'Name (id)' when the finance file knows the filer, else the bare id."""
    name = ((finance_filers or {}).get(fid) or {}).get("filerName")
    return f"{name} ({fid})" if name else str(fid)


def named(fids, finance_filers):
    fids = sorted(fids, key=str)
    shown = ", ".join(label(f, finance_filers) for f in fids[:NAMED_LIMIT])
    more = f" and {len(fids) - NAMED_LIMIT} more" if len(fids) > NAMED_LIMIT else ""
    return shown + more


def tier2(new, old, finance=None):
    """Coverage facts and changes, as (heading, [lines]) sections.

    `finance` is the parsed ga-campaign-finance.json, or None when it is unavailable
    (the cross-file checks are then skipped rather than guessed at).
    """
    sections = []
    filers = new.get("filers") or {}
    meta = new.get("metadata") or {}
    fin_filers = (finance or {}).get("filers")

    if not filers:
        sections.append(("No donor entries", [
            "- The file holds no filers. That is expected early in a cycle, before "
            "anyone has raised money; otherwise check the generator log."]))

    failed = [f for f in (meta.get("failedFilers") or [])]
    if failed:
        kept = [f for f in failed if f in filers]
        sections.append(("Filers the generator could not fetch", [
            f"- {len(failed)} filer(s): {named(failed, fin_filers)}",
            f"- {len(kept)} of them keep last run's entry (so their panel may be stale); "
            f"the other {len(failed) - len(kept)} show no donor detail until a later run succeeds."]))

    if fin_filers is not None:
        stale = [fid for fid, e in filers.items()
                 if fid in fin_filers and fin_filers[fid].get("totalRaised") != e.get("raised")]
        if stale:
            sections.append(("Donor detail is behind the headline totals", [
                f"- {len(stale)} filer(s) whose donor `raised` no longer equals the finance "
                f"file's `totalRaised`: {named(stale, fin_filers)}",
                "- Both come from the same API in the same run, so a mismatch means the "
                "donor fetch failed or was skipped for these filers; their breakdowns "
                "describe an earlier total."]))

        uncovered = [fid for fid, f in fin_filers.items()
                     if (f.get("totalRaised") or 0) > 0 and fid not in filers]
        if uncovered:
            sections.append(("Filers with money but no donor detail", [
                f"- {len(uncovered)} filer(s): {named(uncovered, fin_filers)}"]))

        orphans = [fid for fid in filers if fid not in fin_filers]
        if orphans:
            sections.append(("Donor entries for a filer the finance file no longer holds", [
                f"- {len(orphans)}: {', '.join(sorted(orphans, key=str)[:NAMED_LIMIT])}",
                "- A committee terminating does this; the page never reads them."]))

        f_cycle = (finance.get("metadata") or {}).get("cycle")
        if f_cycle != meta.get("cycle"):
            sections.append(("Cycle differs from the finance file", [
                f"- donors: {meta.get('cycle')}, finance: {f_cycle}"]))

    if old:
        lost = [fid for fid in (old.get("filers") or {}) if fid not in filers]
        if lost:
            sections.append(("Filers that lost their donor entry since the baseline", [
                f"- {len(lost)}: {named(lost, fin_filers)}",
                "- A committee terminating or reporting no money does this. So does a "
                "broken run: if there are many, check the generator log first."]))
    return sections


def render(path, sections):
    out = [f"## GA donor summaries: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("The donor file is well formed and was committed. These lines say where "
                   "the donor panel on a candidate's or legislator's page may be behind "
                   "the headline totals, or missing.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--finance", help="ga-campaign-finance.json, for the cross-file checks")
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
    print(f"Tier 1 passed: {len(new['filers'])} filer entries, every one well formed.")

    finance = None
    if args.finance:
        try:
            finance = load(args.finance)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"(finance file unreadable, cross-file checks skipped: {exc})")

    sections = tier2(new, baseline(args.path, args.baseline_ref), finance)
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
