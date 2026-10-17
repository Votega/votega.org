#!/usr/bin/env python3
"""Validate ga-news.json: gate on self-consistency, report on a thin run.

This replaces `validate_data_update.py --min items=20` in update-ga-news.yml,
which ran every three hours and aborted the job whenever the aggregate fell
under 20 items. That number is the world's, not the file's: individual feeds
sit behind Cloudflare bot protection and intermittently 403 a datacenter
runner, and a fixed floor is a vague proxy for the sharp condition ("did the
sweep half-fail?"). It is also the wrong response to it. The file is rebuilt
whole every three hours from whatever the feeds currently serve, so a thin run
heals itself on the next one; discarding it adds a failure issue every time a
feed flaps and publishes nothing better. The generator keeps the one hard edge
that matters (zero items -> exit 1 before the write, file untouched).

  Tier 1 — the file contradicts itself. metadata.count vs the items it
  counts, entityTagged vs the items carrying entityIds, topicCounts vs the
  topics on the items, a duplicate item id, an item missing a field the page
  renders, an item whose source is not in metadata.sources (the page's filter
  chips come from that list), an entity no item references. No feed outage can
  make any of these true. Exit 1.

  Tier 2 — the run is thin against the committed file. Reported, never gated:
  the item count fell by more than THIN_DROP, and the sources that went silent
  (named, because "which feed" is the only thing a human can act on). A single
  silent source is not reported — that is a Cloudflare 403 on an ordinary day,
  and a tracking issue that rewrites itself every flap would be noise.

Usage:
    python scripts/validate_ga_news.py assets/data/ga-news.json \
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

# Losing this share of last run's items in one three-hour step is not news
# flow, it is feeds failing. Deliberately a REPORT threshold: the next run
# usually restores them.
THIN_DROP = 0.30

REQUIRED_ITEM_FIELDS = ("id", "title", "url", "source")


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


def tier1(d):
    """Contradictions inside the file. Returns a list of strings."""
    errors = []
    meta = d.get("metadata")
    items = d.get("items")
    entities = d.get("entities")
    if not isinstance(meta, dict):
        return ["metadata is missing or not an object"]
    if not isinstance(items, list):
        return ["items is missing or not a list"]
    if not isinstance(entities, dict):
        return ["entities is missing or not an object"]

    if meta.get("count") != len(items):
        errors.append(f"metadata.count is {meta.get('count')!r} but the file holds "
                      f"{len(items)} items")

    tagged = sum(1 for it in items if isinstance(it, dict) and it.get("entityIds"))
    if meta.get("entityTagged") != tagged:
        errors.append(f"metadata.entityTagged is {meta.get('entityTagged')!r} but "
                      f"{tagged} items carry entityIds")

    tally = {}
    for it in items:
        if isinstance(it, dict):
            for t in it.get("topics") or []:
                tally[t] = tally.get(t, 0) + 1
    if (meta.get("topicCounts") or {}) != tally:
        errors.append(f"metadata.topicCounts {meta.get('topicCounts')!r} disagrees "
                      f"with the topics on the items {tally!r}")

    sources = set(meta.get("sources") or [])
    seen, dupes, missing, off_list, referenced = set(), set(), [], set(), set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append(f"items[{i}] is not an object")
            continue
        gaps = [f for f in REQUIRED_ITEM_FIELDS if not it.get(f)]
        if gaps:
            missing.append(f"items[{i}] ({it.get('id')!r}) lacks {', '.join(gaps)}")
        if it.get("id") in seen:
            dupes.add(it.get("id"))
        seen.add(it.get("id"))
        if it.get("source") and it["source"] not in sources:
            off_list.add(it["source"])
        referenced.update(it.get("entityIds") or [])
    if missing:
        errors.append(f"{len(missing)} item(s) missing a required field, "
                      f"e.g. {missing[0]}")
    if dupes:
        errors.append(f"duplicate item id(s): {sorted(map(str, dupes))[:5]}")
    if off_list:
        errors.append(f"item source(s) not in metadata.sources: {sorted(off_list)}")
    orphans = sorted(set(entities) - referenced)
    if orphans:
        errors.append(f"{len(orphans)} entity(ies) no item references, "
                      f"e.g. {orphans[:3]}")
    return errors


def source_counts(d):
    out = {}
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("source"):
            out[it["source"]] = out.get(it["source"], 0) + 1
    return out


def tier2(new, old):
    """Disagreements with the committed file. Returns [(heading, [lines])]."""
    if not old:
        return []
    n_total, o_total = len(new.get("items") or []), len(old.get("items") or [])
    if o_total == 0 or (o_total - n_total) / o_total <= THIN_DROP:
        return []
    ns, os_ = source_counts(new), source_counts(old)
    silent = sorted(s for s in os_ if s not in ns)
    lines = [f"- {o_total} → {n_total} items ({(o_total - n_total) / o_total:.0%} fewer)"]
    if silent:
        lines.append(f"- {len(silent)} source(s) with items last run and none now: "
                     + ", ".join(silent))
    else:
        lines.append("- every source still has items; the drop is spread across feeds "
                     "(items aging out of the window, or feeds serving shorter lists)")
    return [("Thin run", lines)]


def render(path, sections):
    out = [f"## GA news: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("The file is rebuilt from the live feeds every three hours, so a "
                   "thin run normally heals on the next one. It was committed anyway; "
                   "this issue is here so a feed that stays dark gets noticed.")
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
        print("\nThis is a generator bug, not a quiet news day. The rejected file is "
              "uploaded as a workflow artifact so it can be inspected.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['items'])} items, counts and source list agree.")

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
