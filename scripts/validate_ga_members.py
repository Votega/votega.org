#!/usr/bin/env python3
"""Validate ga-members.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of a roster run, and conflating them is how a
validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A `metadata.count` that disagrees with
  the member list it counts, a member missing a field the schema requires, two
  members holding the same district in the same chamber, a chamber holding MORE
  seats than the Georgia Constitution creates, an `_inject` entry the merge
  failed to apply. No fact about the General Assembly can make any of these
  legitimately true, so they mean the producer is broken and the file must not
  be committed. These exit 1.

  Tier 2 — the file disagrees with yesterday's file, or with full strength. A
  seat is vacant, a member resigned, a district or a party changed. Every one of
  these is something Georgia can legitimately do, and the site exists to publish
  exactly that. These are REPORTED, never gated.

The distinction matters because the gate this replaces was on the wrong side of
it. update-ga-members.yml asserted `len(senate) == 56` and `len(house) == 180`
— exact equality on a number the world controls. The chamber sizes are fixed at
full strength, but a death, a resignation or a seat awaiting a special election
makes the real count lower, and that is a true fact the site should publish. When
the assert fired, the validation step exited non-zero, the job aborted before the
commit step, and the entire day's refresh was discarded — every other member's
updated data along with it, unrecoverably, since the file dies with the runner.
This runs daily, and Georgia ran a GA-13 special election days before this was
written.

Counts ABOVE the maximum stay a hard failure: 181 House members is not a fact
about Georgia, it is a broken join or a double-applied override.

See docs/audits/2026-10-13-data-pipeline-audit.md 2.6 for this class of
validator repo-wide, scripts/validate_fec_data.py for the reference
implementation, and the comment above the "Validate output" step of
update-local-government.yml for the first workflow to make the split.

Usage:
    python scripts/validate_ga_members.py assets/data/ga-members.json \
        --overrides assets/data/ga-members-overrides.json \
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
from lib.ga_roster import injects_for_session  # noqa: E402  (stdlib-only module)

# Georgia's General Assembly has a constitutionally fixed size. These are the
# seats that EXIST, not the seats that are filled: the count may legitimately sit
# below them, never above.
CHAMBER_MAX = {"Senate": 56, "House of Representatives": 180}

# Resigned/Removed/Deceased entries are historical records, kept so
# ga-member-votes.json can still join their earlier votes by OCD id — the seat
# itself is already reflected by a successor or by a separate Vacant entry, so
# they must not count as an extra current seat. "Suspended" members still hold
# the seat (badged, not removed) and "Vacant" entries are injected placeholders
# standing in for one, so both DO count. This is deliberately NOT
# lib.ga_voters.DEPARTED_STATUSES, which includes "Vacant" because its callers
# are asking "who can cast a vote", a different question from "which seats are
# accounted for".
DEPARTED_STATUSES = {"Resigned", "Removed", "Deceased"}

REQUIRED_FIELDS = ("id", "name", "chamber", "district")


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


def current_seat(m):
    return m.get("status") not in DEPARTED_STATUSES


def seated(members, chamber):
    """The entries accounted against `chamber`'s fixed seat count."""
    return [m for m in members if m.get("chamber") == chamber and current_seat(m)]


def label(m):
    d = m.get("district")
    return f"{m.get('name', '?')}" + (f" (district {d})" if d is not None else "")


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d, overrides=None, old=None):
    """Return a list of contradictions. Empty means the file is self-consistent.

    `old` is the committed file, used for exactly one check (an unacknowledged biennium
    changeover) — see the comment there for why that one is tier 1.
    """
    errors = []
    members = d.get("members") or []
    meta = d.get("metadata") or {}

    if not members:
        errors.append("no members in the file")
        return errors   # nothing below can say anything useful

    count = meta.get("count")
    if count != len(members):
        errors.append(f"metadata.count ({count}) != len(members) ({len(members)})")

    # A missing required field is a silent JS failure downstream, so it is caught
    # here rather than on the site.
    for m in members:
        missing = [f for f in REQUIRED_FIELDS if f not in m]
        if missing:
            errors.append(f"member {m.get('name', '?')!r} is missing required "
                          f"field(s): {', '.join(missing)}")

    for chamber, maximum in CHAMBER_MAX.items():
        here = seated(members, chamber)

        # MORE seats than the constitution creates cannot be a fact about
        # Georgia — it is a broken join, a duplicated member, or an override
        # applied twice. Fewer is an ordinary vacancy, and is tier 2.
        if len(here) > maximum:
            errors.append(f"{chamber} holds {len(here)} current seats, more than the "
                          f"{maximum} that exist — the roster is double-counting")

        # Two members in one district is the same contradiction seen from the
        # other side, and it names who collided.
        seen = {}
        for m in here:
            dist = m.get("district")
            if dist is None:
                continue
            seen.setdefault(dist, []).append(m.get("name", "?"))
        dups = {dist: names for dist, names in seen.items() if len(names) > 1}
        if dups:
            errors.append(f"{chamber}: duplicate district(s): {dups}")

    # An `_inject` entry absent from the output means the editorial layer did not
    # apply — and that layer is the only thing that knows a member has left, so a
    # silent miss republishes a departed member as sitting.
    #
    # Only the entries IN SCOPE for this file's biennium are owed: an `_inject` tagged
    # `_session` for another biennium is inert by design (a 2025-26 Resigned must not
    # re-seat in 2027-28), and demanding it would turn every rollover into a hard block.
    # An untagged entry applies to every biennium, so it is still demanded — leaving one
    # behind fails loudly here rather than silently departing the wrong seat.
    if overrides:
        ids = {m.get("id") for m in members}
        orphaned = [e.get("id") for e in injects_for_session(overrides, meta.get("session"))
                    if e.get("id") not in ids]
        if orphaned:
            errors.append(f"_inject entries missing from the output (the merge "
                          f"failed to apply): {orphaned}")

    # A different biennium from the committed file, with no rollover acknowledgement in
    # the file. Tier 1 although it compares two files: the real-world event (a new General
    # Assembly) is tier 2, but the producer only ever emits this shape by republishing the
    # outgoing class as sitting — nothing true about Georgia produces it — and the
    # symptom is the "more than N seats" error above, hundreds of lines from the cause.
    # Naming the cause here is the point. A rollover run stamps `metadata.rollover`.
    was = ((old or {}).get("metadata") or {}).get("session")
    if was and meta.get("session") and was != meta["session"] and not meta.get("rollover"):
        errors.append(f"biennium changed from {was} to {meta['session']} with no "
                      f"`metadata.rollover` — the roster was not built in rollover mode "
                      f"(generate_ga_members_soap.py --new-biennium), so the outgoing "
                      f"class is likely still in it")

    return errors


# ── tier 2: full strength, and the file against yesterday's ───────────────────

def under_strength(d):
    """Seats the constitution creates that the roster does not account for.

    Reported, not gated: this is the condition the old exact-equality assert
    treated as a failure, and it is the one thing a vacancy looks like.
    """
    members = d.get("members") or []
    lines = []
    for chamber, maximum in CHAMBER_MAX.items():
        here = seated(members, chamber)
        if len(here) >= maximum:
            continue
        held = {m.get("district") for m in here if m.get("district") is not None}
        gaps = [n for n in range(1, maximum + 1) if n not in held]
        line = (f"- **{chamber}**: {len(here)} of {maximum} seats accounted for "
                f"({maximum - len(here)} short)")
        if gaps:
            line += "; district(s) with no entry: " + ", ".join(str(g) for g in gaps[:12])
            if len(gaps) > 12:
                line += " …"
        lines.append(line)
    return lines


def by_id(d):
    return {m.get("id"): m for m in (d.get("members") or []) if m.get("id")}


def with_context(new, sections):
    """Append the standing status roster — but only to a report that already says something.

    Every member who has ever left the 2025-26 biennium keeps an entry here, so
    this list is a dozen lines long on a day when nothing whatsoever happened.
    It is useful CONTEXT next to a vacancy (the departure that caused it, with
    the date to check against the Governor's writ-of-election executive orders)
    and useful for confirming the overrides layer is current — but it is standing
    state, not news, so it must never be the reason a report exists. As its own
    section it would make every single daily run produce a non-empty report,
    which would open and refresh a tracking issue forever and turn the one thing
    a human is supposed to read into noise they learn to ignore.
    """
    if not sections:
        return sections
    flagged = [m for m in (new.get("members") or []) if m.get("status")]
    if not flagged:
        return sections
    return sections + [("For reference: members carrying a status", [
        f"- **{m.get('name', '?')}** ({m.get('chamber', '?')}, district "
        f"{m.get('district', '?')}): {m['status']}"
        + (f" as of {m['statusDate']}" if m.get("statusDate") else "")
        for m in sorted(flagged, key=lambda m: (m.get("chamber", ""), m.get("name", "")))
    ])]


def tier2(new, old):
    """Material facts and changes, as (heading, [lines]) sections."""
    sections = []

    short = under_strength(new)
    if short:
        sections.append(("Chamber below full strength", short))

    roll = (new.get("metadata") or {}).get("rollover")
    if roll:
        rv = new.get("review") or {}
        sections.append(("Biennium rollover", [
            f"- {roll['from']['session']} → {roll['to']['session']}: "
            f"{roll.get('incoming', 0)} incoming, {roll.get('departing', 0)} departing",
            f"- {len(rv.get('newMemberNameReview') or [])} new member name(s) to review "
            f"BEFORE the first entity-page build (the entity URL slugs on the name)",
            f"- {roll.get('outOfScopeOverrides', 0)} override entr(ies) belong to "
            f"{roll['from']['session']} and were skipped",
        ]))

    if not old:
        return with_context(new, sections)

    nm, om = by_id(new), by_id(old)

    added, removed = sorted(set(nm) - set(om)), sorted(set(om) - set(nm))
    if added or removed:
        lines = []
        for mid in added:
            lines.append(f"- added: **{nm[mid].get('name', mid)}** "
                         f"({nm[mid].get('chamber', '?')}, district "
                         f"{nm[mid].get('district', '?')}) `{mid}`")
        for mid in removed:
            lines.append(f"- removed: **{om[mid].get('name', mid)}** "
                         f"({om[mid].get('chamber', '?')}, district "
                         f"{om[mid].get('district', '?')}) `{mid}`")
        sections.append(("Members added or removed", lines))

    # Party, district and status are the fields that change what a reader sees —
    # on a member's page, in the county lookup, and in the majority tracker.
    for field, heading in (("party", "Party changed"),
                           ("district", "District changed"),
                           ("chamber", "Chamber changed"),
                           ("status", "Status changed")):
        lines = []
        for mid in sorted(set(nm) & set(om)):
            was, now = om[mid].get(field), nm[mid].get(field)
            if was != now:
                lines.append(f"- **{nm[mid].get('name', mid)}**: "
                             f"{was if was is not None else '—'} → "
                             f"{now if now is not None else '—'}")
        if lines:
            sections.append((heading, lines))

    return with_context(new, sections)


def render(path, sections):
    out = [f"## GA roster: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("Both chambers at full strength and no material change this run.")
    else:
        out.append("Each line is something Georgia can legitimately do, so none of them "
                   "blocked the update — the data is committed. They are here because "
                   "they change what a reader sees, and because a vacancy or a "
                   "departure has to be confirmed against the Governor's writ-of-"
                   "election executive orders and the overrides file.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--overrides", help="ga-members-overrides.json, to confirm _inject applied")
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

    overrides = None
    if args.overrides and os.path.exists(args.overrides):
        try:
            overrides = load(args.overrides)
        except json.JSONDecodeError as exc:
            print(f"FAIL: {args.overrides} is not valid JSON: {exc}", file=sys.stderr)
            return 1

    old = baseline(args.path, args.baseline_ref)
    errors = tier1(new, overrides, old)
    if errors:
        print("TIER 1 FAILED — the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a producer bug, not a change in the roster. The rejected file "
              "is uploaded as a workflow artifact so it can be inspected.", file=sys.stderr)
        return 1

    members = new["members"]
    print(f"Tier 1 passed: {len(members)} members, metadata.count agrees, required "
          f"fields present, no duplicate districts, neither chamber over its "
          f"constitutional size "
          f"(Senate {len(seated(members, 'Senate'))}/{CHAMBER_MAX['Senate']}, "
          f"House {len(seated(members, 'House of Representatives'))}/"
          f"{CHAMBER_MAX['House of Representatives']}).")

    sections = tier2(new, old)
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
