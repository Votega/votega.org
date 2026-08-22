#!/usr/bin/env python3
"""Publish Georgia's federal delegation to the Votega/ga-federal-legislators repo.

Reads votega.org's source data and emits a full set of consumer-friendly artifacts:

  data/members.json         Georgia delegation, normalized (see below)
  data/votes.json           Roll-call votes (passthrough from federal-member-votes.json)
  data/members.csv          Flat one-row-per-member table (spreadsheets / journalists)
  data/votes.csv            Flat vote catalog
  data/member-votes.csv     Long/tidy one-row-per-(member,vote) table for pivots & joins
  data/members.schema.json  JSON Schema for members.json
  data/votes.schema.json    JSON Schema for votes.json
  ROSTER.md                 Human-readable roster that renders on GitHub

Normalization applied to members (vs. the raw Congress.gov shape):
  * adds a derived top-level `chamber` (so consumers don't need terms.item[0].chamber)
  * `contactInfo.zipCode` coerced to string (it's an identifier, not a number)
  * `birthYear` coerced to int

Publishing: with GA_FEDERAL_LEGISLATORS set (a GitHub token with Contents:write on the
target repo), each artifact is PUT via the GitHub Contents API. Without it, the script
runs as a DRY RUN, writing the artifacts to $OUT_DIR (default ./out) so the generators
can be tested locally. Exits non-zero on fatal errors so CI catches failures.
"""
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-federal-legislators"
TOKEN_ENV = "GA_FEDERAL_LEGISLATORS"
SCHEMA_VERSION = "1.0.0"

SRC_MEMBERS = os.environ.get("SRC_MEMBERS", "assets/data/current-members.json")
SRC_VOTES = os.environ.get("SRC_VOTES", "assets/data/federal-member-votes.json")


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def normalize_member(m):
    """Add a derived top-level `chamber` and fix field types. Everything else is
    passed through unchanged from Congress.gov."""
    m = dict(m)
    terms = (m.get("terms") or {}).get("item") or []
    m["chamber"] = terms[0].get("chamber") if terms else None
    by = m.get("birthYear")
    if isinstance(by, str) and by.isdigit():
        m["birthYear"] = int(by)
    ci = m.get("contactInfo")
    if isinstance(ci, dict) and ci.get("zipCode") is not None:
        ci = dict(ci)
        ci["zipCode"] = str(ci["zipCode"])
        m["contactInfo"] = ci
    return m


# --------------------------------------------------------------------------- #
# CSV builders
# --------------------------------------------------------------------------- #
def members_csv(members):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["bioguideId", "name", "firstName", "lastName", "party", "chamber",
                "district", "phone", "website", "birthYear", "officeAddress",
                "committees", "imageUrl"])
    for m in members:
        ci = m.get("contactInfo") or {}
        w.writerow([
            m.get("bioguideId"), m.get("name"), m.get("firstName"), m.get("lastName"),
            m.get("partyName"), m.get("chamber"),
            "" if m.get("district") is None else m.get("district"),
            ci.get("phoneNumber"), m.get("officialWebsiteUrl"), m.get("birthYear"),
            ci.get("officeAddress"), "; ".join(m.get("committees") or []),
            (m.get("depiction") or {}).get("imageUrl"),
        ])
    return buf.getvalue().encode()


def votes_csv(votes):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["voteId", "chamber", "date", "bill", "title", "motionText",
                "result", "yea", "nay", "billUrl"])
    for vid, v in sorted(votes.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
        w.writerow([vid, v.get("chamber"), v.get("date"), v.get("bill"), v.get("title"),
                    v.get("motionText"), v.get("result"), v.get("yea"), v.get("nay"),
                    v.get("billUrl")])
    return buf.getvalue().encode()


def member_votes_csv(members, votes, member_votes):
    by_id = {m["bioguideId"]: m for m in members}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["bioguideId", "name", "party", "chamber", "district",
                "voteId", "date", "bill", "title", "vote"])
    for bid, recs in member_votes.items():
        m = by_id.get(bid, {})
        for r in recs:
            v = votes.get(r.get("voteId"), {})
            w.writerow([bid, m.get("name"), m.get("partyName"), m.get("chamber"),
                        "" if m.get("district") is None else m.get("district"),
                        r.get("voteId"), v.get("date"), v.get("bill"), v.get("title"),
                        r.get("vote")])
    return buf.getvalue().encode()


# --------------------------------------------------------------------------- #
# Markdown roster
# --------------------------------------------------------------------------- #
def roster_md(members, meta):
    sens = sorted([m for m in members if m.get("chamber") == "Senate"],
                  key=lambda m: (m.get("lastName") or ""))
    reps = sorted([m for m in members if m.get("chamber") == "House of Representatives"],
                  key=lambda m: (m.get("district") if m.get("district") is not None else 999))

    def phone(m):
        return ((m.get("contactInfo") or {}).get("phoneNumber")) or ""

    def web(m):
        u = m.get("officialWebsiteUrl")
        return f"[site]({u})" if u else ""

    L = ["# Georgia Federal Delegation", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta['generatedAt']} · {meta['count']} members "
             f"({len(sens)} Senate, {len(reps)} House)._")
    L.append("")
    L.append("> Machine-readable versions: [`data/members.json`](data/members.json), "
             "[`data/members.csv`](data/members.csv). Roll-call votes: "
             "[`data/votes.csv`](data/votes.csv), [`data/member-votes.csv`](data/member-votes.csv).")
    L.append("")
    L.append("## U.S. Senate")
    L.append("")
    L.append("| Senator | Party | Phone | Website |")
    L.append("|---------|-------|-------|---------|")
    for m in sens:
        L.append(f"| {m.get('name', '')} | {m.get('partyName', '')} | {phone(m)} | {web(m)} |")
    L.append("")
    L.append("## U.S. House of Representatives")
    L.append("")
    L.append("| District | Representative | Party | Phone | Website |")
    L.append("|----------|----------------|-------|-------|---------|")
    for m in reps:
        L.append(f"| {m.get('district', '')} | {m.get('name', '')} | {m.get('partyName', '')} "
                 f"| {phone(m)} | {web(m)} |")
    L.append("")
    return ("\n".join(L) + "\n").encode()


# --------------------------------------------------------------------------- #
# JSON Schemas
# --------------------------------------------------------------------------- #
def members_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-federal-legislators/main/data/members.schema.json",
        "title": "Georgia Federal Delegation — Members",
        "description": "Georgia's current U.S. Senators and Representatives, filtered from "
                       "votega.org's national Congress.gov roster (state == 'Georgia').",
        "type": "object",
        "required": ["metadata", "members"],
        "properties": {
            "metadata": {
                "type": "object",
                "required": ["generatedAt", "count"],
                "properties": {
                    "generatedAt": {"type": "string", "format": "date-time",
                                    "description": "When THIS published file was built."},
                    "sourceGeneratedAt": {"type": ["string", "null"],
                                          "description": "When votega.org's source current-members.json was generated."},
                    "source": {"type": "string"},
                    "count": {"type": "integer", "description": "Number of members in this file."},
                    "congress": {"type": ["integer", "null"], "description": "Congress number (e.g. 119)."},
                    "schemaVersion": {"type": "string"},
                },
            },
            "members": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["bioguideId", "name", "chamber", "partyName"],
                    "properties": {
                        "bioguideId": {"type": "string",
                                       "description": "Congress.gov stable member ID; primary key and join key into votes.json."},
                        "name": {"type": "string"},
                        "firstName": {"type": "string"},
                        "lastName": {"type": "string"},
                        "honorificName": {"type": ["string", "null"]},
                        "partyName": {"type": "string", "enum": ["Democratic", "Republican", "Independent"]},
                        "state": {"type": "string"},
                        "chamber": {"type": ["string", "null"], "enum": ["Senate", "House of Representatives", None],
                                    "description": "Derived top-level chamber (from terms.item[0].chamber) for convenience."},
                        "district": {"type": ["integer", "null"], "description": "House district number; null for Senators."},
                        "terms": {"type": "object", "description": "Congress.gov term history; source of the derived `chamber`."},
                        "currentMember": {"type": "boolean"},
                        "birthYear": {"type": ["integer", "null"]},
                        "depiction": {"type": ["object", "null"]},
                        "contactInfo": {
                            "type": ["object", "null"],
                            "properties": {
                                "officeAddress": {"type": "string"},
                                "phoneNumber": {"type": "string"},
                                "city": {"type": "string"},
                                "district": {"type": "string"},
                                "zipCode": {"type": ["string", "null"],
                                            "description": "ZIP as a string (identifier, not a number)."},
                            },
                        },
                        "officialWebsiteUrl": {"type": ["string", "null"]},
                        "leadership": {"type": "array", "description": "Current leadership positions; empty if none."},
                        "committees": {"type": "array", "items": {"type": "string"},
                                       "description": "Full committee names (unitedstates/congress-legislators); Georgia-only enrichment."},
                        "sponsoredLegislation": {"type": "object"},
                        "cosponsoredLegislation": {"type": "object"},
                        "recentSponsored": {"type": "array",
                                            "description": "Up to 20 most recent bills sponsored this Congress; Georgia-only enrichment."},
                        "url": {"type": "string", "description": "Congress.gov API URL for the member."},
                        "updateDate": {"type": ["string", "null"],
                                       "description": "Congress.gov's own last-update timestamp for the member record."},
                        "dataUpdatedAt": {"type": ["string", "null"],
                                          "description": "When votega.org last enriched this member's detail (recentSponsored/committees)."},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }


def votes_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-federal-legislators/main/data/votes.schema.json",
        "title": "Georgia Federal Delegation — Roll-call Votes",
        "description": "Roll-call votes for Georgia's federal delegation in the current Congress. "
                       "SCOPE: only roll calls tied to enacted legislation (public laws walked back to "
                       "their votes), NOT every procedural vote. yea/nay are chamber-wide totals.",
        "type": "object",
        "required": ["metadata", "votes", "memberVotes"],
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {
                    "generatedAt": {"type": "string"},
                    "congress": {"type": "integer"},
                    "sessionName": {"type": "string"},
                    "source": {"type": "string"},
                    "totalVotes": {"type": "integer"},
                },
            },
            "votes": {
                "type": "object",
                "description": "Vote catalog keyed by vote ID. House: H{year}_{roll4}; Senate: S{congress}_{session}_{roll5}.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "bill": {"type": ["string", "null"]},
                        "billUrl": {"type": ["string", "null"]},
                        "title": {"type": ["string", "null"]},
                        "motionText": {"type": ["string", "null"]},
                        "date": {"type": "string"},
                        "yea": {"type": "integer", "description": "Chamber-wide yea total (all members, not just Georgia's)."},
                        "nay": {"type": "integer"},
                        "chamber": {"type": "string", "enum": ["House", "Senate"]},
                        "result": {"type": "string", "enum": ["Pass", "Fail"]},
                    },
                },
            },
            "memberVotes": {
                "type": "object",
                "description": "Per-member vote records keyed by bioguideId.",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["voteId", "vote"],
                        "properties": {
                            "voteId": {"type": "string"},
                            "vote": {"type": "string", "enum": ["Yea", "Nay", "Not Voting", "Absent"]},
                        },
                    },
                },
            },
        },
    }


# --------------------------------------------------------------------------- #
# Build + publish
# --------------------------------------------------------------------------- #
def build_artifacts():
    src = json.load(open(SRC_MEMBERS, encoding="utf-8"))
    ga = [normalize_member(m) for m in src.get("members", []) if m.get("state") == "Georgia"]
    if not ga:
        sys.exit("FATAL: no Georgia members found in current-members.json")

    votes_doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    votes = votes_doc.get("votes", {})
    member_votes = votes_doc.get("memberVotes", {})
    if not member_votes:
        sys.exit("FATAL: federal-member-votes.json has no memberVotes")

    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Congress.gov API, filtered to Georgia from votega.org current-members.json",
        "sourceGeneratedAt": src.get("metadata", {}).get("generatedAt"),
        "count": len(ga),
        "congress": votes_doc.get("metadata", {}).get("congress"),
        "schemaVersion": SCHEMA_VERSION,
    }

    return {
        "data/members.json": build_json({"metadata": meta, "members": ga}),
        "data/votes.json": build_json(votes_doc),
        "data/members.csv": members_csv(ga),
        "data/votes.csv": votes_csv(votes),
        "data/member-votes.csv": member_votes_csv(ga, votes, member_votes),
        "data/members.schema.json": build_json(members_schema()),
        "data/votes.schema.json": build_json(votes_schema()),
        "ROSTER.md": roster_md(ga, meta),
    }


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
