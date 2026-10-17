#!/usr/bin/env python3
"""Validate ga-bills.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of a bill sweep, and conflating them is how a
validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A `metadata.totalBills` that disagrees
  with the bills it counts, a per-session `billCount` that disagrees with the
  bills carrying that session id, a session marked preserved with nothing in the
  file, a bill tagged with a session the metadata does not list, a duplicate bill
  id, a bill missing a field every consumer reads. No fact about the General
  Assembly can make any of these legitimately true — they mean the producer or
  its preserved/fetched merge is broken, and the file must not be committed.
  These exit 1.

  Tier 2 — the file disagrees with last week's. A session gained or lost bills,
  a closed session's count moved, a new session appeared at a rollover, a bill
  left the file. Every one of these is something the world (or a retroactive
  amendment) can legitimately do. These are REPORTED, never gated.

The gate this replaces was `validate_data_update.py --metric bills=len:bills
--scope-key metadata.session --min bills=1`, i.e. "the file may not shrink more
than 20% against HEAD". That is a floor cleared by the PRESERVED layer: ~5,500 of
the ~5,650 bills are carried forward verbatim from the closed 2025-26 session, so
the active session (~180 bills, ~3% of the file) can come back empty and the
whole-file delta never moves. It looks safe while the incremental fetch it is
meant to guard fails silently under it — and it still trips on a session
rollover, where the file legitimately changes shape (the --scope-key reset was a
patch for exactly that). The per-session `billCount` equality below is the check
that actually catches a broken merge: it compares what the producer says it wrote
for EACH session against what is in the file.

(The producer itself refuses to write below 100 bills or short a preserved
session, so a tier-1 floor of any kind would be redundant here.)

See docs/audits/2026-10-13-data-pipeline-audit.md 2.6 for this class of
validator repo-wide, scripts/validate_fec_data.py for the reference
implementation, and scripts/validate_ga_votes.py for the same per-session
problem on the votes file.

Usage:
    python scripts/validate_ga_bills.py assets/data/ga-bills.json \
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

# Fields every consumer (ga-bills.html, the entity pages, the slice builder,
# the publisher) reads off a bill. A missing one is a producer bug, not a fact.
BILL_REQUIRED = ("id", "identifier", "chamber", "title", "billUrl", "session")

KNOWN_CHAMBERS = ("lower", "upper")


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


def by_session(bills):
    out = {}
    for b in bills:
        out[b.get("session")] = out.get(b.get("session"), 0) + 1
    return out


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    bills = d.get("bills")
    meta = d.get("metadata") or {}

    if not isinstance(bills, list) or not bills:
        errors.append("no bills in the file")
        return errors          # nothing below can say anything useful

    total = meta.get("totalBills")
    if total != len(bills):
        errors.append(f"metadata.totalBills ({total}) != len(bills) ({len(bills)})")

    for b in bills:
        absent = [f for f in BILL_REQUIRED if f not in b]
        if absent:
            errors.append(f"bill {b.get('identifier', '?')} is missing required "
                          f"field(s): {', '.join(absent)}")
            if len(errors) >= 40:
                break

    ids = [b.get("id") for b in bills if "id" in b]
    if len(set(ids)) != len(ids):
        seen, dupes = set(), []
        for i in ids:
            if i in seen and i not in dupes:
                dupes.append(i)
            seen.add(i)
        errors.append(f"{len(ids) - len(set(ids))} duplicate bill id(s), e.g. {dupes[:3]} "
                      f"— the preserved/fetched merge double-counted a bill")

    # Per-session integrity. A whole-file floor is cleared by the preserved layer
    # alone, so this is the check that actually catches an incremental run that
    # dropped or truncated a session.
    actual = by_session(bills)
    listed = set()
    for row in (meta.get("sessions") or []):
        sid, claimed = row.get("id"), row.get("billCount")
        listed.add(sid)
        if actual.get(sid, 0) != claimed:
            errors.append(f"metadata claims {claimed} bills for session {sid} but the "
                          f"file holds {actual.get(sid, 0)} — the preserved/fetched "
                          f"merge is wrong")
    for sid in actual:
        if listed and sid not in listed:
            errors.append(f"{actual[sid]} bill(s) are tagged session {sid!r}, which "
                          f"metadata.sessions does not list")
    for sid in (meta.get("preservedSessions") or []):
        if actual.get(sid, 0) == 0:
            errors.append(f"session {sid} is marked preserved but has no bills in the file")
    return errors


# ── tier 2: the file against last week's ──────────────────────────────────────

def tier2(new, old=None):
    """Material facts and changes, as (heading, [lines]) sections."""
    sections = []
    bills = new.get("bills") or []
    meta = new.get("metadata") or {}
    actual = by_session(bills)

    # Wording the site has not been taught to bucket. A chamber outside
    # lower/upper falls off both the House and Senate filters.
    odd = sorted({str(b.get("chamber")) for b in bills} - set(KNOWN_CHAMBERS))
    if odd:
        sections.append(("Chamber values the site does not filter on",
                         [f"- `{c}` — these bills appear under neither chamber tab." for c in odd]))

    # The active session is the one the incremental fetch is responsible for;
    # an empty one at the head of a biennium is normal, mid-session it is not.
    active = meta.get("activeSession")
    if active and actual.get(active, 0) == 0:
        sections.append(("The active session holds no bills", [
            f"- session {active} has 0 bills. That is normal at the start of a "
            f"biennium or before a session convenes; mid-session it means the "
            f"incremental fetch returned nothing — check the generate step's log."]))

    if not old:
        return sections

    old_bills = old.get("bills") or []
    old_actual = by_session(old_bills)
    old_meta = old.get("metadata") or {}

    if old_meta.get("session") != meta.get("session"):
        sections.append(("The active session changed", [
            f"- {old_meta.get('session')} → {meta.get('session')} (a rollover or a "
            f"new special session)"]))

    gone = sorted(s for s in old_actual if s not in actual)
    arrived = sorted(s for s in actual if s not in old_actual)
    if gone or arrived:
        sections.append(("Sessions in the file changed", [
            f"- session {s} is gone (held {old_actual[s]} bills)" for s in gone
        ] + [f"- session {s} is new ({actual[s]} bills)" for s in arrived]))

    # Closed sessions are carried forward verbatim, so one moving means a
    # --full-refresh picked up a retroactive amendment (or lost records).
    moved = []
    for s in sorted(set(actual) & set(old_actual)):
        if actual[s] != old_actual[s]:
            moved.append(f"- session {s}: {old_actual[s]} → {actual[s]}"
                         + (" (closed session — carried forward, so this came from a "
                            "full refresh)" if s in (meta.get("preservedSessions") or []) else ""))
    if moved:
        sections.append(("A session's bill count changed", moved))

    new_ids = {b.get("id") for b in bills}
    old_ids = {b.get("id") for b in old_bills}
    removed = sorted(i for i in old_ids - new_ids if i is not None)
    if removed:
        names = {b.get("id"): b.get("identifier") for b in old_bills}
        sections.append(("Bills left the file", [
            f"- {len(removed)} removed, e.g. " +
            ", ".join(str(names.get(i, i)) for i in removed[:8]) +
            (" …" if len(removed) > 8 else "")]))

    return sections


def render(path, sections):
    out = [f"## GA bills: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something the General Assembly or the source can "
                   "legitimately do, so none of them blocked the update — the data is "
                   "committed. They are here because they change what a reader sees on "
                   "the bills page.")
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
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  … and {len(errors) - 40} more", file=sys.stderr)
        print("\nThis is a producer bug, not a change in the record. The rejected file "
              "is uploaded as a workflow artifact so it can be inspected.", file=sys.stderr)
        return 1

    print(f"Tier 1 passed: {len(new['bills'])} bills, per-session counts agree with "
          f"metadata, no duplicate ids, every bill carries its required fields.")

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
