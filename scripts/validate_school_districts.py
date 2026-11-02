#!/usr/bin/env python3
"""Validate _data/school_districts.yml — the Georgia school-district registry.

    python scripts/validate_school_districts.py

Exits 0 on success, 1 on any error. Warnings never fail the run: a district with
no roster yet is the normal state of this file, not a problem.

WHAT IT GUARDS, AND WHY EACH ONE EXISTS
---------------------------------------
This file is the join key for every school-board feature (phase 3 of
docs/LOCAL-EXPANSION-SCOPE.md), and its ids are GOSA district codes that reach
into the Georgia Civic Data dimension. So the structural checks are strict.

  * THE SHAPE IS 159 COUNTY + 21 CITY = 180. Every county has exactly one county
    system and no county has two, so a changed count means either GOSA moved a
    code or someone hand-edited the generated block. Both want a human.
  * IDS ARE UNIQUE ACROSS BOTH LISTS. They are the join key; a collision would
    silently merge two districts.
  * A CITY SYSTEM'S `counties` SLUGS MUST RESOLVE in places.yml. This is the
    strict cross-check validate_local_officials.py uses, and it is safe to be
    strict here because the seven counties that were missing are now registered
    as hidden placeholders. An unresolvable slug is a typo, not a forward
    reference. A county system carries NO `counties` — it is 1:1 with its county
    via countyFips — so one is an error.
  * PARTISANSHIP IS PER DISTRICT, BY LAW. Georgia permits a school board to be
    elected either in partisan elections (party primaries nominate; nominees'
    labels appear on the ballot) or in nonpartisan ones (no primaries, no labels)
    — https://ballotpedia.org/Party_labels_in_Georgia_school_board_elections.
    So the rule mirrors local_officials.yml: a district declares `partisan`, and
    `party` must agree with it. Nonpartisan is required when `partisan: false`;
    a real party is allowed only when it is not false. Forcing every seat to
    Nonpartisan, as an earlier revision of this file did, made it unable to hold
    the actual results — every county with a 2024 BOE contest in the SoS data
    carries party labels.
  * A SUPERINTENDENT IS NOT AN ELECTED SEAT. Georgia local superintendents are
    hired by the board — the same situation as a City Manager, which
    local_officials.yml documents and keeps out of its elected roster. So a
    Superintendent row must carry voting: false (error), should carry no
    last_elected / next_election (warning), and is never counted against
    board_size. Recording an appointed officer as elected would misrepresent who
    voters chose, which is the one mistake this file must not permit.
  * EVERY MEMBER NEEDS A `source`. Same contract as local_officials.yml and
    county_officers.yml: a human confirmed this against a primary record.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "_data", "school_districts.yml")
PLACES_PATH = os.path.join(ROOT, "_data", "places.yml")

EXPECTED_COUNTY = 159
EXPECTED_CITY = 21

VALID_TYPES = {"city", "county"}
VALID_ROLES = {"Chair", "Vice Chair", "Board Member", "Superintendent"}
APPOINTED_ROLES = {"Superintendent"}
# Same vocabulary as local_officials.yml. Which values are LEGAL for a given
# member depends on its district's `partisan` flag — see validate_member.
VALID_PARTIES = {"Republican", "Democratic", "Independent", "Nonpartisan"}
# What a nonpartisan body may record. `Independent` is for a member holding a
# PARTISAN seat with no party, so it is not allowed on a nonpartisan board.
NONPARTISAN_ONLY = {"Nonpartisan"}
PRESIDING_ROLES = {"Chair"}

REQUIRED_MEMBER = ("name", "role", "seat", "source")
_FIPS_RE = re.compile(r"^13\d{3}$")
_ID_RE = re.compile(r"^[0-9]{3,7}$")


def load_places():
    import yaml
    with open(PLACES_PATH, encoding="utf-8") as fh:
        return {p["slug"] for p in (yaml.safe_load(fh) or {}).get("places", [])
                if isinstance(p, dict) and p.get("slug")}


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def validate_member(where, m, errors, warnings, partisan=None):
    if not isinstance(m, dict):
        errors.append("%s: member is not a mapping" % where)
        return False

    for key in REQUIRED_MEMBER:
        if _blank(m.get(key)):
            errors.append("%s: %s is required and must be non-empty" % (where, key))

    role = m.get("role")
    if role and role not in VALID_ROLES:
        errors.append("%s: role %r is not in the vocabulary %s"
                      % (where, role, sorted(VALID_ROLES)))

    party = m.get("party")
    if not _blank(party):
        if party not in VALID_PARTIES:
            errors.append("%s: party %r is not in the vocabulary %s"
                          % (where, party, sorted(VALID_PARTIES)))
        elif partisan is False and party not in NONPARTISAN_ONLY:
            errors.append("%s: party %r, but the district declares "
                          "`partisan: false`. Set the district partisan or record "
                          "the member Nonpartisan — one of the two is wrong."
                          % (where, party))

    src = m.get("source")
    if not _blank(src) and not str(src).startswith(("http://", "https://")):
        errors.append("%s: source must be a URL, got %r" % (where, src))

    appointed = role in APPOINTED_ROLES
    if appointed:
        # The one thing this file must not get wrong.
        if m.get("voting") is not False:
            errors.append(
                "%s: a %s is HIRED BY THE BOARD, not elected, so it must carry "
                "`voting: false`. Leaving it unset would present an appointed "
                "officer as an elected one." % (where, role))
        for key in ("last_elected", "next_election"):
            if not _blank(m.get(key)):
                warnings.append(
                    "%s: a %s has no election, so %s should be blank (got %r)"
                    % (where, role, key, m.get(key)))
    return appointed


def validate_district(kind, d, idx, places, seen_ids, errors, warnings):
    label = "%s[%d]" % (kind, idx)
    if not isinstance(d, dict):
        errors.append("%s: entry is not a mapping" % label)
        return
    did = d.get("id")
    name = d.get("name") or "(unnamed)"
    where = "%s %s" % (label, did or name)

    if _blank(did):
        errors.append("%s: id is required (the GOSA district code, as a string)" % label)
    else:
        if not isinstance(did, str) or not _ID_RE.match(did):
            errors.append("%s: id must be a quoted numeric GOSA code, got %r"
                          % (where, did))
        if did in seen_ids:
            errors.append("%s: duplicate district id %r — ids are the join key"
                          % (where, did))
        seen_ids.add(did)

    if _blank(name):
        errors.append("%s: name is required" % where)

    dtype = d.get("type")
    if dtype not in VALID_TYPES:
        errors.append("%s: type must be one of %s, got %r"
                      % (where, sorted(VALID_TYPES), dtype))
    expected_type = "county" if kind == "countyDistricts" else "city"
    if dtype and dtype != expected_type:
        errors.append("%s: listed under %s but type is %r"
                      % (where, kind, dtype))

    if _blank(d.get("districtCensusId")):
        warnings.append("%s: no districtCensusId — cross-dataset linking will not "
                        "work for this district" % where)

    if kind == "countyDistricts":
        fips = d.get("countyFips")
        if _blank(fips) or not _FIPS_RE.match(str(fips)):
            errors.append("%s: countyFips must be a quoted 5-digit Georgia FIPS "
                          "(13xxx), got %r" % (where, fips))
        if d.get("counties"):
            errors.append("%s: a county system must NOT carry `counties` — it is "
                          "1:1 with its county via countyFips, and the place it "
                          "renders on is derived" % where)
    else:
        cs = d.get("counties")
        if not isinstance(cs, list) or not cs:
            errors.append("%s: a city system must carry a non-empty `counties` "
                          "list of places.yml slugs" % where)
        else:
            for slug in cs:
                if slug not in places:
                    errors.append("%s: counties slug %r is not in places.yml — an "
                                  "unresolvable slug is a typo, not a forward "
                                  "reference" % (where, slug))
        pp = d.get("primaryPlace")
        if not _blank(pp) and pp not in places:
            errors.append("%s: primaryPlace %r is not in places.yml" % (where, pp))

    partisan = d.get("partisan")
    if partisan is not None and not isinstance(partisan, bool):
        errors.append("%s: partisan must be true or false, got %r" % (where, partisan))

    for key in ("board_size", "term_years"):
        v = d.get(key)
        if v is not None and (not isinstance(v, int) or v <= 0):
            errors.append("%s: %s must be a positive integer, got %r"
                          % (where, key, v))

    url = d.get("official_url")
    if not _blank(url) and not str(url).startswith(("http://", "https://")):
        errors.append("%s: official_url must be a URL, got %r" % (where, url))

    members = d.get("members")
    if members is None:
        return  # not yet researched — the normal state, counted by the caller
    if not isinstance(members, list) or not members:
        errors.append("%s: `members` is present but empty. Omit the key entirely "
                      "for a district whose roster is not yet researched — an "
                      "empty list reads as 'this board has no members'" % where)
        return

    elected = 0
    presiding = []
    for i, m in enumerate(members):
        mwhere = "%s member[%d] %s" % (where, i, (m or {}).get("name", "?")
                                       if isinstance(m, dict) else "?")
        appointed = validate_member(mwhere, m, errors, warnings,
                                    partisan=d.get("partisan"))
        if isinstance(m, dict):
            if not appointed:
                elected += 1
            if m.get("role") in PRESIDING_ROLES:
                presiding.append(m.get("name"))

    if len(presiding) > 1:
        warnings.append("%s: %d members hold a presiding role (%s) — a board has "
                        "one Chair" % (where, len(presiding), ", ".join(
                            str(p) for p in presiding)))

    size = d.get("board_size")
    if isinstance(size, int) and size > 0:
        if elected > size:
            errors.append("%s: %d elected member(s) but board_size is %d "
                          "(a Superintendent is appointed and is not counted)"
                          % (where, elected, size))
        elif elected < size:
            warnings.append("%s: %d of %d seats captured" % (where, elected, size))


def validate(data, places):
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["school_districts.yml did not parse into a mapping"], []

    unknown = set(data) - {"cityDistricts", "countyDistricts"}
    if unknown:
        errors.append("unexpected top-level key(s): %s" % sorted(unknown))

    seen_ids = set()
    counts = {}
    for kind, expected in (("countyDistricts", EXPECTED_COUNTY),
                           ("cityDistricts", EXPECTED_CITY)):
        lst = data.get(kind)
        if not isinstance(lst, list) or not lst:
            errors.append("%s is missing or empty" % kind)
            counts[kind] = 0
            continue
        counts[kind] = len(lst)
        if len(lst) != expected:
            errors.append(
                "%s holds %d entries, expected %d. Every Georgia county has "
                "exactly one county system and there are 21 independent city "
                "systems, so a changed count means GOSA moved a code or the "
                "generated block was hand-edited — check before adjusting this "
                "expectation." % (kind, len(lst), expected))
        for i, d in enumerate(lst):
            validate_district(kind, d, i, places, seen_ids, errors, warnings)

    # Every county must be represented exactly once.
    fips = [d.get("countyFips") for d in (data.get("countyDistricts") or [])
            if isinstance(d, dict)]
    dupes = {f for f in fips if f and fips.count(f) > 1}
    if dupes:
        errors.append("county FIPS appearing more than once in countyDistricts: %s"
                      % sorted(dupes))

    return errors, warnings


def main():
    import yaml
    try:
        with open(DATA_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        print("VALIDATION FAILED - %s not found" % DATA_PATH)
        return 1
    except yaml.YAMLError as exc:
        print("VALIDATION FAILED - %s is not valid YAML:\n%s" % (DATA_PATH, exc))
        return 1

    errors, warnings = validate(data, load_places())
    if warnings:
        print("%d warning(s):" % len(warnings))
        print("\n".join("  " + w for w in warnings))
        print()
    if errors:
        print("VALIDATION FAILED - %d error(s) in %s:\n" % (len(errors), DATA_PATH))
        print("\n".join("  " + e for e in errors))
        return 1

    city = data.get("cityDistricts") or []
    county = data.get("countyDistricts") or []
    withr = [d for d in city + county if isinstance(d, dict) and d.get("members")]
    members = sum(len(d["members"]) for d in withr)
    print("OK - %d districts (%d county, %d city), %d with a roster, %d members - %s"
          % (len(city) + len(county), len(county), len(city), len(withr),
             members, os.path.relpath(DATA_PATH, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
