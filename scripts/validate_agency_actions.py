#!/usr/bin/env python3
"""Validate the Cabinet-department rules files: gate on self-consistency, report on change.

Same two-tier split as validate_fec_data.py and validate_presidential_executive_orders.py.

  Tier 1 - a file contradicts itself or the index: count != len(documents), a
  duplicate document number, a type that is neither Rule nor Proposed Rule, a
  publication date before the term or in the future, a slice whose department/slug
  disagrees with the index, an index entry with no file, or a department that held
  rules in the committed file and now holds none (a collapse, not a quiet week).
  These exit 1.

  Tier 2 - a department's file differs from the committed one: new rules, rules
  that vanished, a department going quiet. The Register can do all of these, so
  they are reported and never gate.

Usage:
    python scripts/validate_agency_actions.py assets/data --baseline-ref HEAD --report-out report.md
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

INDEX_NAME = "agency-actions-index.json"
SLICE_DIR = "agency-actions"
TYPES = {"Rule", "Proposed Rule"}
#: A department with at least this many rules last run and none now is a collapse.
COLLAPSE_FLOOR = 1
#: How far ahead a scheduled publication date may legitimately sit (a long weekend
#: plus a day of margin).
SCHEDULE_HORIZON_DAYS = 7


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path.replace(os.sep, '/')}"],
                              capture_output=True, text=True, check=True).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def tier1(index, slices, old_slices=None, today=None):
    """index: parsed index; slices: {department: parsed slice}; old_slices:
    {department: parsed committed slice or None}."""
    errors = []
    today = today or datetime.now(timezone.utc).date()
    old_slices = old_slices or {}
    deps = (index or {}).get("departments") or {}
    if not deps:
        return ["index lists no departments"]

    term_start = _date((index.get("metadata") or {}).get("termStart"))
    if term_start is None:
        errors.append("index.metadata.termStart is not an ISO date")

    for name, entry in deps.items():
        s = slices.get(name)
        if s is None:
            errors.append(f"{name}: index points at {entry.get('file')}, which is missing")
            continue
        meta, docs = s.get("metadata") or {}, s.get("documents")
        if not isinstance(docs, list):
            errors.append(f"{name}: no documents list")
            continue
        if meta.get("count") != len(docs):
            errors.append(f"{name}: metadata.count ({meta.get('count')}) != {len(docs)} documents")
        if entry.get("count") != len(docs):
            errors.append(f"{name}: index count ({entry.get('count')}) != {len(docs)} documents")
        if (meta.get("slug"), meta.get("agencyId")) != (entry.get("slug"), entry.get("agencyId")):
            errors.append(f"{name}: slice slug/agencyId disagree with the index")

        seen = set()
        for i, d in enumerate(docs):
            label = f"{name} documents[{i}] ({d.get('document_number')})"
            n = d.get("document_number")
            if not n:
                errors.append(f"{label}: no document_number")
            elif n in seen:
                errors.append(f"{name}: duplicate document_number {n}")
            seen.add(n)
            if d.get("type") not in TYPES:
                errors.append(f"{label}: type {d.get('type')!r} is not Rule or Proposed Rule")
            if not d.get("title") or not d.get("html_url"):
                errors.append(f"{label}: missing title or html_url")
            p = _date(d.get("publication_date"))
            if p is None:
                errors.append(f"{label}: publication_date {d.get('publication_date')!r} is not an ISO date")
            else:
                if term_start and p < term_start:
                    errors.append(f"{label}: published {p}, before the term start {term_start}")
                # The Register lists documents on public inspection under their
                # SCHEDULED date (next business day, so a weekend run sees Monday).
                # That is true data, not a contradiction; only a date further out
                # than any schedule is a corrupt one.
                if p > today + timedelta(days=SCHEDULE_HORIZON_DAYS):
                    errors.append(f"{label}: published {p}, more than {SCHEDULE_HORIZON_DAYS} days ahead")

        old = old_slices.get(name)
        if old and len(old.get("documents") or []) >= COLLAPSE_FLOOR and not docs:
            errors.append(f"{name}: holds no rules but the committed file has "
                          f"{len(old['documents'])} - a collapse, not a quiet week")
    return errors


def tier2(index, slices, old_slices):
    sections = []
    moved, new_lines, vanished = [], [], []
    for name in sorted(slices):
        docs = {d["document_number"]: d for d in slices[name]["documents"] if d.get("document_number")}
        old = old_slices.get(name)
        if not old:
            new_lines.append(f"- **{name}**: new file, {len(docs)} rules")
            continue
        old_docs = {d["document_number"]: d for d in old.get("documents") or [] if d.get("document_number")}
        added = [d for k, d in docs.items() if k not in old_docs]
        gone = [d for k, d in old_docs.items() if k not in docs]
        if added:
            new_lines.append(f"- **{name}**: {len(added)} new (now {len(docs)}), e.g. "
                             f"[{added[0]['title'][:70]}]({added[0]['html_url']})")
        if gone:
            vanished.append(f"- **{name}**: {len(gone)} no longer returned by the Register, e.g. "
                            f"{gone[0].get('title', '?')[:70]} ({gone[0].get('document_number')})")
    if new_lines:
        sections.append(("New or added rules", new_lines))
    if vanished:
        sections.append(("Rules no longer returned - check these", vanished))
    return sections


def render(sections):
    out = ["## Agency rules: what changed", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("None of these blocked the update - the data is committed.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--baseline-ref", default="HEAD")
    ap.add_argument("--report-out")
    args = ap.parse_args()

    index_path = os.path.join(args.data_dir, INDEX_NAME)
    if not os.path.exists(index_path):
        print(f"FAIL: {index_path} was not generated", file=sys.stderr)
        return 1
    try:
        index = load(index_path)
        slices, old_slices = {}, {}
        for name, entry in (index.get("departments") or {}).items():
            path = os.path.join(args.data_dir, entry.get("file", ""))
            if os.path.exists(path):
                slices[name] = load(path)
            old_slices[name] = baseline(path, args.baseline_ref)
    except json.JSONDecodeError as exc:
        print(f"FAIL: not valid JSON: {exc}", file=sys.stderr)
        return 1

    errors = tier1(index, slices, old_slices)
    if errors:
        print("TIER 1 FAILED - the files contradict themselves, refusing to commit:\n", file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  ... and {len(errors) - 40} more", file=sys.stderr)
        return 1
    total = sum(len(s["documents"]) for s in slices.values())
    print(f"Tier 1 passed: {len(slices)} departments, {total} rules.")

    sections = tier2(index, slices, old_slices)
    report = render(sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
