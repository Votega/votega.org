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

VOTES_URL   = "http://webservices.legis.ga.gov/GGAServices/Votes/Service.svc"
LEG_URL     = "http://webservices.legis.ga.gov/GGAServices/Legislation/Service.svc"
SESSION_URL = "http://webservices.legis.ga.gov/GGAServices/Session/Service.svc"
MEMBERS_URL    = "http://webservices.legis.ga.gov/GGAServices/Members/Service.svc"
COMMITTEES_URL = "http://webservices.legis.ga.gov/GGAServices/Committees/Service.svc"
SVC_NS    = "http://www.legis.ga.gov/2009/01/01/services/"
DATA_NS   = "http://www.legis.ga.gov/2009/01/01/data/"
ns = {"s": SVC_NS, "d": DATA_NS}

# SOAPAction strings are per-contract and NOT uniform — the Votes/Legislation
# contracts use the full action; grep each WSDL's soapAction= to confirm.
ACTION = {
    "GetVotes":                 SVC_NS + "VoteFinder/GetVotes",
    "GetVote":                  SVC_NS + "VoteFinder/GetVote",
    "GetLegislationForSession": SVC_NS + "LegislationSearch/GetLegislationForSession",
    # The Session contract is the odd one out: its soapAction is the BARE operation
    # name, with no namespace and no contract prefix. Taken from the WSDL, not guessed.
    "GetSessions":              "GetSessions",
    "GetMembersBySession":      SVC_NS + "MemberFinder/GetMembersBySession",
    "GetMember":                SVC_NS + "MemberFinder/GetMember",
    "GetCommitteesBySession":   SVC_NS + "CommitteeFinder/GetCommitteesBySession",
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


def get_sessions():
    """Session/GetSessions -> [{id, description, library, isDefault}], newest first-ish.

    Takes no parameters and returns every session the legislature has published (23 as
    of 2026-10, back to 2001-2002). This is the only correct way to learn a SessionId:
    the id space is neither contiguous nor ordered by era (1, 6, 7, 11, 13-15, 18,
    20-27, then 1027+), so probing a range finds the recent sessions and misses every
    older one.

    `isDefault` marks the current REGULAR session, which is NOT the session in
    progress — during the 2026 special session (1034) it stayed on 1033. Do not use it
    to decide which session to fetch live.
    """
    root = soap_call(SESSION_URL, "GetSessions")
    if root is None:
        return []
    out = []
    for el in root.findall(".//d:Session", ns):
        sid = _text(el, "Id", int)
        if sid is None:
            continue
        out.append({
            "id":          sid,
            "description": _text(el, "Description") or "",
            "library":     _text(el, "Library") or None,
            "isDefault":   (_text(el, "IsDefault") or "").lower() == "true",
        })
    return out


def get_members_by_session(legis_session):
    """GetMembersBySession -> one dict per member who served in that session.

    Everyone who served, not just the current seats — 247 for session 1033, of which 11
    carry a `dateVacated`. This is the THIN listing: `phone` is 15% populated and `email`
    is 0%, so a roster needs get_member() per person for contact details. Same
    listing-vs-detail split as GetVotes/GetVote, but much sharper.
    """
    root = soap_call(MEMBERS_URL, "GetMembersBySession",
                     "<s:SessionId>%d</s:SessionId>" % legis_session)
    if root is None:
        return []
    out = []
    for el in root.findall(".//d:MemberListing", ns):
        mid = _text(el, "Id", int)
        if mid is None:
            continue
        name = el.find("d:Name", ns)
        district = el.find("d:District", ns)
        addr = el.find("d:DistrictAddress", ns)
        out.append({
            "id":           mid,
            "legId":        _text(el, "LegId", int),
            "first":        _text(name, "First") if name is not None else None,
            "last":         _text(name, "Last") if name is not None else None,
            "middle":       _text(name, "Middle") if name is not None else None,
            "nickname":     _text(name, "Nickname") if name is not None else None,
            "suffix":       _text(name, "Suffix") if name is not None else None,
            "party":        _text(el, "Party"),
            "chamber":      _text(district, "Type") if district is not None else None,
            "district":     _text(district, "Number", int) if district is not None else None,
            "residence":    _text(el, "Residence"),
            # Set when the member left the seat ("2025-10-12T00:00:00"). A dated departure
            # feed — but the REASON is not in the API, so a caller must never infer a
            # status (resigned / removed / deceased / suspended) from it.
            "dateVacated":  _text(el, "DateVacated"),
            "districtCity": _text(addr, "City") if addr is not None else None,
        })
    return out


def get_member(member_id):
    """GetMember -> the full record for one member, or None on transport failure.

    Flattened to what a roster needs. `sessions` holds one entry per session served;
    order is not guaranteed, so match on sessionId or the isDefault flag.
    """
    root = soap_call(MEMBERS_URL, "GetMember", "<s:MemberId>%d</s:MemberId>" % member_id)
    if root is None:
        return None
    m = root.find(".//s:GetMemberResult", ns)
    if m is None:
        return None

    addr = m.find("d:Address", ns)      # the CAPITOL office — phone and email live here
    name = m.find("d:Name", ns)
    press = m.find("d:Press", ns)
    portraits = {}
    for img in m.findall("d:Portrait/d:Images/d:Image", ns):
        kind, url = _text(img, "ImageType"), _text(img, "Url")
        if kind and url:
            portraits[kind] = url

    sessions = []
    for svc in m.findall("d:SessionsInService/d:LegislativeService", ns):
        sess = svc.find("d:Session", ns)
        dist = svc.find("d:District", ns)
        committees = []
        for cm in svc.findall("d:CommitteeMemberships/d:CommitteeMembership", ns):
            com = cm.find("d:Committee", ns)
            if com is None:
                continue
            committees.append({
                "id":          _text(com, "Id", int),
                "code":        _text(com, "Code"),
                "name":        _text(com, "Name"),
                "type":        _text(com, "Type"),
                "role":        _text(cm, "Role"),
                "dateVacated": _text(cm, "DateVacated"),
            })
        sessions.append({
            "sessionId":   _text(sess, "Id", int) if sess is not None else None,
            "description": _text(sess, "Description") if sess is not None else None,
            "isDefault":   ((_text(sess, "IsDefault") or "").lower() == "true"
                            if sess is not None else False),
            # Party and district sit INSIDE each session's record, so this doubles as a
            # history of party switches and of pre-redistricting seats.
            "party":       _text(svc, "Party"),
            "chamber":     _text(dist, "Type") if dist is not None else None,
            "district":    _text(dist, "Number", int) if dist is not None else None,
            # Leadership role, free text. Normalize via lib/ga_leadership.py.
            "title":       _text(svc, "Title"),
            "dateVacated": _text(svc, "DateVacated"),
            "committees":  committees,
        })

    return {
        "id":         _text(m, "Id", int),
        "first":      _text(name, "First") if name is not None else None,
        "last":       _text(name, "Last") if name is not None else None,
        "phone":      _text(addr, "Phone") if addr is not None else None,
        "email":      _text(addr, "Email") if addr is not None else None,
        "address1":   _text(addr, "Address1") if addr is not None else None,
        "city":       _text(addr, "City") if addr is not None else None,
        "state":      _text(addr, "State") if addr is not None else None,
        "zip":        _text(addr, "Zip") if addr is not None else None,
        # Month and day only ("July 12") — there is NO birth year anywhere in this API.
        "birthday":   _text(m, "Birthday"),
        "occupation": _text(m, "Occupation"),
        "residence":  _text(m, "Residence"),
        "staff":      _text(m, "Staff"),
        "pressUrl":   _text(press, "Url") if press is not None else None,
        "portraits":  portraits,
        "sessions":   sessions,
    }


def get_committees_by_session(legis_session):
    """GetCommitteesBySession -> [{id, code, name, type}].

    Top-level committees only: the House's Appropriations subcommittees are NOT returned.
    Note the names here disagree with the ones in a member's leadership Title on "&" vs
    "and", and are inconsistent with themselves ("Agriculture & Consumer Affairs" next to
    "Industry and Labor") — fold both before matching.
    """
    root = soap_call(COMMITTEES_URL, "GetCommitteesBySession",
                     "<s:SessionId>%d</s:SessionId>" % legis_session)
    if root is None:
        return []
    out = []
    for el in root.findall(".//d:CommitteeListing", ns):
        cid = _text(el, "Id", int)
        if cid is None:
            continue
        out.append({"id": cid, "code": _text(el, "Code"),
                    "name": _text(el, "Name"), "type": _text(el, "Type")})
    return out


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
