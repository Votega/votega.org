"""
Validates _data/county_officers.yml - sheriffs (and later other constitutional
officers) elected countywide. Same posture as validate_local_officials.py: no upstream
API maintains this, so this is the only automated guard.

Exit 0 = valid, 1 = errors.
"""

import sys
from datetime import date

DATA_PATH = "_data/county_officers.yml"
PLACES_PATH = "_data/places.yml"

VALID_ROLES = {"Sheriff"}
VALID_PARTIES = {"Republican", "Democratic", "Independent", "Nonpartisan"}
VALID_STATUSES = {"Vacant", "Suspended", "Resigned", "Removed", "Deceased"}
REQUIRED = ["name", "role", "seat", "party", "source"]
MIN_YEAR = 2000
MAX_YEAR = date.today().year + 12


def validate(data, places):
    """Return (errors, warnings) for parsed data and a {slug: place} map (or None)."""
    errors, warnings = [], []

    def err(ctx, msg):
        errors.append(f"  [{ctx}] {msg}")

    def warn(ctx, msg):
        warnings.append(f"  [{ctx}] {msg}")

    if not isinstance(data, dict) or not isinstance(data.get("counties"), list) \
            or not data["counties"]:
        return ["  'counties' must be a non-empty list"], warnings

    seen = set()
    for i, c in enumerate(data["counties"]):
        cid = c.get("id", f"?[{i}]") if isinstance(c, dict) else f"?[{i}]"
        if not isinstance(c, dict):
            err(cid, "must be a mapping")
            continue
        if cid in seen:
            err(cid, f"duplicate county id {cid!r}")
        seen.add(cid)
        if places is not None:
            place = places.get(cid)
            if place is None:
                err(cid, f"no matching place slug {cid!r} in {PLACES_PATH}")
            elif place.get("type") != "county":
                err(cid, f"place {cid!r} is a {place.get('type')!r}, not a county")
        offs = c.get("officers")
        if not isinstance(offs, list) or not offs:
            err(cid, "officers must be a non-empty list")
            continue
        sheriffs = 0
        for j, o in enumerate(offs):
            ctx = f"{cid}.officers[{j}]"
            if not isinstance(o, dict):
                err(ctx, "officer must be a mapping")
                continue
            for f in REQUIRED:
                if f not in o:
                    err(ctx, f"missing required field: {f}")
            if o.get("role") not in VALID_ROLES:
                err(ctx, f"role must be one of {sorted(VALID_ROLES)}, got {o.get('role')!r}")
            if o.get("role") == "Sheriff":
                sheriffs += 1
            if not isinstance(o.get("name"), str) or not o.get("name", "").strip():
                err(ctx, "name must be a non-empty string")
            party = o.get("party")
            if party in (None, ""):
                warn(ctx, "party is blank")
            elif party not in VALID_PARTIES:
                err(ctx, f"party must be one of {sorted(VALID_PARTIES)}, got {party!r}")
            st = o.get("status")
            if st is not None and st not in VALID_STATUSES:
                err(ctx, f"status must be one of {sorted(VALID_STATUSES)}, got {st!r}")
            years = {}
            for f in ("last_elected", "next_election", "term_end"):
                v = o.get(f)
                if v in (None, ""):
                    continue
                if not isinstance(v, int) or isinstance(v, bool):
                    err(ctx, f"{f} must be a 4-digit year integer, got {v!r}")
                elif not (MIN_YEAR <= v <= MAX_YEAR):
                    err(ctx, f"{f} ({v}) is outside {MIN_YEAR}-{MAX_YEAR}")
                else:
                    years[f] = v
            if "last_elected" in years and "next_election" in years \
                    and years["next_election"] <= years["last_elected"]:
                err(ctx, f"next_election ({years['next_election']}) must be after "
                         f"last_elected ({years['last_elected']})")
            for f in ("phone", "address", "email", "source"):
                v = o.get(f)
                if v is not None and not isinstance(v, str):
                    err(ctx, f"{f} must be a string, got {v!r}")
            if not o.get("source"):
                err(ctx, "source is required - record where this was confirmed")
        if sheriffs > 1:
            err(cid, f"{sheriffs} sheriffs - a county has exactly one")
    return errors, warnings


def load_places():
    import yaml  # lazy: the offline test job installs no packages
    try:
        with open(PLACES_PATH, encoding="utf-8") as f:
            pdata = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    return {p.get("slug"): p for p in (pdata or {}).get("places", []) if isinstance(p, dict)}


def main():
    import yaml
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"VALIDATION FAILED - {DATA_PATH} not found")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"VALIDATION FAILED - {DATA_PATH} is not valid YAML:\n{e}")
        sys.exit(1)
    errors, warnings = validate(data, load_places())
    if warnings:
        print(f"{len(warnings)} warning(s):")
        print("\n".join(warnings))
        print()
    if errors:
        print(f"VALIDATION FAILED - {len(errors)} error(s) in {DATA_PATH}:\n")
        print("\n".join(errors))
        sys.exit(1)
    n = sum(len(c["officers"]) for c in data["counties"])
    print(f"OK - {len(data['counties'])} counties, {n} officers - {DATA_PATH}")


if __name__ == "__main__":
    main()
