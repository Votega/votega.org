#!/usr/bin/env python3
"""Offline invariants of the school-district registry export. No network, no deps.

Pinned: one row per district from both lists, county FIPS resolved for both
kinds (a county system from countyFips, a city system through its place slugs),
rosters and internal fields never leave, blanks are null / empty CSV cells, the
schema $id matches its published path, the output carries no wall-clock time, and
an unresolvable slug fails rather than silently dropping a county.

Run: python scripts/test_publish_school_districts.py
"""
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import school_districts_export as sd  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)


DATA = {
    "cityDistricts": [{
        "id": "763", "name": "Demo City", "type": "city", "counties": ["beta", "alpha"],
        "primaryPlace": "demotown", "districtCensusId": "00510", "officeCountyFips": "13003",
        "board_size": 5, "term_years": 4, "partisan": False, "official_url": "https://x",
        "notes": "internal", "meetings": {"platform": "simbli", "id": "1"},
        "members": [{"name": "A Person", "role": "Chair", "source": "https://x"}],
    }],
    "countyDistricts": [{
        "id": "601", "name": "Alpha County", "type": "county", "countyFips": "13001",
        "districtCensusId": "00030",
    }],
}
PLACES = [{"slug": "alpha", "fips": "13001"}, {"slug": "beta", "fips": 13003},
          {"slug": "demotown"}]
AS_OF = "2026-11-18T21:33:55Z"

arts, summ = sd.build_district_artifacts(DATA, PLACES, AS_OF)
P = summ["paths"]
doc = json.loads(arts[P["districts.json"]])
rows = {r["districtId"]: r for r in doc["districts"]}

check(sorted(arts) == ["data/school-districts/districts.csv",
                       "data/school-districts/districts.json",
                       "data/school-districts/districts.schema.json"], f"paths: {sorted(arts)}")
check([r["districtId"] for r in doc["districts"]] == ["601", "763"], "one row per district, sorted by id")
check(doc["metadata"]["count"] == 2 and summ["count"] == 2, "count")
check(doc["metadata"]["generatedAt"] == AS_OF, "generatedAt is the data's own stamp")
check(summ["county"] == 1 and summ["city"] == 1, "county/city split")

county, city = rows["601"], rows["763"]
check(county["countyFips"] == ["13001"] and county["officeCountyFips"] == "13001",
      f"county system fips: {county}")
check(city["countyFips"] == ["13001", "13003"] and city["officeCountyFips"] == "13003",
      f"city system serves every listed county: {city}")
check(city["primaryPlaceId"] == "demotown" and county["primaryPlaceId"] is None, "primaryPlaceId")
check(city["boardSize"] == 5 and city["termYears"] == 4 and city["partisan"] is False, "board facts")
check(county["boardSize"] is None and county["partisan"] is None and county["officialUrl"] is None,
      "unrecorded -> null")
check(list(county) == sd.COLUMNS and list(city) == sd.COLUMNS, "every row has the contract columns")

blob = b"".join(arts.values()).decode()
for leak in ("A Person", "internal", "simbli", "members"):
    check(leak not in blob, f"{leak!r} must not be published")

table = list(csv.DictReader(io.StringIO(arts[P["districts.csv"]].decode())))
check(table[1]["countyFips"] == "13001; 13003", "CSV joins the list")
check(table[1]["partisan"] == "false" and table[0]["partisan"] == "", "CSV booleans: false is not blank")
check(table[0]["districtCensusId"] == "00030", "zero padding survives")
check("None" not in arts[P["districts.csv"]].decode(), "CSV leaks 'None'")

sch = json.loads(arts[P["districts.schema.json"]])
check(sch["$id"] == "https://raw.githubusercontent.com/Votega/ga-local-government/main/"
      + P["districts.schema.json"], "$id is the published path")
check(sch["schemaVersion"] == sd.SCHEMA_VERSION and sch["schemaStability"], "version + stability")
check(sorted(sch["properties"]) == sorted(sd.COLUMNS), "schema describes every column")

check(sd.build_district_artifacts(DATA, PLACES, AS_OF)[0] == arts, "two builds are byte-identical")

for label, bad in (("unknown slug", [PLACES[0], PLACES[2]]),
                   ("slug without fips", [PLACES[0], {"slug": "beta"}])):
    try:
        sd.build_district_artifacts(DATA, bad, AS_OF)
        check(False, f"{label} must fail the build")
    except ValueError:
        pass

# The stamp: an env override wins; a shallow clone is refused, never guessed.
check(sd.source_updated_at("x", env={"SCHOOL_DISTRICTS_UPDATED_AT": "2026-11-18T16:33:55-05:00"},
                           git=None) == AS_OF, "env stamp normalised to UTC")


def fake_git(shallow, log):
    return lambda *args: shallow if args[0] == "rev-parse" else log


check(sd.source_updated_at("x", env={}, git=fake_git("false", "2026-11-18T16:33:55-05:00")) == AS_OF,
      "git commit date when history is complete")
for label, g in (("shallow clone", fake_git("true", "2026-11-18T16:33:55-05:00")),
                 ("no commit", fake_git("false", ""))):
    try:
        sd.source_updated_at("x", env={}, git=g)
        check(False, f"{label} must refuse to stamp")
    except ValueError:
        pass

if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("ok")
