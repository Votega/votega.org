#!/usr/bin/env python3
"""
Generate curated-ga-bill-votes.json from the official legis.ga.gov record.

Reads assets/data/curated-ga-bills.json (the maintainer-controlled list) and produces,
for each entry, the bill's metadata plus the final passage vote in each chamber with
every member's position.

Sourcing — why this no longer uses Open States
----------------------------------------------
This script used to fetch Open States, which identifies a roll-call voter by bare
surname whenever that surname is shared in the chamber. lib/ga_voters.py could only
attribute such a row when everyone of that surname voted alike — which is false by
definition on a contested vote. A curated "key votes" list selects for exactly those
votes, so the old source failed hardest where this dataset is used: measured against
the official record it was dropping 1-23 members per roll call (SB 443's House vote:
154 of 176; HB 111: 157 of 180).

The SOAP record keys every row on the legislature's own numeric member id
(`Member.Id` == `legisGaGovId`), so the collision cannot occur. Two paths:

  1. LOCAL (primary, no network, no API key) — ga-bills.json and ga-member-votes.json
     are already built from that record, and between them carry everything needed.
  2. SOAP (fallback) — for a curated bill from a session older than those artifacts
     cover (they hold the current biennium only), fetched via lib/ga_soap.py.

Picking the final vote
----------------------
A chamber can hold several passage roll calls on one bill on one day — 89 such groups
in 2025-26, and in 5 of them one passed and another failed, so the choice decides the
outcome shown. `rollNumber` (the chamber's own roll-call number, from the GetVotes
listing) orders them authoritatively; `time` and pass/fail break ties if it is absent.
"""

import json
import os
import sys
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.ga_passage import native_is_passage, normalize_bill
from lib.ga_sessions import legis_session_id
from lib.ga_vote_rules import vote_passed
from lib.ga_soap import (CHAMBERS, VACANT_ID, RollCallNotPublished, get_members_by_session,
                         get_text_url, get_title_index, get_vote_detail, get_vote_listings)
from lib.ga_voters import VOTING_CHAMBERS, MemberIndex, new_stats, summarize
from lib.votes_schema import member_votes_map

CURATED_BILLS_FILE = "assets/data/curated-ga-bills.json"
GA_MEMBERS_FILE    = "assets/data/ga-members.json"
GA_BILLS_FILE      = "assets/data/ga-bills.json"
GA_VOTES_FILE      = "assets/data/ga-member-votes.json"
CROSSWALK_FILE     = "assets/data/id-crosswalk.json"
# Reviewed-only summaries built by scripts/ai_enrich_ga_bills.py (unreviewed AI drafts
# never reach it), keyed "<session>|<identifier>".
SUMMARIES_FILE     = "assets/data/ga-bill-summaries.json"
OUTPUT_FILE        = sys.argv[1] if len(sys.argv) > 1 else "assets/data/curated-ga-bill-votes.json"

#: The project's vote strings -> the option vocabulary this file publishes. Kept as a
#: table rather than lower-casing so "Not Voting"/"Excused" collapse deliberately.
OPTION = {
    "Yea": "yes",
    "Nay": "no",
    "Not Voting": "other",
    "Excused": "other",
    "Present": "abstain",
    "Absent": "other",
    "Other": "other",
}

BILL_URL = "https://www.legis.ga.gov/legislation/%d"


def build_party_lookup():
    """Return {ocd-person-id: party} from ga-members.json."""
    with open(GA_MEMBERS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    lookup = {m["id"]: m["party"] for m in data.get("members", []) if m.get("id")}
    print(f"  Loaded party data for {len(lookup)} members")
    return lookup


#: legis.ga.gov's party strings -> the names the rest of the site publishes. An unlisted
#: string maps to None: a party is never guessed.
LISTING_PARTY = {"Democrat": "Democratic", "Democratic": "Democratic",
                 "Republican": "Republican", "Independent": "Independent"}


def voter_key(legis_id):
    """The memberVotes key for a member who has no roster id (a former member). Same
    `legis:<id>` form the identity docs use; never an OCD id, never a surname."""
    return f"legis:{legis_id}"


def build_voter_index(path=CROSSWALK_FILE):
    """legisGaGovId(int) -> {key, party, rostered, name} for every person the crosswalk knows.

    A sitting or recent member keeps their roster id as the key, exactly as before, so no
    sitting member's vote moves. Someone with a legisGaGovId but no roster id (a 2023-24
    member who is not on the 2025-26 roster) is keyed `legis:<id>` instead of being
    dropped. `party` is the crosswalk role's party, or None when the role is missing.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for p in data.get("people", []):
        ids = p.get("ids") or {}
        legis_id = ids.get("legisGaGovId")
        if not legis_id:
            continue
        roster_id = ids.get("rosterId") or ids.get("ocdPersonId")
        role = p.get("role") or {}
        out[int(legis_id)] = {
            "key": roster_id or voter_key(int(legis_id)),
            "rostered": bool(roster_id),
            "party": LISTING_PARTY.get(role.get("party")),
            "name": (p.get("name") or {}).get("full"),
        }
    return out


def listing_parties(legis_session):
    """{legisGaGovId: party} from the session's own member listing, for people whose
    crosswalk role carries no party. {} when the listing cannot be fetched."""
    return {m["id"]: LISTING_PARTY.get(m.get("party"))
            for m in get_members_by_session(legis_session)}


def select_final_vote(candidates):
    """The operative final passage vote from several in one chamber.

    `rollNumber` is the chamber's own sequence and settles it outright. Without one
    (older records predate the field) fall back to date, then clock time, then a vote
    that passed over one that did not — never to dict or fetch order, which is how a
    failed attempt could be shown in place of the vote that carried.
    """
    def key(v):
        passed = str(v.get("result") or "").lower().startswith("pass")
        return (v.get("rollNumber") or 0, v.get("date") or "",
                _minutes(v.get("time")), 1 if passed else 0)
    return max(candidates, key=key) if candidates else None


def _minutes(clock):
    """'10:43 AM' -> minutes since midnight, for ordering. 0 when absent/unparseable."""
    if not clock:
        return 0
    try:
        t = datetime.strptime(clock.strip().upper(), "%I:%M %p")
    except ValueError:
        return 0
    return t.hour * 60 + t.minute


def build_party_tally(member_votes, party_lookup):
    """{party: {yea, nay, other}} over the members actually recorded on this roll call.

    Derived from the resolved roster, not the raw rows, so a voter listed twice cannot
    inflate it. See CODEBASE-REVIEW-2026-08-18.md 3.5.
    """
    tally = {
        "Democratic":  {"yea": 0, "nay": 0, "other": 0},
        "Republican":  {"yea": 0, "nay": 0, "other": 0},
        "Independent": {"yea": 0, "nay": 0, "other": 0},
    }
    for member_id, option in member_votes.items():
        party = party_lookup.get(member_id)
        if party in tally:
            bucket = "yea" if option == "yes" else ("nay" if option == "no" else "other")
            tally[party][bucket] += 1
    return tally


def vote_record(meta, member_votes, party_lookup):
    """One chamber's vote record in the published shape."""
    return {
        "rollNumber":  meta.get("rollNumber"),
        "date":        meta.get("date", ""),
        "motionText":  meta.get("motionText", ""),
        "result":      (meta.get("result") or "").lower(),
        "partyTally":  build_party_tally(member_votes, party_lookup),
        "memberVotes": member_votes,
    }


def load_reviewed_summaries(path=SUMMARIES_FILE):
    """{"<session>|<identifier>": {text, source}}; {} when the file is absent or unreadable,
    so a missing AI layer only means falling back to the caption."""
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f) or {}).get("summaries", {}) or {}
    except (OSError, ValueError):
        return {}


def pick_summary(entry, reviewed, caption=""):
    """(text, source) for one curated bill. Precedence: the editor's summaryOverride >
    a reviewed AI summary > the official caption. summarySource lets the page label AI
    text as AI; an override is never replaced, and an unreviewed draft is never used."""
    override = (entry.get("summaryOverride") or "").strip()
    if override:
        return override, "editor"
    ai = reviewed.get(f"{entry.get('session')}|{entry.get('identifier')}") or {}
    if ai.get("source") == "ai" and (ai.get("text") or "").strip():
        return ai["text"].strip(), "ai"
    return (caption, "caption") if caption else ("", None)


def describe_silent(member, last_roll):
    """Facts about a sitting member who is on no curated roll call, without guessing why.

    "Seated after every curated roll call" is only said when the roster carries a
    termStart later than the last one; otherwise the entry states what is known, and the
    absence stays visible rather than being explained away.
    """
    start = str(member.get("termStart") or "")[:10]
    if start and last_roll and start > last_roll:
        note = f"seated {start}, after the last curated roll call ({last_roll})"
    elif start:
        note = f"roster term start {start}; no recorded vote on any curated roll call"
    else:
        note = "no term start on the roster; no recorded vote on any curated roll call"
    return {"name": member["name"], "id": member["id"], "note": note}


# --------------------------------------------------------------------------- local

class LocalRecord:
    """The committed SOAP artifacts, indexed for the per-bill lookups below."""

    def __init__(self):
        with open(GA_BILLS_FILE, encoding="utf-8") as f:
            bills = json.load(f).get("bills", [])
        self.bills = {(b.get("session"), normalize_bill(b.get("identifier"))): b
                      for b in bills}
        with open(GA_VOTES_FILE, encoding="utf-8") as f:
            votes = json.load(f)
        self.votes = votes.get("votes", {})
        # voteId -> {ocdPersonId: option}. member_votes_map() handles either schema
        # version; never hand-decode the compact form (see lib/votes_schema.py).
        self.by_vote = {}
        for pid, entries in member_votes_map(votes).items():
            for e in entries:
                self.by_vote.setdefault(e["voteId"], {})[pid] = OPTION.get(e["vote"], "other")
        self.sessions = {v.get("session") for v in self.votes.values()}
        print(f"  Local record: {len(self.bills)} bills, {len(self.votes)} roll calls, "
              f"sessions {sorted(s for s in self.sessions if s)}")

    def covers(self, session):
        return session in self.sessions

    def bill(self, session, identifier):
        return self.bills.get((session, normalize_bill(identifier)))

    def chamber_votes(self, session, identifier):
        """{'house'|'senate': [vote meta + memberVotes, ...]} for one bill."""
        want = normalize_bill(identifier)
        out = {}
        for vid, meta in self.votes.items():
            if meta.get("session") != session or normalize_bill(meta.get("bill")) != want:
                continue
            chamber = meta.get("chamber")
            key = "senate" if chamber == "Senate" else "house" if chamber else None
            if key is None:
                continue
            out.setdefault(key, []).append(dict(meta, _voteId=vid))
        return out


def local_bill_record(entry, local, party_lookup, reviewed=None):
    """Build one bill's record from the committed artifacts, or None if not present."""
    session, identifier = entry["session"], entry["identifier"]
    bill = local.bill(session, identifier)
    if not bill:
        return None

    votes = {}
    for key, candidates in local.chamber_votes(session, identifier).items():
        chosen = select_final_vote(candidates)
        if not chosen:
            continue
        member_votes = local.by_vote.get(chosen["_voteId"], {})
        if not member_votes:
            print(f"  WARNING: {identifier} {key} roll call {chosen['_voteId']} has no "
                  f"member rows — omitting that chamber rather than showing an empty vote")
            continue
        votes[key] = vote_record(chosen, member_votes, party_lookup)

    if not votes:
        print(f"  WARNING: No passage votes found for {identifier} ({session})")

    lid = bill.get("legislationId")
    summary, summary_source = pick_summary(entry, reviewed or {}, bill.get("abstract") or "")
    return {
        "legislationId": lid,
        "session":       session,
        "identifier":    identifier,
        "title":         bill.get("title", ""),
        "summary":       summary,
        "summarySource": summary_source,
        "status":        bill.get("status", ""),
        "statusDate":    bill.get("statusDate", ""),
        "billUrl":       bill.get("billUrl") or (BILL_URL % lid if lid else ""),
        "fullTextUrl":   bill.get("textUrl", ""),
        "votes":         votes,
        "source":        "local",
    }


# ---------------------------------------------------------------------------- SOAP

def soap_bill_record(entry, voters, party_lookup, report=None, reviewed=None):
    """Fetch one bill's passage votes straight from SOAP.

    `voters` is build_voter_index(); `report` collects what could not be attributed, counted
    on the PUBLISHED roll call only (a superseded passage vote that is fetched and thrown
    away is not a loss). For a curated bill older than the committed artifacts. Walks the session's listings
    (one call per chamber), keeps the ones naming this bill, and fetches detail only for
    those — so cost is 2 + (a handful) calls, not one per roll call in the session.
    """
    session, identifier = entry["session"], entry["identifier"]
    legis_session = legis_session_id(session)
    if not legis_session:
        print(f"  ERROR: session {session!r} has no legis.ga.gov id in "
              f"lib/ga_sessions.LEGIS_SESSIONS — add it (with how you confirmed it).")
        return None

    want = normalize_bill(identifier)
    votes, legislation_id = {}, None
    _parties = {}

    def session_parties():
        if "m" not in _parties:
            _parties["m"] = listing_parties(legis_session)
        return _parties["m"]

    for branch in CHAMBERS:
        listings = get_vote_listings(legis_session, branch)
        if not listings:
            print(f"  WARNING: GetVotes({branch}, {legis_session}) returned nothing")
            continue
        hits = [l for l in listings
                if want in {normalize_bill(p) for p in (l.get("legislation") or "").split(",")}
                and native_is_passage(l.get("caption"))]
        if not hits:
            continue
        candidates = []
        for l in hits:
            try:
                detail = get_vote_detail(l["voteId"])
            except RollCallNotPublished:
                continue
            if detail is None:
                continue
            caption, date10, legislation, rows = detail
            member_votes, extra_party = {}, {}
            unattributed, partyless, former = [], [], []
            yea = nay = 0
            for mid, option in rows:
                if mid == VACANT_ID:
                    continue
                if option == "Yea":
                    yea += 1
                elif option == "Nay":
                    nay += 1
                voter = voters.get(mid)
                if not voter:
                    unattributed.append(mid)
                    continue
                member_votes[voter["key"]] = OPTION.get(option, "other")
                if not voter["rostered"]:
                    former.append(mid)
                    party = voter["party"]
                    if party is None:
                        party = session_parties().get(mid)
                    if party:
                        extra_party[voter["key"]] = party
                    else:
                        partyless.append(mid)
            for item in legislation:
                if normalize_bill(item.get("description")) == want:
                    legislation_id = legislation_id or item.get("legislationId")
            day = date10 or l.get("date") or ""
            passed = vote_passed(yea, nay, branch, entry.get("constitutionalAmendment", False),
                                 caption, legislation_id, day)
            candidates.append({
                "rollNumber": l.get("number"), "date": day,
                "time": l.get("time"), "motionText": caption,
                "result": "pass" if passed else "fail",
                "_memberVotes": member_votes, "_extraParty": extra_party,
                "_unattributed": unattributed, "_partyless": partyless, "_former": former,
            })
        chosen = select_final_vote(candidates)
        if chosen and chosen["_memberVotes"]:
            key = "senate" if branch == "Senate" else "house"
            votes[key] = vote_record(chosen, chosen["_memberVotes"],
                                     {**party_lookup, **chosen["_extraParty"]})
            if report is not None:
                where = f"{identifier} {key}"
                report["formerRows"] += len(chosen["_former"])
                report["unattributed"] += [(where, m) for m in chosen["_unattributed"]]
                report["partyless"] += [(where, m) for m in chosen["_partyless"]]

    if not votes:
        print(f"  WARNING: No passage votes found over SOAP for {identifier} ({session})")
        return None

    # One extra call gives the session's titles; without it the card would render a
    # bare bill number. Best-effort — get_title_index returns {} on failure.
    title = get_title_index(legis_session).get(legislation_id, "") if legislation_id else ""
    summary, summary_source = pick_summary(entry, reviewed or {})

    return {
        "legislationId": legislation_id,
        "session":       session,
        "identifier":    identifier,
        "title":         title,
        "summary":       summary,
        "summarySource": summary_source,
        # Status/statusDate come from ga-bills.json, which covers the current
        # biennium only — an older bill shows no status tag rather than a wrong one.
        "status":        "",
        "statusDate":    "",
        "billUrl":       BILL_URL % legislation_id if legislation_id else "",
        # Best-effort, same as the title lookup: the older session isn't in ga-bills.json,
        # so the text link comes from the bill's own SOAP detail.
        "fullTextUrl":   get_text_url(legislation_id) if legislation_id else "",
        "votes":         votes,
        "source":        "soap",
    }


# ---------------------------------------------------------------------------- main

def main():
    with open(CURATED_BILLS_FILE, encoding="utf-8") as f:
        bill_list = json.load(f).get("ga", [])
    print(f"Processing {len(bill_list)} curated bills...\n")

    print("Loading member party data...")
    party_lookup = build_party_lookup()
    print("Loading the local official record...")
    local = LocalRecord()
    reviewed = load_reviewed_summaries()
    print(f"  Loaded {len(reviewed)} reviewed summaries ({SUMMARIES_FILE})")

    # Prior records, so a bill that can't be sourced keeps its last-known data instead
    # of vanishing from the site. Keyed by (session, identifier) because the curated list
    # spans sessions and identifiers repeat across them (e.g. "SB 233" in 2023_24).
    prior = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                for b in json.load(f).get("bills", []):
                    prior[(b.get("session"), b.get("identifier"))] = b
            print(f"Loaded {len(prior)} previously published record(s) as fallback.")
        except (OSError, json.JSONDecodeError) as e:
            print(f"  Could not read existing {OUTPUT_FILE}: {e}")

    member_index = MemberIndex(GA_MEMBERS_FILE)
    print(f"  Loaded {len(member_index)} members for coverage reporting")
    stats = new_stats()
    voters = None
    report = {"formerRows": 0, "unattributed": [], "partyless": []}

    results, failed, retained, by_source = [], [], [], {"local": 0, "soap": 0}
    for entry in bill_list:
        label = entry.get("_name") or entry["identifier"]
        print(f"\n--- {label} ({entry['identifier']}, {entry['session']}) ---")
        record = local_bill_record(entry, local, party_lookup, reviewed)
        if record:
            print(f"  OK — {len(record['votes'])} chamber vote(s) from the local record")
        else:
            # Outside the committed artifacts (an older session): go to the source.
            print(f"  Not in the local record — fetching {entry['session']} over SOAP")
            if voters is None:
                voters = build_voter_index()
                print(f"  Loaded crosswalk: {len(voters)} legisGaGovId -> roster id or legis:<id>")
            record = soap_bill_record(entry, voters, party_lookup, report, reviewed)
            if record:
                print(f"  OK — {len(record['votes'])} chamber vote(s) over SOAP")

        if record:
            by_source[record.pop("source")] += 1
            results.append(record)
            continue

        fallback = prior.get((entry.get("session"), entry["identifier"]))
        if fallback:
            results.append(fallback)
            retained.append(entry["identifier"])
            print(f"  Kept previously published record for {entry['identifier']}")
        else:
            failed.append(entry["identifier"])

    # Coverage is the metric that actually matters to a reader: a legislator with
    # no key votes looks like someone who never voted. Recording it in metadata
    # lets validate_data_update.py catch a regression as a delta, instead of
    # needing a hardcoded floor that goes stale every session.
    voted = {mid for rec in results for v in rec.get("votes", {}).values()
             for mid in (v.get("memberVotes") or {})}
    sitting = [m for m in member_index.by_id.values()
               if not m.get("status") and m.get("chamber") in VOTING_CHAMBERS]
    silent_members = sorted((m for m in sitting if m["id"] not in voted), key=lambda m: m["name"])
    silent = [m["name"] for m in silent_members]
    last_roll = max((str(v.get("date") or "")[:10] for rec in results
                     for v in rec.get("votes", {}).values()), default="")
    without_votes = [describe_silent(m, last_roll) for m in silent_members]
    stats["unresolved"] = len(report["unattributed"])
    stats["formerMember"] = report["formerRows"]

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source":      "legis.ga.gov (official): committed SOAP artifacts, "
                           "SOAP fetch for sessions they do not cover",
            "count":       len(results),
            "fromLocalRecord": by_source["local"],
            "fromSoapFetch":   by_source["soap"],
            "sittingLegislators":   len(sitting),
            "legislatorsWithVotes": len(sitting) - len(silent),
            # Voter resolution is no longer a source of loss on the local path: rows are
            # keyed on the legislature's own member id, resolved once when
            # ga-member-votes.json is built. Kept for the SOAP path, where a member id
            # absent from id-crosswalk.json still means a dropped row.
            "voterResolution":     dict(stats),
            "unresolvedVoterRows": stats["unresolved"],
            # Counted on the published roll calls only. `formerMemberRows` are rows kept
            # under `legis:<id>` for people with no roster id (not lost); the two id lists
            # name anyone still not fully attributed, so nobody drops out silently.
            "formerMemberRows":     report["formerRows"],
            "unattributedVoterIds": sorted({m for _, m in report["unattributed"]}),
            "partylessVoterIds":    sorted({m for _, m in report["partyless"]}),
            "legislatorsWithoutVotes": without_votes,
        },
        "bills": results,
    }

    write_json_atomic(OUTPUT_FILE, output, indent=2)

    print(f"\nWrote {len(results)} bill records to {OUTPUT_FILE} "
          f"({by_source['local']} local, {by_source['soap']} over SOAP)")
    print(f"Voter resolution: {summarize(stats)}")
    print(f"Coverage: {len(sitting) - len(silent)}/{len(sitting)} sitting legislators "
          f"have at least one curated vote")
    if silent:
        print(f"  {len(silent)} with none: {', '.join(silent[:10])}"
              + (" ..." if len(silent) > 10 else ""))

    print(f"Former members kept under legis:<id>: {report['formerRows']} row(s)")
    if report["unattributed"]:
        ids = sorted({m for _, m in report["unattributed"]})
        print(f"WARNING: {len(report['unattributed'])} published SOAP row(s) carried a "
              f"legisGaGovId absent from {CROSSWALK_FILE}; those votes are omitted: "
              f"{', '.join(map(str, ids))}")
        for where, m in report["unattributed"]:
            print(f"    {where}: legisGaGovId {m}")
    if report["partyless"]:
        ids = sorted({m for _, m in report["partyless"]})
        print(f"WARNING: {len(report['partyless'])} published row(s) have a vote but no known "
              f"party, so they are missing from partyTally: {', '.join(map(str, ids))}")

    # Tolerate the odd transient miss, fail on a real outage.
    if failed:
        print(f"\nERROR: {len(failed)} bill(s) could not be sourced and had no prior "
              f"record: {', '.join(failed)}", file=sys.stderr)
    if retained:
        print(f"Retained {len(retained)} prior record(s): {', '.join(retained)}")
    if failed and len(failed) == len(bill_list):
        sys.exit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
