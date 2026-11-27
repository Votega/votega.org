"""Build the school-district registry artifacts from _data/school_districts.yml.

Pure functions over the parsed YAML (no yaml import, no network), so they are
testable with no dependencies. publish_ga_local_government.py loads the files and
calls build_district_artifacts().

Published: the DISTRICTS (all county and city systems). Not published: board
members (rosters are partial and separately human-gated), the internal `notes`,
and the `meetings` scraper settings.

Nothing here reads the clock: generatedAt is when the registry file last changed
(source_updated_at), so an unchanged registry republishes identically.

Blank is always None (JSON null / empty CSV cell), never "".
"""

import csv
import io
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.sibling_publish import build_json  # noqa: E402

REPO_RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-local-government/main"
SCHEMA_VERSION = "1.0.0"
OUT_DIR = "data/school-districts"
DATASET = "school-districts"
UPDATED_AT_ENV = "SCHOOL_DISTRICTS_UPDATED_AT"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Column order is the published contract; new columns are APPENDED only.
COLUMNS = ["districtId", "name", "type", "countyFips", "officeCountyFips",
           "primaryPlaceId", "districtCensusId", "boardSize", "termYears",
           "partisan", "officialUrl"]

_STR = ["string", "null"]
_INT = ["integer", "null"]
PROPERTIES = {
    "districtId": {"type": "string",
                   "description": "Georgia GOSA district code, as a string"},
    "name": {"type": "string", "description": "district name"},
    "type": {"enum": ["county", "city"],
             "description": "county system or independent city system; curated, "
                            "not derivable from the name"},
    "countyFips": {"type": "array", "items": {"type": "string"},
                   "description": "5-digit FIPS of every county the system is "
                                  "recorded as serving (joins data/places.json "
                                  "`fips`). Not a boundary: it does not say which "
                                  "district serves an address"},
    "officeCountyFips": {"type": _STR,
                         "description": "county of the district office"},
    "primaryPlaceId": {"type": _STR,
                       "description": "city place a city system is named for, where "
                                      "VoteGA covers it (data/places.json `placeId`)"},
    "districtCensusId": {"type": _STR,
                         "description": "5-digit Census school-district code; not a "
                                        "county FIPS"},
    "boardSize": {"type": _INT,
                  "description": "authorized board seats; null = not yet recorded"},
    "termYears": {"type": _INT,
                  "description": "length of a board term; null = not yet recorded"},
    "partisan": {"type": ["boolean", "null"],
                 "description": "true = partisan board elections, false = "
                                "nonpartisan, null = not yet recorded"},
    "officialUrl": {"type": _STR,
                    "description": "board's official page; null = not yet recorded"},
}

STABILITY = (
    "Stable field names and meanings. One row per active Georgia school district. "
    "`districtId` is the state's own district code. A blank value is null, never "
    "an empty string; null board facts mean not yet recorded. New fields are "
    "appended, never reordered.")


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
    return None if v in (None, "") else v


def _county_fips(district, fips_by_slug):
    if district.get("type") == "county":
        return [str(district["countyFips"])]
    out = []
    for slug in district.get("counties") or []:
        if not fips_by_slug.get(slug):
            raise ValueError(
                f"school district {district.get('id')}: county slug {slug!r} has no "
                "fips in places.yml, so the published row would drop a county")
        out.append(fips_by_slug[slug])
    if not out:
        raise ValueError(f"school district {district.get('id')}: no county")
    return sorted(out)


def _row(d, fips_by_slug):
    office = d.get("countyFips") if d.get("type") == "county" else d.get("officeCountyFips")
    values = {
        "districtId": str(d["id"]),
        "name": d.get("name"),
        "type": d.get("type"),
        "countyFips": _county_fips(d, fips_by_slug),
        "officeCountyFips": str(office) if office else None,
        "primaryPlaceId": d.get("primaryPlace"),
        "districtCensusId": d.get("districtCensusId"),
        "boardSize": d.get("board_size"),
        "termYears": d.get("term_years"),
        "partisan": d.get("partisan"),
        "officialUrl": d.get("official_url"),
    }
    return {c: _blank_to_none(values[c]) for c in COLUMNS}


def _csv_cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "; ".join(v)
    return v


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: _csv_cell(r[c]) for c in COLUMNS})
    return buf.getvalue().encode()


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          encoding="utf-8").stdout.strip()


def source_updated_at(path, env=None, git=_git):
    """When `path` last changed, as UTC "YYYY-MM-DDTHH:MM:SSZ".

    $SCHOOL_DISTRICTS_UPDATED_AT wins (the workflow asks the GitHub API, because
    its checkout is shallow). Otherwise git, but only with complete history: in a
    shallow clone `git log` answers with the checked-out commit's date, which
    would claim the registry changed on every run.
    """
    env = os.environ if env is None else env
    stamp = (env.get(UPDATED_AT_ENV) or "").strip()
    if not stamp:
        if git("rev-parse", "--is-shallow-repository") != "false":
            raise ValueError(f"shallow clone: set {UPDATED_AT_ENV} to the date "
                             f"{path} last changed")
        stamp = git("log", "-1", "--format=%cI", "--", path)
    if not stamp:
        raise ValueError(f"no commit date for {path}")
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_district_artifacts(data, places, updated_at):
    """-> (artifacts {remote path: bytes}, summary dict)."""
    fips_by_slug = {p["slug"]: str(p["fips"]) for p in places if p.get("fips")}
    districts = (data.get("countyDistricts") or []) + (data.get("cityDistricts") or [])
    rows = sorted((_row(d, fips_by_slug) for d in districts),
                  key=lambda r: r["districtId"])
    county = sum(1 for r in rows if r["type"] == "county")
    p = {k: f"{OUT_DIR}/{k}" for k in (
        "districts.json", "districts.csv", "districts.schema.json")}
    artifacts = {
        p["districts.json"]: build_json({
            "metadata": {"generatedAt": updated_at, "publisher": "VoteGA.org",
                         "schemaVersion": SCHEMA_VERSION, "count": len(rows),
                         "countyDistricts": county,
                         "cityDistricts": len(rows) - county},
            "districts": rows}),
        p["districts.csv"]: to_csv(rows),
        p["districts.schema.json"]: build_json({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": f"{REPO_RAW_BASE}/{p['districts.schema.json']}",
            "title": "VoteGA Georgia school district",
            "schemaVersion": SCHEMA_VERSION,
            "schemaStability": STABILITY,
            "type": "object",
            "required": ["districtId", "name", "type", "countyFips"],
            "properties": PROPERTIES,
        }),
    }
    summary = {"count": len(rows), "county": county, "city": len(rows) - county,
               "paths": p}
    return artifacts, summary
