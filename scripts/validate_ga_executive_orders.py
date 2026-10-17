#!/usr/bin/env python3
"""Validate ga-executive-orders-{year}.json: gate on self-consistency, report on change.

Same two-tier split as validate_fec_data.py (read its header for the reasoning).
It replaces an inline heredoc in update-ga-executive-orders.yml whose gates were
facts the world controls, not contradictions in the file:

  * `if not orders: sys.exit(...)` -- the file is PER CALENDAR YEAR. On 1 January
    the new year's file legitimately holds nothing until the Governor signs the
    year's first order, so this gate failed every one of the twice-daily runs
    until then. A dated time bomb.
  * `len(orders) < prev_n` -- a comparison against LAST RUN'S file, not the file
    against itself. The fetch merges additively so a drop is suspicious, but a
    withdrawn or renumbered order is the Governor's office's business, and the
    gate threw away the whole run (every new order and every enriched hash with
    it) rather than saying which order went missing.

Each time one fired it aborted the job before the commit step and the data died
with the runner. See docs/audits/2026-10-13-data-pipeline-audit.md 2.6.

  Tier 1 - the file contradicts itself. A metadata.count that does not match the
  orders, a missing number/title, a malformed or duplicate order number, a date
  that disagrees with the date encoded in the number, an order from another year
  than the file it sits in, a hash that is not a hash. No fact about Georgia makes
  any of these true, so they mean a producer broke. These exit 1.

  Tier 2 - the file differs from the committed one, or is in a state the calendar
  explains. New orders (named, with dates), a writ of election (the orders that
  corroborate every legislative vacancy date), an order that disappeared or was
  renumbered, a retitled order, an empty year file, orders still waiting on their
  PDF hash. All of these are things the Governor's office or the calendar can do,
  so they are reported and never gate the commit.

Usage:
    python scripts/validate_ga_executive_orders.py \
        assets/data/ga-executive-orders-2026.json --baseline-ref HEAD --report-out report.md

Exit codes: 0 self-consistent (a report may still have been written); 1 tier 1 failed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

NUMBER = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})\.\d{2,}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FILE_YEAR = re.compile(r"ga-executive-orders-(\d{4})\.json$")

# An empty file is the EXPECTED state only early in the year. By March the
# Governor has signed orders (2020-2026 all start in the first weeks), so an
# empty current-year file then is worth a human's look.
JANUARY_GRACE_MONTHS = 2

# Sections that are routine -- reported in the run summary but not worth a
# tracking-issue notification on their own.
INFORMATIONAL = ("New executive orders", "Year file is empty", "Orders awaiting their PDF hash")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, text=True, encoding="utf-8",
                              check=True).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def file_year(path):
    m = FILE_YEAR.search(path or "")
    return int(m.group(1)) if m else None


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d, year=None):
    """`year` is the calendar year the file's NAME claims; None skips that check."""
    errors = []
    meta = d.get("metadata")
    orders = d.get("orders")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(orders, list):
        return ["orders is missing or not a list"]

    if meta.get("count") != len(orders):
        errors.append(f"metadata.count ({meta.get('count')!r}) != {len(orders)} orders")

    meta_year = meta.get("year")
    if not isinstance(meta_year, int):
        errors.append(f"metadata.year {meta_year!r} is not an integer")
    elif year is not None and meta_year != year:
        errors.append(f"metadata.year {meta_year} disagrees with the file name's year {year}")
    want_year = year if year is not None else (meta_year if isinstance(meta_year, int) else None)

    # updatedAt is stamped by every save of a non-empty year, so an empty file
    # (a January seed) is not required to carry one.
    if orders and _parse_date(meta.get("updatedAt")) is None:
        errors.append(f"metadata.updatedAt {meta.get('updatedAt')!r} is not an ISO date")

    seen = {}
    for i, o in enumerate(orders):
        num = o.get("number")
        label = f"orders[{i}] ({num or (o.get('title') or '?')[:40]})"
        if not num:
            errors.append(f"{label}: no number")
        if not o.get("title"):
            errors.append(f"{label}: no title")
        if not o.get("url"):
            errors.append(f"{label}: no url")
        if not o.get("category"):
            errors.append(f"{label}: no category")

        m = NUMBER.match(num) if isinstance(num, str) else None
        if num and not m:
            errors.append(f"{label}: malformed number {num!r} (want MM.DD.YY.NN)")
        if num:
            if num in seen:
                errors.append(f"duplicate number {num}: orders[{seen[num]}] and orders[{i}]")
            seen[num] = i

        signed = _parse_date(o.get("date"))
        if signed is None:
            errors.append(f"{label}: date {o.get('date')!r} is not an ISO date")
        else:
            if m and (f"{signed.month:02d}", f"{signed.day:02d}", f"{signed.year % 100:02d}") != m.groups():
                errors.append(f"{label}: date {signed} disagrees with the date encoded in its number")
            if want_year is not None and signed.year != want_year:
                errors.append(f"{label}: dated {signed}, but this is the {want_year} file")

        # Enrichment is best-effort and an order may legitimately lack all of it
        # (tier 2). What cannot be true is a PARTIAL or malformed record: the
        # enricher writes sha256/bytes/fetchedAt together and carry-forward keeps
        # them together.
        sha = o.get("sha256")
        if sha is not None:
            if not isinstance(sha, str) or not SHA256.match(sha):
                errors.append(f"{label}: sha256 {sha!r} is not a SHA-256 hex digest")
            b = o.get("bytes")
            if not isinstance(b, int) or isinstance(b, bool) or b <= 0:
                errors.append(f"{label}: has a sha256 but bytes is {b!r}")
            if not o.get("fetchedAt"):
                errors.append(f"{label}: has a sha256 but no fetchedAt")
    return errors


# ── tier 2: the file against the committed one, and against the calendar ───────

def _label(o):
    return f"**{o.get('number')}** ({o.get('date')}, {o.get('category')}): {o.get('title')}"


def tier2(new, old, today=None, year=None):
    sections = []
    today = today or datetime.now(timezone.utc).date()
    new_orders = new.get("orders") or []
    old_orders = (old or {}).get("orders") or []

    if not new_orders:
        yr = year or (new.get("metadata") or {}).get("year") or today.year
        if yr > today.year or (yr == today.year and today.month <= JANUARY_GRACE_MONTHS):
            sections.append((
                "Year file is empty",
                [f"- The {yr} file holds no orders. **Expected**: a new calendar year has none until the "
                 "Governor signs the first. Nothing to do; this clears itself on the first order."]))
        else:
            sections.append((
                "Year file is unexpectedly empty",
                [f"- The {yr} file holds no orders, which is **not** expected this late in the year "
                 "(every year since 2020 has orders by mid-January). Check that the listing page at "
                 "gov.georgia.gov still parses."]))

    by_new = {o["number"]: o for o in new_orders if o.get("number")}
    by_old = {o["number"]: o for o in old_orders if o.get("number")}

    added = [o for n, o in by_new.items() if n not in by_old]
    if added and old is not None:
        added.sort(key=lambda o: o["number"])
        sections.append(("New executive orders", [f"- {_label(o)}" for o in added]))
        writs = [o for o in added if o.get("category") == "Writ of Election"]
        if writs:
            sections.append((
                "Writ of election - a legislative vacancy date to corroborate",
                [f"- {_label(o)}: the Governor's writ is the authority for a seat's vacancy date; "
                 "check it against ga-members-overrides.json." for o in writs]))

    dropped = [o for n, o in by_old.items() if n not in by_new]
    if dropped:
        titles_now = {(o.get("title") or "").strip().lower(): o for o in new_orders}
        lines = []
        for o in sorted(dropped, key=lambda o: o["number"]):
            twin = titles_now.get((o.get("title") or "").strip().lower())
            hint = f" -- same title now listed as **{twin['number']}** (renumbered?)" if twin else ""
            lines.append(f"- {_label(o)}{hint}")
        sections.append((
            f"Orders no longer listed ({len(old_orders)} -> {len(new_orders)} total) - check these",
            lines + ["", "The fetch merges additively, so this is unusual: the Governor's office "
                         "withdrew or renumbered an order, or something wrote the file other than the fetch."]))

    changed = [(by_old[n], o) for n, o in by_new.items()
               if n in by_old and ((by_old[n].get("title") or "") != (o.get("title") or "")
                                   or (by_old[n].get("url") or "") != (o.get("url") or ""))]
    if changed:
        lines = []
        for was, now in changed:
            if was.get("title") != now.get("title"):
                lines.append(f"- **{now['number']}** retitled: \"{was.get('title')}\" -> \"{now.get('title')}\"")
            else:
                lines.append(f"- **{now['number']}** PDF link moved (it will be re-hashed): {now.get('url')}")
        sections.append(("Existing orders edited at the source", lines))

    unhashed = [o for o in new_orders if not o.get("sha256")]
    if unhashed:
        sections.append((
            "Orders awaiting their PDF hash",
            [f"- {_label(o)}" for o in unhashed[:10]]
            + ([f"- ... and {len(unhashed) - 10} more"] if len(unhashed) > 10 else [])
            + ["", "The enricher retries on the next run; these only matter if they persist."]))
    return sections


def render(path, sections):
    out = [f"## GA executive orders: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        heads = [h for h, _ in sections]
        routine = all(h.startswith(INFORMATIONAL) for h in heads)
        out.append("None of these blocked the update - the data is committed. They are here "
                   "because they change what a reader sees, or something upstream moved.")
        if routine:
            out.append("")
            out.append("No action needed: only routine items this run.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--baseline-ref", default="HEAD")
    ap.add_argument("--report-out")
    ap.add_argument("--today", help="ISO date to treat as today (testing the January state)")
    args = ap.parse_args()
    year = file_year(args.path)
    old = baseline(args.path, args.baseline_ref)

    if not os.path.exists(args.path):
        if old is not None:
            print(f"FAIL: {args.path} is committed but was not generated", file=sys.stderr)
            return 1
        # Never committed and not produced: a new calendar year before the first
        # order. The fetch only writes a file once it has an order to put in it.
        new = {"metadata": {"year": year}, "orders": []}
        errors = []
    else:
        try:
            new = load(args.path)
        except json.JSONDecodeError as exc:
            print(f"FAIL: {args.path} is not valid JSON: {exc}", file=sys.stderr)
            return 1
        errors = tier1(new, year)
    if errors:
        print("TIER 1 FAILED - the file contradicts itself, refusing to commit:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a producer bug, not a change in the data.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new.get('orders') or [])} orders in {os.path.basename(args.path)}.")

    sections = tier2(new, old, today=_parse_date(args.today), year=year)
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} line(s) - reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
