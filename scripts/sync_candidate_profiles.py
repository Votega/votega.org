#!/usr/bin/env python3
"""
Reconcile a candidate's profile across the phases of their own race.

races.json stores a candidate once per phase rather than once per person, so the
same human appears as two or three objects that are only kept in step by hand.
RECURRING-TASKS tells the maintainer to curate profiles "for the next phase", so
curation lands on the phase being edited and the earlier copies keep whatever
they had. The result, before this script existed:

    88 candidates with a bio in one phase and none in another
    47 the same for a photo, 21 for a website, 5 for an email
    34 whose name is spelled differently depending on the phase
       (`Madison Fain Barton` in the primary, `Matt Barton` in the general)

That last one is visible: candidate.html resolves `?candidate=<id>` by scanning
phases in activePhase-first order, so the same URL renders a different name
depending on which phase the race is currently in.

The real fix is structural — one `people` map per race, with phases holding only
ballot membership. That is a schema change touching every consumer. This is the
backstop until then, in the same spirit as apply_overrides.py: run it after any
programmatic edit to races.json, and the copies cannot silently disagree.

Two rules, because the fields differ in kind:

  LATEST_WINS   Editorial content — bio, photo, website, email, display name.
                The most recently curated phase wins, which is the latest one
                carrying a value, because that is the order curation happens in.
  FILL_ONLY     Identity — the member record a candidate resolves to. A gap is
                filled from a sibling phase, but a value that is already set is
                never overwritten: those are pinned deliberately (see
                ga-race-candidate-overrides.json).

`type` is deliberately NOT synced. 204 candidates say `challenger` in the
primary and `incumbent` in the general, and race.html gates real rendering
decisions on it, so reconciling it changes what those pages show rather than
just what they store. It needs its own change.

Usage:
    python scripts/sync_candidate_profiles.py            # write
    python scripts/sync_candidate_profiles.py --check    # exit 1 if out of step
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RACES = Path("assets/data/races.json")
RESULTS_DIR = Path("_data/election_results")

# Name changes that lose a name part — reported, never silent. See
# dropped_name_parts() for why these matter.
NAME_LOSSES = []

# Chronological, so "latest" means "most recently curated". A GA-13-style
# special election sits between the primary and its own runoff.
PHASE_ORDER = {"primary": 0, "special": 1, "runoff": 2, "general": 3}

LATEST_WINS = ("name", "bio", "imageUrl", "website", "email")
FILL_ONLY = ("existingMemberId", "existingMemberSource", "memberId",
             "memberSource", "isIncumbent")


def phase_candidates(phase_data):
    """Every candidate object on a phase. races.json has two shapes — `ballots`
    (party -> [candidates]) and a flat `candidates` array."""
    for cands in (phase_data.get("ballots") or {}).values():
        for c in cands or []:
            if isinstance(c, dict):
                yield c
    for c in phase_data.get("candidates") or []:
        if isinstance(c, dict):
            yield c


def is_set(value):
    return value not in (None, "")


def name_tokens(name):
    n = (name or "").lower().replace("'", "").replace("\u2019", "")
    n = re.sub(r'"[^"]*"', " ", n)
    n = re.sub(r"\([^)]*\)", " ", n)
    n = re.sub(r"[^a-z\s]", " ", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v|dr|mr|mrs|ms)\b", " ", n)
    return {t for t in n.split() if len(t) > 1}


def match_keys(name):
    """"<given> <surname>" for every given name, mirroring how the results pages
    link a candidate to their profile (nameKeys in _layouts/election_results.html).
    An approximation — it skips the diminutives table — used only to spot a name
    change that would *lose* a match it already had."""
    tokens = sorted(name_tokens(name))
    parts = (name or "").lower().split()
    surname = None
    for token in reversed(parts):
        cleaned = {t for t in name_tokens(token)}
        if cleaned:
            surname = next(iter(cleaned))
            break
    if not surname or len(tokens) < 2:
        return set()
    return {f"{t} {surname}" for t in tokens if t != surname}


def ballot_name_keys():
    """Every candidate name the Secretary of State's results files use.

    Only files that hold counted votes. The pre-election placeholders are built
    *from* races.json, so their names are not independent evidence of what the
    ballot says — counting them would let a races.json spelling vouch for
    itself, which is exactly the check this is trying to make.
    """
    keys = set()
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                sections = json.load(f)
        except (OSError, ValueError):
            continue
        contests = [c for section in sections
                    for race in section.get("races", [])
                    for c in race.get("contests", [])]
        if not any(c.get("totalVotes") for c in contests):
            continue                     # placeholder, not a state export
        for contest in contests:
            for cand in contest.get("candidates", []):
                keys |= match_keys(cand.get("name"))
    return keys


def breaks_ballot_match(before, after, ballot_keys):
    """True when the winning spelling drops a match the losing one had.

    Scott Tippetts goes by his middle name: the primary phase called him
    `Anthony Scott Tippetts`, which matched the ballot's `Scott Tippetts`, and
    the general phase called him `Anthony Tippetts`, which does not — so taking
    the later spelling silently un-linked his name on the results page. Most
    name changes go the other way (`Madison Fain Barton` -> `Matt Barton`
    *gains* the match), which is why this compares against the real ballot
    names rather than just reporting every shortened name.

    A called name belongs in quotes — `Anthony "Scott" Tippetts` — which reads
    correctly and still matches.
    """
    if not ballot_keys:
        return False
    had = match_keys(before) & ballot_keys
    kept = match_keys(after) & ballot_keys
    return bool(had) and not kept


def reconcile(race, ballot_keys=frozenset()):
    """Sync one race in place. Returns [(candidate_id, field, before, after)]."""
    by_id = defaultdict(dict)          # candidate id -> phase name -> object
    for phase_name, phase_data in (race.get("phases") or {}).items():
        for cand in phase_candidates(phase_data):
            if cand.get("id"):
                by_id[cand["id"]][phase_name] = cand

    changes = []
    for cand_id, phases in by_id.items():
        if len(phases) < 2:
            continue
        # Oldest first, so a later phase's value overwrites an earlier one.
        ordered = sorted(phases.items(), key=lambda kv: PHASE_ORDER.get(kv[0], 99))

        for field in LATEST_WINS:
            winner = None
            for _, cand in ordered:
                if is_set(cand.get(field)):
                    winner = cand[field]
            if winner is None:
                continue
            for phase_name, cand in ordered:
                if cand.get(field) != winner:
                    if field == "name" and breaks_ballot_match(
                            cand.get(field), winner, ballot_keys):
                        NAME_LOSSES.append((race["id"], cand_id,
                                            cand.get(field), winner))
                    changes.append((race["id"], cand_id, phase_name, field,
                                    cand.get(field), winner))
                    cand[field] = winner

        for field in FILL_ONLY:
            winner = None
            for _, cand in ordered:
                if is_set(cand.get(field)):
                    winner = cand[field]
                    break                      # earliest set value wins a gap-fill
            if winner is None:
                continue
            for phase_name, cand in ordered:
                if not is_set(cand.get(field)):
                    changes.append((race["id"], cand_id, phase_name, field,
                                    cand.get(field), winner))
                    cand[field] = winner

    return changes


def main():
    check_only = "--check" in sys.argv

    with open(RACES, encoding="utf-8") as f:
        data = json.load(f)

    ballot_keys = ballot_name_keys()
    all_changes = []
    for race in data.get("races", []):
        all_changes.extend(reconcile(race, ballot_keys))

    if not all_changes:
        print("Every multi-phase candidate already agrees with itself.")
        return 0

    by_field = defaultdict(int)
    for _, _, _, field, _, _ in all_changes:
        by_field[field] += 1
    print(f"{len(all_changes)} field(s) out of step across "
          f"{len({(r, c) for r, c, _, _, _, _ in all_changes})} candidate(s):")
    for field, n in sorted(by_field.items(), key=lambda kv: -kv[1]):
        print(f"    {field:22s} {n}")

    names = [c for c in all_changes if c[3] == "name"]
    if names:
        print("\n  name changes:")
        for race_id, cand_id, phase, _, before, after in names:
            print(f"    {race_id} {cand_id} [{phase}]: {before!r} -> {after!r}")

    if NAME_LOSSES:
        print(f"\n  WARNING: {len(NAME_LOSSES)} name change(s) lose a match against "
              f"the Secretary of State's ballot name, so the results pages will stop "
              f"linking that name to its profile. Put the called name in quotes "
              f"instead, e.g. Anthony \"Scott\" Tippetts:")
        for race_id, cand_id, before, after in NAME_LOSSES:
            print(f"    {race_id} {cand_id}: {before!r} -> {after!r}")

    if check_only:
        print("\nOut of step. Re-run without --check to reconcile.")
        return 1

    with open(RACES, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nWrote: {RACES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
