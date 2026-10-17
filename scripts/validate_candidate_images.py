#!/usr/bin/env python3
"""Validate candidate-image-cache.json: gate on self-contradiction, report on change.

  Tier 1 - the manifest contradicts itself or the disk. metadata.count not
  matching the entries, an entry whose file is not on disk (the page would
  render a broken image), a path outside assets/img/candidates, and - the
  copyright invariant in CLAUDE.md - a source URL on a host that is not a
  government (.gov) host or is not one the manifest itself declares in
  metadata.sources. Re-hosting a campaign photo is not a data-quality problem a
  report can soften, so this stays a hard gate.

  Tier 2 - the world. Portraits that could not be fetched this run
  (metadata.failed, named), entries added or dropped since last run, image
  files on disk that nothing references.

This replaces the inline heredoc in update-candidate-images.yml. Both of its
asserts were already tier-1 shaped; what the step lacked was any report, so a
portrait that kept failing to download was invisible. The generator's one
world-gate (`not manifest and urls`) is kept, but moved BEFORE the manifest
write: it said "refusing to write an empty manifest" after having written it.

Usage:
    python scripts/validate_candidate_images.py assets/data/candidate-image-cache.json \
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
from urllib.parse import urlparse

OUTPUT_DIR = "assets/img/candidates"
MAX_LINES = 25


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, check=True).stdout
        return json.loads(blob.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def host_of(url):
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# -- tier 1: the manifest against itself and the disk ---------------------------

def tier1(d, root="."):
    """Return a list of contradictions. Empty means the manifest is consistent."""
    images = d.get("images")
    meta = d.get("metadata") or {}
    if not isinstance(images, dict):
        return ["images is not an object"]

    errors = []
    if meta.get("count") != len(images):
        errors.append(f"metadata.count ({meta.get('count')}) != {len(images)} entries")

    sources = {s.lower() for s in meta.get("sources") or []}
    for s in sorted(sources):
        if not (s == "gov" or s.endswith(".gov")):
            errors.append(f"metadata.sources lists {s!r}, which is not a .gov host - "
                          f"re-hosting a non-government photo reproduces a copyrighted work")

    missing, outside, offhost = [], [], []
    for url, rel in images.items():
        host = host_of(url)
        if host not in sources or not host.endswith(".gov"):
            offhost.append(url)
        if not isinstance(rel, str) or not rel.startswith(OUTPUT_DIR + "/"):
            outside.append(f"{url} -> {rel}")
        elif not os.path.exists(os.path.join(root, rel)):
            missing.append(rel)
    if offhost:
        errors.append(f"{len(offhost)} entr(ies) from a host that is not a declared .gov "
                      f"source: {offhost[:3]}")
    if outside:
        errors.append(f"{len(outside)} entr(ies) outside {OUTPUT_DIR}/: {outside[:3]}")
    if missing:
        errors.append(f"manifest points at {len(missing)} missing file(s): {missing[:5]}")
    return errors


# -- tier 2: what the world did ------------------------------------------------

def capped(lines):
    if len(lines) <= MAX_LINES:
        return lines
    return lines[:MAX_LINES] + [f"- ... and {len(lines) - MAX_LINES} more"]


def tier2(new, old, on_disk=None):
    """as (heading, [lines]) sections. on_disk: image filenames present in the folder."""
    sections = []
    images = new.get("images") or {}

    failed = (new.get("metadata") or {}).get("failed") or []
    if failed:
        sections.append((f"{len(failed)} portrait(s) could not be cached this run",
                         capped([f"- {u}" for u in failed])))

    if on_disk is not None:
        referenced = {os.path.basename(r) for r in images.values()}
        orphans = sorted(set(on_disk) - referenced)
        if orphans:
            sections.append(("Image files nothing references",
                             capped([f"- {o}" for o in orphans])))

    if old and isinstance(old.get("images"), dict):
        o = old["images"]
        dropped = [f"- {u}" for u in sorted(set(o) - set(images))]
        added = [f"- {u}" for u in sorted(set(images) - set(o))]
        if dropped:
            sections.append((f"{len(dropped)} portrait(s) no longer in the manifest - check these first",
                             capped(dropped)))
        if added:
            sections.append((f"{len(added)} portrait(s) newly cached", capped(added)))
    return sections


def render(path, sections):
    out = [f"## Candidate portraits: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something the sources did, so none of them blocked the "
                   "update - the cache is committed. A portrait that is not cached falls "
                   "back to its hot-linked or placeholder image.")
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
        print("TIER 1 FAILED - the manifest contradicts itself or the disk, "
              "refusing to commit:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThe rejected manifest is uploaded as a workflow artifact so it can "
              "be inspected.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['images'])} cached portraits, all files present, "
          f"all sources .gov.")

    on_disk = os.listdir(OUTPUT_DIR) if os.path.isdir(OUTPUT_DIR) else None
    sections = tier2(new, baseline(args.path, args.baseline_ref), on_disk)
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
