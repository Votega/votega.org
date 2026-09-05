"""
Validates _data/local_officials.yml — the hand-curated city-council / county-
commission roster. Because there is no upstream API for local officials, this
is the only automated guard on the data, so it errs toward catching typos in
the controlled vocabularies and internally inconsistent term/voting fields.

Run locally or via the validate-local-officials GitHub Actions workflow on any
push that touches the file.

Exit code 0 = valid. Exit code 1 = one or more errors (details printed to stdout).
"""

import sys
from datetime import date

import yaml

DATA_PATH = "_data/local_officials.yml"
PLACES_PATH = "_data/places.yml"

VALID_TYPES = {"city", "county"}
VALID_ROLES = {
    "Mayor",
    "Mayor Pro Tem",
    "Chair",
    "Vice Chair",
    "Council Member",
    "Commissioner",
}
VALID_PARTIES = {"Republican", "Democratic", "Nonpartisan"}
PRESIDING_ROLES = {"Mayor", "Chair"}

# Sanity window for election/term years — catches fat-fingered dates.
MIN_YEAR = 2000
MAX_YEAR = date.today().year + 12

REQUIRED_MEMBER_FIELDS = [
    "name",
    "role",
    "seat",
    "party",
    "last_elected",
    "next_election",
    "voting",
]

errors = []
warnings = []


def err(context, msg):
    errors.append(f"  [{context}] {msg}")


def warn(context, msg):
    warnings.append(f"  [{context}] {msg}")


def check_year(context, field, value):
    """Year fields are optional while a roster is being filled in (blank = None),
    but if present they must be a plausible 4-digit year."""
    if value in (None, ""):
        return None
    if not isinstance(value, int):
        err(context, f"{field} must be a 4-digit year integer, got: {value!r}")
        return None
    if not (MIN_YEAR <= value <= MAX_YEAR):
        err(context, f"{field} ({value}) is outside {MIN_YEAR}-{MAX_YEAR}")
    return value


def validate_member(juris_id, index, member, partisan):
    context = f"{juris_id}.members[{index}]"

    if not isinstance(member, dict):
        err(context, "member must be a mapping")
        return

    for field in REQUIRED_MEMBER_FIELDS:
        if field not in member:
            err(context, f"missing required field: {field}")

    role = member.get("role")
    if role is not None and role not in VALID_ROLES:
        err(context, f"role must be one of {sorted(VALID_ROLES)}, got: {role!r}")

    party = member.get("party")
    if party in (None, ""):
        # Party is required content, but a blank cell mid-entry is a warning not
        # a hard failure, so a partly-filled roster still validates.
        warn(context, "party is blank")
    elif party not in VALID_PARTIES:
        err(context, f"party must be one of {sorted(VALID_PARTIES)}, got: {party!r}")
    elif partisan is False and party != "Nonpartisan":
        err(context, f"jurisdiction is nonpartisan but member party is {party!r}")
    elif partisan is True and party == "Nonpartisan":
        warn(context, "jurisdiction is partisan but member party is Nonpartisan")

    last_elected = check_year(context, "last_elected", member.get("last_elected"))
    term_end = check_year(context, "term_end", member.get("term_end"))
    next_election = check_year(context, "next_election", member.get("next_election"))

    if last_elected is not None and next_election is not None and next_election < last_elected:
        err(context, f"next_election ({next_election}) is before last_elected ({last_elected})")
    if term_end is not None and next_election is not None and next_election > term_end:
        warn(context, f"next_election ({next_election}) is after term_end ({term_end})")

    # voting / tie_break_only consistency
    voting = member.get("voting")
    tie_break_only = member.get("tie_break_only", False)
    if voting is not None and not isinstance(voting, bool):
        err(context, f"voting must be true/false, got: {voting!r}")
    if not isinstance(tie_break_only, bool):
        err(context, f"tie_break_only must be true/false, got: {tie_break_only!r}")
    if voting is True and tie_break_only is True:
        err(context, "voting:true and tie_break_only:true are contradictory (a tie-breaker does not vote normally)")


def validate_reserved_block(juris_id, member_key, block, allowed):
    """meetings/participate are reserved Phase-2 blocks: any key present must be
    a known one (catches typos like `livestreem_url`), values may be blank."""
    context = f"{juris_id}.{member_key}"
    if block is None:
        return
    if not isinstance(block, dict):
        err(context, "must be a mapping")
        return
    for key in block:
        if key not in allowed:
            err(context, f"unknown key {key!r} (allowed: {sorted(allowed)})")


MEETINGS_KEYS = {
    "schedule", "location_name", "location_address",
    "livestream_url", "agendas_url", "minutes_url",
}
PARTICIPATE_KEYS = {
    "public_comment", "clerk_name", "clerk_email", "clerk_phone", "open_records_url",
}


def validate_jurisdiction(index, juris, seen_ids):
    juris_id = juris.get("id", f"?[{index}]")
    context = juris_id

    for field in ("id", "name", "type", "body", "partisan"):
        if field not in juris:
            err(context, f"missing required field: {field}")

    if juris_id in seen_ids:
        err(context, f"duplicate jurisdiction id: {juris_id!r}")
    seen_ids.add(juris_id)

    jtype = juris.get("type")
    if jtype is not None and jtype not in VALID_TYPES:
        err(context, f"type must be one of {sorted(VALID_TYPES)}, got: {jtype!r}")

    partisan = juris.get("partisan")
    if partisan is not None and not isinstance(partisan, bool):
        err(context, f"partisan must be true/false, got: {partisan!r}")

    validate_reserved_block(juris_id, "meetings", juris.get("meetings"), MEETINGS_KEYS)
    validate_reserved_block(juris_id, "participate", juris.get("participate"), PARTICIPATE_KEYS)

    members = juris.get("members")
    if not isinstance(members, list) or not members:
        err(context, "members must be a non-empty list")
        return

    presiding = [m for m in members if isinstance(m, dict) and m.get("role") in PRESIDING_ROLES]
    if len(presiding) > 1:
        warn(context, f"{len(presiding)} presiding officers (Mayor/Chair) — expected at most 1")

    for i, member in enumerate(members):
        validate_member(juris_id, i, member, partisan)


def load_places():
    """Return {slug: place} from the places registry, or None if it is absent.

    Officials is a DOMAIN of a place: a jurisdiction's `id` must equal a place
    `slug` (the join key the hub renders on). Absent registry = skip the check."""
    try:
        with open(PLACES_PATH) as f:
            pdata = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    if not isinstance(pdata, dict):
        return {}
    return {p.get("slug"): p for p in (pdata.get("places") or []) if isinstance(p, dict)}


def cross_check_places(jurisdictions):
    """Every jurisdiction id must map to a place slug, and types must agree —
    this is what keeps _data/local_officials.yml and _data/places.yml from
    silently drifting (e.g. `newton` vs `newton-county`) as places scale up."""
    places = load_places()
    if places is None:
        warn("places", f"{PLACES_PATH} not found — skipping slug cross-check")
        return
    for juris in jurisdictions:
        if not isinstance(juris, dict):
            continue
        jid = juris.get("id")
        if jid not in places:
            err(jid or "?", f"no matching place slug {jid!r} in {PLACES_PATH} — "
                            f"officials must be onboarded as a place first "
                            f"(see LOCAL-GOVERNMENT-IA.md)")
            continue
        ptype = places[jid].get("type")
        jtype = juris.get("type")
        if ptype and jtype and ptype != jtype:
            err(jid, f"type {jtype!r} disagrees with place type {ptype!r} in {PLACES_PATH}")


def main():
    try:
        with open(DATA_PATH) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"VALIDATION FAILED — {DATA_PATH} not found")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"VALIDATION FAILED — {DATA_PATH} is not valid YAML:\n{e}")
        sys.exit(1)

    if not isinstance(data, dict) or "jurisdictions" not in data:
        print(f"VALIDATION FAILED — {DATA_PATH} must have a top-level 'jurisdictions' list")
        sys.exit(1)

    jurisdictions = data["jurisdictions"]
    if not isinstance(jurisdictions, list) or not jurisdictions:
        print(f"VALIDATION FAILED — 'jurisdictions' must be a non-empty list")
        sys.exit(1)

    seen_ids = set()
    for i, juris in enumerate(jurisdictions):
        if not isinstance(juris, dict):
            err(f"jurisdictions[{i}]", "must be a mapping")
            continue
        validate_jurisdiction(i, juris, seen_ids)

    cross_check_places(jurisdictions)

    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings:
            print(w)
        print()

    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s) in {DATA_PATH}:\n")
        for e in errors:
            print(e)
        sys.exit(1)

    member_count = sum(len(j.get("members", [])) for j in jurisdictions)
    print(f"OK — {len(jurisdictions)} jurisdictions, {member_count} members — {DATA_PATH}")


if __name__ == "__main__":
    main()
