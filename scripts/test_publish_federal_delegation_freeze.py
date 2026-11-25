#!/usr/bin/env python3
"""The federal delegation's per-Congress freeze (publish_federal_delegation.py freeze).

The daily publish replaces data/ in Votega/ga-federal-legislators, so on 3 January 2027 the
119th Congress's record would be overwritten by the 120th's. `freeze` keeps it under
sessions/<slug>/. What must hold:

  * a freeze writes only under sessions/<slug>/, and the daily publish refuses to write
    anything there;
  * data from a different Congress is never filed under the slug (after 3 January the live
    files are the 120th's, so a late `freeze 119th` must refuse rather than mislabel);
  * a final freeze is not replaced without --overwrite, but provisional -> final is the plan;
  * each frozen schema declares the path it lives at and a version;
  * every CSV ends with a `congress` column, and the sponsorship slices decode to flat rows.

Run: python scripts/test_publish_federal_delegation_freeze.py   (no network, no repo writes)
"""
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_federal_delegation as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def exits(fn):
    try:
        fn()
    except SystemExit:
        return True
    return False


def rows(blob):
    return list(csv.reader(io.StringIO(blob.decode())))


MEMBERS = {"metadata": {"generatedAt": "2026-10-29T00:00:00+00:00"}, "members": [
    {"bioguideId": "W000790", "name": "Warnock, Raphael G.", "partyName": "Democratic",
     "state": "Georgia", "terms": {"item": [{"chamber": "Senate"}]}},
    {"bioguideId": "X000000", "name": "Other State", "partyName": "Republican",
     "state": "Ohio", "terms": {"item": [{"chamber": "Senate"}]}}]}
VOTES = {"metadata": {"congress": 119, "generatedAt": "2026-10-15T00:00:00+00:00"},
         "votes": {"S119_1_00001": {"chamber": "Senate", "date": "2025-01-09", "bill": "S. 5",
                                    "title": "A bill", "result": "Passed", "yea": 60, "nay": 40}},
         "memberVotes": {"W000790": [{"voteId": "S119_1_00001", "vote": "Yea"}]}}
UNITY = {"metadata": {"congress": 119, "generatedAt": "2026-10-15T04:00:00+00:00"},
         "members": {"W000790": {"name": "Warnock, Raphael G.", "chamber": "Senate",
                                 "party": "Democratic", "partyUnity": 0.95}}}
SP_INDEX = {"metadata": {"congress": 119, "generatedAt": "2026-10-29T00:00:00+00:00",
                         "totalSponsored": 1, "totalCosponsored": 1},
            "members": {"W000790": [1, 1]}}
SLICE = {"bioguideId": "W000790", "congress": 119,
         "actions": ["Referred to Committee."], "policyAreas": ["Health"],
         "primary": [["S", "5690", "Renewing the Dream Act", "2026-10-15", "2026-10-15", 0, 0]],
         "cosponsored": [["SRES", "950", "A resolution", "2026-10-15", "2026-10-15", 0, None]]}
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def freeze(slug="119th", kind="provisional", votes=VOTES, unity=UNITY, index=SP_INDEX):
    return P.build_freeze(slug, kind, MEMBERS, votes, unity, index, {"W000790": SLICE}, now=NOW)


# --- everything lands under sessions/<slug>/
art = freeze()
check("every freeze artifact is under sessions/119th/",
      all(p.startswith("sessions/119th/") for p in art), True)
check("the freeze has a manifest, a README and the slice",
      {"sessions/119th/freeze.json", "sessions/119th/README.md",
       "sessions/119th/sponsorship/W000790.json"} <= set(art), True)
check("only the Georgia member is frozen",
      json.loads(art["sessions/119th/members.json"])["metadata"]["count"], 1)
check("an artifact outside sessions/ is refused",
      exits(lambda: P.assert_archive_paths({"data/members.json": b"x"}, "119th")), True)
check("the daily publish refuses to write into sessions/",
      exits(lambda: P.assert_no_archive_paths({"sessions/119th/votes.json": b"x"})), True)
check("the daily publish may write data/",
      exits(lambda: P.assert_no_archive_paths({"data/votes.json": b"x"})), False)

# --- never file one Congress's data under another's name
v120 = {"metadata": {"congress": 120}, "votes": {}, "memberVotes": {}}
check("120th votes are refused under 119th",
      exits(lambda: P.build_freeze("119th", "final", MEMBERS, v120, UNITY, SP_INDEX, {})), True)
u120 = {"metadata": {"congress": 120}, "members": {}}
check("a scorecard from another Congress is refused",
      exits(lambda: freeze(unity=u120)), True)
m120 = {"metadata": {"generatedAt": "2027-01-03T06:00:00+00:00", "congress": 120}, "members": MEMBERS["members"]}
check("a roster already turned over to the 120th is refused under 119th",
      exits(lambda: P.build_freeze("119th", "final", m120, VOTES, UNITY, SP_INDEX, {"W000790": SLICE})), True)
m119 = {"metadata": {"generatedAt": "2026-12-30T06:00:00+00:00", "congress": 119}, "members": MEMBERS["members"]}
check("a stamped 119th roster is accepted",
      exits(lambda: P.build_freeze("119th", "final", m119, VOTES, UNITY, SP_INDEX, {"W000790": SLICE})), False)
check("slug derives from the votes file's Congress", P.resolve_freeze_slug(None, VOTES), "119th")
check("an explicit slug must look like 119th", exits(lambda: P.resolve_freeze_slug("2025-2027", VOTES)), True)

# --- final freezes are not replaced casually
check("provisional -> provisional is fine", exits(lambda: P.check_freeze_state("provisional", "provisional", False)), False)
check("provisional -> final is fine", exits(lambda: P.check_freeze_state("provisional", "final", False)), False)
check("nothing -> final is fine", exits(lambda: P.check_freeze_state(None, "final", False)), False)
check("final -> final needs --overwrite", exits(lambda: P.check_freeze_state("final", "final", False)), True)
check("final -> provisional needs --overwrite", exits(lambda: P.check_freeze_state("final", "provisional", False)), True)
check("--overwrite allows replacing a final", exits(lambda: P.check_freeze_state("final", "final", True)), False)
check("an unknown kind is refused", exits(lambda: P.check_freeze_state(None, "draft", False)), True)

# --- schemas declare their own path and a version
for name in ("members", "votes"):
    sch = json.loads(art[f"sessions/119th/{name}.schema.json"])
    check(f"{name} schema $id is its own path", sch["$id"].endswith(f"/sessions/119th/{name}.schema.json"), True)
    check(f"{name} schema carries a version", bool(sch.get("schemaVersion")), True)
check("the live schema keeps the data/ $id",
      P.members_schema()["$id"].endswith("/data/members.schema.json"), True)

# --- CSVs name their Congress in the last column
for f in ("members.csv", "votes.csv", "member-votes.csv", "scorecard.csv", "sponsorship.csv"):
    r = rows(art[f"sessions/119th/{f}"])
    check(f"{f} ends with a congress column = 119", (r[0][-1], r[1][-1]), ("congress", "119"))
check("live members.csv also names the Congress",
      rows(P.members_csv([{"bioguideId": "W000790"}], 119))[1][-1], "119")

# --- sponsorship slices decode to flat rows
sp = rows(art["sessions/119th/sponsorship.csv"])
check("one row per sponsored or cosponsored bill", len(sp) - 1, 2)
check("a sponsored row carries its decoded action and policy area",
      (sp[1][1], sp[1][2], sp[1][3], sp[1][7], sp[1][8]), ("sponsor", "S", "5690", "Referred to Committee.", "Health"))
check("a row with no policy index leaves it blank", (sp[2][1], sp[2][8]), ("cosponsor", ""))

# --- the manifest says what was frozen
man = json.loads(art["sessions/119th/freeze.json"])
check("manifest kind and congress", (man["kind"], man["congress"], man["slug"]), ("provisional", 119, "119th"))
check("manifest counts", man["counts"]["sponsored"], 1)
check("a final freeze says final", json.loads(freeze(kind="final")["sessions/119th/freeze.json"])["kind"], "final")

# --- en bloc nominee table: one row per roll call per nominee, no per-senator column
NOM = {"metadata": {"congress": 119, "generatedAt": "2026-12-30T00:00:00+00:00", "source": "Senate.gov"},
       "batches": {"b1": [{"pn": "PN55-25", "name": "Ann Alpha", "state": "Ohio", "position": "Judge",
                           "title": "Ann Alpha, of Ohio, to be Judge"},
                          {"pn": "PN18", "name": None, "state": None, "position": None, "title": "A list"}]},
       "votes": {"S119_1_00526": "b1", "S119_1_00525": "b1", "S119_9_99999": "b1"}, "pending": []}
NOM_VOTES = {"metadata": VOTES["metadata"], "memberVotes": VOTES["memberVotes"],
             "votes": dict(VOTES["votes"], S119_1_00526={"date": "2025-09-18"},
                           S119_1_00525={"date": "2025-09-17"})}
with_nom = P.build_freeze("119th", "final", MEMBERS, NOM_VOTES, UNITY, SP_INDEX, {"W000790": SLICE},
                          nominees_doc=NOM)
base = "sessions/119th/en-bloc-nominees"
check("the freeze carries the table, its CSV and its schema",
      [f"{base}.json" in with_nom, f"{base}.csv" in with_nom, f"{base}.schema.json" in with_nom],
      [True, True, True])
table = json.loads(with_nom.get(f"{base}.json", b'{"metadata": {}, "nominees": []}'))
check("one row per roll call and nominee, only for roll calls in votes.json",
      [(r["voteId"], r["pn"]) for r in table["nominees"]],
      [("S119_1_00525", "PN55-25"), ("S119_1_00525", "PN18"),
       ("S119_1_00526", "PN55-25"), ("S119_1_00526", "PN18")])
check("the columns are exactly the nominee fields",
      list(table["nominees"][0]) if table["nominees"] else None,
      ["voteId", "pn", "name", "state", "position", "title"])
check("the table names its Congress and count",
      (table["metadata"].get("congress"), table["metadata"].get("count")), (119, 4))
ncsv = rows(with_nom[f"{base}.csv"]) if f"{base}.csv" in with_nom else [[], []]
check("CSV header ends with congress",
      ncsv[0], ["voteId", "pn", "name", "state", "position", "title", "congress"])
nschema = json.loads(with_nom.get(f"{base}.schema.json", b"{}"))
check("the schema says one vote covers the whole batch",
      "one vote" in nschema.get("description", "").lower(), True)
check("schema $id is its own path", nschema.get("$id", "").endswith(f"/{base}.schema.json"), True)
check("the README lists the table", b"en-bloc-nominees" in with_nom["sessions/119th/README.md"], True)
check("a freeze taken without the file still works, with no table",
      any("en-bloc" in p for p in freeze()), False)
check("and its README does not claim one", b"en-bloc" in freeze()["sessions/119th/README.md"], False)
check("another Congress's nominee file is refused",
      exits(lambda: P.build_freeze("119th", "final", MEMBERS, NOM_VOTES, UNITY, SP_INDEX, {"W000790": SLICE},
                                   nominees_doc=dict(NOM, metadata={"congress": 120}))), True)
empty = P.nominee_artifacts("data", {"metadata": {"congress": 120}, "batches": {}, "votes": {}}, {}, 120)
check("an empty file at a turnover publishes an empty table",
      (json.loads(empty["data/en-bloc-nominees.json"])["nominees"],
       len(rows(empty["data/en-bloc-nominees.csv"]))), ([], 1))
votes_schema = P.votes_schema()["properties"]["votes"]["additionalProperties"]
check("votes schema describes the new fields, requiring neither",
      ("documentType" in votes_schema["properties"], "nomineeCount" in votes_schema["properties"],
       "required" in votes_schema), (True, True, False))

if failures:
    print(f"\n{len(failures)} failed")
    sys.exit(1)
print("\nall passed")
