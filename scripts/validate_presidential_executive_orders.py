#!/usr/bin/env python3
"""Validate presidential-executive-orders.json: gate on self-consistency, report on change.

Same two-tier split as validate_fec_data.py (read its header for the reasoning):

  Tier 1 - the file contradicts itself. A malformed EO number, a signing date
  outside the term or in the future, a duplicate document number, a provisional
  entry that carries a number (or a published one that lacks it), counts that do
  not match what they count, a collapse to zero. No fact about the world makes
  any of these true, so they mean the generator broke. These exit 1.

  Tier 2 - the file differs from the committed one. New orders, a provisional
  entry that gained its number, an abstract the Register revised, fewer
  published orders than before, the White House feed being down, and every
  provisional entry that EXPIRED unmatched. All of these are things upstream can
  legitimately do, so they are reported and never gate the commit.

Deliberately NOT a failure: the White House announcing more orders than the
Federal Register has published. That is the normal 3-5 day lag and is exactly
what provisional entries exist to show.

An expiry is the one tier-2 line worth acting on. It means a title was reworded
between whitehouse.gov and the Register (or the Register never published), so
the provisional entry could not be matched - and the join is the fragile part of
this pipeline.

Usage:
    python scripts/validate_presidential_executive_orders.py \
        assets/data/presidential-executive-orders.json --baseline-ref HEAD --report-out report.md

Exit codes: 0 self-consistent (a report may still have been written); 1 tier 1 failed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

EO_NUMBER = re.compile(r"^\d{4,6}$")


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


def _parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d, old, today=None):
    errors = []
    today = today or datetime.now(timezone.utc).date()
    meta = d.get("metadata") or {}
    orders = d.get("orders") or []

    if not orders:
        previous = len((old or {}).get("orders") or [])
        errors.append("no orders in the file" +
                      (f" (the committed file has {previous})" if previous else ""))
        return errors

    term_start = _parse_date(meta.get("termStart"))
    if term_start is None:
        errors.append(f"metadata.termStart {meta.get('termStart')!r} is not an ISO date")

    seen_docs, seen_nums = {}, {}
    for i, o in enumerate(orders):
        label = f"orders[{i}] ({(o.get('title') or '?')[:40]})"
        num, doc_no = o.get("executive_order_number"), o.get("document_number")
        if o.get("provisional"):
            if num is not None or doc_no is not None:
                errors.append(f"{label}: provisional entry carries a number "
                              f"({num!r} / {doc_no!r}) - whitehouse.gov cannot supply one")
        else:
            if num is None or not EO_NUMBER.match(str(num)):
                errors.append(f"{label}: malformed executive_order_number {num!r}")
            if not doc_no:
                errors.append(f"{label}: published order has no document_number")
        if not o.get("title"):
            errors.append(f"{label}: no title")
        if not o.get("html_url"):
            errors.append(f"{label}: no html_url")

        signed = _parse_date(o.get("signing_date"))
        if signed is None:
            errors.append(f"{label}: signing_date {o.get('signing_date')!r} is not an ISO date")
        else:
            if term_start and signed < term_start:
                errors.append(f"{label}: signed {signed}, before the term start {term_start}")
            if signed > today + timedelta(days=1):
                errors.append(f"{label}: signed {signed}, in the future")

        for value, seen, kind in ((doc_no, seen_docs, "document_number"),
                                  (num, seen_nums, "executive_order_number")):
            if value:
                if value in seen:
                    errors.append(f"duplicate {kind} {value}: orders[{seen[value]}] and orders[{i}]")
                seen[value] = i

    prov = sum(1 for o in orders if o.get("provisional"))
    for key, want in (("count", len(orders)), ("provisionalCount", prov),
                      ("federalRegisterCount", len(orders) - prov)):
        if meta.get(key) != want:
            errors.append(f"metadata.{key} ({meta.get(key)}) != {want}")
    return errors


# ── tier 2: the file against the committed one ─────────────────────────────────

def _age(e):
    signed = _parse_date(e.get("signing_date"))
    return (datetime.now(timezone.utc).date() - signed).days if signed else "?"


def _label(o):
    num = o.get("executive_order_number")
    return f"**{o.get('title', '?')}** ({'EO ' + str(num) if num else 'pending'}, signed {o.get('signing_date')})"


def tier2(new, old):
    sections = []
    meta = new.get("metadata") or {}

    expired = meta.get("expiredProvisional") or []
    if expired:
        sections.append((
            "Provisional entries expired unmatched - title matching broke, or the Register never published",
            [f"- **{e['title']}** signed {e['signing_date']} ({_age(e)} days): "
             f"[whitehouse.gov]({e['whitehouse_url']}). Compare its title with the Register's record of "
             f"that date; a reworded title is the usual cause." for e in expired]))

    dupes = meta.get("duplicateRegisterRecords") or []
    if dupes:
        sections.append(("Duplicate Federal Register records collapsed",
                         [f"- `{d_}` (a reprint of an order already listed; the original is kept)" for d_ in dupes]))

    if meta.get("whitehouseFeed") == "unavailable":
        sections.append(("whitehouse.gov feed unavailable",
                         ["- Provisional entries were carried forward from the previous file; "
                          "no new unpublished orders could be detected this run."]))

    if not old:
        return sections
    new_orders, old_orders = new.get("orders") or [], old.get("orders") or []
    by_doc_new = {o["document_number"]: o for o in new_orders if o.get("document_number")}
    by_doc_old = {o["document_number"]: o for o in old_orders if o.get("document_number")}

    added = [o for d_, o in by_doc_new.items() if d_ not in by_doc_old]
    if added:
        sections.append(("New Federal Register orders", [f"- {_label(o)}" for o in added]))

    dropped = [o for d_, o in by_doc_old.items() if d_ not in by_doc_new]
    if dropped:
        sections.append(("Orders no longer in the Federal Register response - check these",
                         [f"- {_label(o)}" for o in dropped]))

    old_prov = {(o["title"], o["signing_date"]) for o in old_orders if o.get("provisional")}
    new_prov = {(o["title"], o["signing_date"]): o for o in new_orders if o.get("provisional")}
    announced = [o for k, o in new_prov.items() if k not in old_prov]
    if announced:
        sections.append(("Newly announced on whitehouse.gov (awaiting the Register)",
                         [f"- {_label(o)}" for o in announced]))

    # A provisional entry from the committed file that is now a numbered order.
    titles_now = {o["title"].lower(): o for o in new_orders if not o.get("provisional")}
    resolved = [f"- {_label(titles_now[t.lower()])}"
                for t, _ in sorted(old_prov) if t.lower() in titles_now]
    if resolved:
        sections.append(("Provisional entries now published with a number", resolved))

    revised = [f"- {_label(o)}" for d_, o in by_doc_new.items()
               if d_ in by_doc_old and (by_doc_old[d_].get("abstract") or None) != (o.get("abstract") or None)]
    if revised:
        sections.append(("Abstract changed", revised))

    o_fr, n_fr = old["metadata"].get("federalRegisterCount") if old.get("metadata") else None, meta.get("federalRegisterCount")
    if o_fr is not None and n_fr is not None and o_fr != n_fr:
        sections.append(("Published order count moved", [f"- {o_fr} -> {n_fr}"]))
    return sections


def render(path, sections):
    out = [f"## Executive orders: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("None of these blocked the update - the data is committed. They are here "
                   "because they change what a reader sees, or because a provisional entry "
                   "failed to match.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--baseline-ref", default="HEAD")
    ap.add_argument("--report-out")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"FAIL: {args.path} was not generated", file=sys.stderr)
        return 1
    try:
        new = load(args.path)
    except json.JSONDecodeError as exc:
        print(f"FAIL: {args.path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    old = baseline(args.path, args.baseline_ref)
    errors = tier1(new, old)
    if errors:
        print("TIER 1 FAILED - the file contradicts itself, refusing to commit:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in the data.", file=sys.stderr)
        return 1
    m = new["metadata"]
    print(f"Tier 1 passed: {m['count']} orders ({m['federalRegisterCount']} published, "
          f"{m['provisionalCount']} provisional).")

    sections = tier2(new, old)
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} item(s) - reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
