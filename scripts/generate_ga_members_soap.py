#!/usr/bin/env python3
"""Generate the canonical GA legislator roster from legis.ga.gov SOAP.

Phase 1 of Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md: this is the producer behind
`assets/data/ga-members.json`. It replaces the Open States producer
(`generate_ga_members_data.py`, kept for rollback per spec §9) and needs no API key and
no quota. Run `compare_members_soap_vs_os.py` against a saved Open States roster to
re-prove equivalence before any change to the mapping.

Keys are UNCHANGED in this phase: `id` is still the OCD person id, carried from the
committed roster by `legisGaGovId`, so every join into vote data keeps working (spec §4).
A member the roster does not know gets `legis-<legisGaGovId>`, assigned once and never
rewritten.

Cost: one `GetMembersBySession` + one `GetCommitteesBySession` + one `GetMember` per
member (~250 calls). No auth, no quota. A single member's detail failing carries that
member forward from the committed roster rather than failing the run or dropping them
(spec §8.5); the count is reported and a large share is fatal.

A biennium ROLLOVER (the session being built differs from the committed file's) is never
done by the daily run: it refuses, says what it detected, and exits 1. A human runs it once
with `--new-biennium` after freezing the outgoing roster; see RECURRING-TASKS.md §3.

Three fields SOAP cannot supply, carried over from the committed roster by legisGaGovId:
  * `id`        — the OCD person id. See spec §4; a member with none gets `legis-<id>`.
  * `birthDate` / `birthYear` — SOAP has month+day only, which cannot yield an age.
  * `termStart` — SOAP has the earliest session served, not a date; `termStartYear` is
    derived from it for a member the committed roster does not know.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.ga_identity import apply_identity_slots, load_pin_overrides
from lib.ga_leadership import committee_index, normalize_title
from lib.ga_roster import (apply_member_overrides, biennium_slug, convening_date,
                           detect_rollover, display_committee, listing_is_too_short,
                           normalize_address, out_of_scope_entries, split_for_rollover,
                           untagged_departures)
from lib.ga_sessions import SESSION_NAMES, all_session_ids, legis_session_id
from lib.ga_soap import (get_committees_by_session, get_member, get_members_by_session)

MEMBERS_FILE    = "assets/data/ga-members.json"
OVERRIDES_FILE  = "assets/data/ga-members-overrides.json"
IDENTITY_SIDECAR = "assets/data/ga-openstates-crosswalk.json"

DELAY = 0.1           # politeness between GetMember calls; there is no quota
#: Carrying a member forward is for a transient. Past this share it is an outage.
MAX_CARRIED_SHARE = 0.1
#: Floor mirroring update-ga-members.yml's own check (spec §7.2): refuse to WRITE a short
#: roster rather than let the workflow discover it after the fact. The General Assembly is
#: 56 + 180; anything materially under that is a bad fetch, not an election result.
MIN_SENATE, MIN_HOUSE = 56, 180

#: Where freeze-ga-roster publishes the outgoing biennium (publish_ga_legislators.REPO).
ARCHIVE_URL = ("https://raw.githubusercontent.com/Votega/ga-legislators/main/"
               "sessions/{slug}/members.json")

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


def first_term_start(term_session, building_description):
    """Convening date of the session a member first served, or None if it isn't knowable.

    Only for a member whose earliest session IS the regular session being built — a
    first-term member at a biennium rollover, who took the oath on the opening day, so
    "the second Monday of January" is accurate where null is merely missing. Never for a
    special-session entrant (seated on a date SOAP does not give) and never for an older
    session, which can overstate tenure (see earliest_session_year).
    """
    m = re.match(r"(\d{4})-\d{4} Regular Session", term_session or "")
    if not m or term_session != building_description:
        return None
    return convening_date(int(m.group(1))).isoformat()


def outgoing_archived(slug):
    """Is sessions/<slug>/members.json published in the sibling repo? Any failure is False."""
    try:
        req = urllib.request.Request(ARCHIVE_URL.format(slug=slug), method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def build_record(listing, detail, legis_session, committees, prior, rollover=False):
    """One roster record in the canonical schema, plus the SOAP-only extras.

    `rollover` additionally derives `termStart` for a first-term member (see
    first_term_start). It is off for an ordinary run: a member who joins mid-biennium
    by special election would otherwise be dated to the opening day.
    """
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
    committee_names = sorted({n for n in (display_committee(c["name"]) for c in coms) if n})

    badge, badge_note = normalize_title(svc.get("title"), listing.get("chamber"), committees)

    term_year, term_session = earliest_session_year(detail)
    term_start = carried.get("termStart")
    if rollover and not term_start:
        term_start = first_term_start(term_session, svc.get("description"))

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
        "address":          normalize_address(detail.get("address1"), detail.get("city"),
                                              detail.get("state"), detail.get("zip")),
        # Two sitting senators have no email in the Members service where the roster has
        # one. Falling back keeps the exit criterion "additive-or-better on every member"
        # true; the alternative is deriving the address, which would be inventing contact
        # details for a public official.
        "email":            detail.get("email") or carried.get("email") or None,
        "officialWebsiteUrl": (
            f"https://www.legis.ga.gov/members/{CHAMBER_SLUG[chamber]}/{legis_id}"
            if chamber in CHAMBER_SLUG else None),
        # Not in SOAP at any granularity that yields an age — preserved, or absent.
        "birthDate":        carried.get("birthDate"),
        "birthYear":        carried.get("birthYear"),
        "termStart":        term_start,
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
        # Same display names as `committees` above — the two must agree, or a consumer
        # joining one to the other silently loses the aliased committee.
        "committeeRoles":   [{"name": display_committee(c["name"]), "role": c.get("role")}
                             for c in coms],
        "termStartSession": term_session,
        "birthdayMonthDay": detail.get("birthday") or None,
        "occupation":       detail.get("occupation") or None,
        "residence":        detail.get("residence") or listing.get("residence") or None,
        "pressUrl":         detail.get("pressUrl") or None,
        "dateVacated":      listing.get("dateVacated") or None,
        "_badgeNote":       badge_note,
        "_soapName":        soap_name if soap_name != name else None,
    }


def slugify_member(m):
    """The entity slug build_entity_pages.py will give this member (name, chamber, district)."""
    parts = [m.get("name"), "senate" if m.get("chamber") == "Senate" else "house",
             m.get("district")]
    s = " ".join(str(p) for p in parts if p not in (None, "")).lower().replace("&", " and ")
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s).strip("-"))


def _load_json(path):
    """A sidecar that does not exist yet is an empty one: every slot reads "unresolved"."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("output", nargs="?", default=None,
                    help=f"roster file to write (default {MEMBERS_FILE})")
    ap.add_argument("--new-biennium", action="store_true",
                    help="acknowledge and perform a biennium rollover; refused otherwise")
    ap.add_argument("--archive-confirmed", action="store_true",
                    help="assert the outgoing roster was frozen (skips the published-"
                         "archive check)")
    return ap.parse_args(argv)


def refuse_rollover(rollover):
    """Print what was detected and why the run stopped."""
    was, now = rollover["from"], rollover["to"]
    print(f"Error: biennium changeover detected — the committed roster is for "
          f"{was['session']} (legis session {was['legisSessionId']}), this run would "
          f"build {now['session']} (legis session {now['legisSessionId']}).\n"
          f"The ordinary run republishes every committed member the new listing lacks as "
          f"sitting, which would carry the whole outgoing class into the new General "
          f"Assembly. Refusing to write. This is not a failure of the data: a person "
          f"rolls the roster over, once —\n"
          f"  1. freeze-ga-roster for {biennium_slug(was['session']) or was['session']}\n"
          f"  2. python scripts/generate_ga_members_soap.py --new-biennium\n"
          f"See RECURRING-TASKS.md §3.", file=sys.stderr)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    output_file = args.output or MEMBERS_FILE
    tag, legis_session = regular_session()
    print(f"Building the SOAP roster for {tag} (legis session {legis_session})\n")

    if not os.path.exists(MEMBERS_FILE):
        print(f"Error: {MEMBERS_FILE} is required (it supplies OCD ids and birth/term "
              f"values SOAP cannot) — aborting", file=sys.stderr)
        return 1
    with open(MEMBERS_FILE, encoding="utf-8") as fh:
        committed = json.load(fh)
    existing = committed.get("members", [])
    by_legis_id = {m["legisGaGovId"]: m for m in existing if m.get("legisGaGovId")}
    print(f"  committed roster: {len(existing)} records "
          f"({len(by_legis_id)} joinable by legisGaGovId)")

    # A changeover is never the daily run's to perform: detect it and stop unless a person
    # asked for it. Neither half is advisory — an unacknowledged rollover would publish the
    # outgoing class as sitting, and `--new-biennium` against an unchanged session would
    # drop the preserved records an ordinary run depends on.
    rollover = detect_rollover(committed.get("metadata"), tag, legis_session)
    if rollover and not args.new_biennium:
        refuse_rollover(rollover)
        return 1
    if args.new_biennium and not rollover:
        print(f"Error: --new-biennium given, but the committed roster is already for "
              f"{tag} (legis session {legis_session}) — there is nothing to roll over. "
              f"Refusing to write.", file=sys.stderr)
        return 1
    if rollover:
        was_slug = biennium_slug(rollover["from"]["session"])
        if not args.archive_confirmed and not (was_slug and outgoing_archived(was_slug)):
            print(f"Error: sessions/{was_slug}/members.json is not published in the "
                  f"ga-legislators repo. Run freeze-ga-roster for {was_slug} FIRST — once "
                  f"this writes, the outgoing roster is gone from the repo. (Pass "
                  f"--archive-confirmed if you froze it and this check cannot see it.)",
                  file=sys.stderr)
            return 1
        loose = untagged_departures(OVERRIDES_FILE)
        if loose:
            print(f"Error: {len(loose)} override entr{'y' if len(loose) == 1 else 'ies'} "
                  f"record a departure without `_session`: {loose[:5]}. Each describes a "
                  f"seat of one biennium; tag it (\"_session\": "
                  f"\"{rollover['from']['session']}\") so it does not leak into {tag}. "
                  f"Refusing to write.", file=sys.stderr)
            return 1
        print(f"ROLLOVER {rollover['from']['session']} -> {tag}: members absent from the "
              f"new listing are dropped, not preserved\n")

    committees = committee_index(get_committees_by_session(legis_session))
    print(f"  committees: {len(committees)} indexed for leadership validation")

    listings = get_members_by_session(legis_session)
    if not listings:
        print("Error: GetMembersBySession returned nothing — aborting", file=sys.stderr)
        return 1
    # A truncated listing would NOT shrink the roster — everyone missing from it is
    # preserved verbatim below — so the count floor downstream cannot catch it. It would
    # quietly republish most of the roster as stale, which looks like a clean run.
    # (Skipped at a rollover: the new class is legitimately smaller than the committed file,
    # which still holds every departed member; the 56/180 floor below still applies.)
    if not rollover and listing_is_too_short(len(listings), len(by_legis_id)):
        print(f"Error: GetMembersBySession returned {len(listings)} members against "
              f"{len(by_legis_id)} in the committed roster. Preserving that many stale "
              f"records would look like a clean run. Refusing to write.", file=sys.stderr)
        return 1

    # Anyone in the committed roster the Members service does not return is PRESERVED
    # VERBATIM, keyed on absence from the listing rather than on lacking a legisGaGovId.
    # That distinction matters: the Lt. Governor has one (805, he presides over the
    # Senate) but is not a member, so an id-based rule silently dropped him.
    in_listing = {l["id"] for l in listings}
    if rollover:
        preserved, departing = split_for_rollover(existing, in_listing)
    else:
        preserved = [m for m in existing if m.get("legisGaGovId") not in in_listing]
        departing = []
    print(f"  members: {len(listings)} listings — fetching detail")
    print(f"  preserved (not in the Members service): "
          f"{', '.join(m.get('name') or '?' for m in preserved) or 'none'}\n")

    members, carried, unknown_ids, notes = [], [], [], []
    vacated_unflagged, vacated_disagrees, lapsed, renamed = [], [], [], []
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

        rec = build_record(listing, detail, legis_session, committees, prior,
                           rollover=bool(rollover))
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
        members.append(rec)

        if i % 50 == 0:
            print(f"    {i}/{len(listings)}")
        time.sleep(DELAY)

    if len(carried) > max(1, int(len(listings) * MAX_CARRIED_SHARE)):
        print(f"Error: {len(carried)} of {len(listings)} members carried forward — that is "
              f"an outage, not a transient. Refusing to write.", file=sys.stderr)
        return 1

    members.extend(preserved)

    # ---- Guards (spec §7). Each refuses to write rather than publishing the damage. ----
    # The key-form guards run BEFORE the editorial layer: an `_inject` entry is allowed a
    # synthetic id (CLAUDE.md documents `ga-senate-7-vacant`), so holding the hand-
    # maintained layer to the producer's key rule would break the documented escape hatch.

    # §7.3 A member's id is assigned once and never changes: re-keying a sitting member
    # breaks their vote join and their append-only vgId.
    was = {m["legisGaGovId"]: m["id"] for m in existing
           if m.get("legisGaGovId") and m.get("id")}
    rekeyed = [f"{m['name']} ({m['legisGaGovId']}): {was[m['legisGaGovId']]} -> {m['id']}"
               for m in members
               if m.get("legisGaGovId") in was and m.get("id") != was[m["legisGaGovId"]]]
    if rekeyed:
        print(f"Error: {len(rekeyed)} member id(s) changed, which breaks the vote join "
              f"and the vgId ledger. Refusing to write.", file=sys.stderr)
        for r in rekeyed:
            print(f"  {r}", file=sys.stderr)
        return 1

    # §7.4 Never invent an OCD id. A synthetic key must be the deterministic legis- form.
    bad_keys = [m["id"] for m in members if not (
        str(m.get("id", "")).startswith("ocd-person/")
        or str(m.get("id", "")) == f"legis-{m.get('legisGaGovId')}")]
    if bad_keys:
        print(f"Error: {len(bad_keys)} member(s) have a key that is neither an OCD id nor "
              f"legis-<legisGaGovId>: {bad_keys[:5]}. Refusing to write.", file=sys.stderr)
        return 1

    # The editorial layer: departures, suspensions, and members the service has not yet
    # caught up with. Without this the roster has no concept of a member having left —
    # 11 Resigned and 1 Suspended would read as sitting and the majority tracker would
    # paint their seats as filled.
    # Scoped to this biennium: an entry tagged `_session` for another one is inert.
    patched, injected = apply_member_overrides(members, OVERRIDES_FILE, session=tag)
    print(f"\n  overrides: patched {patched}, injected {injected}")

    members.sort(key=lambda m: (m.get("chamber") or "", m.get("name") or ""))

    # Identity slots (ocdPersonId / ballotpediaId + provenance). ADDITIVE and
    # nullable: legisGaGovId is the primary key, `id` stays an opaque handle and is never
    # touched here. The values come from generate_openstates_crosswalk.py's sidecar.
    apply_identity_slots(members, _load_json(IDENTITY_SIDECAR), load_pin_overrides())

    # SOAP proposes, a human disposes (spec §8.4): surface a departure, never write a
    # status. Computed AFTER the overrides so these describe the file they ship in — read
    # against the PREVIOUS file instead, a departure characterised in this very run still
    # showed up as outstanding, and the queue lagged a day behind the data.
    for m in members:
        vacated, ours = (m.get("dateVacated") or "")[:10], m.get("statusDate")
        if not vacated:
            continue
        if not m.get("status"):
            vacated_unflagged.append(
                f"{m['name']} ({m.get('legisGaGovId')}) vacated {vacated}")
        elif ours and ours != vacated:
            # Ours may still be the better date — an announced resignation against the
            # day the seat was recorded empty. Surfaced for a human, never applied.
            vacated_disagrees.append(
                f"{m['name']}: we record {ours}, legis.ga.gov {vacated}")

    # §7.2 No silent roster shrink.
    sitting = [m for m in members if m.get("status") in (None, "Suspended")]
    n_sen = sum(1 for m in sitting if m.get("chamber") == "Senate")
    n_house = sum(1 for m in sitting if m.get("chamber") == "House of Representatives")
    if n_sen < MIN_SENATE or n_house < MIN_HOUSE:
        print(f"Error: roster is short — Senate {n_sen}/{MIN_SENATE}, House "
              f"{n_house}/{MIN_HOUSE}. Refusing to write.", file=sys.stderr)
        return 1

    # §7.6 Party vocabulary: a leaked "Democrat" drops the member from every party tally.
    stray = sorted({m.get("party") for m in members
                    if m.get("party") not in (None, "Democratic", "Republican")})
    if stray:
        print(f"Error: unexpected party value(s) {stray} — party tallies bucket on exact "
              f"strings. Refusing to write.", file=sys.stderr)
        return 1

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "legis.ga.gov official web service (Members + Committees)",
            "jurisdiction": "Georgia",
            "session": tag,
            "legisSessionId": legis_session,
            "count": len(members),
            "committeesAvailable": bool(committees),
            "carriedForward": len(carried),
            "withoutOcdId": sum(1 for m in members if m.get("ocdPersonId") is None),
            "preservedNotInMembersService": len(preserved),
            "overridesApplied": patched,
            "overridesInjected": injected,
        },
        "members": members,
        "review": {
            "carriedForward": carried,
            "notInCommittedRoster": unknown_ids,
            "lapsedLeadershipTitles": lapsed,
            "leadershipNeedsReview": notes,
            "vacatedWithoutStatusOverride": vacated_unflagged,
            "vacatedDateDiffersFromOurs": vacated_disagrees,
            "nameDiffersFromLegis": renamed,
            "preservedNotInMembersService": [m.get("name") for m in preserved],
        },
    }
    if rollover:
        # Queues for a human, in the existing `review` object. Only at a rollover: an
        # ordinary run's file must stay byte-identical.
        def line(m):
            return (f"{m.get('name')} ({m.get('legisGaGovId')}): "
                    f"{m.get('chamber')} district {m.get('district')}")
        incoming = [m for m in members if m.get("legisGaGovId") in in_listing
                    and m["legisGaGovId"] not in by_legis_id]
        skipped = out_of_scope_entries(OVERRIDES_FILE, tag)
        output["metadata"]["rollover"] = {
            **rollover, "incoming": len(incoming), "departing": len(departing),
            "outOfScopeOverrides": len(skipped)}
        output["review"].update({
            "incomingCohort": [line(m) for m in incoming],
            # Departed members the new roster no longer carries: they live on in the
            # frozen archive and in the votes of the biennium they served.
            "departingCohort": [line(m) + (f" [{m['status']}]" if m.get("status") else "")
                                for m in departing],
            # A brand-new member is published under the FORMAL legis.ga.gov name, and
            # build_entity_pages.py slugs the entity URL on it. Settle each name (override
            # `name`/`firstName`/`lastName` by legisGaGovId) BEFORE the first entity
            # build; changing one afterwards moves a live URL.
            "newMemberNameReview": [
                f"{m['name']!r} -> /ga-legislators/{slugify_member(m)}/ "
                f"(legisGaGovId {m['legisGaGovId']})" for m in incoming],
            "rolloverPreservedNonMembers": [
                f"{m.get('name')} ({m.get('chamber')}) — verify they still hold the office"
                for m in preserved],
            "overridesOutOfScope": skipped,
        })
    write_json_atomic(output_file, output, indent=2)

    print(f"\nWrote {len(members)} records to {output_file}")
    print(f"  carried forward            : {len(carried)}")
    print(f"  not in the committed roster: {len(unknown_ids)}")
    print(f"  leadership badges          : {sum(1 for m in members if m.get('leadershipRole'))}")
    print(f"  lapsed titles (not badged) : {len(lapsed)}")
    print(f"  departures to characterise : {len(vacated_unflagged)}")
    print(f"  departure dates disagreeing: {len(vacated_disagrees)}")
    print(f"  display names differing from legis: {len(renamed)}")
    for label, rows in (("carried forward", carried), ("new to us", unknown_ids),
                        ("lapsed titles", lapsed), ("needs review", notes),
                        ("vacated, no status", vacated_unflagged),
                        ("vacated date differs", vacated_disagrees), ("renamed", renamed)):
        for r in rows[:8]:
            print(f"    [{label}] {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
