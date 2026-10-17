#!/usr/bin/env python3
"""Validate search-entities.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of an index build, and conflating them is how a
validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A metadata.count that disagrees with the
  records it counts, per-category counts that do not add up to it or do not match
  the records carrying that category, a record the search box cannot render
  (the client reads title, category and url), the same (title, url) twice. No
  fact about Georgia can make any of these true, so they mean the generator is
  broken and the file must not be committed. These exit 1.

  Tier 2 — the file disagrees with yesterday's. A category that is empty, that
  vanished, that appeared, or that moved sharply. Every one of those is
  something the world can do: a chamber emptying between a resignation and a
  special election, a race set rolling over after certification, a roster file
  legitimately shedding departed members. These are REPORTED, never gated.

This replaces the inline heredoc in update-search-corpus.yml, which asserted
`count >= 200`. That floor is a number the content controls, and it could not
see the failure it was nearest to: this index is assembled from seven committed
entity files, so a whole CATEGORY can vanish (one upstream file missing or
unreadable -- generate_search_corpus.load() skips it with a warning on stderr
and carries on) while 5,000 records from the other six clear the floor with
room to spare. The signal lives per category, and per-category figures are
facts the world moves, so they are tier 2: named with their before and after.

The generator also refuses to write fewer than MIN_RECORDS (200) itself, so a
total collapse never reaches this script -- see generate_search_corpus.py.

Usage:
    python scripts/validate_search_corpus.py assets/data/search-entities.json \
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

# Fields the search widget reads (_includes/search.html builds each result from
# rec.title, rec.category and rec.url; rec.desc is indexed for matching). The
# generator never emits a blank title/url/category, and always emits desc as a
# string (possibly "").
REQUIRED_NONBLANK = ("title", "category", "url")
REQUIRED_STRING = REQUIRED_NONBLANK + ("desc",)

# A category moving by more than this share AND by at least MOVE_FLOOR records is
# worth a line. The floor keeps a 9-justice court losing one seat (11%) and a
# 13-person executive losing one (8%) from reading as events at every reshuffle.
MATERIAL_SHIFT = 0.25
MOVE_FLOOR = 3


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


def tally(records):
    out = {}
    for r in records:
        if isinstance(r, dict):
            c = r.get("category")
            if isinstance(c, str) and c:
                out[c] = out.get(c, 0) + 1
    return out


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    meta = d.get("metadata")
    records = d.get("records")
    if not isinstance(meta, dict) or not isinstance(records, list):
        return ["file has no metadata object or no records list"]

    count = meta.get("count")
    cats = meta.get("categories")
    if count != len(records):
        errors.append(f"metadata.count ({count}) != len(records) ({len(records)})")

    if not isinstance(cats, dict) or not all(isinstance(v, int) for v in cats.values()):
        errors.append("metadata.categories is not a {category: int} map")
        cats = None

    # Records first: the category checks below tally them.
    bad = []
    seen = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            bad.append(f"records[{i}] is not an object")
            continue
        for f in REQUIRED_STRING:
            v = r.get(f)
            if not isinstance(v, str) or (f in REQUIRED_NONBLANK and not v.strip()):
                bad.append(f"records[{i}] ({r.get('title')!r}) has no usable {f!r}")
        # The generator's own dedupe key. url alone is NOT unique by design: the
        # GA executives all share ga-executive.html.
        key = (r.get("title"), r.get("url"))
        if key in seen:
            errors.append(f"records[{i}] duplicates records[{seen[key]}]: "
                          f"{key[0]!r} -> {key[1]!r}")
        else:
            seen[key] = i
    errors += bad[:10]
    if len(bad) > 10:
        errors.append(f"... and {len(bad) - 10} more malformed record(s)")

    if cats is not None:
        if sum(cats.values()) != count:
            errors.append(f"metadata.categories sums to {sum(cats.values())}, "
                          f"but metadata.count is {count}")
        actual = tally(records)
        for c in sorted(set(cats) | set(actual)):
            if c not in cats:
                errors.append(f"{actual[c]} record(s) carry category {c!r}, "
                              f"which is not in metadata.categories")
            elif cats[c] != actual.get(c, 0):
                errors.append(f"metadata.categories[{c!r}] is {cats[c]}, but "
                              f"{actual.get(c, 0)} record(s) carry it")
    return errors


# ── tier 2: the file against yesterday's ──────────────────────────────────────

def category_counts(d):
    """Per-category counts, taken from the records themselves."""
    return tally((d or {}).get("records") or [])


def tier2(new, old):
    """Per-category changes between two versions, as (heading, [lines]) sections."""
    if not old:
        return []
    nc, oc = category_counts(new), category_counts(old)
    sections = []

    gone = [f"- **{c}**: {oc[c]} → 0" for c in sorted(oc) if oc[c] and not nc.get(c)]
    if gone:
        sections.append(("Categories now empty — check these first", gone))

    appeared = [f"- **{c}**: 0 → {nc[c]}" for c in sorted(nc) if nc[c] and not oc.get(c)]
    if appeared:
        sections.append(("Categories that appeared", appeared))

    moved = []
    for c in sorted(set(nc) & set(oc)):
        o, n = oc[c], nc[c]
        if o and n and abs(n - o) >= MOVE_FLOOR and abs(n - o) / o > MATERIAL_SHIFT:
            moved.append(f"- **{c}**: {o} → {n} ({n - o:+d})")
    if moved:
        sections.append((f"Categories that moved more than {MATERIAL_SHIFT:.0%}", moved))
    return sections


def render(path, sections):
    out = [f"## Search index: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is a change in what the search index holds that the "
                   "underlying data can legitimately cause, so none of them blocked "
                   "the update — the index is committed. A category that is empty "
                   "can also mean an upstream data file was missing or unreadable "
                   "when the index was built: check the generate step's log for "
                   "`not found -- skipping` before assuming the change is real.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def figures(new, old):
    """The per-category table printed to the run log on every run."""
    nc, oc = category_counts(new), category_counts(old) if old else {}
    lines = [f"  {c:<22} {nc.get(c, 0):>5}" +
             (f"   (was {oc.get(c, 0)})" if old else "")
             for c in sorted(set(nc) | set(oc))]
    lines.append(f"  {'TOTAL':<22} {sum(nc.values()):>5}" +
                 (f"   (was {sum(oc.values())})" if old else ""))
    return "\n".join(lines)


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
    size_kb = os.path.getsize(args.path) // 1024
    print(f"Tier 1 passed: {len(new['records'])} records, {size_kb} KB, category "
          f"counts agree with the records.")

    old = baseline(args.path, args.baseline_ref)
    print("\nPer-category records:")
    print(figures(new, old))

    sections = tier2(new, old)
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} category change(s) — reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
