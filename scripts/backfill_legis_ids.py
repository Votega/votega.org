#!/usr/bin/env python3
"""Propose legisGaGovId backfills for GA members missing one (turnover-safe join).

Why this exists
---------------
generate_ga_votes_from_legis.py joins each legis.ga.gov roll-call row to a person
by the legislature's own numeric `member.id` (== `legisGaGovId`). That join is
collision-proof — BUT only for members who actually carry a `legisGaGovId` in the
crosswalk. Members who don't (freshmen Open States hasn't stamped a `georgia_id`
on yet, and members who RESIGNED mid-session) fall through to a `(chamber,
district)` fallback, and that fallback is unsafe across turnover: a resigned
member and their successor share a district, so the resigned member's votes get
mis-attributed to whoever holds the seat now (confirmed 2026-10-03: Karen
Bennett H94 -> Venola Mason, etc.).

The fix is to give EVERY member a real `legisGaGovId` so resolution can be
id-only. This script finds the gap and proposes the fills; a human reviews the
proposal and merges it into ga-members-overrides.json (the documented channel:
generate_ga_members_data.py reads legisGaGovId from there -> ga-members.json ->
build_id_crosswalk.py -> id-crosswalk.json). It writes NO override itself.

How it matches
--------------
1. Load the crosswalk's existing legisGaGovId set — any legis roster member whose
   id is already there needs nothing, so we never member-detail them.
2. Enumerate the full session roster (members/search-options). It includes members
   who served the session, resigned ones included (247 for 1033 = 180+56 seats +
   11 turnover extras), so resigned members are covered.
3. member-detail each UNRESOLVED roster id for its districtNumber + structured
   name, then match to a ga-members.json person by (chamber, district, lastName).
   The lastName is what disambiguates a seat that holds both a resigned member and
   a successor (both can be null-id — e.g. H94 Bennett + Mason).

Output: out/legis-id-backfill.json — proposals (null-id members we can fill),
conflicts (members whose EXISTING legisGaGovId disagrees with the roster — a red
flag), and the two "unmatched" lists so nothing is silently dropped.

Auth: like the producer, needs LEGIS_GA_CLIENT_KEY (auto-mint) or LEGIS_GA_TOKEN.
Live minting is blocked in the Claude Code agent sandbox, so run this in CI (the
inspect workflow's `backfill` mode) or locally. The matching helpers are pure and
unit-testable offline.

Usage:
  python backfill_legis_ids.py                      # active session -> out/legis-id-backfill.json
  python backfill_legis_ids.py --session 2025_26
  python backfill_legis_ids.py --all-sessions       # every configured legis session
  python backfill_legis_ids.py --out PATH.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

from lib.atomic_io import write_json_atomic
from lib.legis_ga import CHAMBER, LegisGaClient
from lib.ga_sessions import (ACTIVE_SESSION, all_session_ids, legis_session_id,
                             session_name)

GA_MEMBERS_FILE = "assets/data/ga-members.json"
CROSSWALK_FILE = "assets/data/id-crosswalk.json"
DEFAULT_OUTPUT = "out/legis-id-backfill.json"

#: Only General Assembly members carry a legisGaGovId; statewide executives sit in
#: ga-members.json under chamber "executive" and must never be matched here.
LEGISLATOR_CHAMBERS = ("House of Representatives", "Senate")


# -- pure helpers (no network / no disk; unit-testable with fixtures) -----

def normalize_surname(name):
    """Fold a surname for cross-source comparison: case, whitespace, punctuation.

    'O'Steen' == "o steen"; 'White Carden' matches either 'White' or 'Carden'
    handling is left to the caller — this only canonicalizes one token string.
    """
    return re.sub(r"[^a-z]+", " ", (name or "").lower()).strip()


def surname_tokens(name):
    """Surname as a set of word tokens, for robust compound-surname matching
    ('White Carden' -> {'white', 'carden'}; "O'Steen" -> {'o', 'steen'})."""
    return set(normalize_surname(name).split())


def index_ga_members(members):
    """Index the GA roster for matching. Returns
    (by_ocd, by_chamber_district) where by_chamber_district[(chamber, district)]
    is the list of member dicts at that seat (>1 means turnover: a resigned member
    plus a successor, which is exactly why lastName disambiguation is needed)."""
    by_ocd, by_chamber_district = {}, {}
    for m in members:
        if m.get("chamber") not in LEGISLATOR_CHAMBERS:
            continue
        ocd = m.get("id")
        if ocd:
            by_ocd[ocd] = m
        district = m.get("district")
        if district is not None:
            by_chamber_district.setdefault((m["chamber"], int(district)), []).append(m)
    return by_ocd, by_chamber_district


def match_member(chamber, district, surname, by_chamber_district):
    """Match one legis roster member to a ga-members person.

    Returns (member_dict_or_None, basis) where basis describes how it matched:
      'seat+surname' — one surname match among the seat's occupants (the normal win)
      'seat-unique'  — exactly one person at the seat and the surname agrees loosely
      'ambiguous'    — several surname matches (shouldn't happen; surfaced for review)
      'no-surname-match' / 'no-seat' — nothing matched.
    """
    if district is None:
        return None, "no-seat"
    seat = by_chamber_district.get((chamber, int(district))) or []
    if not seat:
        return None, "no-seat"
    want = surname_tokens(surname)
    want_joined = "".join(sorted(want))
    # A legis surname matches a ga lastName when their token sets overlap OR their
    # spaceless-folded forms are equal — handles compound/hyphenated surnames and
    # punctuation drift ("O'Steen" -> "osteen" either way) between the two sources.
    def _matches(last):
        toks = surname_tokens(last)
        return bool(toks & want) or "".join(sorted(toks)) == want_joined
    hits = [m for m in seat if want and _matches(m.get("lastName"))]
    if len(hits) == 1:
        return hits[0], "seat+surname"
    if len(hits) > 1:
        return None, "ambiguous"
    if len(seat) == 1:
        # Single occupant, surname didn't token-overlap (maiden name, data drift) —
        # still a confident seat match, flagged so a human eyeballs the name.
        return seat[0], "seat-unique"
    return None, "no-surname-match"


def detail_fields(detail):
    """Pull (district, surname, party_code) from a members/detail response,
    defensively (the structured `name` object or a flat fallback)."""
    detail = detail or {}
    district = detail.get("districtNumber")
    if district is None:
        district = detail.get("district")
    name = detail.get("name")
    surname = None
    if isinstance(name, dict):
        surname = name.get("last") or name.get("lastName")
    if not surname and isinstance(name, str):
        # "SURNAME, 94TH" or "First Last" — last resort.
        surname = name.split(",")[0].strip().split()[-1] if name else None
    return (int(district) if district is not None else None,
            surname, detail.get("party"))


# -- crosswalk + build (I/O) ----------------------------------------------

def crosswalk_legis_ids(path=CROSSWALK_FILE):
    """The set of legisGaGovId values already present in the crosswalk — roster
    ids in here are resolved and need no member-detail call."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return set()
    out = set()
    for person in data.get("people", []):
        lid = (person.get("ids") or {}).get("legisGaGovId")
        if lid is not None:
            out.add(int(lid))
    return out


def backfill_session(client, our_session, by_ocd, by_chamber_district,
                     known_ids, verbose=True):
    """Enumerate one session's roster, member-detail the unresolved ids, and match
    them to ga-members. Returns (proposals, conflicts, unmatched_legis, stats)."""
    legis_session = legis_session_id(our_session)
    roster = client.members(legis_session) or []
    proposals, conflicts, unmatched_legis = [], [], []
    detailed = already = 0

    for entry in roster:
        mid = entry.get("id")
        if mid is None:
            continue
        mid = int(mid)
        if mid in known_ids:
            already += 1
            continue  # already in the crosswalk — no backfill needed, no detail call
        chamber_type = entry.get("chamberType")
        chamber = CHAMBER.get(chamber_type)
        detail = client.member_detail(mid, legis_session, chamber_type)
        detailed += 1
        district, surname, party = detail_fields(detail)
        # Fall back to the roster's own display name if detail lacked a surname.
        if not surname:
            disp = entry.get("name") or ""
            surname = disp.split(",")[0].strip() if disp else None

        member, basis = match_member(chamber, district, surname, by_chamber_district)
        rec = {
            "legisId": mid,
            "chamber": chamber,
            "district": district,
            "legisSurname": surname,
            "party": party,
            "session": our_session,
            "matchBasis": basis,
        }
        if member is None:
            unmatched_legis.append(rec)
            continue
        current = member.get("legisGaGovId")
        rec.update({
            "ocdPersonId": member.get("id"),
            "memberName": member.get("name"),
            "memberLastName": member.get("lastName"),
            "status": member.get("status"),
            "currentLegisId": current,
        })
        if current is None:
            proposals.append(rec)
        elif int(current) != mid:
            conflicts.append(rec)  # existing id disagrees with the roster — review!
        # else: already correct — nothing to do.

    stats = {
        "session": our_session,
        "rosterCount": len(roster),
        "alreadyResolved": already,
        "detailFetched": detailed,
        "proposed": len(proposals),
        "conflicts": len(conflicts),
        "unmatchedLegis": len(unmatched_legis),
    }
    if verbose:
        print("  %s: roster %d, already-resolved %d, detailed %d -> %d proposals, "
              "%d conflicts, %d unmatched-legis"
              % (our_session, len(roster), already, detailed, len(proposals),
                 len(conflicts), len(unmatched_legis)))
    return proposals, conflicts, unmatched_legis, stats


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Propose legisGaGovId backfills (turnover-safe, review-gated).")
    p.add_argument("--session", default=None, metavar="TAG",
                   help="session tag (default: active, %s)" % ACTIVE_SESSION)
    p.add_argument("--all-sessions", action="store_true", dest="all_sessions",
                   help="sweep every configured legis session (union the proposals)")
    p.add_argument("--out", default=DEFAULT_OUTPUT, metavar="PATH",
                   help="proposal output path (default: %(default)s)")
    return p.parse_args(argv)


def main():
    args = parse_args()

    if args.all_sessions:
        sessions = [t for t in all_session_ids() if legis_session_id(t) is not None]
    else:
        tag = args.session or ACTIVE_SESSION
        if tag not in all_session_ids():
            print("Error: unknown session '%s'. Configured: %s."
                  % (tag, ", ".join(all_session_ids())), file=sys.stderr)
            sys.exit(1)
        if legis_session_id(tag) is None:
            print("Error: session '%s' has no legis.ga.gov id in lib/ga_sessions.py."
                  % tag, file=sys.stderr)
            sys.exit(1)
        sessions = [tag]

    with open(GA_MEMBERS_FILE, encoding="utf-8") as f:
        ga_members = json.load(f)["members"]
    by_ocd, by_chamber_district = index_ga_members(ga_members)
    null_targets = [m for m in by_ocd.values() if m.get("legisGaGovId") is None]
    known_ids = crosswalk_legis_ids()
    print("Loaded %d GA legislators (%d missing legisGaGovId); crosswalk already "
          "knows %d legis ids." % (len(by_ocd), len(null_targets), len(known_ids)))

    client = LegisGaClient()
    all_proposals, all_conflicts, all_unmatched_legis, per_session = [], [], [], []
    seen_ocd = set()
    for tag in sessions:
        print("Enumerating roster for %s (legis session %d)..."
              % (tag, legis_session_id(tag)))
        proposals, conflicts, unmatched_legis, stats = backfill_session(
            client, tag, by_ocd, by_chamber_district, known_ids)
        per_session.append(stats)
        # De-dupe proposals across sessions by OCD (a member can serve both the
        # regular and the special session under the same legis id).
        for rec in proposals:
            if rec["ocdPersonId"] in seen_ocd:
                continue
            seen_ocd.add(rec["ocdPersonId"])
            all_proposals.append(rec)
        all_conflicts.extend(conflicts)
        all_unmatched_legis.extend(unmatched_legis)

    # ga-members with no legisGaGovId that NO session roster accounted for — these
    # are the ones a vote-sweep source would still need to cover. Surfaced, not hidden.
    proposed_ocds = {r["ocdPersonId"] for r in all_proposals}
    unmatched_members = [
        {"ocdPersonId": m.get("id"), "name": m.get("name"), "chamber": m.get("chamber"),
         "district": m.get("district"), "status": m.get("status")}
        for m in null_targets if m.get("id") not in proposed_ocds
    ]

    output = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "sessions": sessions,
            "gaLegislators": len(by_ocd),
            "missingLegisId": len(null_targets),
            "crosswalkKnownIds": len(known_ids),
            "proposed": len(all_proposals),
            "conflicts": len(all_conflicts),
            "unmatchedLegis": len(all_unmatched_legis),
            "unmatchedMembers": len(unmatched_members),
            "perSession": per_session,
            "note": ("Proposals to merge into ga-members-overrides.json "
                     "(key = ocdPersonId, set legisGaGovId). Review each, especially "
                     "'seat-unique'/'ambiguous' basis and any conflicts, before merging."),
        },
        "proposals": sorted(all_proposals, key=lambda r: (r["chamber"], r["district"] or 0)),
        "conflicts": all_conflicts,
        "unmatchedLegis": sorted(all_unmatched_legis,
                                 key=lambda r: (r["chamber"] or "", r["district"] or 0)),
        "unmatchedMembers": sorted(unmatched_members,
                                   key=lambda r: (r["chamber"] or "", r["district"] or 0)),
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_json_atomic(args.out, output, indent=2)

    print("\n=== BACKFILL PROPOSAL ===")
    print("proposals:        %d  (null-id members we can fill)" % len(all_proposals))
    print("conflicts:        %d  (existing legisGaGovId disagrees with roster — REVIEW)"
          % len(all_conflicts))
    print("unmatched legis:  %d  (roster members with no ga-members person)"
          % len(all_unmatched_legis))
    print("unmatched members:%d  (null-id ga-members no roster covered)"
          % len(unmatched_members))
    if all_conflicts:
        print("\nCONFLICTS (existing id != roster id):")
        for r in all_conflicts:
            print("  %s %s %s: ga has %s, roster says %s (%s)"
                  % (r["chamber"], r["district"], r.get("memberLastName"),
                     r.get("currentLegisId"), r["legisId"], r["legisSurname"]))
    if unmatched_members:
        print("\nUNMATCHED ga-members still missing an id (may need a vote-sweep source):")
        for r in unmatched_members:
            print("  %s %s %s  status=%s"
                  % (r["chamber"], r["district"], r["name"], r["status"]))
    flagged = [r for r in all_proposals if r["matchBasis"] != "seat+surname"]
    if flagged:
        print("\nProposals matched on a weaker basis (eyeball before merging):")
        for r in flagged:
            print("  [%s] %s %s -> %s (legis surname %r)"
                  % (r["matchBasis"], r["chamber"], r["district"],
                     r.get("memberName"), r["legisSurname"]))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
