#!/usr/bin/env python3
"""SOAP client for the Georgia General Assembly web services (webservices.legis.ga.gov).

The official roll-call source. No auth, no quota, and every voter row is keyed by the
legislature's own numeric member id (`Member.Id` == the project's `legisGaGovId`), so the
surname-collision problem Open States introduces is gone by construction.

Lifted out of scripts/generate_ga_votes_soap.py so more than one producer can use it:
generate_curated_ga_bills.py needs the same roll calls for bills outside the biennium
our committed artifacts cover.

The listing carries more than the roll call's id
------------------------------------------------
`GetVotes(Branch, SessionId)` returns a `<VoteListing>` per roll call with, among others:

    Number      the chamber's own roll-call number for the session, dense from 1
    Description "House Vote #1" -- the string Open States republishes verbatim
    Time        "10:20 AM", which orders roll calls within a day
    Yeas/Nays   the official tally, independent of the per-member rows in GetVote
    Excused/NotVoting counts
    Branch      the chamber, authoritatively

`Number` matters because it cannot be derived downstream: it counts EVERY roll call the
chamber held, while producers keep only passage votes (312 dropped in 2025-26), and
`VoteId` is not a sequence -- it tracks record creation, and inverts 137 times within a
day in the House. Measured against Open States over 1,898 joined roll calls the two agree
1,891 times; in the 7 disagreements OS labels a passage vote with the number of the
procedural roll call that preceded it, and `Number` is right.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

VOTES_URL = "http://webservices.legis.ga.gov/GGAServices/Votes/Service.svc"
LEG_URL   = "http://webservices.legis.ga.gov/GGAServices/Legislation/Service.svc"
SVC_NS    = "http://www.legis.ga.gov/2009/01/01/services/"
DATA_NS   = "http://www.legis.ga.gov/2009/01/01/data/"
ns = {"s": SVC_NS, "d": DATA_NS}

# SOAPAction strings are per-contract and NOT uniform — the Votes/Legislation
# contracts use the full action; grep each WSDL's soapAction= to confirm.
ACTION = {
    "GetVotes":                 SVC_NS + "VoteFinder/GetVotes",
    "GetVote":                  SVC_NS + "VoteFinder/GetVote",
    "GetLegislationForSession": SVC_NS + "LegislationSearch/GetLegislationForSession",
}

# MemberVoted enum -> the vote strings the rest of the project uses.
VOTE_MAP = {
    "Yea": "Yea",
    "Nay": "Nay",
    "NotVoting": "Not Voting",
    "Excused": "Excused",
    "Unknown": "Other",
}

CHAMBERS = ["House", "Senate"]
# SOAP Branch -> the chamber spelling ga-members.json uses, so a vote record's chamber
# can be compared to a member's without a translation table at every call site.
CHAMBER_NAMES = {"House": "House of Representatives", "Senate": "Senate"}
VACANT_ID = 0           # Member.Id sentinel for an empty seat


class RollCallNotPublished(Exception):
    """GetVote faulted: this roll call isn't published (attendance / procedural)."""


def _envelope(op, inner, url_ns=SVC_NS):
    return ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:s="{url_ns}"><soap:Body><s:{op}>{inner}</s:{op}>'
            '</soap:Body></soap:Envelope>')


def _parse_fault(raw):
    """Return (faultstring, [detail element local-names]) for a SOAP Fault, else (None, [])."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None, []
    fs = root.find(".//faultstring")
    if fs is None:
        return None, []
    detail = root.find(".//detail")
    tags = [el.tag.split("}")[-1] for el in detail.iter()] if detail is not None else []
    return fs.text, tags


def soap_call(url, op, inner="", retries=3, timeout=60):
    """POST a SOAP request; return the parsed root Element, or None on transport failure.

    Retry policy follows CLAUDE.md: retry on HTTP 429 and transport 5xx / network
    errors only; return None on other 4xx. A SOAP *application fault* also arrives as
    500 but is deterministic — never retried: RollCallNotPublishedFault raises
    RollCallNotPublished, any other fault raises RuntimeError.
    """
    body = _envelope(op, inner).encode("utf-8")
    headers = {"Content-Type": "text/xml; charset=utf-8",
               "SOAPAction": '"%s"' % ACTION[op]}
    backoff = 4
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return ET.fromstring(resp.read())
        except urllib.error.HTTPError as e:
            fault, detail_tags = _parse_fault(e.read())
            if fault is not None:
                if any("RollCallNotPublished" in t for t in detail_tags):
                    raise RollCallNotPublished(fault)
                raise RuntimeError("SOAP fault on %s: %s" % (op, (fault or "")[:160]))
            if 400 <= e.code < 500 and e.code != 429:
                print("  %s: HTTP %d (client error) — not retrying" % (op, e.code),
                      file=sys.stderr)
                return None
            if attempt < retries:
                time.sleep(backoff); backoff *= 2; continue
            print("  %s: HTTP %d after %d retries — giving up" % (op, e.code, retries),
                  file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
            if attempt < retries:
                time.sleep(backoff); backoff *= 2; continue
            print("  %s: %s %s after %d retries — giving up"
                  % (op, type(e).__name__, e, retries), file=sys.stderr)
            return None


def _text(el, tag, cast=None):
    child = el.find("d:%s" % tag, ns)
    if child is None or child.text is None:
        return None
    if cast:
        try:
            return cast(child.text)
        except (ValueError, TypeError):
            return None
    return child.text


def get_vote_listings(legis_session, branch):
    """GetVotes -> one dict per roll call in a chamber/session.

    Keys: voteId, caption, number, time, date, yea, nay, excused, notVoting, legislation.
    `number` is the chamber's own roll-call number (see the module docstring); `yea`/`nay`
    are the OFFICIAL tally from the listing, which is independent of the per-member rows
    GetVote returns and so can be used to check them.
    """
    inner = "<s:Branch>%s</s:Branch><s:SessionId>%d</s:SessionId>" % (branch, legis_session)
    root = soap_call(VOTES_URL, "GetVotes", inner)
    if root is None:
        return []
    out = []
    for vl in root.findall(".//d:VoteListing", ns):
        vid = _text(vl, "VoteId", int)
        if vid is None:
            continue
        out.append({
            "voteId":      vid,
            "caption":     _text(vl, "Caption") or "",
            "number":      _text(vl, "Number", int),
            "time":        _text(vl, "Time") or None,
            "date":        (_text(vl, "Date") or "")[:10] or None,
            "yea":         _text(vl, "Yeas", int),
            "nay":         _text(vl, "Nays", int),
            "excused":     _text(vl, "Excused", int),
            "notVoting":   _text(vl, "NotVoting", int),
            "legislation": _text(vl, "Legislation") or "",
        })
    return out


def get_vote_detail(vote_id):
    """GetVote -> (caption, date10, legislation[], member_rows[]).

    legislation[] = [{legislationId:int, description:str}] (bundled bills).
    member_rows[] = [(member_id:int, option:str)].
    Raises RollCallNotPublished if the roll call isn't published; returns None on
    a transport failure.
    """
    root = soap_call(VOTES_URL, "GetVote", "<s:VoteId>%d</s:VoteId>" % vote_id)
    if root is None:
        return None
    # GetVoteResult (services ns) holds the Vote fields directly (data ns) —
    # there is NO nested <Vote> element.
    v = root.find(".//s:GetVoteResult", ns)
    if v is None:
        return None
    caption = (_text(v, "Caption") or "").strip()
    date10  = (_text(v, "Date") or "")[:10] or None

    legislation = []
    for item in v.findall("d:Legislation/d:ItemVotedOn", ns):
        legislation.append({"legislationId": _text(item, "LegislationId", int),
                            "description": _text(item, "Description") or ""})

    rows = []
    for mv in v.findall("d:Votes/d:MemberVote", ns):
        member = mv.find("d:Member", ns)
        mid = _text(member, "Id", int) if member is not None else None
        if mid is None:
            continue
        rows.append((mid, VOTE_MAP.get(_text(mv, "MemberVoted"), "Other")))
    return caption, date10, legislation, rows


def get_title_index(legis_session):
    """GetLegislationForSession -> {legislationId: title} in one call. Best-effort:
    returns {} on failure (titles then fall back to '')."""
    root = soap_call(LEG_URL, "GetLegislationForSession",
                     "<s:SessionId>%d</s:SessionId>" % legis_session)
    if root is None:
        return {}
    idx = {}
    for li in root.findall(".//d:LegislationIndex", ns):
        lid = _text(li, "Id", int)
        if lid is not None:
            idx[lid] = _text(li, "Caption") or ""
    return idx
