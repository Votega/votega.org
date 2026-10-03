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

Two things still need a live run to confirm (each flagged in-code and in
metadata), because every bill captured during the spike had no roll call yet:

  1. The shape of a POPULATED legislation_detail `votes[]` item — assumed to carry
     per-vote metadata (date, caption/motion, totals, result). extract_vote_meta()
     pulls these defensively; confirm the real keys and tighten it.
  2. Passage classification. legis exposes ALL roll calls; today's site shows
     "passage only". This scaffold emits every roll call tagged; overlay the Open
     States passage set at cutover (design §5.3, recommended option (a)).

Auth: needs a legis.ga.gov token. In CI/local set LEGIS_GA_CLIENT_KEY (the public
SPA client key) to auto-mint+refresh; for offline testing inject LEGIS_GA_TOKEN.
Live minting is blocked inside the Claude Code agent sandbox (credential
guardrail) — run this in CI or locally, and unit-test the parsing in-agent.

Usage:
  python generate_ga_votes_from_legis.py            # -> ga-member-votes.legis.json
  python generate_ga_votes_from_legis.py OUT.json   # explicit output path
  python generate_ga_votes_from_legis.py --inspect  # fetch ~5 roll calls, print the
                                                    # memberVoted code distribution,
                                                    # write NOTHING (confirm the map)
  python generate_ga_votes_from_legis.py --sample 50  # cap roll calls (cheap run)
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

from lib.atomic_io import write_json_atomic
from lib.legis_ga import CHAMBER, LegisGaClient, vote_ids
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             session_name)
from lib.votes_schema import encode_member_votes

CROSSWALK_FILE = "assets/data/id-crosswalk.json"
# Parallel output by default — the migration plan (design §7) diffs this against
# the live Open States file before any cutover. Never overwrite the canonical file
# until that validation passes.
DEFAULT_OUTPUT = "assets/data/ga-member-votes.legis.json"

#: Our session tag  <->  legis.ga.gov numeric session id (its `library` in parens).
#: Confirmed: 1033 = 20252026 (regular), 1034 = 2026EX (special). Keep in step with
#: lib/ga_sessions.py when a session is added.
LEGIS_SESSION_ID = {
    "2025_26": 1033,
    "2026_ss": 1034,
}

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
    """Return (by_legis_id, by_chamber_district) mapping to OCD person ids.

    by_legis_id[int]            -> ocdPersonId   (primary, collision-proof join)
    by_chamber_district[(c,d)]  -> ocdPersonId   (fallback for members whose
                                   legisGaGovId is still null in the crosswalk;
                                   `c` is the chamber STRING, `d` the int district)
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    by_legis_id, by_chamber_district = {}, {}
    for person in data.get("people", []):
        ocd = (person.get("ids") or {}).get("ocdPersonId")
        if not ocd:
            continue
        legis_id = (person.get("ids") or {}).get("legisGaGovId")
        if legis_id is not None:
            by_legis_id[int(legis_id)] = ocd
        role = person.get("role") or {}
        chamber, district = role.get("chamber"), role.get("district")
        if chamber and district is not None:
            by_chamber_district.setdefault((chamber, int(district)), ocd)
    return by_legis_id, by_chamber_district


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

    Pulls per-vote metadata (date, motion, totals, result) from the
    legislation_detail `votes[]` item (`vote_row`) when present — ⚠ its exact keys
    are unconfirmed (see docstring #2), so every field is read defensively. yea/nay
    fall back to counts computed from the per-member rows once MEMBER_VOTED is
    confirmed. `bill` comes from Vote/detail's own `legislation[]` description.
    """
    row = vote_row or {}
    legn = (vote_detail.get("legislation") or [{}])
    desc = (legn[0].get("description") if legn else None) or ""
    legislation_id = (legn[0].get("legislationId") if legn else None)
    return {
        "bill": desc,
        "billUrl": ("https://www.legis.ga.gov/legislation/%s" % legislation_id
                    if legislation_id else None),
        "title": (legislation_detail or {}).get("title") or "",
        "session": our_session,
        "motionText": row.get("caption") or row.get("motion") or row.get("description") or "",
        "date": (row.get("date") or row.get("voteDate") or "")[:10] or None,
        "yea": row.get("yeas"),   # may be None -> filled from counts below
        "nay": row.get("nays"),
        "result": row.get("result"),
    }


def build(client, our_session, by_legis_id, by_chamber_district, verbose=True,
          sample=None):
    """Walk the active session's bills -> details -> roll calls, resolving each
    per-member row to an OCD id. Returns (votes_meta, member_votes, stats).

    `sample` caps the number of roll calls processed (used by --sample/--inspect
    to make the first live run cheap and purpose-built for confirmation). The raw
    `memberVoted` code distribution and a few sample resolutions are always
    accumulated into stats so the code->option map can be checked from the logs.
    """
    legis_session = LEGIS_SESSION_ID[our_session]
    votes_meta, member_votes = {}, {}
    seen_votes = set()
    resolved_rows = district_rows = unresolved_rows = bills_with_votes = 0
    code_dist = Counter()        # raw memberVoted code -> count, across all rows
    code_samples = []            # a few (name, code) pairs for eyeballing the map

    # Index legislation_detail votes[] rows by vote id so extract_vote_meta can
    # reach the per-vote metadata that Vote/detail itself does not carry.
    for i, bill in enumerate(client.iter_legislation(legis_session), 1):
        legislation_id = bill.get("legislationId")
        if legislation_id is None:
            continue
        detail = client.legislation_detail(legislation_id)
        vids = vote_ids(detail)
        if not vids:
            continue
        bills_with_votes += 1
        meta_rows = {}
        for r in (detail.get("votes") or []):
            if isinstance(r, dict):
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
            meta = extract_vote_meta(vote, meta_rows.get(vid), our_session, detail)
            # Chamber for the district fallback. Vote/detail did not expose a
            # chamber field in the spike sample; this reads it if present (confirm
            # the key on first run) and otherwise disables the fallback safely.
            roll_chamber = CHAMBER.get(vote.get("chamber"))

            yea = nay = 0
            for pv in (vote.get("votes") or []):
                member = pv.get("member") or {}
                code = pv.get("memberVoted")
                code_dist[code] += 1
                if len(code_samples) < 24:
                    code_samples.append((member.get("name"), code))
                option = MEMBER_VOTED.get(code, "Other")
                ocd, how = resolve_member(member, by_legis_id, by_chamber_district,
                                          chamber=roll_chamber)
                if ocd:
                    resolved_rows += 1
                    if how == "district":
                        district_rows += 1
                    member_votes.setdefault(ocd, []).append(
                        {"voteId": key, "vote": option})
                else:
                    unresolved_rows += 1
                if option == "Yea":
                    yea += 1
                elif option == "Nay":
                    nay += 1
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
        "codeDistribution": dict(code_dist),
        "codeSamples": code_samples,
    }
    return votes_meta, member_votes, stats


def _arg_value(flag, default=None):
    """Read `--flag value` (or `--flag=value`) from argv."""
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return default


def print_inspection(stats):
    """Dump the memberVoted code distribution + sample resolutions, so the
    code->option map (and the current guess in MEMBER_VOTED) can be verified
    against a known tally from the logs. See module docstring #1."""
    print("\n=== INSPECTION: memberVoted code distribution ===")
    for code in sorted(stats["codeDistribution"], key=lambda c: (c is None, c)):
        n = stats["codeDistribution"][code]
        guess = MEMBER_VOTED.get(code, "Other")
        print("  code %-5s -> %-11s (current guess)   count=%d" % (code, guess, n))
    print("\n  Sample rows (name, code):")
    for name, code in stats["codeSamples"]:
        print("    %-24s %s" % (name, code))
    print("\n  WARNING: confirm the map against one roll call's OFFICIAL tally, then "
          "set MEMBER_VOTED + MEMBER_VOTED_CONFIRMED=True.\n")


def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    output_file = positional[0] if positional else DEFAULT_OUTPUT
    inspect = "--inspect" in sys.argv
    sample = _arg_value("--sample")
    sample = int(sample) if sample else (5 if inspect else None)

    our_session = ACTIVE_SESSION
    if our_session not in LEGIS_SESSION_ID:
        print("Error: no legis.ga.gov session id mapped for active session "
              "'%s'. Add it to LEGIS_SESSION_ID." % our_session, file=sys.stderr)
        sys.exit(1)

    by_legis_id, by_chamber_district = build_crosswalk()
    print("Loaded crosswalk: %d legisGaGovId joins, %d (chamber,district) fallbacks"
          % (len(by_legis_id), len(by_chamber_district)))

    client = LegisGaClient()
    print("Fetching legis.ga.gov roll calls for %s (legis session %d)%s..."
          % (our_session, LEGIS_SESSION_ID[our_session],
             " [sample=%d]" % sample if sample else ""))
    votes_meta, member_votes, stats = build(
        client, our_session, by_legis_id, by_chamber_district, sample=sample)

    if inspect:
        print_inspection(stats)
        print("Inspection run — nothing written. Resolved %d/%d rows across %d roll calls."
              % (stats["resolvedRows"],
                 stats["resolvedRows"] + stats["unresolvedRows"], len(votes_meta)))
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
            # ⚠ Honesty flags — clear these as the first-run confirmations land.
            "memberVotedMapConfirmed": MEMBER_VOTED_CONFIRMED,
            "passageClassified": False,   # all roll calls emitted; no passage filter yet
        },
        "voteIds": vote_id_index,
        "votes": votes_meta,
        "memberVotes": member_votes_compact,
    }

    write_json_atomic(output_file, output, separators=(",", ":"))
    size_kb = os.path.getsize(output_file) // 1024
    print("\nDone. %d roll calls · %d members · %d KB -> %s"
          % (len(votes_meta), len(member_votes), size_kb, output_file))
    print("  resolved %d rows, %d unresolved" % (stats["resolvedRows"], stats["unresolvedRows"]))
    if not MEMBER_VOTED_CONFIRMED:
        print("  WARNING: memberVoted code map is PROVISIONAL — cross-check against a "
              "known tally before trusting Yea/Nay (see module docstring).")


if __name__ == "__main__":
    main()
