#!/usr/bin/env python3
"""Generate ga-member-votes.json from legis.ga.gov directly (official source).

This is the official-source replacement for generate_ga_votes_data.py (Open
States). Both write the SAME compact v2 schema (see lib/votes_schema.py), so
nothing downstream changes — only the producer of the per-member vote rows. The
win: legis.ga.gov keys every roll call by the legislature's own numeric member id
(`member.id` == `legisGaGovId`), so the surname collisions Open States' person
matcher introduces (the two Clarks) are resolved by construction.

Status: SCAFFOLD. The control flow, join, and schema output are complete and the
pure helpers are unit-testable offline.

  [DONE] memberVoted code -> option map (MEMBER_VOTED below) CONFIRMED offline
     2026-10-02 by cross-referencing against the existing Open States 2026_ss
     data: 0=Yea, 1=Nay (131 members, zero disagreement). See MEMBER_VOTED.

  [DONE] Populated legislation_detail `votes[]` shape CONFIRMED 2026-10-02 from a
     live row: `{id, number, caption, date, name, yea, nay, notVoting, excused,
     isRollCall}`. So motionText=caption, date=date, yea/nay are authoritative; and
     there is NO result field (pass/fail comes from the passage overlay).

  [DONE] Passage classification (lib/ga_passage.classify, overlay-primary). The
     producer now KEEPS passage roll calls and drops procedural ones: a roll call
     is passage if any bundled bill's (bill, date) matches the Open States passage
     overlay (borrowing OS's result) or its caption reads as passage (fills OS
     gaps). Calibrated on 2025_26 (2026-10-03): the overlay matched 243/300 and the
     `isRollCall` field proved a red herring (always False), so classification is
     caption/overlay based. `--classify-report` remains for re-calibration.

Auth: needs a legis.ga.gov token. In CI/local set LEGIS_GA_CLIENT_KEY (the public
SPA client key) to auto-mint+refresh; for offline testing inject LEGIS_GA_TOKEN.
Live minting is blocked inside the Claude Code agent sandbox (credential
guardrail) — run this in CI or locally, and unit-test the parsing in-agent.

Usage:
  python generate_ga_votes_from_legis.py            # active session -> ga-member-votes.legis.json
  python generate_ga_votes_from_legis.py OUT.json   # explicit output path
  python generate_ga_votes_from_legis.py --session 2025_26   # a specific session (calibration)
  python generate_ga_votes_from_legis.py --list-sessions     # show configured + live sessions
  python generate_ga_votes_from_legis.py --inspect  # fetch ~5 roll calls, print diagnostics,
                                                    # write NOTHING
  python generate_ga_votes_from_legis.py --classify-report --session 2025_26 --sample 300
                                                    # calibrate passage classification vs
                                                    # Open States (precision/recall), write NOTHING
  python generate_ga_votes_from_legis.py --sample 50  # cap roll calls (cheap run)
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

from lib.atomic_io import write_json_atomic
from lib.legis_ga import CHAMBER, LegisGaClient, vote_ids
from lib.ga_passage import (classify, load_os_passage_index, native_is_passage,
                            normalize_bill)
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             legis_session_id, legis_session_library,
                             session_name)
from lib.votes_schema import encode_member_votes

CROSSWALK_FILE = "assets/data/id-crosswalk.json"
# The live Open States votes file — used as the passage overlay / calibration oracle.
OS_VOTES_FILE = "assets/data/ga-member-votes.json"
# Parallel output by default — the migration plan (design §7) diffs this against
# the live Open States file before any cutover. Never overwrite the canonical file
# until that validation passes.
DEFAULT_OUTPUT = "assets/data/ga-member-votes.legis.json"

#: The legis.ga.gov session-id mapping lives in lib/ga_sessions.py
#: (LEGIS_SESSIONS / legis_session_id) — one place to edit when a session rolls.

#: legis.ga.gov `memberVoted` code -> option string (option strings must be keys
#: of lib/votes_schema.VOTE_CODES).
#:
#: Yea/Nay CONFIRMED 2026-10-02 by cross-referencing legis Vote/detail 26674
#: against the existing Open States 2026_ss roll calls: across 131 overlapping
#: members, code 0 was Yea and code 1 was Nay with ZERO disagreement (0=Yea/1=Nay
#: held perfectly on HB 7/8/9/65/66/67, all party-line special-session votes).
#: Codes 2 and 3 are non-Yea/Nay (Open States records both as "Other"): code 3 is
#: the Speaker's abstention (Burns -> "Other" throughout), code 2 is members
#: absent/excused on a given roll call. The exact Excused-vs-Not-Voting label for
#: 2/3 can't be split from OS and does not affect tallies (only Yea/Nay count).
MEMBER_VOTED = {
    0: "Yea",
    1: "Nay",
    2: "Excused",
    3: "Not Voting",
}
#: True = the Yea/Nay axis is confirmed (see above). The 2/3 labels remain a
#: best-effort split of non-voting options, which no downstream tally depends on.
MEMBER_VOTED_CONFIRMED = True


def build_crosswalk(path=CROSSWALK_FILE):
    """Return (by_legis_id, by_chamber_district, chamber_by_ocd).

    by_legis_id[int]            -> ocdPersonId   (primary, collision-proof join)
    by_chamber_district[(c,d)]  -> ocdPersonId   (fallback for members whose
                                   legisGaGovId is still null in the crosswalk;
                                   `c` is the chamber STRING, `d` the int district)
    chamber_by_ocd[ocd]         -> chamber STRING (to derive a roll call's chamber
                                   from its id-resolved members)
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    by_legis_id, by_chamber_district, chamber_by_ocd = {}, {}, {}
    for person in data.get("people", []):
        ocd = (person.get("ids") or {}).get("ocdPersonId")
        if not ocd:
            continue
        legis_id = (person.get("ids") or {}).get("legisGaGovId")
        if legis_id is not None:
            by_legis_id[int(legis_id)] = ocd
        role = person.get("role") or {}
        chamber, district = role.get("chamber"), role.get("district")
        if chamber:
            chamber_by_ocd[ocd] = chamber
            if district is not None:
                by_chamber_district.setdefault((chamber, int(district)), ocd)
    return by_legis_id, by_chamber_district, chamber_by_ocd


#: "ADESANYA, 43RD" / "CLARK, 100TH" -> district number.
_NAME_DISTRICT = re.compile(r",\s*(\d+)\s*(?:ST|ND|RD|TH)\s*$", re.IGNORECASE)


def resolve_member(member, by_legis_id, by_chamber_district, chamber=None):
    """Resolve a Vote/detail `member` object to an OCD person id.

    Primary: numeric member id (== legisGaGovId) — never ambiguous. Fallback (for
    a freshman whose legisGaGovId is still null in the crosswalk): parse the
    district out of the "SURNAME, 43RD" name string and match on (chamber,
    district). The fallback only fires when the roll call's chamber is known;
    returns (ocd_id_or_None, how) where how is 'id' | 'district' | 'unresolved'.
    """
    mid = member.get("id")
    if mid is not None and int(mid) in by_legis_id:
        return by_legis_id[int(mid)], "id"
    if chamber:
        m = _NAME_DISTRICT.search(member.get("name") or "")
        if m:
            ocd = by_chamber_district.get((chamber, int(m.group(1))))
            if ocd:
                return ocd, "district"
    return None, "unresolved"


def extract_vote_meta(vote_detail, vote_row, our_session, legislation_detail):
    """Assemble a votes_meta record for one roll call.

    Pulls per-vote metadata (date, motion, totals) from the legislation_detail
    `votes[]` item (`vote_row`). `result` is not in legis and is left None (the
    Open States passage overlay supplies Pass/Fail — design §5.3).

    `bill` and `title` must describe the SAME bill: a roll call can BUNDLE many
    bills (Vote/detail `legislation[]` lists them all — common on local-calendar
    votes), so we pick the bundled entry matching the bill we iterated to reach
    this vote (`legislation_detail.id`), not just `legislation[0]`. That keeps the
    `bill` identifier paired with its `title`.
    """
    row = vote_row or {}
    legn = vote_detail.get("legislation") or []
    this_id = (legislation_detail or {}).get("id")
    entry = (next((l for l in legn if l.get("legislationId") == this_id), None)
             or (legn[0] if legn else {}))
    desc = entry.get("description") or ""
    legislation_id = entry.get("legislationId") or this_id
    return {
        "bill": desc,
        "billUrl": ("https://www.legis.ga.gov/legislation/%s" % legislation_id
                    if legislation_id else None),
        "title": (legislation_detail or {}).get("title") or "",
        "session": our_session,
        "motionText": (row.get("caption") or row.get("motion")
                       or row.get("description") or "").strip(),
        "date": (row.get("date") or row.get("voteDate") or "")[:10] or None,
        # Authoritative tallies straight from the votes[] row (keys confirmed from a
        # live sample: `yea`/`nay`, alongside `notVoting`/`excused`). May be None on
        # a malformed row -> filled from the computed count in build().
        "yea": row.get("yea"),
        "nay": row.get("nay"),
        # legis.ga.gov votes[] carries NO pass/fail field (confirmed from the raw
        # row: yea/nay/notVoting/excused/isRollCall, no result). Left None here;
        # authoritative Pass/Fail is supplied by the Open States passage overlay at
        # cutover (design §5.3), which is where result belongs anyway.
        "result": None,
    }


def build(client, our_session, by_legis_id, by_chamber_district, chamber_by_ocd,
          os_index, verbose=True, sample=None):
    """Walk the active session's bills -> details -> roll calls, keeping the PASSAGE
    votes (design §5.3, overlay-primary) and resolving each per-member row to an OCD
    id. Returns (votes_meta, member_votes, stats).

    `os_index` is the Open States passage overlay (lib.ga_passage.load_os_passage_index):
    a roll call is kept if it matches the overlay (borrowing OS's result) or its
    caption reads as passage; procedural roll calls are dropped. Pass an empty dict
    to fall back to caption-only (native) classification.

    `sample` caps the number of roll calls EXAMINED (used by --sample/--inspect to
    make a run cheap). The raw `memberVoted` code distribution and a few sample
    resolutions are accumulated into stats so the code->option map can be re-checked.
    """
    legis_session = legis_session_id(our_session)
    votes_meta, member_votes = {}, {}
    seen_votes = set()
    resolved_rows = district_rows = unresolved_rows = bills_with_votes = 0
    passage_overlay = passage_native = dropped_non_passage = 0
    code_dist = Counter()        # raw memberVoted code -> count, across all rows
    code_samples = []            # a few (name, code) pairs for eyeballing the map
    sample_vote_row = None       # first raw legislation.votes[] item (to learn its keys)
    isrollcall_dist = Counter()  # votes[].isRollCall value -> count (passage signal, #3)

    # Index legislation_detail votes[] rows by vote id so extract_vote_meta can
    # reach the per-vote metadata that Vote/detail itself does not carry.
    for i, bill in enumerate(client.iter_legislation(legis_session), 1):
        legislation_id = bill.get("legislationId")
        if legislation_id is None:
            continue
        detail = client.legislation_detail(legislation_id)
        vids = vote_ids(detail)
        if not detail or not vids:
            continue
        bills_with_votes += 1
        meta_rows = {}
        for r in (detail.get("votes") or []):
            if isinstance(r, dict):
                if sample_vote_row is None:
                    sample_vote_row = r
                rid = r.get("voteId") or r.get("id") or r.get("voteNumber")
                if rid is not None:
                    meta_rows[rid] = r

        for vid in vids:
            # `vid` stays raw for the API call + meta_rows lookup; `key` is the
            # canonical STRING id used for every stored key (votes_meta, member
            # entries, seen set) so the compact index never sees int/str dupes.
            key = str(vid)
            if key in seen_votes:
                continue
            seen_votes.add(key)
            vote = client.vote_detail(vid)
            if not vote:
                continue
            meta_row = meta_rows.get(vid)
            isrollcall_dist[(meta_row or {}).get("isRollCall")] += 1
            meta = extract_vote_meta(vote, meta_row, our_session, detail)

            # Passage classification (overlay-primary, design §5.3). Classify from
            # the caption + ALL bundled bills (Vote/detail legislation[]) BEFORE
            # resolving members, so procedural roll calls cost nothing extra.
            bundled = [l.get("description") for l in (vote.get("legislation") or [])
                       if l.get("description")]
            is_passage, result, source = classify(
                meta["motionText"], bundled, meta["date"], os_index)
            if not is_passage:
                dropped_non_passage += 1
                continue
            if result is not None:
                meta["result"] = result
            if source == "overlay":
                passage_overlay += 1
            else:
                passage_native += 1
            rows = vote.get("votes") or []

            # Pass 1 — resolve by numeric id (collision-proof) and tally the
            # chambers of the resolved members. A roll call is single-chamber, so
            # that majority IS this vote's chamber; Vote/detail exposes no chamber
            # field of its own (vote.get("chamber") is only a last-ditch fallback).
            resolved = []           # (ocd, option) to record
            pending = []            # (member, option) unresolved by id
            chamber_tally = Counter()
            yea = nay = 0
            for pv in rows:
                member = pv.get("member") or {}
                code = pv.get("memberVoted")
                code_dist[code] += 1
                if len(code_samples) < 24:
                    code_samples.append((member.get("name"), code))
                option = MEMBER_VOTED.get(code, "Other")
                if option == "Yea":
                    yea += 1
                elif option == "Nay":
                    nay += 1
                mid = member.get("id")
                ocd = by_legis_id.get(int(mid)) if mid is not None else None
                if ocd:
                    resolved.append((ocd, option))
                    ch = chamber_by_ocd.get(ocd)
                    if ch:
                        chamber_tally[ch] += 1
                else:
                    pending.append((member, option))

            roll_chamber = (chamber_tally.most_common(1)[0][0]
                            if chamber_tally else CHAMBER.get(vote.get("chamber")))

            # Pass 2 — resolve the rest (freshmen whose legisGaGovId is still null
            # in the crosswalk) by (chamber, district) parsed from the name string.
            for member, option in pending:
                ocd, how = resolve_member(member, by_legis_id, by_chamber_district,
                                          chamber=roll_chamber)
                if ocd:
                    resolved.append((ocd, option))
                    if how == "district":
                        district_rows += 1
                else:
                    unresolved_rows += 1

            for ocd, option in resolved:
                member_votes.setdefault(ocd, []).append({"voteId": key, "vote": option})
            resolved_rows += len(resolved)

            # Prefer legis's own tally; fall back to the computed count.
            if meta.get("yea") is None:
                meta["yea"] = yea
            if meta.get("nay") is None:
                meta["nay"] = nay
            votes_meta[key] = meta

        if verbose and i % 200 == 0:
            print("  scanned %d bills — %d with roll calls, %d votes, %d members"
                  % (i, bills_with_votes, len(votes_meta), len(member_votes)))
        if sample is not None and len(seen_votes) >= sample:
            print("  --sample limit reached (%d roll calls)" % len(seen_votes))
            break

    stats = {
        "billsWithVotes": bills_with_votes,
        "resolvedRows": resolved_rows,
        "districtFallbackRows": district_rows,
        "unresolvedRows": unresolved_rows,
        "passageByOverlay": passage_overlay,
        "passageByNative": passage_native,
        "droppedNonPassage": dropped_non_passage,
        "codeDistribution": dict(code_dist),
        "codeSamples": code_samples,
        "sampleVoteRow": sample_vote_row,
        "isRollCallDistribution": {str(k): v for k, v in isrollcall_dist.items()},
    }
    return votes_meta, member_votes, stats


def classify_report(client, our_session, os_path=OS_VOTES_FILE, sample=None):
    """Calibrate passage classification for a session (design §5.3).

    Walks the session's roll calls (no per-member fetch needed for the metadata),
    pulls each roll call's bundled bills from Vote/detail, then cross-tabs two
    passage signals against the authoritative Open States passage set:
      * OS overlay  — any (bill, date) of the roll call is in the OS passage index.
      * native rule — isRollCall + caption (lib/ga_passage.native_is_passage).
    Prints precision/recall of the native rule, the isRollCall split, and the
    caption breakdown so the rule (and the overlay match) can be tightened from
    real data. Writes nothing.
    """
    from collections import Counter

    os_index = load_os_passage_index(os_path, our_session)
    print("OS passage index (%s): %d (bill,date) keys" % (our_session, len(os_index)))

    legis_session = legis_session_id(our_session)
    # Pass 1 — unique roll calls + their votes[] metadata (caption/date/isRollCall).
    rollcalls = {}
    for bill in client.iter_legislation(legis_session):
        lid = bill.get("legislationId")
        if lid is None:
            continue
        detail = client.legislation_detail(lid)
        for r in ((detail or {}).get("votes") or []):
            if not isinstance(r, dict):
                continue
            vid = r.get("id") or r.get("voteId")
            if vid is None or vid in rollcalls:
                continue
            rollcalls[vid] = {
                "caption": (r.get("caption") or "").strip(),
                "date": (r.get("date") or "")[:10],
                "isRollCall": bool(r.get("isRollCall")),
                "yea": r.get("yea"), "nay": r.get("nay"),
            }
            if sample is not None and len(rollcalls) >= sample:
                break
        if sample is not None and len(rollcalls) >= sample:
            break
    print("legis roll calls collected: %d%s"
          % (len(rollcalls), " (--sample cap)" if sample else ""))

    # Pass 2 — bundled bills per roll call (Vote/detail legislation[]), then label.
    for vid, rc in rollcalls.items():
        vd = client.vote_detail(vid)
        rc["bills"] = [l.get("description") for l in ((vd or {}).get("legislation") or [])
                       if l.get("description")]
        rc["os_passage"] = any((normalize_bill(b), rc["date"]) in os_index
                               for b in rc["bills"])
        rc["native"] = native_is_passage(rc["caption"])

    # --- report ---
    tp = fp = fn = tn = 0
    for rc in rollcalls.values():
        o, n = rc["os_passage"], rc["native"]
        tp += o and n; fp += n and not o; fn += o and not n; tn += not o and not n
    os_pass = sum(1 for rc in rollcalls.values() if rc["os_passage"])
    print("\n=== PASSAGE CALIBRATION (%s) ===" % our_session)
    print("roll calls: %d | OS-overlay passage: %d | native passage: %d"
          % (len(rollcalls), os_pass, tp + fp))
    print("native vs OS overlay:  TP=%d FP=%d FN=%d TN=%d" % (tp, fp, fn, tn))
    if tp + fp:
        print("  native precision: %.1f%%" % (100.0 * tp / (tp + fp)))
    if tp + fn:
        print("  native recall:    %.1f%%" % (100.0 * tp / (tp + fn)))

    irc = Counter((rc["isRollCall"], rc["os_passage"]) for rc in rollcalls.values())
    print("\nisRollCall x OS-passage (isRollCall, isPassage) -> count:")
    for k in sorted(irc, key=lambda t: (not t[0], not t[1])):
        print("  %s -> %d" % (k, irc[k]))

    print("\ncaptions on OS-passage roll calls:")
    for cap, c in Counter(rc["caption"] for rc in rollcalls.values()
                          if rc["os_passage"]).most_common(12):
        print("  %4d  %r" % (c, cap))
    print("captions on NON-OS-passage roll calls:")
    for cap, c in Counter(rc["caption"] for rc in rollcalls.values()
                          if not rc["os_passage"]).most_common(12):
        print("  %4d  %r" % (c, cap))

    legis_keys = {(normalize_bill(b), rc["date"])
                  for rc in rollcalls.values() for b in rc["bills"]}
    os_only = set(os_index) - legis_keys
    print("\nOS-passage (bill,date) not matched by any legis roll call: %d%s"
          % (len(os_only), " (inflated by --sample cap)" if sample else ""))
    for k in sorted(os_only)[:10]:
        print("   ", k)


def parse_args(argv=None):
    """CLI args. argparse (not hand-rolled) so `--sample N OUT` parses correctly —
    a bare value after --sample must not be mistaken for the positional output."""
    p = argparse.ArgumentParser(
        description="Generate ga-member-votes.json from legis.ga.gov (official source).")
    p.add_argument("output_file", nargs="?", default=DEFAULT_OUTPUT,
                   help="output path (default: %(default)s)")
    p.add_argument("--session", default=None, metavar="TAG",
                   help="session tag to run (default: the active session, %s). Must "
                        "be a session configured in lib/ga_sessions.py." % ACTIVE_SESSION)
    p.add_argument("--list-sessions", action="store_true",
                   help="print the configured sessions (and the live legis list), then exit")
    p.add_argument("--inspect", action="store_true",
                   help="fetch a few roll calls, print diagnostics, write nothing")
    p.add_argument("--classify-report", action="store_true", dest="classify_report",
                   help="calibrate passage classification against Open States, write nothing")
    p.add_argument("--sample", type=int, default=None, metavar="N",
                   help="cap the number of roll calls processed")
    return p.parse_args(argv)


def list_sessions():
    """Show the sessions configured in lib/ga_sessions.py and, if a token can be
    minted, the live legis.ga.gov /api/sessions list — so rolling a session is a
    matter of copying the right id across, not guessing it."""
    print("Configured sessions (lib/ga_sessions.py):")
    for tag in all_session_ids():
        lid = legis_session_id(tag)
        flags = " [ACTIVE]" if tag == ACTIVE_SESSION else ""
        legis = ("legis id=%s library=%s" % (lid, legis_session_library(tag))
                 if lid is not None else "legis id=UNMAPPED")
        print("  %-10s %-28s %s%s" % (tag, session_name(tag), legis, flags))
    print("\nLive legis.ga.gov /api/sessions:")
    try:
        for s in LegisGaClient().sessions() or []:
            print("  id=%-6s library=%-10s isCurrent=%-5s %s"
                  % (s.get("id"), s.get("library"), s.get("isCurrent"),
                     s.get("description")))
    except Exception as exc:
        print("  (unavailable: %s)" % exc)
        print("  Set LEGIS_GA_CLIENT_KEY to fetch the live list.")


def print_inspection(stats, votes_meta=None):
    """Dump the memberVoted code distribution, sample resolutions, and one sample
    votes_meta record — so the (confirmed) code->option map can be re-checked and
    the populated legislation votes[] shape (date/motion/result) can be seen from
    the logs. See module docstring."""
    print("\n=== INSPECTION: memberVoted code distribution ===")
    for code in sorted(stats["codeDistribution"], key=lambda c: (c is None, c)):
        n = stats["codeDistribution"][code]
        label = MEMBER_VOTED.get(code, "Other")
        print("  code %-5s -> %-11s   count=%d" % (code, label, n))
    print("  (map %s)" % ("CONFIRMED 0=Yea/1=Nay" if MEMBER_VOTED_CONFIRMED
                          else "PROVISIONAL — verify against an official tally"))
    print("\n  Sample rows (name, code):")
    for name, code in stats["codeSamples"]:
        print("    %-24s %s" % (name, code))
    if stats.get("isRollCallDistribution"):
        print("\n  votes[].isRollCall distribution (passage-classification signal): %s"
              % stats["isRollCallDistribution"])
    if stats.get("sampleVoteRow") is not None:
        print("\n  RAW legislation.votes[] item (reveals the real keys, e.g. result):")
        print("    %s" % json.dumps(stats["sampleVoteRow"]))
    if votes_meta:
        print("\n  Sample votes_meta record (checks the legislation votes[] shape):")
        sample_key = next(iter(votes_meta))
        print("    %s -> %s" % (sample_key, json.dumps(votes_meta[sample_key])))
        populated = [k for k in ("date", "motionText", "result")
                     if votes_meta[sample_key].get(k)]
        print("    votes[]-sourced fields populated: %s"
              % (", ".join(populated) if populated else
                 "NONE (date/motion/result still empty — confirm the votes[] keys)"))
    print()


def main():
    args = parse_args()
    if args.list_sessions:
        list_sessions()
        return

    output_file = args.output_file
    inspect = args.inspect
    sample = args.sample if args.sample is not None else (5 if inspect else None)

    # Default to the active session; --session targets a specific one (e.g. the
    # regular session for calibration). The legis id comes from lib/ga_sessions.py.
    our_session = args.session or ACTIVE_SESSION
    if our_session not in all_session_ids():
        print("Error: unknown session '%s'. Configured: %s. (Run --list-sessions.)"
              % (our_session, ", ".join(all_session_ids())), file=sys.stderr)
        sys.exit(1)
    if legis_session_id(our_session) is None:
        print("Error: session '%s' has no legis.ga.gov id in lib/ga_sessions.py "
              "(LEGIS_SESSIONS). Add it, then re-run." % our_session, file=sys.stderr)
        sys.exit(1)

    if args.classify_report:
        classify_report(LegisGaClient(), our_session, sample=sample)
        return

    by_legis_id, by_chamber_district, chamber_by_ocd = build_crosswalk()
    print("Loaded crosswalk: %d legisGaGovId joins, %d (chamber,district) fallbacks"
          % (len(by_legis_id), len(by_chamber_district)))

    # Passage overlay (design §5.3). Degrade to caption-only if OS file is absent.
    try:
        os_index = load_os_passage_index(OS_VOTES_FILE, our_session)
        print("Loaded OS passage overlay: %d (bill,date) keys for %s"
              % (len(os_index), our_session))
    except FileNotFoundError:
        os_index = {}
        print("No OS votes file at %s — falling back to caption-only passage "
              "classification." % OS_VOTES_FILE)

    client = LegisGaClient()
    print("Fetching legis.ga.gov roll calls for %s (legis session %d)%s..."
          % (our_session, legis_session_id(our_session),
             " [sample=%d]" % sample if sample else ""))
    votes_meta, member_votes, stats = build(
        client, our_session, by_legis_id, by_chamber_district, chamber_by_ocd,
        os_index, sample=sample)

    if inspect:
        print_inspection(stats, votes_meta)
        print("Inspection run — nothing written. Kept %d passage roll calls "
              "(%d overlay, %d native; %d non-passage dropped); resolved %d/%d rows "
              "(%d via district fallback)."
              % (len(votes_meta), stats["passageByOverlay"], stats["passageByNative"],
                 stats["droppedNonPassage"], stats["resolvedRows"],
                 stats["resolvedRows"] + stats["unresolvedRows"],
                 stats["districtFallbackRows"]))
        return

    if not votes_meta:
        print("Error: collected zero roll calls — refusing to write. Either the "
              "session has no votes yet, or the enumeration/token failed above.",
              file=sys.stderr)
        sys.exit(1)
    if not member_votes:
        print("Error: roll calls found but no member rows resolved — check the "
              "crosswalk join and the memberVoted map.", file=sys.stderr)
        sys.exit(1)

    member_votes_compact, vote_id_index = encode_member_votes(
        member_votes, list(votes_meta.keys()))

    by_session = {}
    for v in votes_meta.values():
        sid = v.get("session") or our_session
        by_session[sid] = by_session.get(sid, 0) + 1

    output = {
        "metadata": {
            "schemaVersion": 2,
            "generatedAt": datetime.now().isoformat(),
            "biennium": BIENNIUM,
            "sessions": [{"id": sid, "name": session_name(sid),
                          "voteCount": by_session.get(sid, 0)}
                         for sid in all_session_ids()],
            "activeSession": our_session,
            "activeSessionName": session_name(our_session),
            "session": our_session,
            "sessionName": session_name(our_session),
            "source": "legis.ga.gov API",
            "totalVotes": len(votes_meta),
            "billsWithVotes": stats["billsWithVotes"],
            "resolvedRows": stats["resolvedRows"],
            "districtFallbackRows": stats["districtFallbackRows"],
            "unresolvedRows": stats["unresolvedRows"],
            "memberVotedMapConfirmed": MEMBER_VOTED_CONFIRMED,
            # Passage-only (design §5.3): overlay-primary, caption (native) fills gaps.
            "passageClassified": True,
            "passageByOverlay": stats["passageByOverlay"],
            "passageByNative": stats["passageByNative"],
            "droppedNonPassage": stats["droppedNonPassage"],
            "passageOverlaySource": OS_VOTES_FILE if os_index else None,
        },
        "voteIds": vote_id_index,
        "votes": votes_meta,
        "memberVotes": member_votes_compact,
    }

    write_json_atomic(output_file, output, separators=(",", ":"))
    size_kb = os.path.getsize(output_file) // 1024
    print("\nDone. %d passage roll calls · %d members · %d KB -> %s"
          % (len(votes_meta), len(member_votes), size_kb, output_file))
    print("  passage: %d via OS overlay, %d via caption (native); %d non-passage dropped"
          % (stats["passageByOverlay"], stats["passageByNative"], stats["droppedNonPassage"]))
    print("  resolved %d rows, %d unresolved" % (stats["resolvedRows"], stats["unresolvedRows"]))
    if not MEMBER_VOTED_CONFIRMED:
        print("  WARNING: memberVoted code map is PROVISIONAL — cross-check against a "
              "known tally before trusting Yea/Nay (see module docstring).")


if __name__ == "__main__":
    main()
