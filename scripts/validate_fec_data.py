#!/usr/bin/env python3
"""Validate ga-fec-data.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of a generator run, and conflating them is how
a validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A published index that disagrees with
  the function meant to produce it, a count that does not match the thing it
  counts, an index pointing at a candidate that is not in the file. No fact
  about the FEC can make any of these legitimately true, so they mean the
  generator is broken and the file must not be committed. These exit 1.

  Tier 2 — the file disagrees with last week's file. A member's money appeared
  or vanished, their committee changed, their preferred filing moved to another
  candidacy. Every one of these is something the FEC can legitimately report,
  and the site exists to publish exactly that. These are REPORTED, never gated.

The collapse check is the one deliberate exception, and it reads the baseline.
It exists because the failure it catches leaves every surviving record
perfectly self-consistent: a fetch that loses half the delegation to 429s
produces a SMALLER file, not a malformed one. Tier 1 passes it, tier 2 writes a
long and accurate report about it, and a hundred members' finances quietly
leave the site. See collapse() for why that one gates and what stops it from
becoming the hand-pinned floor this validator replaced.

The distinction matters because the two are indistinguishable by shape. Everton
Blair's totals going to zero is the signature of the bug fixed in October 2026
(a re-designated committee the fetch skipped) AND of his PAC legitimately
winding down. A gate cannot tell them apart, so a gate on that condition either
blocks true data or gets overridden until it means nothing. A report hands a
human the diff and keeps the site current.

This replaces the inline heredoc in update-fec-data.yml, whose floors
("expected >= 12 incumbents") were pinned to the shape of the 2026 delegation
and would fire on an ordinary vacancy. See
docs/audits/2026-10-13-data-pipeline-audit.md 2.6, and the comment at the head
of update-local-government.yml for the pattern this follows.

Usage:
    python scripts/validate_fec_data.py assets/data/ga-fec-data.json \
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_fec_data import preferred_filing  # noqa: E402

# A total moving by more than this much, in either direction, is worth a line in
# the report. Amended filings and a quarter's fundraising both land well under
# it; a committee swap does not.
MATERIAL_SHIFT = 0.25

# Losing more than this share of the records the last run published is not a
# week in politics; it is a fetch that half-failed. Deliberately far above any
# real week: candidates do not leave the FEC's list mid-cycle, so within one
# cycle this number only moves up.
COLLAPSE_DROP = 0.5


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


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    candidates = d.get("candidates") or {}
    meta = d.get("metadata") or {}

    if not candidates:
        errors.append("no candidates in the file")
        return errors   # nothing below can say anything useful

    n = meta.get("totalCandidates")
    if n != len(candidates):
        errors.append(f"metadata.totalCandidates ({n}) != len(candidates) ({len(candidates)})")

    # The FEC list endpoint caps per_page at 100, so a House count of exactly 100
    # means pagination stopped at the cap and the field is truncated alphabetically.
    # Not a fact about the world: 100 is an artifact of the API, not a number of
    # candidates Georgia could plausibly have.
    house = [c for c in candidates.values() if c.get("office") == "H"]
    if len(house) == 100:
        errors.append("House count is exactly 100 — pagination truncated at the per_page cap")

    # Every index value must name a candidate the file actually holds.
    for index_name in ("byBioguideId", "byNormalizedName"):
        for key, cid in (d.get(index_name) or {}).items():
            if cid not in candidates:
                errors.append(f"{index_name}[{key}] -> {cid}, which is not in candidates")
    for key, cids in (d.get("byDistrict") or {}).items():
        for cid in cids:
            if cid not in candidates:
                errors.append(f"byDistrict[{key}] contains {cid}, which is not in candidates")

    # The single-valued indexes must agree with preferred_filing() recomputed on
    # this same file. This is the check that would have caught the Buddy Carter
    # bug: the published index said H4GA01039 while the rule says S6GA00374.
    # Nothing about the FEC can make the published value and the recomputed value
    # legitimately differ — only a broken generator can.
    for single, plural in (("byBioguideId", "byBioguideIdAll"),
                           ("byNormalizedName", "byNormalizedNameAll")):
        published = d.get(single) or {}
        every = d.get(plural) or {}
        if set(published) != set(every):
            only_single = sorted(set(published) - set(every))[:3]
            only_plural = sorted(set(every) - set(published))[:3]
            errors.append(f"{single} and {plural} cover different keys "
                          f"(only in {single}: {only_single}; only in {plural}: {only_plural})")
        for key in set(published) & set(every):
            want = preferred_filing(every[key], candidates)
            if published[key] != want:
                errors.append(f"{single}[{key}] is {published[key]} but preferred_filing() "
                              f"says {want} — the index disagrees with the rule that builds it")

    # Money without a filer behind it means the totals were attached to the wrong
    # record, which is the shape of the pre-October-2026 committee bug.
    orphaned = [cid for cid, c in candidates.items()
                if c.get("totalRaised") is not None and not c.get("committeeId")][:5]
    if orphaned:
        errors.append(f"candidate(s) carry totals with no committeeId: {orphaned}")

    return errors


# ── the collapse check: the file against last week's, for a catastrophic shrink ─

def collapse(new, old):
    """Return errors for a shrink no week of politics can explain.

    This gates rather than reports, which is the opposite of everything in tier
    2, so the asymmetry is the argument: if the shrink is a fetch failure,
    committing it destroys live data for every reader; if it is somehow real,
    holding it costs one week and a human glance. Everything short of
    catastrophic stays in tier 2, where Everton Blair's totals going to zero
    belongs — that one is indistinguishable by shape from a real wind-down, and
    gating on it is exactly the mistake this validator was written to undo.

    Skipped when the cycle rolls over. The candidate list for a new cycle starts
    nearly empty and fills over a year, so 2026 -> 2028 is a ~99% drop that means
    nothing is wrong. Gating on it would be the hand-pinned floor in a new hat:
    a check that fires on a calendar date and gets overridden until it means
    nothing.
    """
    if not old:
        return []

    n_cycle = (new.get("metadata") or {}).get("cycle")
    o_cycle = (old.get("metadata") or {}).get("cycle")
    if n_cycle != o_cycle:
        print(f"Collapse check skipped: cycle {o_cycle} -> {n_cycle}. A new cycle "
              f"starts with few candidates, so a drop here is expected.")
        return []

    nc = new.get("candidates") or {}
    oc = old.get("candidates") or {}

    def with_totals(d):
        return sum(1 for c in d.values() if c.get("totalRaised") is not None)

    errors = []
    for label, n, o in (("candidates", len(nc), len(oc)),
                        ("candidates carrying totals", with_totals(nc), with_totals(oc))):
        if o and n < o * (1 - COLLAPSE_DROP):
            errors.append(f"{label}: {o} -> {n}, a {1 - n / o:.0%} drop in one run "
                          f"with the cycle unchanged ({n_cycle})")
    return errors


# ── tier 2: the file against last week's ──────────────────────────────────────

def describe(entry):
    """The facts about one candidate a reader would want to see change."""
    return {
        "name":        entry.get("name", ""),
        "office":      entry.get("office", ""),
        "committee":   entry.get("committeeId"),
        "designation": entry.get("committeeDesignation", ""),
        "raised":      entry.get("totalRaised"),
    }


def money(v):
    return "—" if v is None else f"${v:,.0f}"


def shifted(old, new):
    """True when a total moved far enough to be worth a reader's attention."""
    if old is None or new is None:
        return old is not new          # appeared or vanished
    if old == 0:
        return new != 0
    return abs(new - old) / abs(old) > MATERIAL_SHIFT


def tier2(new, old):
    """Material changes between two versions, as (heading, [lines]) sections."""
    if not old:
        return []
    nc, oc = new.get("candidates") or {}, old.get("candidates") or {}
    sections = []

    # A member's page switching to a different FEC candidacy changes which race
    # the money and the "View full FEC filing" link describe.
    flips = []
    for bio, cid in (new.get("byBioguideId") or {}).items():
        was = (old.get("byBioguideId") or {}).get(bio)
        if was and was != cid:
            flips.append(f"- **{nc.get(cid, {}).get('name', bio)}** ({bio}): "
                         f"`{was}` [{oc.get(was, {}).get('office', '?')}] → "
                         f"`{cid}` [{nc.get(cid, {}).get('office', '?')}]")
    if flips:
        sections.append(("Preferred filing changed", flips))

    # Totals appearing or vanishing is the headline number on a member's page
    # going from a figure to "No current FEC filing found", or back.
    appeared, vanished, moved = [], [], []
    for cid in sorted(set(nc) | set(oc)):
        n, o = describe(nc.get(cid, {})), describe(oc.get(cid, {}))
        if cid not in oc or cid not in nc:
            continue        # roster churn, covered below
        if o["raised"] is None and n["raised"] is not None:
            appeared.append(f"- **{n['name']}** (`{cid}`): now {money(n['raised'])}")
        elif o["raised"] is not None and n["raised"] is None:
            vanished.append(f"- **{n['name']}** (`{cid}`): was {money(o['raised'])}, now none")
        elif shifted(o["raised"], n["raised"]):
            moved.append(f"- **{n['name']}** (`{cid}`): "
                         f"{money(o['raised'])} → {money(n['raised'])}")
    if appeared:
        sections.append(("Totals appeared", appeared))
    if vanished:
        sections.append((f"Totals vanished — check these first", vanished))
    if moved:
        sections.append((f"Totals moved more than {MATERIAL_SHIFT:.0%}", moved))

    # A committee change is how a re-designation or a new campaign shows up.
    #
    # A field that did not exist last week is not a change. When committeeName and
    # committeeDesignation were introduced, every candidate whose committee was
    # otherwise untouched read as `C00x [?] -> C00x [P]`: 209 of the 226 lines in
    # the first report, which buried the 17 real ones. So a designation only counts
    # as changed when BOTH sides carry one; absent-to-present on an unchanged
    # committee is the schema catching up, not the FEC saying anything.
    cmte = []
    for cid in sorted(set(nc) & set(oc)):
        n, o = describe(nc[cid]), describe(oc[cid])
        committee_moved = n["committee"] != o["committee"]
        redesignated = (o["designation"] and n["designation"]
                        and n["designation"] != o["designation"])
        if not (committee_moved or redesignated):
            continue
        cmte.append(f"- **{n['name']}** (`{cid}`): "
                    f"`{o['committee']}` [{o['designation'] or '?'}] → "
                    f"`{n['committee']}` [{n['designation'] or '?'}]")
    if cmte:
        sections.append(("Filing committee changed", cmte))

    # Roster churn, and the incumbent coverage the old hard floor used to gate on.
    added, removed = sorted(set(nc) - set(oc)), sorted(set(oc) - set(nc))
    if added or removed:
        lines = []
        if added:
            lines.append(f"- {len(added)} added: " +
                         ", ".join(f"{nc[c].get('name', c)} (`{c}`)" for c in added[:8]) +
                         (" …" if len(added) > 8 else ""))
        if removed:
            lines.append(f"- {len(removed)} removed: " +
                         ", ".join(f"{oc[c].get('name', c)} (`{c}`)" for c in removed[:8]) +
                         (" …" if len(removed) > 8 else ""))
        sections.append(("Candidates added or removed", lines))

    n_bio, o_bio = len(new.get("byBioguideId") or {}), len(old.get("byBioguideId") or {})
    if n_bio != o_bio:
        sections.append(("Incumbents mapped to a bioguide ID",
                         [f"- {o_bio} → {n_bio}"]))
    return sections


def render(path, sections):
    out = [f"## FEC data: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is a change the FEC can legitimately report, so none of "
                   "them blocked the update — the data is committed. They are here "
                   "because they change what a reader sees on a member's page.")
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
                    help="report a catastrophic shrink instead of failing on it. For a "
                         "human who has inspected the rejected file and confirmed the "
                         "drop is real — never the default, or the check means nothing.")
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
    print(f"Tier 1 passed: {len(new['candidates'])} candidates, indexes agree with "
          f"preferred_filing(), no orphaned totals.")

    old = baseline(args.path, args.baseline_ref)

    shrink = collapse(new, old)
    if shrink:
        stream = sys.stdout if args.allow_collapse else sys.stderr
        print("\nCOLLAPSE CHECK: the file is self-consistent but far smaller than "
              "the committed one:", file=stream)
        for e in shrink:
            print(f"  - {e}", file=stream)
        if not args.allow_collapse:
            print("\nRefusing to commit. Every surviving record here is internally "
                  "valid, so this is what a half-failed fetch looks like — check the "
                  "run log for rate-limit backoffs before anything else. The rejected "
                  "file is uploaded as a workflow artifact. If the drop is real, "
                  "re-dispatch with allow_collapse=true.", file=stream)
            return 1
        print("\nallow_collapse was set, so this is a warning and the file will be "
              "committed.", file=stream)

    sections = tier2(new, old)
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} material change(s) — reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
