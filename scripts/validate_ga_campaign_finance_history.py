#!/usr/bin/env python3
"""Validate ga-campaign-finance-history.json (Georgia LEGACY records): gate on
self-consistency, report on change.

This is the pre-2026 archive from the Ethics Commission's legacy system. It is a
different id space from PeachFile (validate_ga_campaign_finance.py's file): the
numeric ranges overlap while naming different entities, so a record that is not
tagged `source: legacy` is a join hazard, not a curiosity.

  Tier 1 — the file contradicts itself. A `metadata.count` that is not the number
  of records, a record missing a field the pages read, a record not tagged
  `source: legacy`, a key that is not the record's own `<filerEntityId>:
  <electionCycleId>`, an index naming a record the file lacks, no composite keys
  at all. No fact about the Commission can make any of these true.

  Tier 2 — the file disagrees with the last one. A cycle year with fewer records
  than before, an office that thinned, a year that vanished. This archive is
  frozen, so a change is rare — but the Commission can backfill, correct or
  withdraw a record, and each is a fact the site should publish. REPORTED, never
  gated.

What the inline heredoc this replaces gated on, and why that discarded good data:

  len(filers) < 1200 and min(cycleYears) > 2020 — floors on what the source
  returns. The first is "~1,500 records expected", a number about one week of the
  Commission's database (today 1,545); a legitimate cleanup that removed 350
  records would abort the quarterly run and lose the whole pull, and the job runs
  four times a year so the next chance is three months out. The second assumes
  the archive reaches back past 2020. Both were groping at one real failure — an
  office that "silently returned nothing rather than erroring" — which a global
  count cannot localise: losing the 151 Senate records of 2022 moves 1,545 to
  1,394, comfortably above the floor. The replacement compares per cycle year and
  per office against the committed file and NAMES what shrank.

  What stays tier 1 is exactly what the heredoc got right: count agreement,
  required fields, composite keys, and `source == 'legacy'`. The old checks looked
  at ONE sample record; these look at all of them, because a bad record in the
  middle is as real as one at the front.

Two generator gates are deliberately left alone, and why. generate_ga_campaign_
finance_history.py exits 1 on `not filers`, and on `short_reads`: an office
whose row count differs from the API's own `totalItems`. That second one IS the
precise condition the floor was approximating — the generator knows, per office,
that a page failed — so it stays. It costs nothing to keep: a truncated archive
is not worth committing over a complete one, and the source is frozen, so a
re-run produces the same file.

What this CANNOT see: byCycleYear and byOffice are tallied from records, so a
year or office with no records has no key. Nothing absolute can iterate over what
is missing, so tier 2 takes the union of the two files' keys and reads absences
from the baseline.

Usage:
    python scripts/validate_ga_campaign_finance_history.py \
        assets/data/ga-campaign-finance-history.json \
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

REQUIRED_FIELDS = ("filerEntityId", "office", "totalRaised", "cycleYear", "source")


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


def expected_key(rec):
    cid = rec.get("electionCycleId")
    fid = rec.get("filerEntityId")
    return f"{fid}:{cid}" if cid is not None else fid


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    filers = d.get("filers") or {}
    meta = d.get("metadata") or {}

    if not filers:
        errors.append("no records in the file")
        return errors   # nothing below can say anything useful

    if meta.get("count") != len(filers):
        errors.append(f"metadata.count ({meta.get('count')}) != len(filers) ({len(filers)})")

    # Every record, not a sample: a bad row in the middle is as real as one at the front.
    missing = {}
    for k, f in filers.items():
        gone = [field for field in REQUIRED_FIELDS if field not in f]
        if gone:
            missing[k] = gone
    if missing:
        first = {k: missing[k] for k in sorted(missing)[:3]}
        errors.append(f"{len(missing)} record(s) missing required fields, e.g. {first}")

    # These ids share a numeric range with PeachFile's but are a different id space
    # entirely; an untagged record could be joined to the wrong entity.
    untagged = [k for k, f in filers.items() if f.get("source") != "legacy"]
    if untagged:
        errors.append(f"{len(untagged)} record(s) not tagged source=legacy "
                      f"(e.g. {sorted(untagged)[:3]}) — the legacy and PeachFile id "
                      f"spaces overlap, so these could join to the wrong entity")

    # Composite keys. If keying ever collapses to a bare filer id, per-cycle rows
    # overwrite each other and roughly a quarter of the dataset disappears.
    if not any(":" in k for k in filers):
        errors.append("no composite recordId keys — per-cycle rows are being lost")
    wrong = [k for k, f in filers.items() if k != expected_key(f)]
    if wrong:
        errors.append(f"{len(wrong)} record(s) keyed other than "
                      f"<filerEntityId>:<electionCycleId>, e.g. {sorted(wrong)[:3]}")

    for index_name in ("bySeat", "byOffice", "byCycleYear", "byNormalizedName"):
        for key, ids in (d.get(index_name) or {}).items():
            for rid in ids:
                if rid not in filers:
                    errors.append(f"{index_name}[{key}] names {rid}, which is not in filers")
                    break

    years = {str(y) for y in meta.get("cycleYears") or []}
    if years != set((d.get("byCycleYear") or {}).keys()):
        errors.append("metadata.cycleYears disagrees with the keys of byCycleYear")

    return errors


# ── tier 2: the file against the committed one ─────────────────────────────────

def counts(d, field):
    out = {}
    for f in (d.get("filers") or {}).values():
        v = f.get(field)
        out[v] = out.get(v, 0) + 1
    return out


def tier2(new, old):
    """Material changes between two versions, as (heading, [lines]) sections."""
    if not old:
        return []
    sections = []

    for field, label, order in (("cycleYear", "Cycle year", lambda k: (k is None, k or 0)),
                                ("office", "Office", lambda k: str(k))):
        nc, oc = counts(new, field), counts(old, field)
        fell, rose = [], []
        for k in sorted(set(nc) | set(oc), key=order):
            was, now = oc.get(k, 0), nc.get(k, 0)
            shown = "no year" if k is None else k
            if now < was:
                fell.append(f"- **{shown}**: {was} → {now} record(s)"
                            + (" — gone entirely" if now == 0 else ""))
            elif now > was:
                rose.append(f"- **{shown}**: {was} → {now} record(s)")
        if fell:
            sections.append((f"{label}s that lost records — check these first", fell))
        if rose:
            sections.append((f"{label}s that gained records", rose))

    # A record identity that disappeared while the counts balance (one withdrawn,
    # one added in the same year/office) would otherwise be invisible.
    nk, ok = set(new.get("filers") or {}), set(old.get("filers") or {})
    if nk != ok and not sections:
        gone, came = sorted(ok - nk), sorted(nk - ok)
        sections.append(("Records swapped", [
            f"- {len(gone)} removed (e.g. `{gone[0]}`), {len(came)} added (e.g. `{came[0]}`)"]))
    return sections


def render(path, sections):
    out = [f"## GA campaign finance history: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("This archive is frozen, so any change here is the Ethics Commission "
                   "backfilling, correcting or withdrawing a record. None of it blocked "
                   "the update — the data is committed. It is here because it changes "
                   "the per-cycle figures a reader sees.")
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
    years = sorted(int(y) for y in new["metadata"].get("cycleYears") or [])
    span = f"{years[0]}-{years[-1]}" if years else "none"
    print(f"Tier 1 passed: {len(new['filers'])} records, composite keys, all tagged "
          f"legacy, cycle years {span}.")

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
