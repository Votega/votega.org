"""
Convert ga-legislative-candidates.json into races.json entries
for all GA State House and Senate districts.

This script owns the *primary* ballot for every ga-house-* / ga-senate-* race and
rebuilds it from source on each run. Everything downstream of the primary —
`activePhase`, `phases.general`, `phases.runoff`, `primaryResult` — exists only
in races.json (set_general_candidates.py writes the general ballots) and is
carried forward on merge, never regenerated.

That merge is the point. This script previously replaced every legislative race
wholesale, which on 2026-08-17 wiped 391 promoted general-election candidates
across 236 races; it was restored from git. A run now refuses to complete if it
would reduce the post-primary candidate count.
See CODEBASE-REVIEW-2026-08-18.md finding 1.1.

Usage:
  python scripts/build_legislative_races.py
  python scripts/build_legislative_races.py --allow-loss    # accept a reduction
  python scripts/build_legislative_races.py --force-reset --allow-loss
                                                            # old behaviour:
                                                            # reset every race
                                                            # back to the primary
"""
import json, re, string, sys
from datetime import datetime, timezone
from pathlib import Path

SRC       = Path("assets/data/ga-legislative-candidates.json")
DEST      = Path("assets/data/races.json")
GA_MEMBERS = Path("assets/data/ga-members.json")
OVERRIDES  = Path("assets/data/ga-race-candidate-overrides.json")

FORCE_RESET = "--force-reset" in sys.argv
ALLOW_LOSS  = "--allow-loss" in sys.argv

# --- Cycle parameters: the one place to change at a cycle rollover (2026 -> 2028).
# Race IDs, the `cycle` field, and the phase election dates all derive from these,
# so a rollover is a three-line edit here rather than scattered literals. Mirrors
# GA_SESSION in the GA data generators. See CODEBASE-REVIEW-2026-08-18.md finding 5.9.
CYCLE        = 2026
PRIMARY_DATE = "2026-05-19"
GENERAL_DATE = "2026-11-03"

# Keys this script derives from source on every run. Anything else found on an
# existing race is downstream state and is carried forward untouched.
BUILDER_OWNED = {"id", "level", "chamber", "district", "cycle", "phases",
                 "activePhase", "_note"}


def is_legislative(race_id: str) -> bool:
    return race_id.startswith("ga-house-") or race_id.startswith("ga-senate-")


def count_candidates(phase: dict) -> int:
    """Candidates in a phase, across both shapes (`ballots` dict / `candidates` list)."""
    if not isinstance(phase, dict):
        return 0
    total = 0
    ballots = phase.get("ballots")
    if isinstance(ballots, dict):
        total += sum(len(v) for v in ballots.values() if isinstance(v, list))
    cands = phase.get("candidates")
    if isinstance(cands, list):
        total += len(cands)
    return total


def merge_race(existing: dict | None, fresh: dict) -> dict:
    """Freshly built primary + everything downstream preserved from `existing`."""
    if not existing:
        return fresh

    merged = dict(fresh)

    # Phase progression is downstream state, not something source can tell us.
    merged["activePhase"] = existing.get("activePhase", fresh["activePhase"])

    phases = dict(fresh.get("phases", {}))
    for name, prior in (existing.get("phases") or {}).items():
        if name == "primary":
            # Keep the rebuilt ballots; retain any other keys set on the phase.
            combined = dict(prior)
            combined.update(fresh["phases"]["primary"])
            phases["primary"] = combined
        elif count_candidates(prior) or name not in phases:
            # A populated general/runoff always wins over the empty stub the
            # builder emits — this is the data that used to be destroyed.
            phases[name] = prior
    merged["phases"] = phases

    # Race-level keys the builder does not produce (e.g. primaryResult).
    for k, v in existing.items():
        if k not in merged and k not in BUILDER_OWNED:
            merged[k] = v

    return merged

def title_case(name: str) -> str:
    """Convert ALL CAPS name to Title Case, handling common edge cases."""
    if not name:
        return name
    # Words that should stay lower (unless first word)
    lower_words = {"a","an","the","and","or","of","in","on","for","to","at","by","from","with"}
    words = name.lower().split()
    result = []
    for i, w in enumerate(words):
        # Always capitalize first word, single letters (initials), or non-minor words
        if i == 0 or len(w) == 1 or w not in lower_words:
            # Handle hyphenated names
            if '-' in w:
                w = '-'.join(p.capitalize() for p in w.split('-'))
            else:
                w = w.capitalize()
        result.append(w)
    return ' '.join(result)

def normalize_website(url: str) -> str:
    if not url:
        return ''
    url = url.strip()
    if not url:
        return ''
    if not url.lower().startswith('http'):
        url = 'https://' + url.lower()
    return url

def make_candidate_id(chamber_slug: str, district: int, party_slug: str, idx: int) -> str:
    return f"ga-{chamber_slug}-{district}-{CYCLE}-{party_slug}-{idx+1}"

def make_race_id(chamber_slug: str, district: int) -> str:
    return f"ga-{chamber_slug}-{district}-{CYCLE}"

def parse_district(contest_name: str):
    """Extract district number from 'State House, District 12 (D)' -> 12"""
    m = re.search(r'District\s+(\d+)', contest_name, re.IGNORECASE)
    return int(m.group(1)) if m else None

def load_member_lookup() -> dict:
    """Build (chamber_slug, district) -> member dict from ga-members.json."""
    if not GA_MEMBERS.exists():
        return {}
    with open(GA_MEMBERS, encoding="utf-8") as f:
        data = json.load(f)
    lookup = {}
    for m in data.get("members", []):
        ch = "house" if m.get("chamber") == "House of Representatives" else "senate"
        lookup[(ch, m["district"])] = m
    return lookup

def load_candidate_overrides() -> dict:
    """Load ga-race-candidate-overrides.json, stripping metadata keys."""
    if not OVERRIDES.exists():
        return {}
    with open(OVERRIDES, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}

def load_race_overrides() -> dict:
    """Load race-level overrides from the _raceOverrides block in ga-race-candidate-overrides.json."""
    if not OVERRIDES.exists():
        return {}
    with open(OVERRIDES, encoding="utf-8") as f:
        raw = json.load(f)
    block = raw.get("_raceOverrides", {})
    return {k: v for k, v in block.items() if not k.startswith("_")}

def candidate_from_row(row: dict, idx: int, chamber_slug: str, district: int, party_slug: str) -> dict:
    name = title_case(row.get("Official_FullName__c") or row.get("Name_on_Ballot__c") or "")
    is_incumbent = bool(row.get("Incumbent__c"))
    is_disqualified = (row.get("Declaration__c") or "").lower() == "disqualified"

    c = {
        "id": make_candidate_id(chamber_slug, district, party_slug, idx),
        "type": "challenger",
        "name": name,
        "party": row.get("Candidate_Party__c") or row.get("vr_Political_Party__c") or "",
        "occupation": title_case(row.get("Occupation__c") or ""),
        "county": title_case(row.get("County__c") or ""),
    }
    if is_incumbent:
        c["isIncumbent"] = True
    if is_disqualified:
        c["withdrawn"] = True

    website = normalize_website(row.get("Campaign_Website__c") or "")
    if website:
        c["website"] = website

    email = (row.get("Email__c") or "").strip().lower()
    if email:
        c["email"] = email

    return c

# Populated during build_races(); inspected by main().
REMOVED_IDS = []
REMOVAL_MISMATCHES = []
SEAT_HOLDER_MISMATCHES = []


def override_target_name(patch: dict) -> str:
    """The candidate name a `remove: true` override says it targets.

    `_name` is documentation, written as e.g.
    "Brian Lamar Prince (duplicate of d-1)" — the parenthetical is the reason,
    not part of the name.
    """
    raw = (patch.get("_name") or "").strip()
    return raw.split(" (")[0].strip()


def shares_a_name(candidate_name: str, member_name: str) -> bool:
    """True unless the two names have no name-part in common at all.

    Deliberately weaker than `names_match`. This guards a lookup that is already
    keyed on chamber and district, so the only question is "is this obviously a
    different person" — and the sources disagree about names constantly. Against
    the 420 links in races.json today, `names_match` would reject 84 correct ones
    (`Thomas Stephen Tarvin` vs `Steve Tarvin`, `Dr. Jasmine Clark` vs `Jasmine
    Clark`); requiring only the surname still rejects 7 (`Sylvia Wayfer Baker` vs
    `Sylvia Wayfer`, `Angela Butler Osteen` vs `Angie O'Steen`, `Freddie Powell`
    vs `Freddie Powell Sims`). Requiring one shared token rejects exactly the 5
    that are genuinely different people — each one a seat that changed hands,
    every one of them pointing at a member whose status is `Resigned`.

    Unlinking a real incumbent is worse than the bug being guarded against, so
    when in doubt this says yes.
    """
    def parts(name):
        n = (name or "").lower().replace("'", "").replace("\u2019", "")
        n = re.sub(r"\([^)]*\)", " ", n)              # drop "(Dem)"-style suffixes
        n = re.sub(r"[^a-z\s]", " ", n)
        n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", n)  # generational suffixes
        n = re.sub(r"\b(dr|mr|mrs|ms|rev|hon)\b", " ", n)
        return {t for t in n.split() if len(t) > 1}

    cand, seat = parts(candidate_name), parts(member_name)
    if not cand or not seat:
        return True                                   # nothing to judge on — allow
    return bool(cand & seat)


def names_match(candidate_name: str, member_name: str) -> bool:
    """Return True if candidate_name likely refers to the same person as member_name.
    Requires last name match plus first name or first-initial match."""
    cn = candidate_name.lower().split()
    mn = member_name.lower().split()
    if not cn or not mn:
        return False
    if cn[-1] != mn[-1]:  # last names must match
        return False
    return cn[0] == mn[0] or cn[0][0] == mn[0][0]  # first name or initial


def build_races(src_data: dict, member_lookup: dict, candidate_overrides: dict, race_overrides: dict = None) -> list:
    """Build list of race dicts from the collected candidate data."""
    races = []

    # Collect all districts from both parties
    # Key: (chamber_slug, district_num)  ->  { "Democrat": [rows], "Republican": [rows] }
    districts = {}

    for party_label in ("Democrat", "Republican"):
        party_slug = "d" if party_label == "Democrat" else "r"
        contests = src_data["results"].get(party_label, {})
        for contest_name, rows in contests.items():
            if "State House" not in contest_name and "State Senate" not in contest_name:
                continue
            if "Special Election" in contest_name:
                continue  # special elections are separate races; skip to avoid duplicate candidates
            district = parse_district(contest_name)
            if district is None:
                continue
            chamber_slug = "house" if "State House" in contest_name else "senate"
            key = (chamber_slug, district)
            if key not in districts:
                districts[key] = {"Democrat": [], "Republican": []}
            districts[key][party_label].extend(rows)

    # Build one race per district
    for (chamber_slug, district), parties in sorted(districts.items(), key=lambda x: (x[0][0], x[0][1])):
        chamber_name = "Georgia House of Representatives" if chamber_slug == "house" else "Georgia State Senate"

        ballots = {}
        for party_label in ("Democrat", "Republican"):
            party_slug = "d" if party_label == "Democrat" else "r"
            rows = parties[party_label]
            if not rows:
                continue
            candidates = []
            for i, row in enumerate(rows):
                c = candidate_from_row(row, i, chamber_slug, district, party_slug)

                # Auto-enrich incumbents with imageUrl and member link from ga-members.json.
                #
                # Guarded by name, not district alone. When a seat changes hands
                # mid-term the export flags the *new* holder as the incumbent while
                # ga-members.json may still list the person they replaced, and an
                # unguarded lookup then files the newcomer under their predecessor's
                # member record. That is how Bill Fincher (HD-23), Eric Gisler
                # (HD-121) and Steven McNeel (SD-18) came to carry the ids of three
                # legislators who had resigned — which showed up on the *resigned*
                # members' pages as "Running for ... in 2026". The auto-detect pass
                # below has always checked the name; this one did not.
                if c.get("isIncumbent"):
                    member = member_lookup.get((chamber_slug, district))
                    if member and not shares_a_name(c["name"], member["name"]):
                        SEAT_HOLDER_MISMATCHES.append(
                            (c["id"], c["name"], member["name"]))
                        member = None
                    if member:
                        if member.get("imageUrl") and not c.get("imageUrl"):
                            c["imageUrl"] = member["imageUrl"]
                        if member.get("id") and not c.get("existingMemberId"):
                            c["existingMemberId"] = member["id"]
                            c["existingMemberSource"] = "state"

                # Apply manual overrides (take precedence over auto-enrichment)
                patch = candidate_overrides.get(c["id"])
                if patch and patch.get("remove"):
                    # Candidate ids are positional (row index into the source
                    # export), so a re-ordered or shortened source row list makes
                    # `ga-house-15-2026-d-3` point at a different person. Verify
                    # the recorded name before deleting anyone.
                    # See CODEBASE-REVIEW-2026-08-18.md finding 5.2.
                    expected = override_target_name(patch)
                    if expected and not names_match(expected, c["name"]):
                        REMOVAL_MISMATCHES.append((c["id"], expected, c["name"]))
                        candidates.append(c)          # keep — do not guess
                    else:
                        REMOVED_IDS.append(c["id"])
                    continue

                if patch:
                    c.update({k: v for k, v in patch.items() if not k.startswith("_")})

                candidates.append(c)
            ballots[party_label] = candidates

        if not ballots:
            continue

        # If no candidate was flagged as incumbent by source data, try to detect one
        # by matching the known current member (from ga-members.json) against candidate names.
        all_candidates = [c for party_candidates in ballots.values() for c in party_candidates]
        already_flagged = any(c.get("isIncumbent") for c in all_candidates)
        if not already_flagged:
            member = member_lookup.get((chamber_slug, district))
            if member:
                for c in all_candidates:
                    if names_match(c["name"], member["name"]):
                        c["isIncumbent"] = True
                        if member.get("imageUrl") and not c.get("imageUrl"):
                            c["imageUrl"] = member["imageUrl"]
                        if member.get("id") and not c.get("existingMemberId"):
                            c["existingMemberId"] = member["id"]
                            c["existingMemberSource"] = "state"
                        print(f"  Auto-detected incumbent: {c['name']} ({chamber_slug} {district})")
                        break

        race_id = make_race_id(chamber_slug, district)
        race = {
            "id":          race_id,
            "level":       "state",
            "chamber":     chamber_name,
            "district":    district,
            "cycle":       CYCLE,
            "activePhase": "primary",
            "phases": {
                "primary": {
                    "electionDate": PRIMARY_DATE,
                    "ballots": ballots
                },
                "general": {
                    "electionDate": GENERAL_DATE,
                    "candidates": []
                }
            }
        }
        if race_overrides:
            patch = race_overrides.get(race_id, {})
            for k, v in patch.items():
                if not k.startswith("_"):
                    race[k] = v
                elif k == "_note":
                    race["_note"] = v
        races.append(race)

    return races

def main():
    with open(SRC, encoding="utf-8") as f:
        src = json.load(f)

    member_lookup       = load_member_lookup()
    candidate_overrides = load_candidate_overrides()
    race_overrides      = load_race_overrides()
    print(f"Loaded {len(member_lookup)} GA members for incumbent enrichment")
    print(f"Loaded {len(candidate_overrides)} candidate override(s)")
    print(f"Loaded {len(race_overrides)} race override(s)")

    new_races = build_races(src, member_lookup, candidate_overrides, race_overrides)
    print(f"Built {len(new_races)} legislative race entries")

    removal_keys = {k for k, v in candidate_overrides.items()
                    if isinstance(v, dict) and v.get("remove")}
    print(f"Applied {len(REMOVED_IDS)} of {len(removal_keys)} 'remove' override(s)")

    unused = sorted(removal_keys - set(REMOVED_IDS)
                    - {cid for cid, _, _ in REMOVAL_MISMATCHES})
    if unused:
        print(f"  note: {len(unused)} 'remove' override(s) matched no candidate "
              f"(source no longer emits that row): {', '.join(unused[:6])}"
              + (" ..." if len(unused) > 6 else ""))

    if SEAT_HOLDER_MISMATCHES:
        # Not fatal: the candidate is still built, just without a member link.
        # Worth seeing, because it means the seat changed hands and the correct
        # id has to be pinned in ga-race-candidate-overrides.json.
        print(f"\nnote: {len(SEAT_HOLDER_MISMATCHES)} incumbent(s) do not match the "
              f"member ga-members.json lists for their district — not linked to a "
              f"member record. Pin the right id in ga-race-candidate-overrides.json "
              f"if the seat changed hands:")
        for cid, cand_name, member_name in SEAT_HOLDER_MISMATCHES:
            print(f"    {cid}: candidate '{cand_name}' vs seat holder '{member_name}'")

    if REMOVAL_MISMATCHES:
        print("\nERROR: 'remove' override(s) point at a different candidate than "
              "recorded.\nCandidate ids are positional, so the source export has "
              "almost certainly\nre-ordered. Nobody was deleted. Re-check these "
              "against the source and\nupdate ga-race-candidate-overrides.json:\n",
              file=sys.stderr)
        for cid, expected, actual in REMOVAL_MISMATCHES:
            print(f"  {cid}: expected {expected!r}, found {actual!r}", file=sys.stderr)
        sys.exit(1)

    with open(DEST, encoding="utf-8") as f:
        dest = json.load(f)

    dest_races = dest.get("races", [])
    existing_by_id = {r["id"]: r for r in dest_races if is_legislative(r["id"])}

    before = sum(count_candidates(r.get("phases", {}).get(p, {}))
                 for r in existing_by_id.values()
                 for p in r.get("phases", {}) if p != "primary")

    if FORCE_RESET:
        print("\n!! --force-reset: rebuilding from source, discarding downstream phases")
        merged_by_id = {r["id"]: r for r in new_races}
    else:
        merged_by_id = {r["id"]: merge_race(existing_by_id.get(r["id"]), r)
                        for r in new_races}

    after = sum(count_candidates(m.get("phases", {}).get(p, {}))
                for m in merged_by_id.values()
                for p in m.get("phases", {}) if p != "primary")

    carried = sum(1 for rid, m in merged_by_id.items()
                  if existing_by_id.get(rid, {}).get("activePhase") == m.get("activePhase") != "primary")

    print(f"\nPost-primary candidate entries: {before} before -> {after} after")
    print(f"Races keeping a non-primary activePhase: {carried}")

    if after < before and not ALLOW_LOSS:
        print(
            f"\nERROR: this run would destroy {before - after} post-primary candidate "
            f"entries.\n"
            f"General-election ballots exist only in races.json (set_general_candidates.py\n"
            f"puts them there), so they cannot be rebuilt from "
            f"{SRC.name}.\n\n"
            f"If the loss is intended, re-run with --allow-loss. To deliberately reset\n"
            f"every legislative race back to the primary, use --force-reset --allow-loss.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rebuild the list in place so unrelated races keep their original position
    # and the diff stays readable.
    out_races, seen = [], set()
    for r in dest_races:
        if is_legislative(r["id"]):
            if r["id"] in merged_by_id:
                out_races.append(merged_by_id[r["id"]])
                seen.add(r["id"])
            # a legislative race no longer in source is dropped, as before
        else:
            out_races.append(r)
    for r in new_races:                      # districts that are new this run
        if r["id"] not in seen:
            out_races.append(merged_by_id[r["id"]])

    dest["races"] = out_races
    dest["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(dest, f, indent=2, ensure_ascii=False)

    # Stats
    house  = [r for r in new_races if r["chamber"] == "Georgia House of Representatives"]
    senate = [r for r in new_races if r["chamber"] == "Georgia State Senate"]
    total_cands = sum(
        len(candidates)
        for r in new_races
        for candidates in r["phases"]["primary"]["ballots"].values()
    )
    enriched = sum(
        1 for r in new_races
        for candidates in r["phases"]["primary"]["ballots"].values()
        for c in candidates if c.get("imageUrl")
    )
    print(f"  House races:  {len(house)}")
    print(f"  Senate races: {len(senate)}")
    print(f"  Total candidates across all ballots: {total_cands}")
    print(f"  Candidates with imageUrl: {enriched}")
    print(f"  Total races in races.json: {len(dest['races'])}")

if __name__ == "__main__":
    main()
