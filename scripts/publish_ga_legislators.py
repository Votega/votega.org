#!/usr/bin/env python3
"""Publish Georgia state legislators + their votes to the Votega/ga-legislators repo.

Georgia runs two-year General Assembly sessions, and both source datasets are
DESTRUCTIVELY REPLACED at the biennium rollover: ga-member-votes.json is refetched
for the new session (GA_SESSION bump) and ga-members.json turns over to the new
roster as Open States seats the incoming members. Left flat, the sibling repo would
lose every prior session. So — mirroring Votega/ga-legislation — this repo is a
session ARCHIVE: per-session data lives under sessions/<YYYY-YYYY>/ and is never
overwritten once a new session begins (the generator only ever writes the *current*
session's directory, and the Contents API only PUTs, never deletes prior dirs).

Four modes (the datasets update on different schedules / clocks, so each is its own
entry point):

  members        from ga-members.json      -> data/all.json (passthrough, the LIVE
                                               roster the target repo splits into
                                               house/senate.json), data/members.csv,
                                               data/members.schema.json, ROSTER.md
  votes          from ga-member-votes.json -> one sessions/<slug>/{votes.json, votes.csv,
                                               votes.schema.json} per session in the
                                               biennium (roll calls split by their
                                               `session` tag) + root latest.json pointer
  scorecard      from ga-party-unity.json  -> sessions/<biennium>/{scorecard.json,
                                               scorecard.csv, scorecard.schema.json} +
                                               root scorecard-latest.json pointer. DERIVED
                                               (party unity + participation), biennium grain.
  freeze-roster  from ga-members.json      -> sessions/<slug>/{members.json, members.csv,
                                               members.schema.json, ROSTER.md}

The roster and the votes turn over on DIFFERENT clocks: votes flip on the manual
GA_SESSION bump, but the roster turns over gradually via Open States after the
election. So the roster is NOT archived automatically alongside votes — it is frozen
by an explicit, deliberate `freeze-roster` run at end-of-session (sine die), before
Open States erodes the outgoing roster. See RECURRING-TASKS.md §3.

ga-members.json also carries 4 statewide executives (chamber == "executive") and
departed members (status Resigned/Removed/Deceased); both are excluded from the roster
and CSV using VOTING_CHAMBERS — the same filter ga.js and the search-corpus builder use.

Publishing/dry-run behavior comes from lib.sibling_publish. Usage:
    python3 scripts/publish_ga_legislators.py <members|votes|freeze-roster> [session-slug]
"""
import csv
import io
import json
import os
import sys

from lib.ga_voters import VOTING_CHAMBERS
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             session_name, session_slug, tag_session)
from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-legislators"
TOKEN_ENV = "GA_LEGISLATORS_TOKEN"
SCHEMA_VERSION = "1.0.0"

SRC_MEMBERS = "assets/data/ga-members.json"
SRC_VOTES = "assets/data/ga-member-votes.json"
SRC_SCORECARD = "assets/data/ga-party-unity.json"

DEPARTED = {"Resigned", "Removed", "Deceased"}


def sitting_legislators(members):
    """General Assembly members currently holding a seat (excludes executives and
    Resigned/Removed/Deceased; keeps active, Suspended, and Vacant placeholders)."""
    return [m for m in members
            if m.get("chamber") in VOTING_CHAMBERS and m.get("status") not in DEPARTED]


# --------------------------------------------------------------------------- #
# members mode
# --------------------------------------------------------------------------- #
def members_csv(legislators):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "name", "firstName", "lastName", "party", "chamber", "district",
                "title", "status", "phone", "email", "website", "committees", "legisGaGovId"])
    for m in legislators:
        w.writerow([
            m.get("id"), m.get("name"), m.get("firstName"), m.get("lastName"),
            m.get("party"), m.get("chamber"),
            "" if m.get("district") is None else m.get("district"),
            m.get("title"), m.get("status") or "active", m.get("phone"), m.get("email"),
            m.get("officialWebsiteUrl"),
            "; ".join(c.get("name", c) if isinstance(c, dict) else c
                      for c in (m.get("committees") or [])),
            m.get("legisGaGovId"),
        ])
    return buf.getvalue().encode()


def roster_md(legislators, meta, session=None):
    sen = sorted([m for m in legislators if m.get("chamber") == "Senate"],
                 key=lambda m: (m.get("district") if m.get("district") is not None else 999))
    hou = sorted([m for m in legislators if m.get("chamber") == "House of Representatives"],
                 key=lambda m: (m.get("district") if m.get("district") is not None else 999))

    def row(m):
        status = "" if not m.get("status") else f" _({m['status']})_"
        web = f"[site]({m['officialWebsiteUrl']})" if m.get("officialWebsiteUrl") else ""
        name = (m.get("name") or "").replace("|", "\\|")
        return (f"| {m.get('district', '')} | {name}{status} | {m.get('party') or ''} "
                f"| {m.get('phone') or ''} | {web} |")

    # A session-frozen archive links to files beside it under sessions/<slug>/; the
    # current-roster ROSTER.md at the repo root links to the live data/ files.
    if session:
        heading = f"# Georgia General Assembly — {session}"
        freshness = (f"_Session roster frozen at sine die from {meta.get('generatedAt', '')} · "
                     f"{len(sen)} Senators, {len(hou)} Representatives._")
        machine = ("> Machine-readable: [`members.json`](members.json) / "
                   "[`members.csv`](members.csv). Roll-call votes for this session: "
                   "[`votes.csv`](votes.csv) (full records in [`votes.json`](votes.json)). "
                   "Voting scorecard (party unity + participation): [`scorecard.csv`](scorecard.csv) "
                   "(full records in [`scorecard.json`](scorecard.json)).")
    else:
        heading = "# Georgia General Assembly"
        freshness = (f"_Last updated {meta.get('generatedAt', '')} · {len(sen)} Senators, "
                     f"{len(hou)} Representatives (current, live roster)._")
        machine = ("> Machine-readable: [`data/all.json`](data/all.json) / "
                   "[`data/members.csv`](data/members.csv). Current session's votes and "
                   "past sessions: see [`latest.json`](latest.json) and [`sessions/`](sessions). "
                   "Derived voting scorecard (party unity + participation): "
                   "[`scorecard-latest.json`](scorecard-latest.json).")

    L = [heading, ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(freshness)
    L.append("")
    L.append(machine)
    L.append("")
    for title, group in (("State Senate", sen), ("House of Representatives", hou)):
        L.append(f"## {title}")
        L.append("")
        L.append("| District | Member | Party | Phone | Website |")
        L.append("|----------|--------|-------|-------|---------|")
        L.extend(row(m) for m in group)
        L.append("")
    return ("\n".join(L) + "\n").encode()


def members_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-legislators/main/data/members.schema.json",
        "title": "Georgia General Assembly — Members",
        "description": "Georgia state legislators from Open States. NOTE: also includes 4 statewide "
                       "executives (chamber == 'executive'); filter to chamber in "
                       "['Senate', 'House of Representatives'] for legislators only. The target repo "
                       "splits this file into house.json / senate.json.",
        "type": "object",
        "required": ["members"],
        "properties": {
            "metadata": {"type": "object"},
            "members": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "name", "chamber"],
                    "properties": {
                        "id": {"type": "string", "description": "OCD person id (join key into votes.json's memberVotes)."},
                        "name": {"type": "string"},
                        "firstName": {"type": ["string", "null"]},
                        "lastName": {"type": ["string", "null"]},
                        "party": {"type": ["string", "null"]},
                        "chamber": {"type": "string", "enum": ["Senate", "House of Representatives", "executive"]},
                        "district": {"type": ["integer", "null"]},
                        "title": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"], "description": "null = sitting; else Vacant/Suspended/Resigned/Removed/Deceased."},
                        "phone": {"type": ["string", "null"]},
                        "email": {"type": ["string", "null"]},
                        "officialWebsiteUrl": {"type": ["string", "null"]},
                        "committees": {"type": "array"},
                        "legisGaGovId": {"type": ["integer", "null"]},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def build_members():
    doc = json.load(open(SRC_MEMBERS, encoding="utf-8"))
    legislators = sitting_legislators(doc.get("members", []))
    return {
        "data/all.json": open(SRC_MEMBERS, "rb").read(),
        "data/members.csv": members_csv(legislators),
        "data/members.schema.json": build_json(members_schema()),
        "ROSTER.md": roster_md(legislators, doc.get("metadata", {})),
    }


# --------------------------------------------------------------------------- #
# votes mode
# --------------------------------------------------------------------------- #
def votes_csv(votes):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["voteId", "date", "bill", "title", "motionText", "yea", "nay", "result", "billUrl"])
    for vid, v in sorted(votes.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
        w.writerow([vid, v.get("date"), v.get("bill"), v.get("title"), v.get("motionText"),
                    v.get("yea"), v.get("nay"), v.get("result"), v.get("billUrl")])
    return buf.getvalue().encode()


# NOTE: no per-(member, vote) CSV for the state repo. 235 members x ~2,200 votes is
# ~230k rows / 30 MB+ of UUID pairs — it would bloat repo history on every weekly update
# and pushes the Contents API. That breakdown already lives in votes.json's memberVotes{}
# (keyed by OCD person id), joinable to members.csv / votes.csv. The federal repo, being
# ~1k rows, does ship member-votes.csv.


def votes_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-legislators/main/sessions/votes.schema.json",
        "title": "Georgia General Assembly — Roll-call Votes",
        "description": "Passage votes from the Georgia General Assembly (Open States), keyed by OCD "
                       "vote id. memberVotes is keyed by OCD person id (the `id` in members data).",
        "type": "object",
        "required": ["votes", "memberVotes"],
        "properties": {
            "metadata": {"type": "object"},
            "votes": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "bill": {"type": ["string", "null"]},
                        "billUrl": {"type": ["string", "null"]},
                        "title": {"type": ["string", "null"]},
                        "session": {"type": ["string", "null"], "description": "Session id, e.g. '2025_26' or '2026_ss'."},
                        "motionText": {"type": ["string", "null"]},
                        "date": {"type": ["string", "null"]},
                        "yea": {"type": "integer"},
                        "nay": {"type": "integer"},
                        "result": {"type": ["string", "null"]},
                    },
                },
            },
            "memberVotes": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "voteId": {"type": "string"},
                            "vote": {"type": "string",
                                     "enum": ["Yea", "Nay", "Not Voting", "Present", "Absent", "Excused", "Other"]},
                        },
                    },
                },
            },
        },
    }


def compact_json(obj):
    """Compact (unindented) UTF-8 JSON bytes. Used for the large per-session votes.json —
    the 2025_26 regular session alone is ~17 MB, and pretty-printing it would roughly
    double that and strain the Contents API's per-file size limit."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def build_votes():
    """Split the biennium's roll calls by session into per-session archive dirs and
    refresh the root latest.json pointer. ga-member-votes.json now covers the whole
    biennium (each roll call tagged with its `session`); each session directory gets a
    self-contained votes.json ({metadata, votes, memberVotes} scoped to that session)
    plus votes.csv and votes.schema.json. Closed sessions re-emit byte-stable."""
    doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    meta = doc.get("metadata", {})
    votes = doc.get("votes", {})
    member_votes = doc.get("memberVotes", {})

    ids_by_session = {}
    for vid, v in votes.items():
        ids_by_session.setdefault(tag_session(v.get("session")), set()).add(vid)

    artifacts = {}
    sessions_index = []
    # Emit every session in the biennium, even one with no roll calls yet, so the archive
    # is complete and latest.json's currentSession always resolves.
    for sid in list(all_session_ids()) + [s for s in ids_by_session if s not in all_session_ids()]:
        vids = ids_by_session.get(sid, set())
        slug = session_slug(sid)
        base = f"sessions/{slug}"
        sess_votes = {vid: votes[vid] for vid in vids}
        # Restrict each member's roll-call entries to this session; drop members with none.
        sess_mv = {}
        for pid, entries in member_votes.items():
            kept = [e for e in entries if e.get("voteId") in vids]
            if kept:
                sess_mv[pid] = kept
        sess_doc = {
            "metadata": {
                "session": sid,
                "sessionName": session_name(sid),
                "biennium": BIENNIUM,
                "generatedAt": meta.get("generatedAt"),
                "source": meta.get("source", "Open States API"),
                "totalVotes": len(sess_votes),
            },
            "votes": sess_votes,
            "memberVotes": sess_mv,
        }
        artifacts[f"{base}/votes.json"] = compact_json(sess_doc)
        artifacts[f"{base}/votes.csv"] = votes_csv(sess_votes)
        artifacts[f"{base}/votes.schema.json"] = build_json(votes_schema())
        sessions_index.append({
            "id": sid, "name": session_name(sid), "slug": slug,
            "voteCount": len(sess_votes),
            "files": {"votes": f"{base}/votes.json", "votesCsv": f"{base}/votes.csv",
                      "votesSchema": f"{base}/votes.schema.json"},
        })

    active_slug = session_slug(meta.get("activeSession") or ACTIVE_SESSION)
    # Root pointer: the biennium, the session currently in progress, and every session's
    # files. Uses the source data timestamp (not now()) so an unchanged run produces a
    # byte-identical pointer. The live roster is always data/all.json; the frozen roster
    # for the whole General Assembly lives at sessions/<biennium>/members.json.
    artifacts["latest.json"] = build_json({
        "biennium": BIENNIUM,
        "currentSession": active_slug,
        "activeSession": meta.get("activeSession") or ACTIVE_SESSION,
        "generatedAt": meta.get("generatedAt"),
        "currentRoster": "data/all.json",
        "rosterArchive": f"sessions/{BIENNIUM}/members.json",
        "sessions": sorted(sessions_index, key=lambda s: s["slug"]),
    })
    return artifacts


# --------------------------------------------------------------------------- #
# scorecard mode (derived: party-unity + participation per legislator)
# --------------------------------------------------------------------------- #
# The scorecard is a DERIVED product — computed by generate_party_unity.py from
# votes.json + members.json, both already published to this repo. It is archived
# at the biennium grain (not per-session): party unity gets more reliable the more
# party-line votes it sees, so the score aggregates the whole General Assembly
# (regular + special sessions), matching how generate_party_unity.py builds it.
def scorecard_csv(members):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name", "party", "chamber", "district",
                "partyUnity", "independenceRate", "votedWithParty", "partyLineVotes",
                "participationRate", "missedRate", "cast", "missed", "totalRollCalls",
                "presidingOfficer", "id"])
    for m in members:
        w.writerow([
            m.get("name"), m.get("party"), m.get("chamber"),
            "" if m.get("district") is None else m.get("district"),
            "" if m.get("partyUnity") is None else m.get("partyUnity"),
            "" if m.get("independenceRate") is None else m.get("independenceRate"),
            m.get("votedWithParty"), m.get("partyLineVotes"),
            m.get("participationRate"), m.get("missedRate"),
            m.get("cast"), m.get("missed"), m.get("totalRollCalls"),
            "true" if m.get("presidingOfficer") else "false",
            m.get("id"),
        ])
    return buf.getvalue().encode()


def scorecard_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-legislators/main/sessions/scorecard.schema.json",
        "title": "Georgia General Assembly — Voting Scorecard (derived)",
        "description": "Party-unity and participation scores per legislator, DERIVED from "
                       "votes.json + members.json in this repo. Party unity = share of party-line "
                       "roll calls (own-party majority opposite the other party's majority) on which "
                       "the member voted with their own caucus. Participation = share of the member's "
                       "own-chamber passage roll calls on which they cast a Yea or Nay.",
        "type": "object",
        "required": ["members"],
        "properties": {
            "metadata": {"type": "object"},
            "members": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "name", "chamber"],
                    "properties": {
                        "id": {"type": "string", "description": "OCD person id (join key into votes.json / members data)."},
                        "name": {"type": "string"},
                        "party": {"type": ["string", "null"]},
                        "chamber": {"type": "string", "enum": ["Senate", "House of Representatives"]},
                        "district": {"type": ["integer", "null"]},
                        "partyUnity": {"type": ["number", "null"], "description": "null when undefined (independent, or no party-line votes)."},
                        "independenceRate": {"type": ["number", "null"], "description": "1 - partyUnity."},
                        "votedWithParty": {"type": "integer"},
                        "partyLineVotes": {"type": "integer", "description": "Denominator for partyUnity."},
                        "participationRate": {"type": "number"},
                        "missedRate": {"type": "number", "description": "1 - participationRate."},
                        "cast": {"type": "integer"},
                        "missed": {"type": "integer"},
                        "totalRollCalls": {"type": "integer"},
                        "presidingOfficer": {"type": "boolean", "description": "Votes only to break ties by custom; partyUnity is typically null."},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def build_scorecard():
    doc = json.load(open(SRC_SCORECARD, encoding="utf-8"))
    meta = doc.get("metadata", {})
    members = doc.get("members", [])
    # Biennium archive dir, matching build_votes' rosterArchive at sessions/<biennium>/.
    slug = BIENNIUM
    base = f"sessions/{slug}"
    artifacts = {
        f"{base}/scorecard.json": open(SRC_SCORECARD, "rb").read(),
        f"{base}/scorecard.csv": scorecard_csv(members),
        f"{base}/scorecard.schema.json": build_json(scorecard_schema()),
    }
    # Root pointer, mirroring latest.json. Uses the source generatedAt (not now())
    # so an unchanged run re-emits byte-identical.
    artifacts["scorecard-latest.json"] = build_json({
        "biennium": BIENNIUM,
        "generatedAt": meta.get("generatedAt"),
        "count": meta.get("count"),
        "scoredForUnity": meta.get("scoredForUnity"),
        "files": {
            "scorecard": f"{base}/scorecard.json",
            "scorecardCsv": f"{base}/scorecard.csv",
            "scorecardSchema": f"{base}/scorecard.schema.json",
        },
        "derivedFrom": ["sessions/{}/votes.json".format(slug), "data/all.json"],
    })
    return artifacts


# --------------------------------------------------------------------------- #
# freeze-roster mode (deliberate, per-session at sine die)
# --------------------------------------------------------------------------- #
def build_freeze_roster(slug):
    """Snapshot the CURRENT ga-members.json roster into sessions/<slug>/ as a permanent
    record of who served in that General Assembly. Run once, at end of session, before
    Open States turns the roster over to the incoming members."""
    doc = json.load(open(SRC_MEMBERS, encoding="utf-8"))
    legislators = sitting_legislators(doc.get("members", []))
    meta = doc.get("metadata", {})
    base = f"sessions/{slug}"
    return {
        f"{base}/members.json": open(SRC_MEMBERS, "rb").read(),
        f"{base}/members.csv": members_csv(legislators),
        f"{base}/members.schema.json": build_json(members_schema()),
        f"{base}/ROSTER.md": roster_md(legislators, meta, session=slug),
    }


def resolve_slug(explicit):
    """Slug for a freeze-roster run. Explicit arg wins; otherwise default to the biennium
    (BIENNIUM). The roster is the same sitting membership across a biennium's regular and
    special sessions, so one snapshot per General Assembly — at sessions/<biennium>/ —
    is the natural record, matching latest.json's rosterArchive pointer."""
    if explicit:
        return explicit
    print(f"No session slug given — defaulting to the biennium: {BIENNIUM}")
    return BIENNIUM


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "members":
        artifacts = build_members()
    elif mode == "votes":
        artifacts = build_votes()
    elif mode == "scorecard":
        artifacts = build_scorecard()
    elif mode == "freeze-roster":
        slug = resolve_slug(sys.argv[2] if len(sys.argv) > 2 else None)
        artifacts = build_freeze_roster(slug)
    else:
        sys.exit("usage: publish_ga_legislators.py <members|votes|scorecard|freeze-roster> [session-slug]")
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV)


if __name__ == "__main__":
    main()
