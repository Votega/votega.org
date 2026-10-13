#!/usr/bin/env python3
"""Generate a PARALLEL GA legislator roster from legis.ga.gov SOAP, for comparison.

Phase 0 of Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md. Writes
`assets/data/ga-members.soap.json` and **never** the canonical `ga-members.json`, so
nothing on the site changes. Pair it with `compare_members_soap_vs_os.py`, whose
reconciliation table is the artifact that decides whether Phase 1 is worth doing.

Same shape as the Open States producer (`generate_ga_members_data.py`) so the two files
diff field by field, plus the fields only SOAP has.

Cost: one `GetMembersBySession` + one `GetCommitteesBySession` + one `GetMember` per
member (~250 calls). No auth, no quota. A single member's detail failing carries that
member forward from the committed roster rather than failing the run or dropping them
(spec §8.5); the count is reported and a large share is fatal.

Three fields SOAP cannot supply, carried over from the committed roster by legisGaGovId:
  * `id`        — the OCD person id. See spec §4; a member with none gets `legis-<id>`.
  * `birthDate` / `birthYear` — SOAP has month+day only, which cannot yield an age.
  * `termStart` — SOAP has the earliest session served, not a date; `termStartYear` is
    derived from it for a member the committed roster does not know.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.ga_leadership import committee_index, normalize_title
from lib.ga_sessions import SESSION_NAMES, all_session_ids, legis_session_id
from lib.ga_soap import (get_committees_by_session, get_member, get_members_by_session)

MEMBERS_FILE   = "assets/data/ga-members.json"
DEFAULT_OUTPUT = "assets/data/ga-members.soap.json"
OUTPUT_FILE    = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT

DELAY = 0.1           # politeness between GetMember calls; there is no quota
#: Carrying a member forward is for a transient. Past this share it is an outage.
MAX_CARRIED_SHARE = 0.1

PARTY = {"Democrat": "Democratic", "Republican": "Republican"}
CHAMBER = {"House": "House of Representatives", "Senate": "Senate"}
TITLE = {"House of Representatives": "Representative", "Senate": "Senator"}
CHAMBER_SLUG = {"House of Representatives": "house", "Senate": "senate"}


def regular_session():
    """(tag, legisSessionId) for the biennium's regular session — the roster's scope.

    Not the active session: a special session's listing covers only the members serving in
    it, while the regular session's covers everyone who served in the biennium (247 for
    1033, including the 11 who have since left).
    """
    for tag in all_session_ids():
        if "Regular" in SESSION_NAMES.get(tag, ""):
            sid = legis_session_id(tag)
            if sid:
                return tag, sid
    raise SystemExit("no regular session in SESSION_NAMES has a legis session id")


def format_phone(raw):
    """SOAP gives bare digits ('4046560220'); the roster uses '404-656-0220'."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw or None


def compose_address(detail):
    """One line, matching the committed roster's shape: street, City, ST ZIP."""
    street = (detail.get("address1") or "").strip()
    city = (detail.get("city") or "").strip()
    state = (detail.get("state") or "").strip()
    zipc = (detail.get("zip") or "").strip()
    tail = " ".join(p for p in (state, zipc) if p)
    parts = [p for p in (street, city, tail) if p]
    return ", ".join(parts) or None


def portrait(detail):
    """Prefer the full-resolution portrait; the thumbs carry a ?size= query."""
    p = detail.get("portraits") or {}
    return p.get("HighRes") or p.get("LargeThumb") or p.get("SmallThumb") or None


def current_service(detail, legis_session):
    """The member's LegislativeService record for the session being built."""
    for svc in detail.get("sessions") or []:
        if svc.get("sessionId") == legis_session:
            return svc
    return None


def earliest_session_year(detail):
    """Year of the earliest session the member served — the stand-in for termStartYear.

    A member first seated by a mid-biennium special election gets their session's start
    year, which can overstate tenure by up to a year; `termStartSession` records which
    unit the value came from so a renderer can be careful.
    """
    years = []
    for svc in detail.get("sessions") or []:
        m = re.match(r"(\d{4})", svc.get("description") or "")
        if m:
            years.append((int(m.group(1)), svc.get("description")))
    return min(years) if years else (None, None)


def build_record(listing, detail, legis_session, committees, prior):
    """One roster record in the canonical schema, plus the SOAP-only extras."""
    chamber = CHAMBER.get(listing.get("chamber")) or listing.get("chamber")
    svc = current_service(detail, legis_session) or {}
    legis_id = listing.get("id")
    carried = prior or {}

    # Display name, NOT the formal one SOAP returns. SOAP gives the legal name
    # ("Timothy Bearden", "Michael 'Doc' Rhett", "Larry Walker, III") where the site uses
    # the common one ("Tim Bearden", "Doc Rhett", "Larry Walker"). All 18 such members
    # would otherwise have their entity URL move, because build_entity_pages.py slugs on
    # the name. `Nickname` cannot rebuild it either: populated on 5 of the 18 and itself
    # inconsistent (`Reynaldo "Rey"`, `Tremaine Teddy`). So a known member keeps the name
    # we already publish, and a genuine rename is surfaced for review instead of applied.
    soap_name = " ".join(p for p in (listing.get("first"), listing.get("last")) if p)
    name = carried.get("name") or soap_name

    # Committee names for the session, chairs and members alike, flattened to the shape
    # the site already consumes. `role` is kept separately rather than folded into the
    # string, so nothing that renders the list has to parse it back out.
    coms = [c for c in (svc.get("committees") or []) if c.get("name")]
    committee_names = sorted({c["name"] for c in coms})

    badge, badge_note = normalize_title(svc.get("title"), listing.get("chamber"), committees)

    term_year, term_session = earliest_session_year(detail)

    return {
        # Carried from the committed roster (spec §4): SOAP has no OCD id. A member the
        # roster does not know gets a deterministic synthetic key, assigned once.
        "id":               carried.get("id") or f"legis-{legis_id}",
        "name":             name,
        "firstName":        carried.get("firstName") or listing.get("first") or None,
        "lastName":         carried.get("lastName") or listing.get("last") or None,
        "party":            PARTY.get(listing.get("party")) or listing.get("party") or None,
        "chamber":          chamber,
        "district":         listing.get("district"),
        # Derived, not sourced: the committed roster's `title` is only ever
        # "Representative"/"Senator". SOAP's Title is a LEADERSHIP role -> leadershipRole.
        "title":            TITLE.get(chamber),
        "imageUrl":         portrait(detail),
        "phone":            format_phone(detail.get("phone")),
        "address":          compose_address(detail),
        "email":            detail.get("email") or None,
        "officialWebsiteUrl": (
            f"https://www.legis.ga.gov/members/{CHAMBER_SLUG[chamber]}/{legis_id}"
            if chamber in CHAMBER_SLUG else None),
        # Not in SOAP at any granularity that yields an age — preserved, or absent.
        "birthDate":        carried.get("birthDate"),
        "birthYear":        carried.get("birthYear"),
        "termStart":        carried.get("termStart"),
        "termStartYear":    carried.get("termStartYear") or term_year,
        "committees":       committee_names,
        "legisGaGovId":     legis_id,
        # Departure status stays editorial: SOAP has the date but not the reason, and
        # "Suspended" members keep the seat. The producer only surfaces the signal.
        "status":           None,
        "statusDate":       None,
        "statusNote":       None,

        # ---- SOAP-only, not in the committed roster ----
        "leadershipRole":   badge,
        "committeeRoles":   [{"name": c["name"], "role": c.get("role")} for c in coms],
        "termStartSession": term_session,
        "birthdayMonthDay": detail.get("birthday") or None,
        "occupation":       detail.get("occupation") or None,
        "residence":        detail.get("residence") or listing.get("residence") or None,
        "pressUrl":         detail.get("pressUrl") or None,
        "dateVacated":      listing.get("dateVacated") or None,
        "_badgeNote":       badge_note,
        "_soapName":        soap_name if soap_name != name else None,
    }


def main():
    tag, legis_session = regular_session()
    print(f"Building the SOAP roster for {tag} (legis session {legis_session})\n")

    if not os.path.exists(MEMBERS_FILE):
        print(f"Error: {MEMBERS_FILE} is required (it supplies OCD ids and birth/term "
              f"values SOAP cannot) — aborting", file=sys.stderr)
        return 1
    with open(MEMBERS_FILE, encoding="utf-8") as fh:
        existing = json.load(fh).get("members", [])
    by_legis_id = {m["legisGaGovId"]: m for m in existing if m.get("legisGaGovId")}
    print(f"  committed roster: {len(existing)} records "
          f"({len(by_legis_id)} joinable by legisGaGovId)")

    committees = committee_index(get_committees_by_session(legis_session))
    print(f"  committees: {len(committees)} indexed for leadership validation")

    listings = get_members_by_session(legis_session)
    if not listings:
        print("Error: GetMembersBySession returned nothing — aborting", file=sys.stderr)
        return 1

    # Anyone in the committed roster the Members service does not return is PRESERVED
    # VERBATIM, keyed on absence from the listing rather than on lacking a legisGaGovId.
    # That distinction matters: the Lt. Governor has one (805, he presides over the
    # Senate) but is not a member, so an id-based rule silently dropped him.
    in_listing = {l["id"] for l in listings}
    preserved = [m for m in existing if m.get("legisGaGovId") not in in_listing]
    print(f"  members: {len(listings)} listings — fetching detail")
    print(f"  preserved (not in the Members service): "
          f"{', '.join(m.get('name') or '?' for m in preserved) or 'none'}\n")

    members, carried, unknown_ids, notes = [], [], [], []
    vacated_unflagged, lapsed, renamed = [], [], []
    for i, listing in enumerate(listings, 1):
        legis_id = listing["id"]
        prior = by_legis_id.get(legis_id)
        detail = get_member(legis_id)
        if detail is None:
            if prior:
                members.append(dict(prior))
                carried.append(f"{listing.get('first')} {listing.get('last')} ({legis_id})")
            else:
                print(f"  WARNING: {legis_id} detail failed and is not in the committed "
                      f"roster — omitted", file=sys.stderr)
            continue

        rec = build_record(listing, detail, legis_session, committees, prior)
        if not prior:
            unknown_ids.append(f"{rec['name']} ({legis_id}) -> {rec['id']}")
        if rec.pop("_badgeNote", None):
            notes.append(f"{rec['name']}: {listing.get('chamber')} title needs review")
        soap_name = rec.pop("_soapName", None)
        if soap_name:
            renamed.append(f"{rec['name']!r} (we publish) vs {soap_name!r} (legis.ga.gov)")
        svc = current_service(detail, legis_session) or {}
        if svc.get("title") and rec["leadershipRole"] is None:
            lapsed.append(f"{rec['name']}: {svc['title']!r}")
        # SOAP proposes, a human disposes (spec §8.4): flag a departure the overrides
        # file has not characterised, never write a status.
        if rec["dateVacated"] and not (prior or {}).get("status"):
            vacated_unflagged.append(f"{rec['name']} ({legis_id}) vacated {rec['dateVacated'][:10]}")
        members.append(rec)

        if i % 50 == 0:
            print(f"    {i}/{len(listings)}")
        time.sleep(DELAY)

    if len(carried) > max(1, int(len(listings) * MAX_CARRIED_SHARE)):
        print(f"Error: {len(carried)} of {len(listings)} members carried forward — that is "
              f"an outage, not a transient. Refusing to write.", file=sys.stderr)
        return 1

    members.extend(preserved)
    members.sort(key=lambda m: (m.get("chamber") or "", m.get("name") or ""))

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "legis.ga.gov SOAP (Members + Committees services)",
            "jurisdiction": "Georgia",
            "session": tag,
            "legisSessionId": legis_session,
            "count": len(members),
            "committeesAvailable": bool(committees),
            "carriedForward": len(carried),
            "withoutOcdId": sum(1 for m in members if not str(m.get("id", "")).startswith("ocd-person/")),
            "preservedNotInMembersService": len(preserved),
            "parallelTo": MEMBERS_FILE,
            "note": "Phase 0 comparison artifact. NOT consumed by the site.",
        },
        "members": members,
        "review": {
            "carriedForward": carried,
            "notInCommittedRoster": unknown_ids,
            "lapsedLeadershipTitles": lapsed,
            "leadershipNeedsReview": notes,
            "vacatedWithoutStatusOverride": vacated_unflagged,
            "nameDiffersFromLegis": renamed,
            "preservedNotInMembersService": [m.get("name") for m in preserved],
        },
    }
    write_json_atomic(OUTPUT_FILE, output, indent=2)

    print(f"\nWrote {len(members)} records to {OUTPUT_FILE}")
    print(f"  carried forward            : {len(carried)}")
    print(f"  not in the committed roster: {len(unknown_ids)}")
    print(f"  leadership badges          : {sum(1 for m in members if m.get('leadershipRole'))}")
    print(f"  lapsed titles (not badged) : {len(lapsed)}")
    print(f"  departures to characterise : {len(vacated_unflagged)}")
    print(f"  display names differing from legis: {len(renamed)}")
    for label, rows in (("carried forward", carried), ("new to us", unknown_ids),
                        ("lapsed titles", lapsed), ("needs review", notes),
                        ("vacated, no status", vacated_unflagged), ("renamed", renamed)):
        for r in rows[:8]:
            print(f"    [{label}] {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
