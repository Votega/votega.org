#!/usr/bin/env python3
"""Validate presidential-laws.json: gate on self-consistency and lost laws.

This replaces `validate_data_update.py --metric laws/records --scope-key
metadata.congress` (default 20% shrink-vs-HEAD) in update-presidential-laws.yml.

As with vp-tie-votes there was no absolute floor and the --scope-key handled the
Congress rollover (a new Congress starts with no laws), so nothing here was the
world's number. What was wrong is the percentage. The file is rebuilt whole from
Congress.gov's paginated /law/{congress}, and `fetch_all_laws` ends on the first
page that returns nothing, so a failed later page silently truncates the list to
whatever came before. Pages are 250 laws: a failure on page two truncates 300
laws to 250 (-17%, passes the 20% gate) and 370 to 250 (-32%, fails it), so the
gate caught the failure only for some sizes of the truth.

  Tier 1 -- the file contradicts itself. metadata.count vs the laws it counts,
  a law signed before metadata.termStart (the generator filters those out), the
  same type/number twice, a record missing a field the page renders, a
  congressUrl for a different Congress than metadata.congress, a GovInfo record
  with a package id but none of the links built from it, laws not newest-first.
  Exit 1.

  Loss -- the one deliberate baseline gate, as in the other migrated validators.
  A signed law is immutable and the file is rebuilt whole, so within one Congress
  the set of (type, number) only grows: one at HEAD that is gone now refuses the
  commit. A set difference, so it fires on the first lost law and is blind to
  how many pages the truth spans. A new Congress is exempt (it starts empty).

  Tier 2 -- reported, never gated: GovInfo provenance regressions (laws enriched
  at HEAD that are not now: the enrichment is best-effort, rate-limited on
  DEMO_KEY, and the generator rewrites the file fresh, so a bad week quietly
  strips it) and the share of laws enriched.

Usage:
    python scripts/validate_presidential_laws.py assets/data/presidential-laws.json \
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

REQUIRED = ("billLabel", "type", "number", "title", "signingDate", "congressUrl")


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


def key(law):
    return f"{law.get('type')}-{law.get('number')}"


def tier1(d):
    """Contradictions inside the file. Returns a list of strings."""
    meta, laws = d.get("metadata"), d.get("laws")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(laws, list):
        return ["laws is missing or not a list"]
    errors = []
    if meta.get("count") != len(laws):
        errors.append(f"metadata.count is {meta.get('count')!r} but the file holds "
                      f"{len(laws)} laws")
    term, congress = meta.get("termStart") or "", meta.get("congress")
    seen, dupes, gappy, early, wrong_cong, half = set(), set(), [], [], [], []
    for i, law in enumerate(laws):
        if not isinstance(law, dict):
            errors.append(f"laws[{i}] is not an object")
            continue
        gaps = [f for f in REQUIRED if not law.get(f)]
        if gaps:
            gappy.append(f"laws[{i}] ({law.get('billLabel')!r}) lacks {', '.join(gaps)}")
        if key(law) in seen:
            dupes.add(key(law))
        seen.add(key(law))
        if term and (law.get("signingDate") or "") < term:
            early.append(key(law))
        if congress and f"/{congress}th-congress/" not in (law.get("congressUrl") or ""):
            wrong_cong.append(key(law))
        if law.get("govinfoPackageId") and not (law.get("officialTextUrl")
                                                and law.get("officialPdfUrl")):
            half.append(key(law))
    if gappy:
        errors.append(f"{len(gappy)} law(s) missing a required field, e.g. {gappy[0]}")
    if dupes:
        errors.append(f"duplicate law(s): {sorted(dupes)[:5]}")
    if early:
        errors.append(f"{len(early)} law(s) signed before termStart {term}: {early[:3]}")
    if wrong_cong:
        errors.append(f"{len(wrong_cong)} law(s) whose congressUrl is not the "
                      f"{congress}th Congress: {wrong_cong[:3]}")
    if half:
        errors.append(f"{len(half)} law(s) carry a govinfoPackageId without the links "
                      f"built from it: {half[:3]}")
    dates = [law.get("signingDate") or "" for law in laws if isinstance(law, dict)]
    if dates != sorted(dates, reverse=True):
        errors.append("laws are not newest-first (the generator sorts them)")
    return errors


def collapse(new, old):
    """A self-consistent file that has lost laws the committed one holds."""
    if not old:
        return []
    if (new.get("metadata") or {}).get("congress") != (old.get("metadata") or {}).get("congress"):
        return []          # a new Congress legitimately starts empty
    gone = sorted(set(map(key, old.get("laws") or [])) - set(map(key, new.get("laws") or [])))
    if not gone:
        return []
    return [f"{len(gone)} signed law(s) at HEAD are missing now: {', '.join(gone[:5])} "
            "-- signed laws are immutable, so a Congress.gov page failed mid-pagination "
            "and truncated the list"]


def tier2(new, old):
    """Things worth a human glance. Returns [(heading, [lines])]."""
    sections = []
    laws = new.get("laws") or []
    if old and (new.get("metadata") or {}).get("congress") == (old.get("metadata") or {}).get("congress"):
        was = {key(x) for x in old.get("laws") or [] if x.get("govinfoPackageId")}
        stripped = sorted(key(x) for x in laws if key(x) in was and not x.get("govinfoPackageId"))
        if stripped:
            sections.append(("GovInfo provenance lost", [
                f"- {k}" for k in stripped[:15]] + (["- ..."] if len(stripped) > 15 else []) + [
                "", "These were enriched at HEAD and are not now. The enrichment is "
                "best-effort (DEMO_KEY rate-limits after ~30 calls) and the file is "
                "regenerated fresh each run, so check GOVINFO_API_KEY first."]))
    return sections


def render(path, sections):
    out = [f"## Presidential laws: what changed in `{os.path.basename(path)}`", ""]
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
                    help="report lost laws instead of failing on them. For a human who "
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
        print("\nThis is a generator bug, not a quiet Congress. The rejected file is "
              "uploaded as a workflow artifact.", file=sys.stderr)
        return 1
    n = len(new["laws"])
    enriched = sum(1 for x in new["laws"] if x.get("govinfoPackageId"))
    print(f"Tier 1 passed: {n} laws ({enriched} with GovInfo provenance), "
          f"{new['metadata'].get('congress')}th Congress.")

    old = baseline(args.path, args.baseline_ref)
    lost = collapse(new, old)
    if lost:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nLOSS CHECK: the file is self-consistent but is missing laws the "
              "committed one has:", file=stream)
        for e in lost:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. The weekly run will retry; check the log "
                  "for Congress.gov page failures first. The rejected file is "
                  "uploaded as a workflow artifact.", file=stream)
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
