#!/usr/bin/env python3
"""Validate current-members.json and the federal sponsorship artifacts.

Gate on self-consistency, report on change. Two kinds of wrong can come out of a
run, and conflating them is how a validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A `metadata.count` that disagrees with
  the member list it counts, a member missing a field the schema requires, an
  index entry naming a bioguide ID the roster does not hold, a slice whose row
  count disagrees with the inline summary written in the same run, more seats
  than Congress has. No fact about Congress can make any of these legitimately
  true, so they mean the generator is broken and nothing may be committed.
  These exit 1.

  Tier 2 — the file disagrees with yesterday's, or with a full house. Seats are
  vacant, Congress.gov dropped a member's detail fetch, a brand-new Congress has
  barely any bills introduced yet. Every one of these is something the world can
  legitimately do, and the site exists to publish exactly that. These are
  REPORTED, never gated.

The gates this replaces were on the wrong side of that line in three places,
and all three are on a DAILY job whose regenerated file dies with the runner:

  * `assert count >= 500` — a floor on a number the world controls. Under it the
    whole day's refresh is discarded rather than published as the fact it is.
  * `assert failures <= max(5, count * 0.05)` — a Congress.gov detail-endpoint
    outage is upstream weather, not a bug in this repo. Gating on it throws away
    the ~500 members who DID enrich.
  * `assert s is not None` on every Georgia member's inline sponsorship summary
    — this one gates on a degraded state the pipeline DESIGNS FOR.
    `fetch_member_legislation()` deliberately returns None rather than a
    truncated list when one page of a member's record fails, the writer then
    leaves that member out, and the entity page reads a null summary as "no
    tab". One flaky page for one of sixteen members aborted the job before the
    commit step and discarded the other fifteen members' fresh records plus the
    entire 500-member roster.

Counts ABOVE a fixed maximum stay a hard failure: 600 members of Congress or 17
Georgia seats is not a fact about the world, it is a broken filter or a
double-applied merge.

See docs/audits/2026-10-13-data-pipeline-audit.md 2.6 for this class of
validator repo-wide, scripts/validate_fec_data.py for the reference
implementation, and the comment above the "Validate output" step of
update-local-government.yml for the first workflow to make the split.

Usage:
    python scripts/validate_current_members.py --data-dir assets/data \
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

# 435 representatives + 100 senators + the 6 non-voting delegates and the
# resident commissioner that Congress.gov's current-members list includes.
# These are the seats that EXIST: the count may legitimately sit below, never
# above.
SEATS_MAX = 541

# Georgia's apportionment: 14 House districts + 2 Senate seats. Same rule — a
# vacancy takes the delegation below 16, nothing takes it above.
GA_SEATS_MAX = 16

# `recentSponsored` is a convenience slice republished to the sibling repo. The
# cap is in the generator, so exceeding it is a code bug, not a fact.
RECENT_CAP = 20

ROSTER_REQUIRED = ("bioguideId", "name", "partyName", "state", "terms")

# Below this many records across the whole delegation, a reader's Sponsored
# Legislation panel looks broken — but so does a Congress that convened three
# weeks ago, which is why this reports rather than gates.
SPONSORED_FLOOR = 100
COSPONSORED_FLOOR = 500


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


def georgia(roster):
    return [m for m in (roster.get("members") or []) if m.get("state") == "Georgia"]


# ── tier 1: the artifacts against themselves ──────────────────────────────────

def tier1(roster, index, slices):
    """Return a list of contradictions. Empty means the set is self-consistent.

    `slices` maps bioguideId -> the parsed slice, or None when the file the
    index promises is missing or unreadable.
    """
    errors = []
    members = roster.get("members") or []
    meta = roster.get("metadata") or {}

    if not members:
        errors.append("no members in current-members.json")
        return errors          # nothing below can say anything useful

    count = meta.get("count")
    if count != len(members):
        errors.append(f"metadata.count ({count}) != len(members) ({len(members)})")

    if len(members) > SEATS_MAX:
        errors.append(f"{len(members)} members, more than the {SEATS_MAX} seats that "
                      f"exist — the roster is double-counting")

    for m in members:
        missing = [f for f in ROSTER_REQUIRED if f not in m]
        if missing:
            errors.append(f"member {m.get('name', '?')!r} is missing required "
                          f"field(s): {', '.join(missing)}")

    # Two rows for one bioguide ID is the same contradiction seen from the other
    # side, and it names the collision. The ID is the join key every entity page
    # and both sponsorship artifacts key on.
    seen = {}
    for m in members:
        bid = m.get("bioguideId")
        if bid:
            seen.setdefault(bid, []).append(m.get("name", "?"))
    dups = {bid: names for bid, names in seen.items() if len(names) > 1}
    if dups:
        errors.append(f"duplicate bioguideId(s): {dups}")

    # Chamber is read off the LAST term, so an empty terms list leaves the site
    # unable to say whether a member is a Senator.
    termless = [m.get("name", "?") for m in members
                if not ((m.get("terms") or {}).get("item") or [])][:5]
    if termless:
        errors.append(f"member(s) with no terms.item, so no chamber can be derived: {termless}")

    ga = georgia(roster)
    if len(ga) > GA_SEATS_MAX:
        errors.append(f"{len(ga)} Georgia members, more than the {GA_SEATS_MAX} seats "
                      f"Georgia holds — the delegation filter is double-counting")

    errors += _tier1_sponsorship(roster, index, slices)
    return errors


def _tier1_sponsorship(roster, index, slices):
    errors = []
    if index is None:
        errors.append("federal-sponsorship-index.json was not generated")
        return errors

    meta = index.get("metadata") or {}
    counts = index.get("members")
    if counts is None:
        errors.append("the sponsorship index has no `members` object")
        return errors

    # Fields the index must carry about its own run. The entity panel stamps its
    # provenance line from generatedAt and rebuilds every bill URL from congress.
    for field in ("congress", "generatedAt"):
        if not meta.get(field):
            errors.append(f"the sponsorship index carries no {field}")

    if counts and len(counts) != meta.get("memberCount"):
        errors.append(f"index metadata.memberCount ({meta.get('memberCount')}) != "
                      f"{len(counts)} count entries")

    ga = georgia(roster)
    ga_by_id = {m.get("bioguideId"): m for m in ga if m.get("bioguideId")}
    if len(counts) > GA_SEATS_MAX:
        errors.append(f"the index holds {len(counts)} members, more than Georgia's "
                      f"{GA_SEATS_MAX} seats")

    # An index entry for someone the roster does not hold points outside the
    # data it describes.
    stray = sorted(set(counts) - set(ga_by_id))[:5]
    if stray:
        errors.append(f"index entries for bioguide ID(s) not in the Georgia roster: {stray}")

    # A member the roster says sponsored things, with nothing published for them,
    # is the one case CLAUDE.md calls "a real failure": the roster and the slices
    # are written in the SAME run, so they cannot legitimately disagree. A member
    # whose summary is null is the designed degraded state and belongs to tier 2.
    for bid, m in sorted(ga_by_id.items()):
        name = m.get("name", bid)
        s = m.get("sponsorship")
        if s is None:
            if bid in counts:
                errors.append(f"{name}: the index publishes counts {counts[bid]} but the "
                              f"roster's inline summary is null — the two disagree")
            continue

        if s.get("congress") != meta.get("congress"):
            errors.append(f"{name}: inline summary is for Congress {s.get('congress')}, "
                          f"the index for {meta.get('congress')}")
        if bid not in counts:
            errors.append(f"{name}: carries a sponsorship summary but has no index entry")
            continue
        want = [s.get("sponsored"), s.get("cosponsored")]
        if counts[bid] != want:
            errors.append(f"{name}: index {counts[bid]} != inline summary {want}")

        sl = slices.get(bid)
        if sl is None:
            errors.append(f"{name}: the index promises a slice but "
                          f"federal-sponsorship/{bid}.json is missing or unreadable")
            continue
        for key, n in (("primary", s.get("sponsored")), ("cosponsored", s.get("cosponsored"))):
            rows = sl.get(key)
            if rows is None:
                errors.append(f"{name}: slice has no `{key}` list")
            elif len(rows) != n:
                errors.append(f"{name}: slice {key} holds {len(rows)} rows, "
                              f"summary says {n}")
        # Positional rows: 7 fields, and the first three (type, number, title) are
        # what the panel renders, so a blank one publishes an unreadable entry.
        for row in ((sl.get("primary") or []) + (sl.get("cosponsored") or []))[:50]:
            if len(row) != 7:
                errors.append(f"{name}: slice row is not 7 fields: {row}")
            elif not (row[0] and row[1] and row[2]):
                errors.append(f"{name}: slice row missing type/number/title: {row}")

        recent = m.get("recentSponsored") or []
        if len(recent) > RECENT_CAP:
            errors.append(f"{name}: recentSponsored holds {len(recent)} rows, more than "
                          f"the {RECENT_CAP} the generator caps it at")
        elif len(recent) != min(RECENT_CAP, s.get("sponsored") or 0):
            errors.append(f"{name}: recentSponsored holds {len(recent)} rows, not the "
                          f"min({RECENT_CAP}, {s.get('sponsored')}) its own summary implies")

    # The index's own totals, against the entries it holds.
    if counts:
        for field, pos in (("totalSponsored", 0), ("totalCosponsored", 1)):
            got = sum(c[pos] for c in counts.values() if len(c) > pos)
            if meta.get(field) != got:
                errors.append(f"index metadata.{field} ({meta.get(field)}) != {got} "
                              f"summed over its own entries")

    # An index with nothing in it, while the roster says members sponsored
    # measures, would publish an empty panel over a populated record.
    if not counts and any(m.get("sponsorship") for m in ga):
        errors.append("the sponsorship index is empty but the roster carries "
                      "sponsorship summaries")
    return errors


# ── tier 2: a full house, an upstream outage, and yesterday's file ────────────

def tier2(roster, index, old_roster=None, old_index=None):
    """Material facts and changes, as (heading, [lines]) sections."""
    sections = []
    members = roster.get("members") or []
    meta = roster.get("metadata") or {}
    ga = georgia(roster)

    # The condition `assert count >= 500` used to gate on. Vacancies are a fact
    # about Congress, and the one thing a mid-term resignation looks like.
    if len(members) < SEATS_MAX:
        sections.append(("Congress below a full house", [
            f"- {len(members)} of {SEATS_MAX} seats filled "
            f"({SEATS_MAX - len(members)} vacant or not yet seated)"]))
    if len(ga) < GA_SEATS_MAX:
        sections.append(("Georgia delegation below full strength", [
            f"- {len(ga)} of {GA_SEATS_MAX} seats filled — "
            + (", ".join(sorted(m.get("name", "?") for m in ga)) or "no Georgia members at all, "
               "which would mean the state filter broke")]))

    # An upstream outage, which the old assert turned into a discarded day.
    failures = meta.get("enrichmentFailures") or 0
    if failures:
        sections.append(("Congress.gov detail fetches that failed", [
            f"- {failures} of {len(members)} members did not enrich. Their rows are "
            f"published from the list endpoint alone, so committees, contact info "
            f"and portraits may be stale for them until the next run."]))

    # The designed degraded state: a null summary means one page of that member's
    # record failed and the writer refused to publish a truncated list.
    nulls = [m.get("name", "?") for m in ga if m.get("sponsorship") is None]
    if nulls:
        sections.append(("Sponsorship record not published this run", [
            "- " + ", ".join(sorted(nulls)),
            "",
            "A failed page discards that member's whole list on purpose — a "
            "truncated list is indistinguishable from a real one and would publish "
            "as fact that they sponsored less than they did. Their entity page "
            "hides the Sponsored Legislation tab until the next run fills it in."]))

    imeta = (index or {}).get("metadata") or {}
    total_s, total_c = imeta.get("totalSponsored") or 0, imeta.get("totalCosponsored") or 0
    if total_s < SPONSORED_FLOOR or total_c < COSPONSORED_FLOOR:
        sections.append(("Delegation sponsorship record is thin", [
            f"- {total_s} sponsored (reporting under {SPONSORED_FLOOR}) and {total_c} "
            f"cosponsored (under {COSPONSORED_FLOOR}) across the delegation in the "
            f"{imeta.get('congress', '?')}th Congress.",
            "",
            "Worth a look, but NOT a failure: a Congress that convened weeks ago "
            "legitimately has almost nothing introduced yet, and gating on this "
            "would make every January run discard the roster."]))

    if old_roster:
        nm = {m.get("bioguideId"): m for m in members if m.get("bioguideId")}
        om = {m.get("bioguideId"): m for m in (old_roster.get("members") or [])
              if m.get("bioguideId")}
        added, removed = sorted(set(nm) - set(om)), sorted(set(om) - set(nm))
        if added or removed:
            lines = [f"- added: **{nm[b].get('name', b)}** ({nm[b].get('state', '?')}) `{b}`"
                     for b in added]
            lines += [f"- removed: **{om[b].get('name', b)}** ({om[b].get('state', '?')}) `{b}`"
                      for b in removed]
            sections.append(("Members added or removed", lines))

        # Party and state are what a reader sees on the member's page and in the
        # majority arithmetic; a party switch is rare and worth a human's eye.
        for field, heading in (("partyName", "Party changed"), ("state", "State changed")):
            lines = [f"- **{nm[b].get('name', b)}**: {om[b].get(field)} → {nm[b].get(field)}"
                     for b in sorted(set(nm) & set(om))
                     if om[b].get(field) != nm[b].get(field)]
            if lines:
                sections.append((heading, lines))

    if old_index:
        o = (old_index.get("metadata") or {})
        was, now = o.get("congress"), imeta.get("congress")
        if was and now and was != now:
            sections.append(("Congress rolled over", [
                f"- the sponsorship record now covers the {now}th Congress, was the "
                f"{was}th. Every member's record starts near zero again."]))
        for bid, c in sorted((old_index.get("members") or {}).items()):
            new_c = (index or {}).get("members", {}).get(bid)
            if new_c is None:
                sections.append(("Sponsorship slice dropped", [
                    f"- `{bid}` had {c} last run and has no slice now"]))
            elif len(c) == len(new_c) == 2 and (new_c[0] < c[0] or new_c[1] < c[1]):
                sections.append(("Sponsorship counts went down", [
                    f"- `{bid}`: {c} → {new_c}. Counts only fall when a Congress rolls "
                    f"over or a fetch came back short."]))
    return sections


def render(sections):
    out = ["## Federal members and sponsorship: what changed", ""]
    if not sections:
        out.append("A full house, every member enriched, and no material change this run.")
    else:
        out.append("Each line is something the world (or Congress.gov) can legitimately "
                   "do, so none of them blocked the update — the data is committed. They "
                   "are here because they change what a reader sees on a member's page.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def read_slices(data_dir, index):
    """Parse every slice the index promises; None marks one we could not read."""
    slices = {}
    for bid in (index or {}).get("members") or {}:
        path = os.path.join(data_dir, "federal-sponsorship", f"{bid}.json")
        try:
            slices[bid] = load(path)
        except (OSError, json.JSONDecodeError):
            slices[bid] = None
    return slices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="assets/data")
    ap.add_argument("--baseline-ref", default="HEAD",
                    help="git ref to diff the new files against (default HEAD)")
    ap.add_argument("--report-out", help="write the tier-2 markdown report here")
    args = ap.parse_args()

    roster_path = os.path.join(args.data_dir, "current-members.json")
    index_path = os.path.join(args.data_dir, "federal-sponsorship-index.json")

    if not os.path.exists(roster_path):
        print(f"FAIL: {roster_path} was not generated", file=sys.stderr)
        return 1
    try:
        roster = load(roster_path)
    except json.JSONDecodeError as exc:
        print(f"FAIL: {roster_path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    index = None
    if os.path.exists(index_path):
        try:
            index = load(index_path)
        except json.JSONDecodeError as exc:
            print(f"FAIL: {index_path} is not valid JSON: {exc}", file=sys.stderr)
            return 1

    errors = tier1(roster, index, read_slices(args.data_dir, index))
    if errors:
        print("TIER 1 FAILED — the data contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in the data. The rejected files "
              "are uploaded as a workflow artifact so they can be inspected.",
              file=sys.stderr)
        return 1

    ga = georgia(roster)
    imeta = (index or {}).get("metadata") or {}
    print(f"Tier 1 passed: {len(roster['members'])} members (metadata.count agrees, "
          f"required fields present, no duplicate bioguide IDs, every member has a "
          f"term), {len(ga)} from Georgia, and "
          f"{len((index or {}).get('members') or {})} sponsorship slices whose rows "
          f"agree with the inline summaries "
          f"({imeta.get('totalSponsored')} sponsored + "
          f"{imeta.get('totalCosponsored')} cosponsored).")

    sections = tier2(roster, index,
                     baseline(roster_path, args.baseline_ref),
                     baseline(index_path, args.baseline_ref))
    report = render(sections)
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
