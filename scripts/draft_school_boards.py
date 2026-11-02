#!/usr/bin/env python3
"""Draft school-board rosters for _data/school_districts.yml from the GA SoS results.

    python scripts/draft_school_boards.py                 # every county
    python scripts/draft_school_boards.py newton cobb     # by county slug
    python scripts/draft_school_boards.py --changes-only  # hide districts already matching

WHY THIS EXISTS
    There is no upstream API for school-board members, so every roster in
    _data/school_districts.yml is hand-curated. This is the "assisted" drafter:
    it turns the WINNERS of the most recent general election into draft blocks a
    human reviews and confirms. It does NOT write the data file — it prints YAML
    to paste and a diff against what is already curated, so a person stays the
    merge gate. Same contract as generate_local_officials.py, whose SoS helpers
    this reuses rather than duplicating.

    generate_local_officials.py deliberately SKIPS these contests (its
    _SKIP_OFFICE excludes "board of education|boe|school|superintendent") because
    it drafts county commissions. This is the other half.

HARD LIMITS OF THE SOURCE — read before trusting a draft
    0. THREE OFFICE SHAPES occur in the real data and all three are handled:
       "County BOE - District 2" (Cobb, Jackson, Newton, Whitfield),
       "Board of Education - District 4" (Thomas) and
       "County Board of Education - District 5" (Talbot).
    1. LOCAL offices only exist in the API from ~2024 onward, and Georgia school
       boards are 4-year STAGGERED, so a single cycle covers ROUGHLY HALF a board.
       The rest was last elected in a pre-2024 cycle the API lacks. Measured on a
       sample of eight counties, five had a 2024 BOE contest and three had none at
       all — so for some districts this yields nothing, which is not an error.
    2. `isWinner` is unreliable on these contests, so the vote LEADER is taken.
       Under Georgia's majority rule a leader under 50% goes to a runoff, and
       local runoffs are not in this portal, so a sub-50% leader is emitted with
       `_needs_runoff_check` and must not be trusted as the winner.
    3. No term-length data. Georgia school-board terms are set per district and
       have no machine source, so `last_elected` is emitted (reliable) and
       term_end / next_election are left for the curator.
    4. NO SUPERINTENDENT IS EVER DRAFTED. Georgia local superintendents are hired
       by the board, not elected, so they cannot come from election results.
    5. NO ROLE ABOVE Board Member IS INFERRED. A board chair is normally chosen
       by the board from among its members, not elected as chair by voters, so
       every drafted member is a Board Member and the curator promotes the chair.

PARTISANSHIP IS DERIVED, AND THE EVIDENCE IS SHOWN
    Georgia law lets each district choose partisan or nonpartisan school-board
    elections (https://ballotpedia.org/Party_labels_in_Georgia_school_board_elections),
    so `partisan` is a real per-district fact. The SoS results reveal which mode
    was used: party labels on the candidates mean a partisan election, their
    absence a nonpartisan one. So this emits a `partisan:` suggestion plus
    `_partisan_evidence` naming what it saw — and it is only confident in one
    direction. Seeing a label proves partisan; seeing none is weaker, because an
    unopposed candidate with no recorded party looks the same either way, so that
    case is flagged for confirmation.
"""

import argparse
import os
import re
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_local_officials import (API, SEATING_SLUG, SEATING_YEAR,  # noqa: E402
                                      _get, _text, clean_name, list_counties,
                                      map_party, short_name, slug_of, winner_of)

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "_data", "school_districts.yml")

# A school-board contest. Both shapes occur in the real data: "County BOE -
# District 2" (Cobb, Jackson, Newton, Whitfield) and "Board of Education -
# District 4" (Thomas).
_BOE_RE = re.compile(r"\bboe\b|board\s+of\s+education", re.I)
# Things that mention a board but are not a seat on it.
_NOT_A_SEAT = re.compile(r"superintendent|referendum|question|sales\s+tax|esplost|"
                         r"\bbond\b|charter", re.I)

# The county systems whose district NAME does not contain their county's name, so
# they cannot be matched by name. Kept explicit because guessing is how a roster
# lands on the wrong district. (See the same three in school_districts.yml.)
_COUNTY_ALIASES = {
    "chatham": "625",   # Savannah-Chatham County
    "spalding": "726",  # Griffin-Spalding County
    "upson": "745",     # Thomaston-Upson County
}


def load_registry():
    """(by_county_slug, city_by_county_slug) from _data/school_districts.yml."""
    import yaml
    with open(DATA_PATH, encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
    by_slug, cities = {}, {}
    for e in d.get("countyDistricts") or []:
        name = (e.get("name") or "")
        # Must match slug_of()'s output exactly, which HYPHENATES a two-word
        # county: "ben-hill-county-ga" -> "ben-hill". Stripping the separator
        # instead produced "benhill" and silently lost Ben Hill and Jeff Davis.
        slug = re.sub(r"[^a-z0-9-]", "",
                      re.sub(r"\s+", "-", re.sub(r"\s+County$", "", name).strip()).lower())
        by_slug[slug] = e
    for slug, did in _COUNTY_ALIASES.items():
        match = [e for e in (d.get("countyDistricts") or []) if e.get("id") == did]
        if match:
            by_slug[slug] = match[0]
    for e in d.get("cityDistricts") or []:
        for c in e.get("counties") or []:
            cities.setdefault(c, []).append(e)
    return by_slug, cities, d


def classify(office):
    """(role, seat) for a school-board seat, or None if the office is not one."""
    o = re.sub(r"\s+", " ", office or "").strip()
    if not _BOE_RE.search(o) or _NOT_A_SEAT.search(o):
        return None
    # "County BOE - District 2" / "Board of Education - District 4"
    m = re.search(r"district\s+([0-9]+[A-Za-z]?)", o, re.I)
    if m:
        return ("Board Member", "District %s" % m.group(1))
    m = re.search(r"\bpost\s+([0-9]+[A-Za-z]?)", o, re.I)
    if m:
        return ("Board Member", "Post %s" % m.group(1))
    if re.search(r"at[-\s]?large", o, re.I):
        return ("Board Member", "At-Large")
    # A seat we recognise as a board contest but cannot label. Emit it with the
    # verbatim office as the seat so a human can fix it, rather than drop it.
    return ("Board Member", o)


def city_district_for(office, candidates):
    """The city system a contest belongs to, or None for the county system."""
    norm = re.sub(r"[^a-z ]", " ", (office or "").lower())
    for e in candidates or []:
        key = re.sub(r"\s+(city|public\s+schools?|schools?)$", "",
                     (e.get("name") or "").lower()).strip()
        key = re.sub(r"^city\s+schools?\s+of\s+", "", key).strip()
        if key and re.search(r"\b%s\b" % re.escape(key), norm):
            return e
    return None


def draft_county(county_short, cities_here):
    """{district_id_or_None: {members, partisan, evidence}} for one county."""
    try:
        d = _get(f"{API}/elections/{county_short}/{SEATING_SLUG}/data")
    except urllib.error.HTTPError as exc:
        return {"_error": "HTTP %s" % exc.code}
    out = {}
    for it in d.get("ballotItems") or []:
        office = _text(it.get("name"))
        cls = classify(office)
        if not cls:
            continue
        role, seat = cls
        w = winner_of(it)
        if not w:
            continue
        full, abbr, share = w
        disp = short_name(full)
        city = city_district_for(office, cities_here)
        key = city.get("id") if city else None
        bucket = out.setdefault(key, {"members": [], "labelled": 0, "unlabelled": 0})
        m = {
            "name": disp,
            "role": role,
            "seat": seat,
            # map_party() funnels anything that is not Rep/Dem to "Nonpartisan",
            # which on a ballot that DID print a label is a guess — an
            # independent belongs under `Independent`, not `Nonpartisan`. So only
            # the two unambiguous values are asserted; anything else is left for
            # the curator with the raw abbreviation shown.
            "party": (map_party(abbr)
                      if abbr and map_party(abbr) in ("Republican", "Democratic")
                      else None),
            "_sos_party": abbr or None,
            "last_elected": SEATING_YEAR,
            "term_end": None,
            "next_election": None,
            "voting": True,
            "source": f"{API}/elections/{county_short}/{SEATING_SLUG}/data",
            "_office": office,
            "_share": round(share, 3),
        }
        if full != disp:
            m["full_name"] = full
        if share < 0.5:
            m["_needs_runoff_check"] = True
        if abbr:
            bucket["labelled"] += 1
            if not m["party"]:
                m["_unmapped_party"] = abbr
        else:
            bucket["unlabelled"] += 1
            m["_no_party_label"] = True
        bucket["members"].append(m)

    for bucket in out.values():
        bucket["members"].sort(key=lambda m: _seat_key(m["seat"]))
        # Only one direction is safe to conclude. A label proves a partisan
        # ballot; its absence could equally be an unopposed candidate with no
        # party recorded, so that is a suggestion, not a finding.
        if bucket["labelled"]:
            bucket["partisan"] = True
            bucket["evidence"] = ("%d of %d candidates carry a party label"
                                  % (bucket["labelled"],
                                     bucket["labelled"] + bucket["unlabelled"]))
        else:
            bucket["partisan"] = None
            bucket["evidence"] = ("no candidate carried a party label (%d seat(s)) "
                                  "— likely a nonpartisan election, but CONFIRM: an "
                                  "unopposed candidate with no recorded party looks "
                                  "the same" % bucket["unlabelled"])
    return out


def _seat_key(seat):
    m = re.search(r"(\d+)", seat or "")
    return (0 if m else 1, int(m.group(1)) if m else 0, seat or "")


def _q(s):
    s = str(s)
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"') if re.search(
        r'[:#\'"{}\[\],&*?|<>=!%@`]|^\s|\s$', s) else s


def emit(district, bucket):
    """YAML to paste under a district entry, with provenance comments."""
    lines = []
    did = district.get("id")
    lines.append("  # --- %s (id %s) ------------------------------------------"
                 % (district.get("name"), did))
    if bucket["partisan"] is True:
        lines.append("    partisan: true   # %s" % bucket["evidence"])
    else:
        lines.append("    # partisan: false   # %s" % bucket["evidence"])
    lines.append("    members:")
    for m in bucket["members"]:
        lines.append("      - name: %s" % _q(m["name"]))
        if m.get("full_name"):
            lines.append("        full_name: %s" % _q(m["full_name"]))
        lines.append("        role: %s" % m["role"])
        lines.append("        seat: %s" % _q(m["seat"]))
        if m["party"]:
            lines.append("        party: %s" % m["party"])
        else:
            lines.append("        # party:          # no label in the results; set "
                         "Nonpartisan if this district is nonpartisan")
        lines.append("        last_elected: %d" % m["last_elected"])
        lines.append("        term_end:        # no machine source — confirm")
        lines.append("        next_election:   # no machine source — confirm")
        lines.append("        voting: true")
        lines.append("        source: %s" % _q(m["source"]))
        flags = []
        if m.get("_needs_runoff_check"):
            flags.append("LEADER UNDER 50%% (%.1f%%) — a runoff decided this and is "
                         "NOT in the portal; confirm before use"
                         % (100 * m["_share"]))
        if m.get("_no_party_label"):
            flags.append("no party label in the results")
        if m.get("_unmapped_party"):
            flags.append("the ballot printed party %r, which is neither Rep nor "
                         "Dem — set Independent if this is a partisan seat held "
                         "by an independent, or Nonpartisan if the district is "
                         "nonpartisan" % m["_unmapped_party"])
        for f in flags:
            lines.append("        # ⚠ %s" % f)
        lines.append("        # SoS office: %s" % m["_office"])
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="county slugs (default: all 159)")
    ap.add_argument("--changes-only", action="store_true",
                    help="skip districts whose curated roster already has members")
    args = ap.parse_args()

    by_slug, cities, registry = load_registry()
    shorts = ([s for s in list_counties()] if not args.slugs
              else ["%s-county-ga" % s for s in args.slugs])

    drafted = empty = errors = 0
    blocks, no_contest, failed = [], [], []
    for short in sorted(shorts):
        slug = slug_of(short)
        county = by_slug.get(slug)
        if not county:
            failed.append("%s: no county system in school_districts.yml" % slug)
            errors += 1
            continue
        res = draft_county(short, cities.get(slug))
        if "_error" in res:
            failed.append("%s: %s" % (slug, res["_error"]))
            errors += 1
            continue
        if not res:
            no_contest.append(slug)
            empty += 1
            continue
        for did, bucket in sorted(res.items(), key=lambda kv: kv[0] or ""):
            target = county if did is None else next(
                (e for e in registry.get("cityDistricts") or [] if e.get("id") == did),
                county)
            if args.changes_only and target.get("members"):
                continue
            blocks.append(emit(target, bucket))
            drafted += 1

    if blocks:
        print("# DRAFT — review every line, then paste under the matching district")
        print("# in _data/school_districts.yml. Winners of the %s general only, so a"
              % SEATING_SLUG)
        print("# staggered board is only PARTLY covered. Nothing here is authoritative.")
        print()
        print("\n\n".join(blocks))
        print()

    print("=" * 72)
    print("%d district(s) drafted, %d county/counties with no %s board contest, "
          "%d error(s)" % (drafted, empty, SEATING_YEAR, errors))
    if no_contest:
        print("\nNo %d board contest (a staggered board elected in a cycle the API "
              "lacks — not an error):\n  %s"
              % (SEATING_YEAR, ", ".join(sorted(no_contest))))
    if failed:
        print("\nErrors:\n  %s" % "\n  ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
