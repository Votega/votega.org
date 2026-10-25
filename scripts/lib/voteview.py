#!/usr/bin/env python3
"""Senate roll calls from Voteview (UCLA) - the fallback when senate.gov refuses us.

senate.gov began answering every non-browser request with an Akamai 403 (first
seen in the 2026-10-25 weekly runs), which stops the Senate half of both
generate_federal_votes_data.py and generate_vp_tie_votes.py. Congress.gov has no
Senate roll-call endpoint, so the one machine-readable source left is Voteview's
static CSVs: no key, no quota, derived from the Senate record, and joinable to
our delegation by bioguide id (members file) rather than by name.

Three files per Congress, all under BASE:

    rollcalls/HS<c>_rollcalls.csv   one row per roll call
    votes/HS<c>_votes.csv           one row per member per roll call (~10 MB)
    members/HS<c>_members.csv       icpsr -> bioguide_id, party_code, state

**The official record always wins.** Voteview is a derivative: 4 of the 915 Senate
roll calls we hold disagree with it by a vote or a day (S119_1_00026 is 80-17
officially, 79-18 here). So callers use this only for roll calls they do not
already have, and mark what they took from it so a later run can replace it.

**Join key.** Voteview numbers Senate roll calls continuously across a Congress
(`rollnumber`); the Senate restarts at 1 each session. `clerk_rollnumber` is the
Senate's own number, so `(session, clerk_rollnumber)` is our (session, number) -
verified exact against all 915 committed roll calls.

**What it cannot see.** The Vice President's tie-breaking vote is not recorded
(Vance has one row, roll 1). A tie-break shows only as a tied tally on a question
that carried; a VP "Nay" is indistinguishable from a failed tie.

Network access goes through an injected `fetch` so the tests need none.
"""

import csv
import io
import re

from lib.http import fetch_bytes

BASE = "https://voteview.com/static/data/out"

#: cast_code -> the labels generate_federal_votes_data.VOTE_MAP already uses.
#: 1-3 Yea (3 = announced/paired), 4-6 Nay, 7-8 Present, 9 Not Voting.
CAST_LABEL = {
    **{c: "Yea" for c in "123"},
    **{c: "Nay" for c in "456"},
    **{c: "Not Voting" for c in "789"},
}

#: Voteview party_code -> the names the House XML and the member pages use.
PARTY_NAME = {"100": "Democratic", "200": "Republican", "328": "Independent"}

_BILL_RE = re.compile(r"^(HR|S|HJRES|SJRES|HCONRES|SCONRES|HRES|SRES)(\d+)$")


def url(kind, congress):
    return f"{BASE}/{kind}/HS{congress}_{kind}.csv"


def cast_label(code):
    return CAST_LABEL.get(str(code).strip(), "Other")


def party_name(code):
    return PARTY_NAME.get(str(code).strip(), "Other")


def split_bill_number(raw):
    """'SCONRES7' -> ('sconres', '7'); a nomination ('PN1129') or '' -> (None, None).

    The type is the TYPE_SLUG key the federal generator already uses.
    """
    m = _BILL_RE.match((raw or "").strip().upper())
    return (m.group(1).lower(), m.group(2)) if m else (None, None)


def _rows(raw):
    return csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))


def load_senate(congress, fetch=None):
    """Fetch and shape the Senate side of one Congress, or None if any file is missing.

    Returns {'rolls': {(session, number): row}, 'casts': {(session, number):
    {icpsr: code}}, 'members': {icpsr: row}}. All three files must arrive: a roll
    call with a tally but no member votes would publish an empty party breakdown.
    """
    fetch = fetch or (lambda u, label: fetch_bytes(u, label=label))
    raws = {k: fetch(url(k, congress), f"voteview {k}") for k in ("rollcalls", "votes", "members")}
    if not all(raws.values()):
        return None

    rolls, by_rollnumber = {}, {}
    for row in _rows(raws["rollcalls"]):
        if row["chamber"] != "Senate":
            continue
        key = (int(row["session"]), int(row["clerk_rollnumber"]))
        rolls[key] = row
        by_rollnumber[row["rollnumber"]] = key

    casts = {}
    for row in _rows(raws["votes"]):
        if row["chamber"] != "Senate":
            continue
        key = by_rollnumber.get(row["rollnumber"])
        if key:
            casts.setdefault(key, {})[row["icpsr"]] = row["cast_code"]

    members = {r["icpsr"]: r for r in _rows(raws["members"]) if r["chamber"] == "Senate"}
    return {"rolls": rolls, "casts": casts, "members": members}


def senate_roll(data, session, number, bioguides):
    """One roll call, shaped for the generators, or None if Voteview lacks it.

    `bioguides` is the set of members to return individual votes for; the party
    tally always covers every senator who cast a vote.
    """
    key = (session, number)
    row = data["rolls"].get(key)
    if row is None:
        return None
    tally, member_votes = {}, {}
    for icpsr, code in (data["casts"].get(key) or {}).items():
        member = data["members"].get(icpsr)
        if member is None:
            continue
        label = cast_label(code)
        bucket = tally.setdefault(party_name(member["party_code"]),
                                  {"yea": 0, "nay": 0, "other": 0})
        bucket["yea" if label == "Yea" else "nay" if label == "Nay" else "other"] += 1
        if member["bioguide_id"] in bioguides:
            member_votes[member["bioguide_id"]] = label
    bill_type, bill_number = split_bill_number(row["bill_number"])
    return {
        "session": session,
        "number": number,
        "date": row["date"],
        "question": row["vote_question"] or "",
        "result": row["vote_result"] or "",
        "title": row["vote_desc"] or None,
        "yea": int(row["yea_count"] or 0),
        "nay": int(row["nay_count"] or 0),
        "bill_type": bill_type,
        "bill_number": bill_number,
        "party_tally": tally or None,
        "member_votes": member_votes,
    }
