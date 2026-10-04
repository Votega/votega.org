#!/usr/bin/env python3
"""Generate ga-member-votes.json from the legis.ga.gov SOAP web service (official source).

Third producer of the SAME compact v2 schema as generate_ga_votes_data.py (Open
States) and generate_ga_votes_from_legis.py (legis.ga.gov /api). Nothing downstream
changes — only the source of the per-member vote rows.

Why this source over the other two:
  * vs Open States: the roll call keys every member by the legislature's own numeric
    id (MemberVote.Member.Id == legisGaGovId), so the surname collisions Open States'
    person matcher introduces are resolved BY CONSTRUCTION — an integer join, never a
    name. And it reaches back to 2001 (Open States starts 2017).
  * vs the legis.ga.gov /api producer (generate_ga_votes_from_legis.py): that one needs
    a Bearer-JWT mint whose live call trips the agent credential guardrail (CI-only).
    This SOAP service (webservices.legis.ga.gov) is UNAUTHENTICATED — it runs in-agent,
    locally and in CI identically — and has no request quota (unlike Open States' 250/day).

Source shape (all verified live 2026-10-04):
  * GetVotes(Branch, SessionId)  -> every published roll call listing for a chamber.
    Branch is "House" | "Senate"; SessionId is the legis numeric id (lib/ga_sessions.py
    LEGIS_SESSIONS — 2025_26 -> 1033, same ids the /api producer uses).
  * GetVote(VoteId)              -> full roll call: Legislation[] (bundled bills, each
    {LegislationId, Description}) + Votes[] (per member {Member.Id, MemberVoted}).
    MemberVoted is a string enum: Yea | Nay | NotVoting | Excused | Unknown.
  * GetLegislationForSession(SessionId) -> all bills' {Id, Description, Caption} in ONE
    call, used as the legislationId -> title index (GetVote carries no title).

Parity with the other producers (so the three files diff cleanly, design §6/§7):
  * Member resolution is ID-ONLY via the id-crosswalk (legisGaGovId -> OCD person id).
    An unresolved id stays unresolved — NEVER district-guessed (that mis-attributes a
    departed member's votes to the seat's successor). Backfill the id instead.
  * Member.Id == 0 is the VACANT-seat/placeholder sentinel — skipped, never tallied.
  * Passage classification is the shared overlay-primary rule (lib/ga_passage.classify):
    a roll call is kept if any bundled (bill, date) matches the Open States passage
    overlay (borrowing OS's authoritative Pass/Fail) OR its caption reads as passage
    (fills OS gaps; Pass/Fail then derived from the tally via derive_result, which
    reproduces OS's rule exactly — see that function); procedural roll calls are
    dropped. (The overlay is a cross-check, NOT a hard dependency — result stands on
    the SOAP tally alone, so OS can be retired.) Attendance
    listings are skipped before the GetVote call; unpublished roll calls (attendance that
    reaches GetVote) fault with RollCallNotPublishedFault and are counted, not fatal.
  * Each kept roll call EXPLODES into one votes_meta record per bundled bill, keyed
    "{voteId}-{legislationId}", all sharing the roll call's members and tally.

Output defaults to assets/data/ga-member-votes.soap.json — PARALLEL to the live file.
Diff it against the Open States and /api outputs before any cutover; never overwrite the
canonical ga-member-votes.json until that validation passes.

Usage:
  python generate_ga_votes_soap.py                 # ALL configured sessions -> parallel file
  python generate_ga_votes_soap.py OUT.json        # explicit output path
  python generate_ga_votes_soap.py --session 2025_26   # one session only
  python generate_ga_votes_soap.py --chamber House     # one chamber
  python generate_ga_votes_soap.py --inspect          # a few roll calls, diagnostics, write nothing
  python generate_ga_votes_soap.py --no-titles        # skip the per-session title index call
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

from lib.atomic_io import write_json_atomic
from lib.ga_passage import classify, load_os_passage_index, normalize_bill
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             legis_session_id, session_name)
from lib.votes_schema import encode_member_votes

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

#: MemberVoted string enum -> option string. Option strings MUST be keys of
#: lib/votes_schema.VOTE_CODES. SOAP gives Yea/Nay/NotVoting/Excused distinctly
#: (richer than the /api 2/3 ambiguity); "Unknown" -> "Other".
VOTE_MAP = {
    "Yea": "Yea",
    "Nay": "Nay",
    "NotVoting": "Not Voting",
    "Excused": "Excused",
    "Unknown": "Other",
}

CHAMBERS      = ["House", "Senate"]
VACANT_ID     = 0                       # Member.Id sentinel for an empty seat
CROSSWALK_FILE = "assets/data/id-crosswalk.json"
OS_VOTES_FILE  = "assets/data/ga-member-votes.json"   # passage overlay / result oracle
DEFAULT_OUTPUT = "assets/data/ga-member-votes.soap.json"


class RollCallNotPublished(Exception):
    """GetVote faulted: this roll call isn't published (attendance / procedural)."""


def derive_result(yea, nay):
    """Pass/Fail from the tally. Open States' `result` field is empirically a SIMPLE
    majority of those voting — `yea > nay` reproduces OS's Pass/Fail on 2503/2503
    (100%) of the biennium's votes, while the GA constitutional-majority rule
    (House 91 / Senate 29 of elected) only matches 98.56% because resolutions and
    procedural motions pass on a present-majority. Matching OS exactly keeps the
    rendered Pass/Fail byte-identical across a cutover; a future "true constitutional
    result" would be a separate, deliberate change. Returns None if the tally is absent."""
    if yea is None or nay is None:
        return None
    return "Pass" if yea > nay else "Fail"


# --------------------------------------------------------------------------- SOAP

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
    """GetVotes -> [{voteId, caption}] for one chamber/session (just what we need to
    enumerate roll calls and skip Attendance before the per-vote GetVote fetch)."""
    inner = "<s:Branch>%s</s:Branch><s:SessionId>%d</s:SessionId>" % (branch, legis_session)
    root = soap_call(VOTES_URL, "GetVotes", inner)
    if root is None:
        return []
    out = []
    for vl in root.findall(".//d:VoteListing", ns):
        vid = _text(vl, "VoteId", int)
        if vid is not None:
            out.append({"voteId": vid, "caption": (_text(vl, "Caption") or "")})
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


# ------------------------------------------------------------------------ crosswalk

def build_crosswalk(path=CROSSWALK_FILE):
    """legisGaGovId(int) -> ocdPersonId, from id-crosswalk.json (the canonical,
    collision- and turnover-proof join — identical to the /api producer's)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    by_legis_id = {}
    for person in data.get("people", []):
        ids = person.get("ids") or {}
        ocd = ids.get("ocdPersonId")
        legis_id = ids.get("legisGaGovId")
        if ocd and legis_id is not None:
            by_legis_id[int(legis_id)] = ocd
    return by_legis_id


# ---------------------------------------------------------------------------- build

def build_session(our_session, by_legis_id, os_index, title_index,
                  chambers=CHAMBERS, sample=None, verbose=True):
    """Fetch one session's roll calls across `chambers`, keep PASSAGE votes (overlay-
    primary), resolve members by id ONLY, and explode each roll call into one record
    per bundled bill. Returns (votes_meta, member_votes, stats)."""
    legis_session = legis_session_id(our_session)
    votes_meta, member_votes = {}, {}
    seen = set()
    stats = Counter()
    unresolved_members = Counter()
    unresolved_names = {}

    for branch in chambers:
        listings = get_vote_listings(legis_session, branch)
        if verbose:
            print("  GetVotes(%s, %d): %d listings" % (branch, legis_session, len(listings)))
        for lst in listings:
            if lst["caption"].strip().lower() == "attendance":
                stats["attendanceSkipped"] += 1
                continue
            vid = lst["voteId"]
            if vid in seen:
                continue
            seen.add(vid)
            try:
                detail = get_vote_detail(vid)
            except RollCallNotPublished:
                stats["unpublished"] += 1
                continue
            except RuntimeError as e:
                print("    vote %d: %s" % (vid, e), file=sys.stderr)
                stats["faults"] += 1
                continue
            if detail is None:
                stats["faults"] += 1
                continue
            caption, date10, legn, rows = detail

            bundled = [l["description"] for l in legn if l["description"]]
            is_passage, _result, source = classify(caption, bundled, date10, os_index)
            if not is_passage:
                stats["droppedNonPassage"] += 1
                continue
            stats["rollCalls"] += 1
            stats["passageByOverlay" if source == "overlay" else "passageByNative"] += 1

            # Resolve members by numeric id ONLY; skip the VACANT sentinel; tally Y/N.
            resolved, yea, nay = [], 0, 0
            for mid, option in rows:
                if mid == VACANT_ID:
                    stats["sentinelRows"] += 1
                    continue
                if option == "Yea":
                    yea += 1
                elif option == "Nay":
                    nay += 1
                ocd = by_legis_id.get(mid)
                if ocd:
                    resolved.append((ocd, option))
                else:
                    stats["unresolvedRows"] += 1
                    unresolved_members[mid] += 1
            stats["resolvedRows"] += len(resolved)

            # EXPLODE: one record per bundled bill, sharing members + tally.
            for entry in legn:
                lid = entry["legislationId"]
                if lid is None:
                    continue
                key = "%d-%d" % (vid, lid)
                if key in votes_meta:
                    continue
                bill = entry["description"] or ""
                votes_meta[key] = {
                    "bill": bill,
                    "billUrl": ("https://www.legis.ga.gov/legislation/%d" % lid),
                    "title": title_index.get(lid, ""),
                    "session": our_session,
                    "motionText": caption,
                    "date": date10,
                    "yea": yea,
                    "nay": nay,
                    # Pass/Fail derived from THIS roll call's tally (derive_result —
                    # reproduces OS's rule exactly). Deliberately NOT the OS overlay:
                    # the overlay indexes on (bill, date) only, so when a bill has two
                    # roll calls the same day both would inherit ONE roll call's result
                    # (67 such mis-assignments observed). The per-roll-call tally is
                    # correct for each, and fully decouples result from OS.
                    "result": derive_result(yea, nay),
                }
                for ocd, option in resolved:
                    member_votes.setdefault(ocd, []).append({"voteId": key, "vote": option})

            if sample is not None and len(seen) >= sample:
                if verbose:
                    print("    --sample cap reached (%d roll calls examined)" % len(seen))
                break
        if sample is not None and len(seen) >= sample:
            break

    stats["unresolvedMembers"] = len(unresolved_members)
    stats["unresolvedGap"] = sorted(
        ({"legisId": mid, "name": unresolved_names.get(mid), "rows": n}
         for mid, n in unresolved_members.items()), key=lambda r: -r["rows"])
    return votes_meta, member_votes, stats


# ----------------------------------------------------------------------------- CLI

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate ga-member-votes.json from the legis.ga.gov SOAP service.")
    p.add_argument("output_file", nargs="?", default=DEFAULT_OUTPUT,
                   help="output path (default: %(default)s)")
    p.add_argument("--session", default=None, metavar="TAG",
                   help="one session tag to run (default: ALL configured sessions). "
                        "Must be configured in lib/ga_sessions.py.")
    p.add_argument("--chamber", choices=["House", "Senate", "both"], default="both")
    p.add_argument("--sample", type=int, default=None, metavar="N",
                   help="cap roll calls examined per session (cheap run)")
    p.add_argument("--inspect", action="store_true",
                   help="fetch a few roll calls, print diagnostics, write nothing")
    p.add_argument("--no-titles", action="store_true", dest="no_titles",
                   help="skip the per-session GetLegislationForSession title index")
    p.add_argument("--no-overlay", action="store_true", dest="no_overlay",
                   help="OS-free cutover mode: classify passage by the native caption "
                        "rule ONLY (lib.ga_passage), without the Open States overlay. "
                        "Default keeps the overlay as a validation cross-check.")
    return p.parse_args(argv)


def main():
    args = parse_args()
    sample = args.sample if args.sample is not None else (5 if args.inspect else None)
    chambers = CHAMBERS if args.chamber == "both" else [args.chamber]

    if args.session:
        if args.session not in all_session_ids():
            print("Error: unknown session '%s'. Configured: %s."
                  % (args.session, ", ".join(all_session_ids())), file=sys.stderr)
            sys.exit(1)
        sessions = [args.session]
    else:
        sessions = list(all_session_ids())
    # Only sessions mapped to a legis numeric id can be sourced from SOAP.
    sessions = [s for s in sessions if legis_session_id(s) is not None]
    if not sessions:
        print("Error: none of the configured sessions have a legis id (lib/ga_sessions.py).",
              file=sys.stderr)
        sys.exit(1)

    by_legis_id = build_crosswalk()
    print("Loaded crosswalk: %d legisGaGovId joins (id-only resolution)" % len(by_legis_id))

    votes_meta, member_votes = {}, {}
    agg = Counter()
    unresolved_gap = {}
    for our_session in sessions:
        legis_session = legis_session_id(our_session)
        if args.no_overlay:
            os_index = {}
            print("Session %s (legis %d): OS overlay DISABLED (--no-overlay) — native "
                  "caption classification only." % (our_session, legis_session))
        else:
            try:
                os_index = load_os_passage_index(OS_VOTES_FILE, our_session)
                print("Session %s (legis %d): OS passage overlay = %d (bill,date) keys"
                      % (our_session, legis_session, len(os_index)))
            except FileNotFoundError:
                os_index = {}
                print("Session %s: no OS votes file — caption-only passage classification."
                      % our_session)
        title_index = {} if args.no_titles else get_title_index(legis_session)
        if title_index:
            print("  title index: %d bills" % len(title_index))

        vm, mv, stats = build_session(our_session, by_legis_id, os_index, title_index,
                                      chambers=chambers, sample=sample)
        votes_meta.update(vm)
        for ocd, entries in mv.items():
            member_votes.setdefault(ocd, []).extend(entries)
        for k, val in stats.items():
            if k in ("unresolvedGap", "unresolvedMembers"):
                continue
            agg[k] += val
        for g in stats.get("unresolvedGap", []):
            unresolved_gap[g["legisId"]] = unresolved_gap.get(g["legisId"], 0) + g["rows"]
        print("  %s: %d roll calls -> %d bill-votes, %d members (%d overlay, %d native, "
              "%d dropped, %d unpublished, %d attendance skipped)"
              % (our_session, stats["rollCalls"], len(vm), len(mv),
                 stats["passageByOverlay"], stats["passageByNative"],
                 stats["droppedNonPassage"], stats["unpublished"],
                 stats["attendanceSkipped"]))

    if args.inspect:
        sk = next(iter(votes_meta), None)
        print("\n=== INSPECTION (nothing written) ===")
        print("roll calls: %d | bill-votes: %d | members: %d"
              % (agg["rollCalls"], len(votes_meta), len(member_votes)))
        print("passage: %d overlay / %d native | dropped non-passage: %d | unpublished: %d"
              % (agg["passageByOverlay"], agg["passageByNative"],
                 agg["droppedNonPassage"], agg["unpublished"]))
        print("resolved rows: %d | unresolved: %d across %d members | sentinel rows: %d"
              % (agg["resolvedRows"], agg["unresolvedRows"],
                 len(unresolved_gap), agg["sentinelRows"]))
        if sk:
            print("sample votes_meta[%s] = %s" % (sk, json.dumps(votes_meta[sk])))
        if unresolved_gap:
            print("UNRESOLVED legis ids (backfill legisGaGovId — never district-guess):")
            for mid, n in sorted(unresolved_gap.items(), key=lambda t: -t[1])[:15]:
                print("  legisId %-6s %d rows" % (mid, n))
        return

    if not votes_meta:
        print("Error: collected zero roll calls — refusing to write.", file=sys.stderr)
        sys.exit(1)
    if not member_votes:
        print("Error: roll calls found but no member rows resolved — check the crosswalk.",
              file=sys.stderr)
        sys.exit(1)

    member_votes_compact, vote_id_index = encode_member_votes(
        member_votes, list(votes_meta.keys()))

    by_session = {}
    for v in votes_meta.values():
        sid = v.get("session")
        by_session[sid] = by_session.get(sid, 0) + 1

    output = {
        "metadata": {
            "schemaVersion": 2,
            "generatedAt": datetime.now().isoformat(),
            "biennium": BIENNIUM,
            "sessions": [{"id": sid, "name": session_name(sid),
                          "voteCount": by_session.get(sid, 0)}
                         for sid in all_session_ids()],
            "activeSession": ACTIVE_SESSION,
            "activeSessionName": session_name(ACTIVE_SESSION),
            "sessionsFetched": sessions,
            "source": "legis.ga.gov SOAP (webservices.legis.ga.gov/GGAServices)",
            "totalVotes": len(votes_meta),
            "rollCalls": agg["rollCalls"],
            "billVotes": len(votes_meta),
            "resolvedRows": agg["resolvedRows"],
            "unresolvedRows": agg["unresolvedRows"],
            "unresolvedMembers": len(unresolved_gap),
            "sentinelRowsDropped": agg["sentinelRows"],
            "attendanceSkipped": agg["attendanceSkipped"],
            "rollCallsUnpublished": agg["unpublished"],
            # Passage-only (overlay-primary, lib/ga_passage), same rule as the /api producer.
            "passageClassified": True,
            "passageByOverlay": agg["passageByOverlay"],
            "passageByNative": agg["passageByNative"],
            "droppedNonPassage": agg["droppedNonPassage"],
            "passageOverlaySource": None if args.no_overlay else OS_VOTES_FILE,
        },
        "voteIds": vote_id_index,
        "votes": votes_meta,
        "memberVotes": member_votes_compact,
    }

    write_json_atomic(args.output_file, output, separators=(",", ":"))
    size_kb = os.path.getsize(args.output_file) // 1024
    print("\nDone. %d passage roll calls -> %d bill-votes · %d members · %d KB -> %s"
          % (agg["rollCalls"], len(votes_meta), len(member_votes), size_kb, args.output_file))
    print("  passage: %d via OS overlay, %d via caption; %d non-passage dropped, "
          "%d unpublished, %d attendance skipped, %d sentinel rows dropped"
          % (agg["passageByOverlay"], agg["passageByNative"], agg["droppedNonPassage"],
             agg["unpublished"], agg["attendanceSkipped"], agg["sentinelRows"]))
    if unresolved_gap:
        print("  %d unresolved legis ids (backfill legisGaGovId — never district-guess):"
              % len(unresolved_gap))
        for mid, n in sorted(unresolved_gap.items(), key=lambda t: -t[1])[:15]:
            print("    legisId %-6s %d rows" % (mid, n))


if __name__ == "__main__":
    main()
