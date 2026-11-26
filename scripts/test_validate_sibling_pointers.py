#!/usr/bin/env python3
"""validate_sibling_pointers.py finds index entries that name a missing file, accepts
null pointers and folder-relative manifest paths, and never passes vacuously.

Usage: python scripts/test_validate_sibling_pointers.py   (offline; exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_sibling_pointers as V  # noqa: E402

failures = []


def check(label, got, want):
    print(f"  ok   {label}" if got == want else f"  FAIL {label}: got {got!r}, want {want!r}")
    if got != want:
        failures.append(label)


TREE = {"latest.json", "scorecard-latest.json", "README.md", "data/all.json",
        "sessions/2025-2026/members.json", "sessions/2025-2026/votes.json",
        "data/officials/manifest.json", "data/officials/officials.json", "data/bills/manifest.json"}

check("index files are the root pointers and the dataset manifests",
      V.index_files(TREE | {"sessions/2025-2026/votes.schema.json", "data/x.json"}),
      ["data/bills/manifest.json", "data/officials/manifest.json", "latest.json",
       "scorecard-latest.json"])

latest = {"biennium": "2027-2028", "currentRoster": "data/all.json",
          "rosterArchive": "sessions/2027-2028/members.json",
          "sessions": [{"files": {"votes": "sessions/2027-2028/votes.json"}}],
          "earlierBienniums": [{"roster": "sessions/2025-2026/members.json"}],
          "source": "https://example.org/a.json", "note": "see README.md", "id": "2025_26"}
check("a pointer to a file not yet published is reported",
      V.dangling(latest, TREE, "latest.json"),
      ["sessions/2027-2028/members.json", "sessions/2027-2028/votes.json"])
check("a null pointer is fine", V.dangling({"rosterArchive": None}, TREE, "latest.json"), [])
check("URLs, prose and ids are not paths",
      V.dangling({"u": "https://x.org/y.json", "p": "see README.md", "t": "<slug>/a.json",
                  "abs": "/assets/data/x.json"}, TREE, "latest.json"), [])
check("a manifest path may be root-relative or folder-relative",
      V.dangling({"files": [{"path": "data/officials/officials.json"}, {"path": "officials.json"},
                            {"path": "gone.csv"}]}, TREE, "data/officials/manifest.json"),
      ["gone.csv"])


def fake(files, fail=False):
    def get(url, token=None):
        if fail:
            raise urllib.error.URLError("offline")
        if "/git/trees/" in url:
            return json.dumps({"tree": [{"path": p, "type": "blob"} for p in files]}).encode()
        return json.dumps(files[url.split("/main/", 1)[1]]).encode()
    return get


good = {"latest.json": {"currentRoster": "data/all.json", "rosterArchive": None}, "data/all.json": {}}
bad = {"latest.json": {"rosterArchive": "sessions/2027-2028/members.json"}}
print("main():")
check("passes when every path resolves", V.main(["r"], get=fake(good)), 0)
check("fails on a dangling path", V.main(["r"], get=fake(bad)), 1)
check("fails when nothing could be read", V.main(["r"], get=fake({}, fail=True)), 1)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
