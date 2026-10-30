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
  * adds a derived top-level `chamber` (the chamber of the member's most recent term, so consumers
    don't have to pick a term)
  * `contactInfo.zipCode` coerced to string (it's an identifier, not a number)
  * `birthYear` coerced to int

Publishing: with GA_FEDERAL_LEGISLATORS set (a GitHub token with Contents:write on the
target repo), each artifact is PUT via the GitHub Contents API. Without it, the script
runs as a DRY RUN, writing the artifacts to $OUT_DIR (default ./out) so the generators
can be tested locally. Exits non-zero on fatal errors so CI catches failures.
"""
import base64
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from lib.congress_session import congress_ordinal, congress_years
from lib.federal_sponsorship import bill_url
from lib.sibling_publish import build_json, publish_or_dry_run, min_items, _urlopen_retry

REPO = "Votega/ga-federal-legislators"
TOKEN_ENV = "GA_FEDERAL_LEGISLATORS"
SCHEMA_VERSION = "1.0.0"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
SESSIONS_DIR = "sessions"
SCHEMA_STABILITY = ("Additive changes only within a major version: new properties and new CSV columns (appended, never inserted); no property is ever newly required. `congress` is carried in the metadata and as the last CSV column so a downloaded copy says which Congress it describes.")

SRC_MEMBERS = os.environ.get("SRC_MEMBERS", "assets/data/current-members.json")
SRC_VOTES = os.environ.get("SRC_VOTES", "assets/data/federal-member-votes.json")
SRC_UNITY = os.environ.get("SRC_UNITY", "assets/data/federal-party-unity.json")
SRC_SPONSOR_INDEX = os.environ.get("SRC_SPONSOR_INDEX", "assets/data/federal-sponsorship-index.json")
SRC_SPONSOR_DIR = os.environ.get("SRC_SPONSOR_DIR", "assets/data/federal-sponsorship")


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def normalize_member(m):
    """Add a derived top-level `chamber` and fix field types. Everything else is
    passed through unchanged from Congress.gov."""
    m = dict(m)
    terms = (m.get("terms") or {}).get("item") or []
    # Terms run oldest -> newest, so the LAST one is where the member sits now. Taking
    # item[0] reports a House-to-Senate member by their first chamber (43 members of
    # the full Congress, e.g. Grassley, Schiff, Wyden); no Georgia member is affected.
    # Matches congress.js, find-my-reps.html and the other generators.
    m["chamber"] = terms[-1].get("chamber") if terms else None
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
def members_csv(members, congress=None):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["bioguideId", "name", "firstName", "lastName", "party", "chamber",
                "district", "phone", "website", "birthYear", "officeAddress",
                "committees", "imageUrl", "congress"])
    for m in members:
        ci = m.get("contactInfo") or {}
        w.writerow([
            m.get("bioguideId"), m.get("name"), m.get("firstName"), m.get("lastName"),
            m.get("partyName"), m.get("chamber"),
            "" if m.get("district") is None else m.get("district"),
            ci.get("phoneNumber"), m.get("officialWebsiteUrl"), m.get("birthYear"),
            ci.get("officeAddress"), "; ".join(m.get("committees") or []),
            (m.get("depiction") or {}).get("imageUrl"), _cell(congress),
        ])
    return buf.getvalue().encode()


def _cell(value):
    return "" if value is None else value


def votes_csv(votes, congress=None):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["voteId", "chamber", "date", "bill", "title", "motionText",
                "result", "yea", "nay", "billUrl", "congress"])
    for vid, v in sorted(votes.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
        w.writerow([vid, v.get("chamber"), v.get("date"), v.get("bill"), v.get("title"),
                    v.get("motionText"), v.get("result"), v.get("yea"), v.get("nay"),
                    v.get("billUrl"), _cell(congress)])
    return buf.getvalue().encode()


def member_votes_csv(members, votes, member_votes, congress=None):
    by_id = {m["bioguideId"]: m for m in members}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["bioguideId", "name", "party", "chamber", "district",
                "voteId", "date", "bill", "title", "vote", "congress"])
    for bid, recs in member_votes.items():
        m = by_id.get(bid, {})
        for r in recs:
            v = votes.get(r.get("voteId"), {})
            w.writerow([bid, m.get("name"), m.get("partyName"), m.get("chamber"),
                        "" if m.get("district") is None else m.get("district"),
                        r.get("voteId"), v.get("date"), v.get("bill"), v.get("title"),
                        r.get("vote"), _cell(congress)])
    return buf.getvalue().encode()


# --------------------------------------------------------------------------- #
# Markdown roster
# --------------------------------------------------------------------------- #
def roster_md(members, meta, session=None):
    sens = sorted([m for m in members if m.get("chamber") == "Senate"],
                  key=lambda m: (m.get("lastName") or ""))
    reps = sorted([m for m in members if m.get("chamber") == "House of Representatives"],
                  key=lambda m: (m.get("district") if m.get("district") is not None else 999))

    def phone(m):
        return ((m.get("contactInfo") or {}).get("phoneNumber")) or ""

    def web(m):
        u = m.get("officialWebsiteUrl")
        return f"[site]({u})" if u else ""

    cong = meta.get("congress")
    title = "# Georgia Federal Delegation"
    if cong:
        title += f" ({congress_ordinal(cong)} Congress)"
    L = [title, ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta['generatedAt']} · {meta['count']} members "
             f"({len(sens)} Senate, {len(reps)} House)._")
    L.append("")
    L.append("> Machine-readable versions: [`data/members.json`](data/members.json), "
             "[`data/members.csv`](data/members.csv). Roll-call votes: "
             "[`data/votes.csv`](data/votes.csv), [`data/member-votes.csv`](data/member-votes.csv).")
    L.append("")
    if session:
        L.append(f"> This is the frozen record of the {session} Congress, kept as history. "
                 "The current Congress is in [`data/`](../../data); every frozen Congress lives under "
                 "[`sessions/`](../).")
    else:
        L.append("> Prior Congresses are preserved under [`sessions/`](sessions); the files "
                 "below describe the current Congress only and are replaced at each new Congress.")
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
def schema_url(path):
    """Canonical $id for a schema published at `path`. A frozen Congress's schema declares
    sessions/<slug>/..., not the live data/ file, so two documents never share one $id."""
    return f"{RAW_BASE}/{path}"


def members_schema(path="data/members.schema.json"):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_url(path),
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": SCHEMA_STABILITY,
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
                                    "description": "Derived top-level chamber (from the most recent entry in terms.item, i.e. the last one) for convenience."},
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
                        "sponsorship": {
                            "type": ["object", "null"],
                            "description": "Complete current-Congress sponsorship counts, from a full "
                                           "paginated walk of both Congress.gov endpoints; null if that "
                                           "refresh could not fetch the member's record. Georgia-only.",
                            "properties": {
                                "congress": {"type": "integer"},
                                "sponsored": {"type": "integer"},
                                "cosponsored": {"type": "integer"},
                            },
                        },
                        "recentSponsored": {"type": "array",
                                            "description": "The 20 most recently introduced bills sponsored "
                                                           "this Congress, drawn from the complete list; "
                                                           "Georgia-only enrichment."},
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


def votes_schema(path="data/votes.schema.json"):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_url(path),
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": SCHEMA_STABILITY,
        "title": "Georgia Federal Delegation — Roll-call Votes",
        "description": "Roll-call votes for Georgia's federal delegation in the current Congress. "
                       "SCOPE: every recorded roll call both chambers held, enumerated from the "
                       "Clerk of the House's per-year roll files and the Senate's per-session vote "
                       "index - including measures that failed, amendments, procedural motions and "
                       "Senate nominations. A vote on anything other than a measure (a quorum call, "
                       "a motion to adjourn, a nomination) has bill and billUrl null. Voice votes "
                       "and unanimous-consent agreements are not recorded by name and cannot appear. "
                       "yea/nay are chamber-wide totals.",
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
def check_sources(ga, votes_doc):
    """Decide whether the sources are fit to publish. Returns a list of warnings;
    raises SystemExit when publishing would wipe or contradict the public repo.

    Nothing here discards data -- the sources are already committed, so a refusal
    just leaves the sibling repo as it was until the next trigger. The question is
    only which conditions are worth refusing for.

    FATAL: no Georgia members (an empty roster would blank members.json), and a
    vote catalog that contradicts its per-member records (votes with no
    memberVotes, or the reverse).

    NOT fatal: a Congress that has not held a roll call yet. The 120th convenes
    3 January 2027 and its first recorded votes come days later, while the roster
    -- the part that changes on swearing-in day -- is exactly what readers need.
    The old gate (`memberVotes` non-empty) held the whole publish, new members
    included, until the first vote.
    """
    if not ga:
        sys.exit("FATAL: no Georgia members found in current-members.json")
    votes = votes_doc.get("votes") or {}
    member_votes = votes_doc.get("memberVotes") or {}
    if bool(votes) != bool(member_votes):
        sys.exit("FATAL: federal-member-votes.json is self-contradictory: "
                 f"{len(votes)} vote(s) but {len(member_votes)} member(s) with records")
    if not member_votes:
        return ["federal-member-votes.json holds no roll calls yet (a Congress that has "
                "not voted); publishing the roster with empty vote files"]
    return []


def build_artifacts():
    src = json.load(open(SRC_MEMBERS, encoding="utf-8"))
    ga = [normalize_member(m) for m in src.get("members", []) if m.get("state") == "Georgia"]
    votes_doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    for warning in check_sources(ga, votes_doc):
        print(f"WARNING: {warning}")
    votes = votes_doc.get("votes", {})
    member_votes = votes_doc.get("memberVotes", {})

    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Congress.gov API, filtered to Georgia from votega.org current-members.json",
        "sourceGeneratedAt": src.get("metadata", {}).get("generatedAt"),
        "count": len(ga),
        "congress": votes_doc.get("metadata", {}).get("congress"),
        "schemaVersion": SCHEMA_VERSION,
    }

    congress = meta["congress"]
    return {
        "data/members.json": build_json({"metadata": meta, "members": ga}),
        "data/votes.json": build_json(votes_doc),
        "data/members.csv": members_csv(ga, congress),
        "data/votes.csv": votes_csv(votes, congress),
        "data/member-votes.csv": member_votes_csv(ga, votes, member_votes, congress),
        "data/members.schema.json": build_json(members_schema()),
        "data/votes.schema.json": build_json(votes_schema()),
        "ROSTER.md": roster_md(ga, meta),
    }


# --------------------------------------------------------------------------- #
# freeze mode: keep a finished Congress as history under sessions/<slug>/
# --------------------------------------------------------------------------- #
# The daily publish replaces data/ in place, so on 3 January 2027 data/ stops describing
# the 119th and starts describing the 120th. `freeze` writes the 119th's whole Georgia
# record into sessions/119th/ first, and nothing the daily publish writes can reach
# that directory (assert_no_archive_paths). Run it twice: a provisional freeze any time,
# and a --final one after the Congress's last roll call and BEFORE the first daily run of
# the new Congress (the date-derived Congress number flips at 00:00 UTC on 3 January, 11
# hours before the 120th convenes, so "final by 2 January").
FREEZE_KINDS = ("provisional", "final")
SLUG_RE = re.compile(r"^\d+(st|nd|rd|th)$")


def resolve_freeze_slug(explicit, votes_doc):
    """`119th`. An explicit slug wins; otherwise it is derived from the votes file's Congress."""
    if explicit:
        if not SLUG_RE.match(explicit):
            sys.exit(f"freeze: slug must look like '119th', got {explicit!r}")
        return explicit
    congress = (votes_doc.get("metadata") or {}).get("congress")
    if not isinstance(congress, int):
        sys.exit("freeze: federal-member-votes.json has no metadata.congress; pass the slug explicitly")
    return congress_ordinal(congress)


def assert_same_congress(slug, congresses):
    """Every source file must describe the Congress being frozen.

    After 3 January the live files describe the 120th, so a late run of `freeze 119th`
    would otherwise file the 120th's data under the 119th's name -- and a final freeze
    of it could not be told apart from the real one. `congresses` is {source: number}.
    """
    bad = {k: v for k, v in congresses.items() if not isinstance(v, int) or congress_ordinal(v) != slug}
    if bad:
        sys.exit(f"freeze: refusing to file data under sessions/{slug}/ -- these sources "
                 f"describe a different Congress: {bad}")


def assert_archive_paths(artifacts, slug):
    """Every freeze artifact lives under sessions/<slug>/ (LICENSE/NOTICE are injected later)."""
    bad = [pth for pth in artifacts if not pth.startswith(f"sessions/{slug}/")]
    if bad:
        sys.exit(f"freeze: refusing to publish outside sessions/{slug}/: {bad}")


def assert_no_archive_paths(artifacts):
    """The daily publish must never write into sessions/: that is the whole point of the archive."""
    bad = [pth for pth in artifacts if pth.startswith("sessions/")]
    if bad:
        sys.exit(f"daily publish: refusing to write into the frozen archive: {bad}")


def check_freeze_state(existing_kind, kind, overwrite):
    """A final freeze is not replaced casually. provisional -> provisional/final is fine
    (that is the plan); final -> anything needs --overwrite."""
    if kind not in FREEZE_KINDS:
        sys.exit(f"freeze: kind must be one of {FREEZE_KINDS}, got {kind!r}")
    if existing_kind == "final" and not overwrite:
        sys.exit("freeze: this Congress already has a FINAL freeze; re-run with --overwrite "
                 "to replace it deliberately.")


def existing_freeze_kind(slug):
    """`kind` of the freeze already published at sessions/<slug>/freeze.json, or None.
    Only checks when a token is set (a dry run writes to disk, not the repo)."""
    token = os.environ.get(TOKEN_ENV)
    if not token:
        return None
    url = f"https://api.github.com/repos/{REPO}/contents/{SESSIONS_DIR}/{slug}/freeze.json"
    req = urllib.request.Request(url, headers={"Authorization": f"token {token}",
                                               "Accept": "application/vnd.github.v3+json"})
    try:
        body = json.loads(_urlopen_retry(req))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    try:
        return json.loads(base64.b64decode(body["content"])).get("kind")
    except (KeyError, ValueError):
        return None


def scorecard_csv(unity_doc, congress):
    cols = ["bioguideId", "name", "chamber", "party", "totalRollCalls", "cast", "missed",
            "participationRate", "missedRate", "partyUnity", "partyLineVotes", "votedWithParty",
            "independenceRate", "unityRank", "participationRank", "cohortSize"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols + ["congress"])
    for bid, rec in sorted((unity_doc.get("members") or {}).items()):
        w.writerow([bid] + [_cell(rec.get(c)) for c in cols[1:]] + [_cell(congress)])
    return buf.getvalue().encode()


def sponsorship_csv(slices, congress):
    """Decode the positional sponsorship slices into one flat row per bill.

    Slice rows are [type, number, title, introducedDate, actionDate, actionIdx, policyIdx],
    the last two indexing the slice's own `actions` / `policyAreas` tables (see
    lib/federal_sponsorship.py). A flat table is what a spreadsheet user can actually open;
    the raw slices are published beside it for anyone who wants the compact form."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["bioguideId", "role", "billType", "billNumber", "title", "introducedDate",
                "actionDate", "latestAction", "policyArea", "billUrl", "congress"])
    for bid in sorted(slices):
        sl = slices[bid]
        actions, policies = sl.get("actions") or [], sl.get("policyAreas") or []
        for role, key in (("sponsor", "primary"), ("cosponsor", "cosponsored")):
            for row in sl.get(key) or []:
                typ, num, title, intro, act, ai, pi = (list(row) + [None] * 7)[:7]
                w.writerow([bid, role, typ, num, title, _cell(intro), _cell(act),
                            actions[ai] if isinstance(ai, int) and 0 <= ai < len(actions) else "",
                            policies[pi] if isinstance(pi, int) and 0 <= pi < len(policies) else "",
                            bill_url(congress, typ, num), _cell(congress)])
    return buf.getvalue().encode()


def freeze_readme(slug, congress, kind, meta, counts):
    first, second = congress_years(congress)
    L = [f"# {slug} Congress: Georgia delegation (frozen record)", "",
         f"The Georgia federal delegation's record for the {slug} Congress "
         f"(January 3, {first} to January 3, {second + 1}), kept as history. "
         f"Freeze kind: **{kind}**, taken {meta['frozenAt']}."]
    if kind == "provisional":
        L += ["", "> **Provisional.** The Congress was still sitting when this was taken, so later "
              "votes, sponsorships and roster changes are missing. A final freeze replaces it "
              "once the Congress has adjourned."]
    L += ["", "The live files in [`data/`](../../data) describe the current Congress and are "
          "replaced at each new Congress. Nothing in this directory is touched by the daily "
          "publish.", "", "## Files", "",
          f"- `members.json`, `members.csv`: the {counts['members']} delegation members "
          "(`members.schema.json`).",
          f"- `votes.json`: every recorded roll call ({counts['votes']}) joined to the "
          "delegation, in the same shape as the live file (`votes.schema.json`). `votes.csv` "
          "and `member-votes.csv` are flat versions.",
          "- `scorecard.json`, `scorecard.csv`: party-unity and participation per member.",
          f"- `sponsorship/`: each member's complete sponsored and cosponsored record "
          f"({counts['sponsored']} sponsored, {counts['cosponsored']} cosponsored) in the compact "
          "form the site uses: `index.json` plus one `<bioguideId>.json` per member, where each "
          "row is `[type, number, title, introducedDate, actionDate, actionIdx, policyIdx]` and "
          "the last two index that file's own `actions` and `policyAreas` lists. "
          "`sponsorship.csv` is the same data, one flat row per bill.",
          "- `freeze.json`: what was frozen, when, from which sources, and with what counts.", "",
          "## Notes", "",
          "- Members are keyed by `bioguideId`, Congress.gov's stable id.",
          "- Where a Senate roll call is marked in `votes.json` `metadata.senateRollsFromVoteview`, "
          "it was taken from Voteview because senate.gov was unreachable; those records may "
          "differ slightly from the official one.",
          "- Reuse is governed by the repository's `LICENSE` and `NOTICE.md`.", ""]
    return ("\n".join(L) + "\n").encode()


def build_freeze(slug, kind, src_members_doc, votes_doc, unity_doc, sponsor_index, slices, now=None):
    """The whole sessions/<slug>/ artifact set. Pure: no network, no disk."""
    congress = (votes_doc.get("metadata") or {}).get("congress")
    assert_same_congress(slug, {
        "federal-member-votes.json": congress,
        "federal-party-unity.json": (unity_doc.get("metadata") or {}).get("congress"),
        "federal-sponsorship-index.json": (sponsor_index.get("metadata") or {}).get("congress"),
    })
    ga = [normalize_member(m) for m in src_members_doc.get("members", [])
          if m.get("state") == "Georgia"]
    for warning in check_sources(ga, votes_doc):
        print(f"WARNING: {warning}")
    votes = votes_doc.get("votes", {})
    member_votes = votes_doc.get("memberVotes", {})
    base = f"{SESSIONS_DIR}/{slug}"
    frozen_at = (now or datetime.now(timezone.utc)).isoformat()

    sponsor_meta = sponsor_index.get("metadata") or {}
    counts = {"members": len(ga), "votes": len(votes),
              "sponsored": sponsor_meta.get("totalSponsored", 0),
              "cosponsored": sponsor_meta.get("totalCosponsored", 0)}
    manifest = {
        "congress": congress, "slug": slug, "kind": kind, "frozenAt": frozen_at,
        "congressYears": list(congress_years(congress)), "counts": counts,
        "sources": {
            "members": (src_members_doc.get("metadata") or {}).get("generatedAt"),
            "votes": (votes_doc.get("metadata") or {}).get("generatedAt"),
            "scorecard": (unity_doc.get("metadata") or {}).get("generatedAt"),
            "sponsorship": sponsor_meta.get("generatedAt"),
        },
        "schemaVersion": SCHEMA_VERSION,
    }
    meta = {
        "generatedAt": frozen_at,
        "source": "Congress.gov API, filtered to Georgia from votega.org current-members.json",
        "sourceGeneratedAt": (src_members_doc.get("metadata") or {}).get("generatedAt"),
        "count": len(ga), "congress": congress, "schemaVersion": SCHEMA_VERSION,
        "freeze": {"kind": kind, "frozenAt": frozen_at, "slug": slug},
    }
    artifacts = {
        f"{base}/members.json": build_json({"metadata": meta, "members": ga}),
        f"{base}/members.csv": members_csv(ga, congress),
        f"{base}/members.schema.json": build_json(members_schema(f"{base}/members.schema.json")),
        f"{base}/votes.json": build_json(votes_doc),
        f"{base}/votes.csv": votes_csv(votes, congress),
        f"{base}/member-votes.csv": member_votes_csv(ga, votes, member_votes, congress),
        f"{base}/votes.schema.json": build_json(votes_schema(f"{base}/votes.schema.json")),
        f"{base}/scorecard.json": build_json(unity_doc),
        f"{base}/scorecard.csv": scorecard_csv(unity_doc, congress),
        f"{base}/sponsorship/index.json": build_json(sponsor_index),
        f"{base}/sponsorship.csv": sponsorship_csv(slices, congress),
        f"{base}/README.md": freeze_readme(slug, congress, kind, manifest, counts),
        f"{base}/freeze.json": build_json(manifest),
    }
    for bid, sl in slices.items():
        artifacts[f"{base}/sponsorship/{bid}.json"] = build_json(sl)
    assert_archive_paths(artifacts, slug)
    return artifacts


def load_sponsorship_slices(sponsor_index):
    out = {}
    for bid in sorted((sponsor_index.get("members") or {})):
        path = os.path.join(SRC_SPONSOR_DIR, f"{bid}.json")
        try:
            out[bid] = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            sys.exit(f"freeze: the sponsorship index lists {bid} but {path} is missing or unreadable")
    return out


def run_freeze(argv):
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--final", "--overwrite"}
    if unknown:
        sys.exit(f"freeze: unknown option(s) {sorted(unknown)}; use --final and/or --overwrite")
    args = [a for a in argv if not a.startswith("--")]
    kind = "final" if "--final" in flags else "provisional"
    votes_doc = json.load(open(SRC_VOTES, encoding="utf-8"))
    slug = resolve_freeze_slug(args[0] if args else None, votes_doc)
    check_freeze_state(existing_freeze_kind(slug), kind, "--overwrite" in flags)
    sponsor_index = json.load(open(SRC_SPONSOR_INDEX, encoding="utf-8"))
    artifacts = build_freeze(
        slug, kind, json.load(open(SRC_MEMBERS, encoding="utf-8")), votes_doc,
        json.load(open(SRC_UNITY, encoding="utf-8")), sponsor_index,
        load_sponsorship_slices(sponsor_index))
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV,
                       validate=min_items(f"{SESSIONS_DIR}/{slug}/members.json", "members"))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "freeze":
        run_freeze(sys.argv[2:])
        return
    artifacts = build_artifacts()
    assert_no_archive_paths(artifacts)
    publish_or_dry_run(REPO, artifacts, TOKEN_ENV,
                       validate=min_items("data/members.json", "members"))


if __name__ == "__main__":
    main()
