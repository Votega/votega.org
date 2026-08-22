#!/usr/bin/env python3
"""Publish Georgia state legislators + their votes to the Votega/ga-legislators repo.

Two modes (the two source datasets update on different schedules, so each update
workflow publishes its own half):

  members   from ga-members.json      -> data/all.json (passthrough), members.csv,
                                          members.schema.json, ROSTER.md
  votes     from ga-member-votes.json -> data/votes.json (passthrough), votes.csv,
                                          member-votes.csv, votes.schema.json

ga-members.json also carries 4 statewide executives (chamber == "executive") and
departed members (status Resigned/Removed/Deceased); both are excluded from the roster
and CSV using VOTING_CHAMBERS — the same filter ga.js and the search-corpus builder use.
data/all.json stays a full passthrough (the target repo splits it into house/senate.json).

Publishing/dry-run behavior comes from lib.sibling_publish. Usage:
    python3 scripts/publish_ga_legislators.py <members|votes>
"""
import csv
import io
import json
import os
import sys

from lib.ga_voters import VOTING_CHAMBERS
from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-legislators"
TOKEN_ENV = "GA_LEGISLATORS_TOKEN"
SCHEMA_VERSION = "1.0.0"

SRC_MEMBERS = "assets/data/ga-members.json"
SRC_VOTES = "assets/data/ga-member-votes.json"

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


def roster_md(legislators, meta):
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

    L = ["# Georgia General Assembly", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta.get('generatedAt', '')} · {len(sen)} Senators, "
             f"{len(hou)} Representatives._")
    L.append("")
    L.append("> Machine-readable: [`data/all.json`](data/all.json) / "
             "[`data/members.csv`](data/members.csv). Vote records: "
             "[`data/votes.csv`](data/votes.csv), [`data/member-votes.csv`](data/member-votes.csv).")
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
        "$id": "https://raw.githubusercontent.com/Votega/ga-legislators/main/data/votes.schema.json",
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
    doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    votes = doc.get("votes", {})
    return {
        "data/votes.json": open(SRC_VOTES, "rb").read(),
        "data/votes.csv": votes_csv(votes),
        "data/votes.schema.json": build_json(votes_schema()),
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "members":
        artifacts = build_members()
    elif mode == "votes":
        artifacts = build_votes()
    else:
        sys.exit("usage: publish_ga_legislators.py <members|votes>")
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV)


if __name__ == "__main__":
    main()
