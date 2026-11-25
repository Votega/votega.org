#!/usr/bin/env python3
"""Assert the curated-votes SOAP path keeps former members instead of dropping them.

A 2023-24 member with a legisGaGovId but no roster id used to be skipped by the
crosswalk, so their vote vanished and the party bars undercounted. They are now keyed
`legis:<id>`; a sitting member's key is unchanged; and anyone still unattributable is
reported with their id. Offline: SOAP calls are stubbed.

Usage:
  python scripts/test_curated_former_members.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_curated_ga_bills as G  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def person(legis, roster, party, name):
    return {"name": {"full": name}, "role": {"party": party} if party else None,
            "ids": {"legisGaGovId": legis, "rosterId": roster, "ocdPersonId": None}}


CROSSWALK = {"people": [
    person(1, "ocd-person/sitting", "Democratic", "Sitting Dem"),
    person(2, None, "Republican", "Former Rep"),          # no roster id, role party
    person(3, None, None, "Former No Role"),               # no role: party from the listing
    person(4, None, None, "Former Unknown Party"),         # listing gives none either
]}


def write_crosswalk():
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(CROSSWALK, f)
    return path


def index_cases():
    path = write_crosswalk()
    try:
        idx = G.build_voter_index(path)
    finally:
        os.remove(path)
    check("a sitting member keeps their roster id as the key",
          idx[1]["key"], "ocd-person/sitting")
    check("a former member is keyed legis:<id>, not dropped", idx[2]["key"], "legis:2")
    check("a former member's party comes from the crosswalk role", idx[2]["party"], "Republican")
    check("no role means no party yet (never guessed)", idx[3]["party"], None)
    check("build_crosswalk still returns rostered people only (callers unchanged)",
          {k for k, v in idx.items() if v["rostered"]}, {1})


ROWS = [(1, "Nay"), (2, "Yea"), (3, "Yea"), (4, "Nay"), (99, "Yea")]
LISTING = [{"voteId": 10, "caption": "PASSAGE", "number": 5, "time": "10:00 AM",
            "date": "2024-03-14", "legislation": "SB 7"}]


def soap_case():
    path = write_crosswalk()
    try:
        idx = G.build_voter_index(path)
    finally:
        os.remove(path)
    G.get_vote_listings = lambda sid, branch: LISTING if branch == "House" else []
    G.get_vote_detail = lambda vid: ("PASSAGE", "2024-03-14", [], ROWS)
    G.get_members_by_session = lambda sid: [{"id": 3, "party": "Democrat"}]
    G.get_title_index = lambda sid: {}
    G.get_text_url = lambda lid: ""
    G.legis_session_id = lambda tag: 1031
    report = {"formerRows": 0, "unattributed": [], "partyless": []}
    rec = G.soap_bill_record({"session": "2023_24", "identifier": "SB 7"}, idx,
                             {"ocd-person/sitting": "Democratic"}, report)
    v = rec["votes"]["house"]
    check("every attributable row is kept", sorted(v["memberVotes"]),
          ["legis:2", "legis:3", "legis:4", "ocd-person/sitting"])
    check("the sitting member's vote is unchanged", v["memberVotes"]["ocd-person/sitting"], "no")
    t = v["partyTally"]
    check("Democratic tally counts the sitting member and the listing-party former member",
          (t["Democratic"]["yea"], t["Democratic"]["nay"]), (1, 1))
    check("Republican tally counts the former member", (t["Republican"]["yea"], t["Republican"]["nay"]), (1, 0))
    check("a former member with no known party is reported with the id",
          [m for _, m in report["partyless"]], [4])
    check("an id absent from the crosswalk is reported with the id, not hidden",
          [m for _, m in report["unattributed"]], [99])
    check("former rows are counted", report["formerRows"], 3)


def silent_cases():
    m = {"name": "A", "id": "x", "termStart": "2026-04-18"}
    check("seated after the last roll call is said only with a start date",
          "seated 2026-04-18" in G.describe_silent(m, "2026-03-31")["note"], True)
    m = {"name": "B", "id": "y", "termStart": "2026-03-15"}
    check("a start date before the last roll call does not claim a cause",
          "seated" in G.describe_silent(m, "2026-03-31")["note"], False)
    m = {"name": "C", "id": "z", "termStart": None}
    check("no start date is stated as such",
          "no term start" in G.describe_silent(m, "2026-03-31")["note"], True)


if __name__ == "__main__":
    index_cases()
    soap_case()
    silent_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall ok")
