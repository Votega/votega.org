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

Three modes (the datasets update on different schedules / clocks, so each is its own
entry point):

  members        from ga-members.json      -> data/all.json (passthrough, the LIVE
                                               roster the target repo splits into
                                               house/senate.json), data/members.csv,
                                               data/members.schema.json, ROSTER.md
  votes          from ga-member-votes.json -> sessions/<slug>/{votes.json, votes.csv,
                                               votes.schema.json} + root latest.json
                                               pointer to the current session
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
import re
import sys

from lib.ga_voters import VOTING_CHAMBERS
from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-legislators"
TOKEN_ENV = "GA_LEGISLATORS_TOKEN"
SCHEMA_VERSION = "1.0.0"

SRC_MEMBERS = "assets/data/ga-members.json"
SRC_VOTES = "assets/data/ga-member-votes.json"

DEPARTED = {"Resigned", "Removed", "Deceased"}


def session_slug(meta):
    """Directory-friendly session label, e.g. '2025-2026', from the source metadata's
    sessionName ('2025-2026 Regular Session'). Falls back to the raw `session` id
    ('2025_26' -> '2025-26'). Mirrors publish_ga_bills.py so both sibling archives
    bucket a biennium under the same slug."""
    m = re.search(r"(\d{4})\D+(\d{4})", meta.get("sessionName") or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return (meta.get("session") or "unknown").replace("_", "-")


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
                   "[`votes.csv`](votes.csv) (full records in [`votes.json`](votes.json)).")
    else:
        heading = "# Georgia General Assembly"
        freshness = (f"_Last updated {meta.get('generatedAt', '')} · {len(sen)} Senators, "
                     f"{len(hou)} Representatives (current, live roster)._")
        machine = ("> Machine-readable: [`data/all.json`](data/all.json) / "
                   "[`data/members.csv`](data/members.csv). Current session's votes and "
                   "past sessions: see [`latest.json`](latest.json) and [`sessions/`](sessions).")

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


def build_votes():
    """Archive the current session's votes under sessions/<slug>/ and refresh the root
    latest.json pointer. Votes are session-scoped and never overwritten across sessions,
    so — like ga-legislation's bills — they live only in the session directory; there is
    no flat data/votes.json (consumers resolve the current file via latest.json)."""
    doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    meta = doc.get("metadata", {})
    votes = doc.get("votes", {})
    slug = session_slug(meta)
    base = f"sessions/{slug}"

    files = {
        "votes": f"{base}/votes.json",
        "votesCsv": f"{base}/votes.csv",
        "votesSchema": f"{base}/votes.schema.json",
    }
    return {
        files["votes"]: open(SRC_VOTES, "rb").read(),
        files["votesCsv"]: votes_csv(votes),
        files["votesSchema"]: build_json(votes_schema()),
        # Root pointer to "the current session", so consumers never hard-code a slug.
        # Uses the source data timestamp (not now()) so an unchanged weekly run produces
        # a byte-identical pointer and skips a no-op commit.
        "latest.json": build_json({
            "currentSession": slug,
            "sessionName": meta.get("sessionName"),
            "generatedAt": meta.get("generatedAt"),
            "voteCount": len(votes),
            "files": files,
            # The live roster always sits at data/all.json (refreshed by the `members`
            # mode); a per-session roster snapshot appears at sessions/<slug>/members.json
            # once that session is frozen at sine die (see the `freeze-roster` mode).
            "currentRoster": "data/all.json",
            "rosterArchive": f"{base}/members.json",
        }),
    }


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
    """Slug for a freeze-roster run. Explicit arg wins; otherwise default to the current
    votes session (ga-member-votes.json carries a sessionName; ga-members.json does not).
    At sine die the two are aligned, which is exactly when this should run."""
    if explicit:
        return explicit
    vmeta = json.load(open(SRC_VOTES, encoding="utf-8")).get("metadata", {})
    slug = session_slug(vmeta)
    print(f"No session slug given — defaulting to current votes session: "
          f"{slug} ({vmeta.get('sessionName')})")
    return slug


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "members":
        artifacts = build_members()
    elif mode == "votes":
        artifacts = build_votes()
    elif mode == "freeze-roster":
        slug = resolve_slug(sys.argv[2] if len(sys.argv) > 2 else None)
        artifacts = build_freeze_roster(slug)
    else:
        sys.exit("usage: publish_ga_legislators.py <members|votes|freeze-roster> [session-slug]")
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV)


if __name__ == "__main__":
    main()
