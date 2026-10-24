#!/usr/bin/env python3
"""Assert the closed-biennium archive path cannot disturb the live pipeline.

  - the archive tags are invisible to the daily session iteration,
  - their directory slug is 'YYYY-YYYY' (the archive naming), not 'YYYY-YY',
  - an archive publish emits only sessions/<slug>/ files and never a daily pointer,
  - the producer refuses to write a live file, and keeps voters the crosswalk lacks.

Usage:
  python scripts/test_publish_ga_legislators_archive.py

Offline; stdlib only. Exits 0 on success, 1 on any failure.
"""

import csv
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
import generate_ga_votes_soap as G  # noqa: E402
import publish_ga_legislators as P  # noqa: E402
from lib import ga_sessions as S  # noqa: E402
from lib.votes_schema import encode_member_votes  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def exits(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    return False


print("sessions")
check("daily iteration unchanged", S.all_session_ids(), ["2025_26", "2026_ss"])
check("preserved set unchanged", S.preserved_session_ids(), ["2025_26"])
check("archive tags kept out of daily iteration",
      [t for t in S.ARCHIVE_SESSIONS if t in S.all_session_ids()], [])
for tag, slug in [("2023_24", "2023-2024"), ("2021_22", "2021-2022"),
                  ("2019_20", "2019-2020"), ("2017_18", "2017-2018"),
                  ("2025_26", "2025-2026"), ("2026_ss", "2026-ss")]:
    check(f"slug {tag}", S.session_slug(tag), slug)
check("session_name archive", S.session_name("2019_20"), "2019-2020 Regular Session")
check("legis ids resolve",
      [S.legis_session_id(t) for t in S.ARCHIVE_SESSIONS], [1031, 1029, 27, 25])

print("producer guards")
ids = G.ArchiveIds({7: "ocd-person-x"})
check("crosswalk id preferred", ids.get(7), "ocd-person-x")
check("departed member falls back", ids.get(123), "legis-123")
for live in G.LIVE_OUTPUTS:
    check(f"refuses live output {live}", G.archive_output_ok(live), False)
check("allows out/archive path", G.archive_output_ok("out/archive/x.json"), True)

print("anomalous roll calls")
ok_rows = [(i, "Yea") for i in range(1, 91)] + [(i, "Nay") for i in range(91, 181)]
check("clean House roll call passes", G.roll_call_anomaly(ok_rows, 90, 90, "House"), None)
check("vacant sentinel rows ignored",
      G.roll_call_anomaly(ok_rows + [(G.VACANT_ID, "Nay")] * 3, 90, 90, "House"), None)
dup_rows = [(i, o) for i in range(1, 181) for o in ("Yea", "Yea", "Nay", "Nay")]
check("4 rows per member is flagged",
      "180 members listed more than once" in (G.roll_call_anomaly(dup_rows, 360, 360, "House") or ""), True)
check("tally above seat count is flagged",
      "exceeds the 56 seats" in (G.roll_call_anomaly([(1, "Yea")], 40, 20, "Senate") or ""), True)

print("publisher archive")
votes = {"1-2": {"bill": "HB 1", "title": "T", "session": "2023_24", "motionText": "m",
                 "chamber": "House of Representatives", "date": "2023-03-01",
                 "yea": 2, "nay": 0, "result": "Pass", "billUrl": "u", "rollNumber": 5}}
mv, vote_ids = encode_member_votes({"legis-1": [{"voteId": "1-2", "vote": "Yea"}],
                                    "legis-2": [{"voteId": "1-2", "vote": "Yea"}]},
                                   list(votes))
members = [{"id": "legis-1", "legisGaGovId": 1, "name": "A B", "party": "Republican",
            "chamber": "House", "district": 1, "dateVacated": None},
           {"id": "legis-2", "legisGaGovId": 2, "name": "C D", "party": "Democrat",
            "chamber": "Senate", "district": 2, "dateVacated": None}]


def doc(**meta):
    base = {"schemaVersion": 2, "archive": True, "session": "2023_24",
            "sessionName": "2023-2024 Regular Session", "biennium": "2023-2024"}
    return {"metadata": {**base, **meta}, "members": members, "voteIds": vote_ids,
            "votes": votes, "memberVotes": mv}


def write(d):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, f)
    f.close()
    return f.name


good = write(doc())
art = P.build_archive("2023_24", good)
check("only sessions/2023-2024/ paths",
      sorted(art), sorted(f"sessions/2023-2024/{n}" for n in (
          "votes.json", "votes.csv", "votes.schema.json",
          "members.json", "members.csv", "members.schema.json")))
check("no daily pointer emitted", [p for p in art if p in P.POINTER_FILES], [])
rows = list(csv.DictReader(io.StringIO(art["sessions/2023-2024/members.csv"].decode())))
check("members.csv has session column", {r["session"] for r in rows}, {"2023_24"})
check("members.csv rows", len(rows), 2)
v = json.loads(art["sessions/2023-2024/votes.json"])
check("votes.json memberVotes decoded to legacy shape",
      v["memberVotes"]["legis-1"], [{"voteId": "1-2", "vote": "Yea"}])
check("votes.json carries excludedRollCalls", v["metadata"]["excludedRollCalls"], [])
check("votes.json names its session", v["metadata"]["session"], "2023_24")

check("rejects a current-biennium tag", exits(P.build_archive, "2025_26", good), True)
check("rejects tag/file mismatch", exits(P.build_archive, "2021_22", good), True)
check("rejects a partial file", exits(P.build_archive, "2023_24", write(doc(partial=True))), True)
check("rejects a non-archive file",
      exits(P.build_archive, "2023_24", write(doc(archive=False))), True)
check("path guard rejects pointer",
      exits(P.assert_archive_paths, {"latest.json": b"x"}, "2023-2024"), True)
check("path guard rejects other slug",
      exits(P.assert_archive_paths, {"sessions/2025-2026/votes.json": b"x"}, "2023-2024"), True)

print("identifier dictionary")
check("exactly one id carries across all sessions unconditionally",
      [i["name"] for i in P.IDENTIFIERS if i["acrossSessions"].startswith("Yes --")],
      ["legisGaGovId"])
check("identifiers mode emits only IDENTIFIERS.md", sorted(P.build_identifiers()), ["IDENTIFIERS.md"])
md = P.build_identifiers()["IDENTIFIERS.md"].decode()
check("dictionary names every id", all(f"`{i['name']}`" in md for i in P.IDENTIFIERS), True)
sch = json.loads(art["sessions/2023-2024/members.schema.json"])
check("archive schema embeds the dictionary", set(sch["identifiers"]),
      {i["name"] for i in P.IDENTIFIERS})
check("votes.json says how to join members",
      "legisGaGovId" in v["metadata"]["memberVotesKey"], True)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
