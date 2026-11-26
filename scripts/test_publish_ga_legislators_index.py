#!/usr/bin/env python3
"""latest.json and scorecard-latest.json in Votega/ga-legislators keep pointing at every
earlier General Assembly. Before this, both were rebuilt from the current biennium only,
so the backfilled 2017-2024 archive was already unindexed and 2025-2026 would have joined
it at the rollover.

Usage: python scripts/test_publish_ga_legislators_index.py   (offline; exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
import publish_ga_legislators as P  # noqa: E402

failures = []


def check(label, got, want):
    print(f"  ok   {label}" if got == want else f"  FAIL {label}: got {got!r}, want {want!r}")
    if got != want:
        failures.append(label)


def frozen(root, tag, biennium, sessions, scorecard=False):
    os.makedirs(os.path.join(root, tag), exist_ok=True)
    with open(os.path.join(root, tag, "ga-votes-index.json"), "w", encoding="utf-8") as fh:
        json.dump({"metadata": {"biennium": biennium, "sessions": [
            {"id": i, "name": n, "voteCount": c} for i, n, c in sessions]}}, fh)
    if scorecard:
        with open(os.path.join(root, tag, "ga-party-unity.json"), "w", encoding="utf-8") as fh:
            json.dump({"metadata": {"biennium": biennium}}, fh)


ARCHIVE = {"2023_24": "2023-2024 Regular Session", "2017_18": "2017-2018 Regular Session"}
SESSIONS = [("2025_26", "2025-2026 Regular Session", 2154), ("2026_ss", "2026 Special Session", 264)]

with tempfile.TemporaryDirectory() as root:
    got = P.earlier_bienniums("2025-2026", root, ARCHIVE)
    check("the backfilled archive is indexed, newest first", [b["biennium"] for b in got],
          ["2023-2024", "2017-2018"])
    check("an archive biennium points at its votes and roster",
          (got[0]["sessions"][0]["files"]["votes"], got[0]["roster"], got[0]["sessions"][0]["voteCount"]),
          ("sessions/2023-2024/votes.json", "sessions/2023-2024/members.json", None))
    check("an archive biennium claims no scorecard", "scorecard" in got[0], False)

    frozen(root, "2025_26", "2025-2026", SESSIONS)
    check("a biennium frozen early, before the rollover, is not earlier",
          [b["biennium"] for b in P.earlier_bienniums("2025-2026", root, ARCHIVE)],
          ["2023-2024", "2017-2018"])

    after = P.earlier_bienniums("2027-2028", root, ARCHIVE)
    check("after the rollover 2025-2026 heads the list", [b["biennium"] for b in after],
          ["2025-2026", "2023-2024", "2017-2018"])
    check("its sessions keep their published folders and vote counts",
          [(s["slug"], s["voteCount"], s["files"]["votesCsv"]) for s in after[0]["sessions"]],
          [("2025-2026", 2154, "sessions/2025-2026/votes.csv"),
           ("2026-ss", 264, "sessions/2026-ss/votes.csv")])
    check("no scorecard until it is frozen", "scorecard" in after[0], False)
    frozen(root, "2025_26", "2025-2026", SESSIONS, scorecard=True)
    check("the frozen scorecard is indexed",
          P.earlier_bienniums("2027-2028", root, ARCHIVE)[0]["scorecard"]["scorecard"],
          "sessions/2025-2026/scorecard.json")

    os.makedirs(os.path.join(root, "2019_20"))
    with open(os.path.join(root, "2019_20", "ga-votes-index.json"), "w") as fh:
        fh.write("{not json")
    try:
        P.earlier_bienniums("2027-2028", root, ARCHIVE)
        refused = False
    except SystemExit:
        refused = True
    check("an unreadable frozen index refuses the publish", refused, True)

print("rosterArchive:")
with tempfile.TemporaryDirectory() as root:
    check("null while no biennium is frozen", P.roster_archive("2025-2026", root), None)
    frozen(root, "2025_26", "2025-2026", SESSIONS)
    check("null when the votes are frozen but the roster is not",
          P.roster_archive("2025-2026", root), None)
    open(os.path.join(root, "2025_26", "ga-members.json"), "w").write("{}")
    check("points at the frozen roster once there is one",
          P.roster_archive("2025-2026", root), "sessions/2025-2026/members.json")
    check("null after the rollover: the new biennium's roster is years from frozen",
          P.roster_archive("2027-2028", root), None)

print("against the committed data:")
latest = json.loads(P.build_votes()["latest.json"])
check("latest.json lists the 2017-2024 archive today",
      [b["biennium"] for b in latest["earlierBienniums"]],
      ["2023-2024", "2021-2022", "2019-2020", "2017-2018"])
check("current fields unchanged", sorted(k for k in latest if k != "earlierBienniums"),
      ["activeSession", "biennium", "currentRoster", "currentSession", "generatedAt",
       "rosterArchive", "sessions"])
check("rosterArchive still points at the frozen 2025-2026 roster",
      latest["rosterArchive"], "sessions/2025-2026/members.json")
if os.path.exists(P.SRC_SCORECARD):
    sc = json.loads(P.build_scorecard()["scorecard-latest.json"])
    check("scorecard-latest.json has no earlier scorecard yet", sc["earlierBienniums"], [])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
