#!/usr/bin/env python3
"""Generate assets/data/ga-zip-districts.json: for every Georgia ZIP code, the
counties and the legislative districts it touches, each ranked by the estimated
share of the ZIP's residents living there.

    HUD-USPS crosswalks (ZIP -> tract, ZIP -> county, ZIP -> congressional district;
    residential-address ratios, quarterly)
  + scripts/data/ga-tract-districts.json  (tract -> 2020 population by 2023 state
    Senate / House district; built by build_ga_tract_district_table.py)
  + scripts/data/usps-ga-zips.json        (which ZIPs are real Georgia delivery ZIPs,
    and which are PO-box-only; built by build_usps_ga_zips.py)
  -> assets/data/ga-zip-districts.json

How a ZIP's state district shares are estimated
-----------------------------------------------
HUD says what fraction of a ZIP's residential addresses sit in each census tract.
The tract table says what fraction of each tract's residents live in each district.
Their product, summed over the ZIP's tracts, is the ZIP's share in a district.
Tracts with no residents are left out and the rest renormalised, so a tract that
is all empty blocks cannot add a district nobody lives in.

EVERY district with any share is listed, ranked biggest first. Nothing is cut off:
a voter on the edge of a ZIP lives in a small sliver, and hiding the sliver is
exactly how they would get the wrong ballot. The share is published so a consumer
can choose to mark small ones, never so this file can drop them.

This is "districts touching the ZIP", never "your district". A ZIP can span
several, and only a street address resolves one.

Needs HUD_USER_TOKEN in the environment (never printed, never written). A HUD
failure exits 1 and leaves the committed file untouched.

Usage:
    python scripts/generate_ga_zip_districts.py [out_path]
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import datetime

from lib.atomic_io import write_json_atomic

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
DEFAULT_OUT = os.path.join(ROOT, "assets", "data", "ga-zip-districts.json")
TRACT_TABLE = os.path.join(HERE, "data", "ga-tract-districts.json")
USPS_ZIPS = os.path.join(HERE, "data", "usps-ga-zips.json")

HUD_URL = "https://www.huduser.gov/hudapi/public/usps"
HUD_TYPES = {"zip-tract": 1, "zip-county": 2, "zip-cd": 5}
GA_STATE_FIPS = "13"
#: Shares are rounded for the file; a district with any share at all is still
#: listed, at no less than this.
SHARE_FLOOR = 0.00001
SHARE_DIGITS = 5


def http_get_json(url, token, tries=4):
    """GET with retries on 429/5xx only; any other 4xx is not retryable."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt * 2)
                continue
            sys.exit(f"FATAL: HUD returned HTTP {e.code} for {url} "
                     "(401 = bad token, 403 = token not registered for this dataset)")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt * 2)
    sys.exit(f"FATAL: gave up fetching {url}")


def fetch_hud(token):
    """{'zip-tract': [...], ...} plus the data's year/quarter."""
    out, vintage = {}, set()
    for name, type_no in HUD_TYPES.items():
        data = http_get_json(f"{HUD_URL}?type={type_no}&query=GA", token)["data"]
        out[name] = data["results"]
        vintage.add((str(data.get("year")), str(data.get("quarter"))))
    if len(vintage) != 1:
        sys.exit(f"FATAL: the three HUD crosswalks are from different releases: {sorted(vintage)}")
    year, quarter = next(iter(vintage))
    return out, year, quarter


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def title_city(name):
    """HUD gives upper case; this is only a display label."""
    return re.sub(r"\b([A-Za-z])([A-Za-z']*)", lambda m: m.group(1).upper() + m.group(2).lower(), name or "")


def _weights(rows):
    """Residential-address ratios for one ZIP; the total ratio when it has no
    residential addresses at all (a business-only ZIP)."""
    res = [(r["geoid"], float(r["res_ratio"])) for r in rows]
    if sum(w for _, w in res) > 0:
        return [(g, w) for g, w in res if w > 0]
    tot = [(r["geoid"], float(r["tot_ratio"])) for r in rows]
    return [(g, w) for g, w in tot if w > 0]


def _ranked(shares):
    """[(key, share)] -> [{'district'|..: key, 'share': s}] biggest first, ties by key."""
    total = sum(shares.values())
    if total <= 0:
        return None
    out = [(k, max(round(v / total, SHARE_DIGITS), SHARE_FLOOR)) for k, v in shares.items() if v > 0]
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def state_shares(tract_rows, tracts, chamber):
    """Estimated share of a ZIP's residents in each district of one chamber."""
    weights = [(t, w) for t, w in _weights(tract_rows) if tracts.get(t, {}).get("p", 0) > 0]
    shares = {}
    for t, w in weights:
        rec = tracts[t]
        for district, pop in rec[chamber].items():
            shares[district] = shares.get(district, 0.0) + w * pop / rec["p"]
    return _ranked(shares)


def build_entries(hud, tract_table, usps):
    """{zip: entry}. Pure: no network, no files."""
    tracts, county_names = tract_table["tracts"], tract_table["counties"]
    by = {name: {} for name in HUD_TYPES}
    city = {}
    for name, rows in hud.items():
        for r in rows:
            by[name].setdefault(r["zip"], []).append(r)
            city.setdefault(r["zip"], r.get("city"))

    entries = {}
    for z in sorted(set(usps["zips"]) | set(by["zip-tract"])):
        kind = usps["zips"].get(z, "unverified")
        entry = {"city": title_city(city.get(z)) or None, "kind": kind,
                 "counties": None, "stateSenate": None, "stateHouse": None, "usHouse": None}
        if kind != "po-box" and z in by["zip-tract"]:
            counties = _ranked({g[2:]: w for g, w in _weights(by["zip-county"].get(z, []))
                                if g.startswith(GA_STATE_FIPS)})
            if counties:
                entry["counties"] = [{"fips": f, "name": county_names.get(f), "share": s} for f, s in counties]
            for key, chamber in (("stateSenate", "s"), ("stateHouse", "h")):
                ranked = state_shares(by["zip-tract"][z], tracts, chamber)
                if ranked:
                    entry[key] = [{"district": int(d), "share": s} for d, s in ranked]
            cds = _ranked({int(g[len(GA_STATE_FIPS):]): w for g, w in _weights(by["zip-cd"].get(z, []))
                           if g.startswith(GA_STATE_FIPS)})
            if cds:
                entry["usHouse"] = [{"district": d, "share": s} for d, s in cds]
        entries[z] = entry
    return entries


def build_document(entries, year, quarter, tract_table, generated_at):
    with_districts = sum(1 for e in entries.values() if e["stateHouse"])
    return {
        "metadata": {
            "generatedAt": generated_at,
            "source": "HUD-USPS ZIP Code Crosswalk (residential-address ratios), combined with the "
                      "Georgia General Assembly's 2023 Senate and House plans and 2020 Census "
                      "block populations",
            "hudRelease": f"{year} Q{quarter}",
            "statePlans": tract_table["metadata"]["plans"],
            "censusVintage": tract_table["metadata"]["censusVintage"],
            "count": len(entries),
            "withDistricts": with_districts,
            "poBox": sum(1 for e in entries.values() if e["kind"] == "po-box"),
            "unverified": sum(1 for e in entries.values() if e["kind"] == "unverified"),
            "meaning": "Districts and counties TOUCHING the ZIP, ranked by estimated share of the ZIP's "
                       "residents, largest first. Every district with any residents is listed. "
                       "A ZIP is not a district: only a street address identifies the districts "
                       "a voter lives in. PO-box ZIPs carry no districts.",
        },
        "zips": entries,
    }


def keep_generated_at(doc, path):
    """A quiet quarter must commit nothing: reuse the old stamp when nothing but
    the stamp would change."""
    try:
        old = load_json(path)
    except (OSError, ValueError):
        return doc
    probe = json.loads(json.dumps(doc))
    probe["metadata"]["generatedAt"] = old.get("metadata", {}).get("generatedAt")
    if probe == old:
        doc["metadata"]["generatedAt"] = old["metadata"]["generatedAt"]
    return doc


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    token = os.environ.get("HUD_USER_TOKEN")
    if not token:
        sys.exit("FATAL: HUD_USER_TOKEN is not set")
    tract_table, usps = load_json(TRACT_TABLE), load_json(USPS_ZIPS)
    hud, year, quarter = fetch_hud(token)
    entries = build_entries(hud, tract_table, usps)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    doc = keep_generated_at(build_document(entries, year, quarter, tract_table, now), out)
    write_json_atomic(out, doc, separators=(",", ":"))
    m = doc["metadata"]
    print(f"Wrote {out}: {m['count']} ZIPs ({m['withDistricts']} with districts, {m['poBox']} PO-box, "
          f"{m['unverified']} not in the USPS Georgia list); HUD {m['hudRelease']}")


if __name__ == "__main__":
    main()
