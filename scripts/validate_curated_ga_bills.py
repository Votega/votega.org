#!/usr/bin/env python3
"""Validate curated-ga-bill-votes.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of the curated-votes run, and conflating them is
how a validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A `metadata.count` that disagrees with
  the bills it counts, a source breakdown larger than the whole, more legislators
  "with votes" than are sitting, a chamber vote whose party tally exceeds the
  roster it tallies (the tally is double-counting rows), a bill or vote missing a
  field the page reads, the same bill twice. No fact about the General Assembly
  can make any of these legitimately true. These exit 1.

  Tier 2 — anything the world, or the editorial list, can legitimately do. The
  curated list gained or lost a bill, a session rolled over, a roll call carried
  member ids the crosswalk does not know (unresolved voter rows), fewer
  legislators have a key vote than are sitting. These are REPORTED, never gated.

The gates this replaces:

  * `validate_data_update.py --metric bills=metadata.count --metric
    coverage=metadata.legislatorsWithVotes --min bills=1` — a 20% shrink limit
    against HEAD. The curated list is nine bills, so one edit to it is an 11%+
    move on its own, and a session rollover changes `legislatorsWithVotes`
    legitimately (the roster is replaced, a vacancy lowers it). Both are the
    world, or the editor, moving. `--min bills=1` is likewise an editorial
    choice: an emptied list is self-consistent, and the producer already exits 1
    when EVERY listed bill failed to source.
  * the inline `ghosts or unres` block, which only printed a `::warning::` that
    nobody reads on a green run. The degraded state is DESIGNED FOR — an
    unresolved row is dropped by the producer on purpose and counted in
    metadata — so it belongs in the tier-2 report where a human sees it, not in
    a gate.
  * `tally <= roster` — kept, and kept as tier 1: a party tally larger than the
    roster it tallies is arithmetic, not politics.

The producer RETAINS a previously published record when a bill cannot be
re-sourced, so `fromLocalRecord + fromSoapFetch` may be less than `count` — but
never more. That inequality is checked; equality is not.

See docs/audits/2026-10-13-data-pipeline-audit.md 2.6, scripts/validate_fec_data.py
(reference implementation) and scripts/validate_ga_bills.py (the bill file this
one reads).

Usage:
    python scripts/validate_curated_ga_bills.py assets/data/curated-ga-bill-votes.json \
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

BILL_REQUIRED = ("identifier", "session", "title", "votes")
VOTE_REQUIRED = ("memberVotes", "partyTally")
TALLY_KEYS = ("yea", "nay", "other")
CHAMBERS = ("house", "senate")


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


def key(b):
    return (b.get("session"), b.get("identifier"))


def label(b):
    return f"{b.get('identifier', '?')} ({b.get('session', '?')})"


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    bills = d.get("bills")
    meta = d.get("metadata")

    if not isinstance(bills, list):
        return ["bills is missing or not a list"]
    if not isinstance(meta, dict):
        return ["metadata is missing"]

    if meta.get("count") != len(bills):
        errors.append(f"metadata.count ({meta.get('count')}) != len(bills) ({len(bills)})")

    local, soap = meta.get("fromLocalRecord"), meta.get("fromSoapFetch")
    if isinstance(local, int) and isinstance(soap, int) and local + soap > len(bills):
        errors.append(f"fromLocalRecord ({local}) + fromSoapFetch ({soap}) exceed the "
                      f"{len(bills)} bills in the file")

    sitting, covered = meta.get("sittingLegislators"), meta.get("legislatorsWithVotes")
    if isinstance(sitting, int) and isinstance(covered, int) and covered > sitting:
        errors.append(f"legislatorsWithVotes ({covered}) exceeds sittingLegislators ({sitting})")

    res = meta.get("voterResolution")
    if isinstance(res, dict) and "unresolved" in res and \
            meta.get("unresolvedVoterRows") not in (None, res["unresolved"]):
        errors.append(f"unresolvedVoterRows ({meta.get('unresolvedVoterRows')}) != "
                      f"voterResolution.unresolved ({res['unresolved']})")

    keys = [key(b) for b in bills]
    if len(set(keys)) != len(keys):
        errors.append("the same bill appears more than once (session + identifier)")

    for b in bills:
        absent = [f for f in BILL_REQUIRED if f not in b]
        if absent:
            errors.append(f"bill {label(b)} is missing required field(s): {', '.join(absent)}")
            continue
        votes = b["votes"]
        if not isinstance(votes, dict):
            errors.append(f"bill {label(b)}: votes is not a chamber map")
            continue
        for chamber, v in votes.items():
            where = f"{label(b)} {chamber}"
            if chamber not in CHAMBERS:
                errors.append(f"{where}: unknown chamber key")
            absent = [f for f in VOTE_REQUIRED if not isinstance(v.get(f), dict)]
            if absent:
                errors.append(f"{where}: {', '.join(absent)} missing or not a map")
                continue
            bad = [p for p, t in v["partyTally"].items()
                   if not isinstance(t, dict) or any(not isinstance(t.get(k), int) for k in TALLY_KEYS)]
            if bad:
                errors.append(f"{where}: partyTally row(s) without integer yea/nay/other: {bad}")
                continue
            roster = len(v["memberVotes"])
            tally = sum(t["yea"] + t["nay"] + t["other"] for t in v["partyTally"].values())
            if tally > roster:
                errors.append(f"{where}: partyTally {tally} exceeds the {roster}-member "
                              f"roster - the tally is double-counting rows")
    return errors


# ── tier 2: what the world and the editor can do ──────────────────────────────

def tier2(new, old=None):
    """Material facts and changes, as (heading, [lines]) sections."""
    sections = []
    bills = new.get("bills") or []
    meta = new.get("metadata") or {}

    if not bills:
        sections.append(("The curated list is empty", [
            "- No bills in the file. If the list in generate_curated_ga_bills.py was "
            "emptied on purpose that is fine; otherwise check the generate step's log."]))

    unres = meta.get("unresolvedVoterRows") or 0
    ghosts = meta.get("ghostVoterIds") or 0
    if unres or ghosts:
        sections.append(("Roll-call rows that could not be attributed", [
            f"- {unres} row(s) with no usable member id, {ghosts} ghost id(s). Their "
            f"votes are omitted, so the affected legislators show no key vote on that bill.",
            "- Fix by extending id-crosswalk.json (or the roster) for the member ids named "
            "in the generate step's log."]))

    sitting, covered = meta.get("sittingLegislators"), meta.get("legislatorsWithVotes")
    if isinstance(sitting, int) and isinstance(covered, int) and covered < sitting:
        sections.append(("Sitting legislators with no key vote", [
            f"- {sitting - covered} of {sitting} sitting legislators appear in no curated "
            f"roll call; a legislator missing from every key vote reads as one who never voted."]))

    retained = len(bills) - (meta.get("fromLocalRecord") or 0) - (meta.get("fromSoapFetch") or 0)
    if retained > 0:
        sections.append(("Records kept from the previous run", [
            f"- {retained} bill(s) could not be re-sourced this run, so last run's record "
            f"was kept. Check the generate step's log for the cause."]))

    if not old:
        return sections

    old_bills = old.get("bills") or []
    old_meta = old.get("metadata") or {}
    nk, ok = {key(b): b for b in bills}, {key(b): b for b in old_bills}

    added, removed = sorted(set(nk) - set(ok), key=str), sorted(set(ok) - set(nk), key=str)
    if added or removed:
        sections.append(("Curated bills added or removed", (
            [f"- added {label(nk[k])}" for k in added] +
            [f"- removed {label(ok[k])}" for k in removed])))

    lost = []
    for k in sorted(set(nk) & set(ok), key=str):
        gone = sorted(set(ok[k].get("votes") or {}) - set(nk[k].get("votes") or {}))
        if gone:
            lost.append(f"- {label(nk[k])} lost its {', '.join(gone)} vote")
    if lost:
        sections.append(("A bill lost a chamber vote", lost))

    oc, nc = old_meta.get("legislatorsWithVotes"), covered
    if isinstance(oc, int) and isinstance(nc, int) and nc != oc:
        sections.append(("Key-vote coverage changed", [
            f"- legislators with a key vote: {oc} → {nc} (a vacancy, a new member or a "
            f"changed list all move this)."]))
    return sections


def render(path, sections):
    out = [f"## Curated GA bill votes: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something the General Assembly, the source or the "
                   "editorial list can legitimately do, so none of them blocked the "
                   "update — the data is committed. They are here because they change "
                   "what a reader sees under Key Votes.")
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

    print(f"Tier 1 passed: {len(new['bills'])} curated bills; counts agree with metadata "
          f"and every party tally fits inside its roster.")

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
