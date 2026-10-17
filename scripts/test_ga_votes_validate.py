#!/usr/bin/env python3
"""Assert validate_ga_votes.py gates on self-contradiction and only reports change.

The property under test is the split itself. A check in the wrong tier is the
bug: a self-contradiction that only gets reported ships a vote record that shows
one roll call under another's heading, and a legitimate change that gates throws
away ~1,500 SOAP calls' worth of sweep and leaves the site a week stale.

Two cases matter most, because they are what the heredoc this replaces actually
failed the run on:

  * a file holding fewer than 1,000 roll calls or fewer than 150 members with a
    record (`assert votes >= 1000`, `assert members >= 150`) — the shape of a
    new biennium, and of a session that has not convened
  * a result caption the producer's rule does not normalize
    (`assert result in ('Pass','Fail')`) — the chambers write their own wording

Both must be proven tier 2. A MISSING result stays tier 1, since the field is
required and the site reads it.

Usage:
  python scripts/test_ga_votes_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_votes as V  # noqa: E402

failures = []

SESSIONS = ("2025_26", "2023_24")


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def vote(n, session):
    return {
        "bill": f"HB {n}",
        "billUrl": f"https://legis.ga.gov/legislation/{n}",
        "title": f"A bill about {n}",
        "session": session,
        "motionText": "Agree to Senate Substitute",
        "chamber": "House of Representatives",
        "rollNumber": n,
        "time": "2025-02-01T10:00:00",
        "excused": 0,
        "notVoting": 1,
        "date": "2025-02-01",
        "yea": 120,
        "nay": 40,
        "result": "Pass" if n % 7 else "Fail",
    }


def sound(n_votes=1200, n_members=200):
    """A self-consistent file in the compact (v2) shape the producer emits.

    Deliberately above both reporting floors, so a tier-1 case never trips a
    tier-2 line by accident.
    """
    votes, per_session = {}, {s: 0 for s in SESSIONS}
    for i in range(n_votes):
        s = SESSIONS[i % len(SESSIONS)]
        votes[f"v{i:05d}"] = vote(i, s)
        per_session[s] += 1
    vote_ids = list(votes)
    member_votes = {
        f"ocd-person/{p:04d}": {str(i): ("Y" if (i + p) % 3 else "N")
                                for i in range(p % 7, len(vote_ids), 11)}
        for p in range(n_members)
    }
    return {
        "metadata": {
            "schemaVersion": 2,
            "generatedAt": "2026-10-17T07:30:00Z",
            "session": SESSIONS[0],
            "sessionName": "2025-2026 Regular Session",
            "source": "legis.ga.gov SOAP",
            "totalVotes": len(votes),
            "totalBillsSeen": len(votes),
            "paginationComplete": True,
            "passageOverlaySource": None,
            "sessions": [{"id": s, "voteCount": per_session[s]} for s in SESSIONS],
            "sessionsPreserved": [SESSIONS[1]],
        },
        "voteIds": vote_ids,
        "votes": votes,
        "memberVotes": member_votes,
    }


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound(), expect_no_overlay=True), [])

    d = sound()
    d["metadata"]["totalVotes"] = 7
    check("a total that does not match what it counts is tier 1",
          any("totalVotes" in e for e in V.tier1(d)), True)

    d = sound()
    d["voteIds"] = d["voteIds"][:500]
    check("a voteIds index shorter than the records is tier 1",
          any("fewer than the" in e for e in V.tier1(d)), True)

    d = sound()
    d["voteIds"][1] = d["voteIds"][0]
    check("a duplicate in voteIds is tier 1",
          any("duplicates" in e for e in V.tier1(d)), True)

    d = sound()
    d["voteIds"][5] = "not-a-real-vote-id"
    check("a record absent from the voteIds index is tier 1",
          any("absent from the voteIds index" in e for e in V.tier1(d)), True)

    d = sound()
    d["votes"]["v00001"].pop("chamber")
    check("a vote missing its stored chamber is tier 1 "
          "(it can never be inferred from motionText)",
          any("missing required field" in e for e in V.tier1(d)), True)

    d = sound()
    d["votes"]["v00001"]["result"] = None
    check("a null result is tier 1", any("null result" in e for e in V.tier1(d)), True)

    # The check that actually catches a broken incremental merge, which the
    # whole-file floors cannot: they are cleared by the preserved layer alone.
    d = sound()
    d["metadata"]["sessions"][0]["voteCount"] += 50
    check("a per-session count disagreeing with the records is tier 1",
          any("preserved/fetched merge is wrong" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["sessionsPreserved"] = ["2021_22"]
    check("a session marked preserved with nothing in the file is tier 1",
          any("marked preserved but has no votes" in e for e in V.tier1(d)), True)

    d = sound()
    d["memberVotes"]["ocd-person/0001"]["999999"] = "Y"
    check("a member row indexing outside voteIds is tier 1",
          any("index outside voteIds" in e for e in V.tier1(d)), True)

    d = sound()
    d["memberVotes"]["ocd-person/0001"]["3"] = "Yea"
    check("a member row carrying a decoded option instead of a code is tier 1",
          any("the codec does not" in e for e in V.tier1(d)), True)

    d = sound()
    d["memberVotes"]["ocd-person/0001"] = [{"voteId": "v00000", "vote": "Yea"}]
    check("a legacy-shape member row is tier 1 (the compact schema was not written)",
          any("not {index: code} maps" in e for e in V.tier1(d)), True)

    d = sound()
    d.pop("voteIds")
    check("a missing voteIds index is tier 1",
          any("compact schema was not written" in e for e in V.tier1(d)), True)

    d = sound()
    d["metadata"]["passageOverlaySource"] = "openstates"
    check("an overlay source present when --no-overlay was passed is tier 1",
          any("passageOverlaySource" in e for e in V.tier1(d, expect_no_overlay=True)), True)
    check("...and is NOT checked when the overlay was allowed",
          V.tier1(d, expect_no_overlay=False), [])

    d = sound()
    d["votes"] = {}
    check("an empty file is tier 1", V.tier1(d) != [], True)

    d = sound()
    d["memberVotes"] = {}
    check("a file with no member rows is tier 1", V.tier1(d) != [], True)

    # ── everything below is the world moving, and must NOT gate ──
    #
    # These are the conditions the old heredoc failed the run on. Each aborted
    # the job before the commit step and discarded the whole sweep, which dies
    # with the runner.
    d = sound(n_votes=40, n_members=60)
    check("a brand-new biennium with 40 roll calls is NOT tier 1 "
          "(the old `votes >= 1000` floor's false positive)",
          V.tier1(d, expect_no_overlay=True), [])

    d = sound(n_votes=1200, n_members=12)
    check("only a dozen members with a record is NOT tier 1 "
          "(the old `members >= 150` floor's false positive)",
          V.tier1(d, expect_no_overlay=True), [])

    d = sound()
    d["votes"]["v00001"]["result"] = "Agreed to"
    check("a result caption the producer does not normalize is NOT tier 1 "
          "(the old `result in (Pass, Fail)` gate's false positive)",
          V.tier1(d, expect_no_overlay=True), [])

    d = sound()
    d["metadata"]["paginationComplete"] = False
    check("a sweep that reports itself incomplete is NOT tier 1",
          V.tier1(d, expect_no_overlay=True), [])

    # A session rollover: the oldest session drops out of the preserved layer.
    d = sound()
    d["votes"] = {k: v for k, v in d["votes"].items()
                  if v["session"] != SESSIONS[1]}
    d["voteIds"] = list(d["votes"])
    d["metadata"]["totalVotes"] = len(d["votes"])
    d["metadata"]["sessions"] = [{"id": SESSIONS[0], "voteCount": len(d["votes"])}]
    d["metadata"]["sessionsPreserved"] = []
    d["memberVotes"] = {p: {} for p in d["memberVotes"]}
    check("a session leaving the file is NOT tier 1",
          V.tier1(d, expect_no_overlay=True), [])


def tier2_cases():
    old = sound()

    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline and a healthy sweep -> nothing to report",
          V.tier2(sound(), None), [])

    # Each old gate must now produce a REPORT LINE, so a human sees what the
    # gate used to hide.
    heads = [h for h, _ in V.tier2(sound(n_votes=40, n_members=60), None)]
    check("a thin sweep is reported",
          "Fewer records than a busy biennium holds" in heads, True)

    new = copy.deepcopy(old)
    new["votes"]["v00001"]["result"] = "Agreed to"
    heads = [h for h, _ in V.tier2(new, old)]
    check("unnormalized result wording is reported",
          "Result wording the producer does not normalize" in heads, True)

    new = copy.deepcopy(old)
    new["metadata"]["paginationComplete"] = False
    heads = [h for h, _ in V.tier2(new, old)]
    check("an incomplete sweep is reported",
          "The sweep reported itself incomplete" in heads, True)

    new = copy.deepcopy(old)
    for k in list(new["votes"])[:300]:
        new["votes"].pop(k)
    heads = [h for h, _ in V.tier2(new, old)]
    check("the file losing roll calls is reported",
          "The file lost roll calls" in heads, True)
    check("...and the session that shrank is named",
          "A session holds fewer votes than it did" in heads, True)

    new = copy.deepcopy(old)
    new["votes"]["v99999"] = vote(99999, "2027_28")
    heads = [h for h, _ in V.tier2(new, old)]
    check("a new session is reported", "Sessions in the file changed" in heads, True)

    new = copy.deepcopy(old)
    new["memberVotes"].pop("ocd-person/0001")
    heads = [h for h, _ in V.tier2(new, old)]
    check("the member count moving is reported",
          "Members with a vote record changed" in heads, True)

    # The report is what a human reads; it must say the data shipped anyway.
    body = V.render("ga-member-votes.json", V.tier2(new, old))
    check("the report states the data was committed anyway",
          "none of them blocked the update" in body, True)
    check("an empty report says so",
          "no material change this run" in V.render("ga-member-votes.json", []), True)


def main():
    print("tier 1 — gate on self-contradiction:")
    tier1_cases()
    print("\ntier 2 — report change, never gate:")
    tier2_cases()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
