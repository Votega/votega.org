#!/usr/bin/env python3
"""Assert the ga-legislators published artifacts name their own session.

data/all.json, data/members.csv and ROSTER.md are overwritten IN PLACE at a biennium
rollover, so a downloaded copy must say which General Assembly it describes.

Usage:
  python scripts/test_publish_ga_legislators_session.py

Offline; stdlib only. Exits 0 on success, 1 on any failure.
"""

import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))
import publish_ga_legislators as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


MEMBERS = [
    {"id": "legis-1", "name": "A B", "chamber": "Senate", "district": 1,
     "party": "Republican", "legisGaGovId": 1, "committees": [{"name": "Rules"}]},
    {"id": "legis-2", "name": "C D", "chamber": "House of Representatives", "district": 2,
     "party": "Democratic", "legisGaGovId": 2},
]

# --- members.csv ----------------------------------------------------------- #
rows = list(csv.reader(io.StringIO(P.members_csv(MEMBERS, "2025_26").decode())))
check("members.csv keeps every pre-existing column in place",
      rows[0][:14], ["id", "name", "firstName", "lastName", "party", "chamber", "district",
                     "title", "status", "phone", "email", "website", "committees",
                     "legisGaGovId"])
# `session` was the last column until votegaUrl was appended after it (new columns are
# appended, never inserted), so consumers find it by header name.
si = rows[0].index("session")
check("members.csv has a session column at its original position", si, 14)
check("every row carries the session", {r[si] for r in rows[1:]}, {"2025_26"})
check("votegaUrl is appended after session", rows[0][-1], "votegaUrl")
check("rows match the header width", {len(r) for r in rows}, {len(rows[0])})
try:
    P.members_csv(MEMBERS, None)
    check("a roster with no session refuses to publish", "published", "SystemExit")
except SystemExit:
    check("a roster with no session refuses to publish", True, True)

# --- ROSTER.md ------------------------------------------------------------- #
live = P.roster_md(MEMBERS, {"generatedAt": "T", "session": "2025_26"}).decode()
check("live ROSTER.md names the session", "2025_26" in live.splitlines()[0], True)
check("live ROSTER.md links sessions/ for history", "(sessions)" in live, True)
frozen = P.roster_md(MEMBERS, {"generatedAt": "T", "session": "2025_26"}, session="2025-2026").decode()
check("frozen ROSTER.md still headed by its slug", frozen.splitlines()[0].endswith("2025-2026"), True)

# --- members.schema.json --------------------------------------------------- #
meta_schema = P.members_schema()["properties"]["metadata"]
props = meta_schema.get("properties", {})
for k in ("session", "legisSessionId", "generatedAt"):
    check(f"schema describes metadata.{k}", bool(props.get(k, {}).get("description")), True)
check("schema points at sessions/ for history", "sessions/" in meta_schema.get("description", ""), True)
check("schema stays additive (no new required keys)", P.members_schema()["required"], ["members"])


def validate(schema, doc):
    """Minimal check of the properties we added: type of each described metadata key.

    The metadata properties are reached defensively: a schema that stopped
    describing them is exactly the regression this file exists to catch, so it
    has to come back as a failure message rather than a KeyError that aborts the
    run before the remaining cases get to speak.
    """
    types = {"string": str, "integer": int, "null": type(None)}
    meta = doc.get("metadata", {})
    described = schema.get("properties", {}).get("metadata", {}).get("properties")
    if not described:
        return "schema describes no metadata properties"
    for k, spec in described.items():
        if k not in meta:
            continue
        t = spec["type"]
        ok = [t] if isinstance(t, str) else t
        if not any(isinstance(meta[k], types[x]) for x in ok):
            return f"metadata.{k}={meta[k]!r} violates {t}"
    return None


# The CURRENTLY committed payload must still validate against the new schema.
src = os.path.join("assets", "data", "ga-members.json")
if os.path.exists(src):
    doc = json.load(open(src, encoding="utf-8"))
    check("committed ga-members.json validates against the new metadata schema",
          validate(P.members_schema(), doc), None)
    check("committed ga-members.json carries metadata.session",
          bool(doc["metadata"].get("session")), True)
    check("build_members emits the session column",
          P.build_members()["data/members.csv"].decode().splitlines()[0].split(",")[14] == "session", True)

# --- votes / scorecard CSVs ------------------------------------------------ #
v = list(csv.reader(io.StringIO(P.votes_csv({"x": {"date": "d"}}, "2026_ss").decode())))
check("votes.csv ends with session", (v[0][-1], v[1][-1]), ("session", "2026_ss"))
sc = list(csv.reader(io.StringIO(P.scorecard_csv([{"id": "i"}], "2025-2026").decode())))
check("scorecard.csv ends with biennium", (sc[0][-1], sc[1][-1]), ("biennium", "2025-2026"))

# --- schema identity ------------------------------------------------------- #
# Every schema must declare the path it is actually written to. They used to share
# one hardcoded $id apiece: both sessions' votes.schema.json claimed to be
# `sessions/votes.schema.json`, a URL no file occupies, and the frozen roster's copy
# claimed to be the live `data/members.schema.json`. Two documents under one $id is a
# resolver cache away from serving the wrong body.
written = {}
for artifacts in (P.build_members(), P.build_votes(), P.build_scorecard(),
                  P.build_freeze_roster("2025-2026")):
    for path, blob in artifacts.items():
        if path.endswith(".schema.json"):
            written[path] = json.loads(blob)

check("every mode emitted a schema", len(written) >= 4, True)
for path, doc in sorted(written.items()):
    check(f"$id matches its path: {path}",
          doc.get("$id"),
          f'{getattr(P, "RAW_BASE", "<no RAW_BASE>")}/{path}')
    check(f"schemaVersion present: {path}",
          doc.get("schemaVersion"),
          getattr(P, "SCHEMA_VERSION", "<no SCHEMA_VERSION>"))
    check(f"schemaStability present: {path}", bool(doc.get("schemaStability")), True)

ids = [d.get("$id") for d in written.values()]
check("no two schemas share an $id", len(ids), len(set(ids)))

# The stability prose has to say that metadata.session is NOT required and why, or a
# consumer has no way to learn the guarantee short of reading the publisher.
members_stability = written["data/members.schema.json"].get("schemaStability", "")
check("members stability explains the session guarantee",
      "required" in members_stability and "2026-10" in members_stability, True)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
