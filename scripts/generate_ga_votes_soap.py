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
canonical ga-member-votes.json until that validation passes. (update-ga-votes.yml passes
the canonical path explicitly, along with --no-overlay.)

Incremental model: only the ACTIVE session is fetched live; the closed sessions of the
biennium are merged forward from the existing output file. Closed sessions cannot change,
and re-fetching them dominated the run — the 2025-2026 regular session is 1,497 of 1,522
roll calls, so a full sweep spent 98% of its GetVote calls re-downloading immutable
records. Fetch cost drops to ~25 calls. This is the model lib/ga_sessions.py documents
(ACTIVE_SESSION / preserved_session_ids); the bills producer does the same.

The merge is NOT a concatenation, because `memberVotes` is keyed by PERSON, not session,
so one member's row spans both sessions:
  * `votes` is preserved-first, so every preserved voteId keeps its index position and
    every preserved member row stays byte-identical (lib/votes_schema.encode_member_votes
    takes `base_vote_ids` for exactly this).
  * the member map is a UNION with the PRESERVED layer as its base — 12 of 246 members
    have votes only in the closed session (they left mid-biennium) and cannot appear in
    an active-session fetch, so building up from the fetch would drop their entire
    history. scripts/test_votes_incremental.py pins this and the index invariants.

Preservation is a hard requirement, not a fallback: if the prior file cannot be read, is
not the compact schema, or is missing a session it claims to carry, the run ABORTS and
tells you to re-run with --full-refresh.

What incremental means for provenance: metadata counters from `statsScope` onward describe
only THIS RUN'S FETCH (`sessionsFetched`), so they drop sharply on an incremental run —
that is preservation working, not data loss. Whole-file figures are `totalVotes`,
`rollCallsTotal` and `sessions[].voteCount`. Two derivations also freeze for closed
sessions, which is the main reason to keep the full-refresh hatch: crosswalk backfills
(an unresolved legisGaGovId resolved later) and result derivation (the two-thirds
constitutional-amendment rule, read from ga-bills.json) no longer reach them.

A biennium rollover needs NO full refresh: SESSION_NAMES then holds only the new biennium,
so nothing is marked for preservation and the run is already a single-session fetch.

Usage:
  python generate_ga_votes_soap.py                 # active session + preserved -> parallel file
  python generate_ga_votes_soap.py OUT.json        # explicit output path
  python generate_ga_votes_soap.py --full-refresh  # re-fetch ALL sessions (slow, ~1.5k calls)
  python generate_ga_votes_soap.py --session 2025_26   # re-fetch one, preserve the rest
  python generate_ga_votes_soap.py --chamber House     # one chamber (partial: preserves nothing)
  python generate_ga_votes_soap.py --inspect          # a few roll calls, diagnostics, write nothing
  python generate_ga_votes_soap.py --no-titles        # skip the per-session title index call
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.ga_passage import classify, load_os_passage_index, normalize_bill
from lib.ga_vote_rules import is_state_constitutional_amendment, vote_passed
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             legis_session_id, session_name, preserved_session_ids)
from lib.ga_soap import (CHAMBER_NAMES, CHAMBERS, VACANT_ID, RollCallNotPublished,
                         get_title_index, get_vote_detail, get_vote_listings)
from lib.votes_schema import (encode_member_votes, merge_member_votes,
                              preserved_layer)


CROSSWALK_FILE = "assets/data/id-crosswalk.json"
BILLS_FILE     = "assets/data/ga-bills.json"           # abstracts -> constitutional-amendment ids
OS_VOTES_FILE  = "assets/data/ga-member-votes.json"   # passage overlay / result oracle
DEFAULT_OUTPUT = "assets/data/ga-member-votes.soap.json"



def derive_result(yea, nay, chamber=None, constitutional_amendment=False):
    """Pass/Fail from the tally (see lib/ga_vote_rules.py for the rule).

    A simple majority of those voting (`yea > nay`) — which reproduced Open States'
    `result` on all 2503/2503 of the biennium's votes at the SOAP cutover — except for
    a resolution proposing a Georgia constitutional amendment, which needs two-thirds
    of the chamber's elected members (House 120 / Senate 38). Those had been labelled
    Pass on a bare majority (HR 1114 at 99-73; SR 838, 875 and 668, which the Senate
    lost), so this now takes the chamber and an amendment flag. Returns None if the
    tally is absent."""
    passed = vote_passed(yea, nay, chamber, constitutional_amendment)
    if passed is None:
        return None
    return "Pass" if passed else "Fail"


def load_amendment_ids(bills_file):
    """legislationIds of resolutions proposing a Georgia constitutional amendment, read
    from the committed ga-bills.json (whose abstracts this script does not fetch).
    Empty set — and a warning — if the file is absent, in which case those votes fall
    back to the simple-majority rule until the next bills run."""
    try:
        with open(bills_file, encoding="utf-8") as f:
            bills = json.load(f).get("bills", [])
    except (OSError, ValueError) as e:
        print("  WARNING: could not read %s (%s); constitutional-amendment votes will use "
              "the simple-majority rule" % (bills_file, e), file=sys.stderr)
        return set()
    return {b["legislationId"] for b in bills
            if b.get("legislationId") is not None
            and b.get("billType") == "resolution"
            and is_state_constitutional_amendment(b.get("abstract"))}


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
                  chambers=CHAMBERS, sample=None, verbose=True, amendment_ids=frozenset()):
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
            resolved, yea, nay, vacant = [], 0, 0, 0
            for mid, option in rows:
                if mid == VACANT_ID:
                    stats["sentinelRows"] += 1
                    vacant += 1
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

            # The GetVotes listing carries the chamber's OFFICIAL tally, produced
            # independently of the per-member rows GetVote returns. Comparing the two
            # is a free check that we read every row: a mismatch means the rows we
            # counted are not the roll call the clerk recorded. Counted, not fatal —
            # the tallies we publish stay the row-derived ones, so a mismatch is a
            # signal to investigate rather than a reason to drop a vote.
            if lst.get("yea") is not None and (lst["yea"], lst["nay"]) != (yea, nay):
                stats["listingTallyMismatch"] += 1
                print("    vote %d: listing says %s-%s, member rows give %d-%d"
                      % (vid, lst["yea"], lst["nay"], yea, nay), file=sys.stderr)

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
                    # The chamber that actually held this roll call, straight from the
                    # GetVotes(Branch, ...) call that produced the listing. Readers used to
                    # infer it from motionText, which cannot be done reliably: an "Agree to
                    # Senate Substitute" is a HOUSE vote (the House agreeing to the Senate's
                    # product), so the chamber named in the motion is the OTHER one. Spelled
                    # with ga-members.json's chamber vocabulary so a reader can compare it
                    # to member.chamber directly.
                    "chamber": CHAMBER_NAMES[branch],
                    # The chamber's own roll-call number for the session, and the time of
                    # day, both straight off the GetVotes listing. Neither can be recovered
                    # later: `number` counts every roll call the chamber held (312 of which
                    # this producer drops as non-passage), and voteId is not a sequence —
                    # it tracks record creation and inverts within a day. They are what
                    # orders two passage votes on one bill on one day, which decides which
                    # one is the operative final vote (89 such groups in 2025-26).
                    **({"rollNumber": lst["number"]} if lst.get("number") else {}),
                    **({"time": lst["time"]} if lst.get("time") else {}),
                    # Chamber-level non-voting counts from the same listing, which the
                    # per-member rows do not total on their own.
                    **({"excused": lst["excused"]} if lst.get("excused") else {}),
                    **({"notVoting": lst["notVoting"]} if lst.get("notVoting") else {}),
                    "date": date10,
                    "yea": yea,
                    "nay": nay,
                    # Empty seats on this roll call (the VACANT sentinel rows dropped
                    # above), omitted when zero. The official tallies in ga-bills.json
                    # count every seat (House always 180, Senate always 56), so without
                    # this the party-tally enrichment reads each vacancy as a member it
                    # failed to attribute and reports coverage < 1 on a complete roster.
                    **({"vacant": vacant} if vacant else {}),
                    # Pass/Fail derived from THIS roll call's tally (derive_result —
                    # reproduces OS's rule exactly). Deliberately NOT the OS overlay:
                    # the overlay indexes on (bill, date) only, so when a bill has two
                    # roll calls the same day both would inherit ONE roll call's result
                    # (67 such mis-assignments observed). The per-roll-call tally is
                    # correct for each, and fully decouples result from OS.
                    "result": derive_result(yea, nay, branch, lid in amendment_ids),
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
    p.add_argument("--full-refresh", action="store_true",
                   default=os.environ.get("FULL_REFRESH") == "1",
                   help="re-fetch EVERY configured session instead of preserving the "
                        "closed ones (slow: ~1.5k GetVote calls vs ~25; also settable "
                        "as FULL_REFRESH=1)")
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
    elif args.full_refresh:
        sessions = list(all_session_ids())
    else:
        sessions = [ACTIVE_SESSION]
    # Only sessions mapped to a legis numeric id can be sourced from SOAP.
    sessions = [s for s in sessions if legis_session_id(s) is not None]
    if not sessions:
        print("Error: none of the configured sessions have a legis id (lib/ga_sessions.py).",
              file=sys.stderr)
        sys.exit(1)

    if args.session or args.full_refresh:
        preserve = [s for s in all_session_ids() if s not in sessions]
    else:
        preserve = preserved_session_ids()   # the canonical closed-session set

    # A partial fetch must not be merged with a complete frozen layer: the result would
    # look whole while missing most of the active session, and the workflow's
    # `votes >= 1000` floor is cleared by the preserved layer alone. Sampling and a
    # single-chamber run stay what they were — obviously-partial diagnostics.
    partial = bool(sample) or chambers != CHAMBERS
    if partial and preserve and not args.inspect:
        print("Warning: --sample/--chamber writes a PARTIAL file (closed sessions not "
              "preserved). Use --inspect to avoid writing at all.", file=sys.stderr)
        preserve = []

    # Carry the closed sessions forward from the existing file. Fatal if that fails:
    # publishing the active session alone would silently drop thousands of roll calls
    # and every vote of the members who have since left.
    preserved_votes, preserved_mv, prior_counts = {}, {}, {}
    if preserve and not args.inspect:
        try:
            with open(args.output_file, encoding="utf-8") as fh:
                prior = json.load(fh)
            preserved_votes, preserved_mv = preserved_layer(prior, preserve)
            prior_counts = {row.get("id"): row.get("voteCount")
                            for row in ((prior.get("metadata") or {}).get("sessions") or [])
                            if row.get("id") in set(preserve)}
        except (OSError, ValueError) as exc:
            print("Error: cannot preserve closed sessions (%s) from %s: %s\n"
                  "       Re-run with --full-refresh to rebuild every session from SOAP."
                  % (", ".join(preserve), args.output_file, exc), file=sys.stderr)
            sys.exit(1)
        missing = [sid for sid in preserve
                   if not any((r or {}).get("session") == sid
                              for r in preserved_votes.values())]
        if missing:
            print("Error: %s carries no votes for %s — refusing to publish a file that "
                  "would silently drop them.\n"
                  "       Re-run with --full-refresh to rebuild every session from SOAP."
                  % (args.output_file, ", ".join(missing)), file=sys.stderr)
            sys.exit(1)
        print("Preserving %d bill-votes and %d member records from %d closed session(s): %s"
              % (len(preserved_votes), len(preserved_mv), len(preserve), ", ".join(preserve)))

    by_legis_id = build_crosswalk()
    print("Loaded crosswalk: %d legisGaGovId joins (id-only resolution)" % len(by_legis_id))

    amendment_ids = load_amendment_ids(BILLS_FILE)
    print("Constitutional-amendment resolutions (2/3 rule): %d" % len(amendment_ids))

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
                                      chambers=chambers, sample=sample,
                                      amendment_ids=amendment_ids)
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

    fetched_votes, fetched_members = len(votes_meta), len(member_votes)

    # Merge the frozen layer UNDER the fresh fetch. Preserved first, so every preserved
    # voteId keeps its index and every preserved member row stays byte-identical; and
    # preserved is the BASE of the member union, so a member who left mid-biennium (and
    # so cannot appear in an active-session fetch) keeps their whole history.
    # See scripts/test_votes_incremental.py for the invariants this relies on.
    if preserved_votes:
        votes_meta = {**preserved_votes, **votes_meta}
        member_votes = merge_member_votes(preserved_mv, member_votes)
        shortfall = {sid: prior for sid, prior in prior_counts.items()
                     if prior and sum(1 for r in votes_meta.values()
                                      if (r or {}).get("session") == sid) < prior}
        if shortfall:
            print("Error: preserved fewer bill-votes than %s claims for %s — refusing to write."
                  % (args.output_file,
                     ", ".join("%s (expected %d)" % (k, v) for k, v in shortfall.items())),
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
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "biennium": BIENNIUM,
            "sessions": [{"id": sid, "name": session_name(sid),
                          "voteCount": by_session.get(sid, 0)}
                         for sid in all_session_ids()],
            "activeSession": ACTIVE_SESSION,
            "activeSessionName": session_name(ACTIVE_SESSION),
            "sessionsFetched": sessions,
            "sessionsPreserved": preserve,
            "updateMode": "full" if not preserve else "incremental",
            "source": "legis.ga.gov SOAP (webservices.legis.ga.gov/GGAServices)",
            "totalVotes": len(votes_meta),
            # Roll calls across the WHOLE file, recovered from the merged records so the
            # figure stays comparable run to run; `rollCalls` below counts only this
            # run's fetch, like every other counter in the statsScope block.
            "rollCallsTotal": len({(r.get("session"), r.get("chamber"), r.get("date"),
                                    r.get("rollNumber")) for r in votes_meta.values()}),
            # Everything from here to passageOverlaySource describes THIS RUN'S FETCH,
            # not the file: on an incremental run they cover `sessionsFetched` only, so
            # a drop against the previous run is the preservation working, not data loss.
            "statsScope": "sessionsFetched",
            "rollCalls": agg["rollCalls"],
            "billVotes": fetched_votes,
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
    print("  %d bill-votes / %d members fetched (%s) · %d / %d preserved (%s)"
          % (fetched_votes, fetched_members, ", ".join(sessions),
             len(votes_meta) - fetched_votes, len(member_votes) - fetched_members,
             ", ".join(preserve) or "none"))
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
