#!/usr/bin/env python3
"""Offline checks for the MCP index builder (scripts/lib/mcp_index.py, build_mcp_index.py).

Pins: the member keys (ga:<legisGaGovId> / us:<bioguideId>) and that the roster id appears only
as a vote-slice name built by the same transform as build_member_votes_slices; vgId merge
forwards; slices null when no file exists; federal chamber from the LAST term; local officials
filtered by the term rules (history dropped, incoming kept) with blanks as null; ZIP sharding
loses nothing; the county index is counties_doc() over the committed tract table; and every
tier-1 rule in index_errors() with a negative control. Stdlib only, no network.

Usage: python scripts/test_mcp_index.py
"""
import copy
import gzip
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import mcp_index as M  # noqa: E402
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402
import build_mcp_index as B  # noqa: E402
from build_member_votes_slices import member_slug as site_member_slug  # noqa: E402
from publish_ga_district_information import TRACTS_SRC, counties_doc  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


GEN = "2026-11-21T00:00:00+00:00"
TODAY = "2026-11-21"

GA = {"metadata": {"session": "2025_26", "legisSessionId": 1033, "generatedAt": GEN},
      "members": [
          {"id": "ocd-person/aaaa-1111", "name": "Ann One", "firstName": "Ann", "lastName": "One",
           "party": "Democratic", "chamber": "House of Representatives", "district": 5,
           "legisGaGovId": 101, "status": None, "statusDate": None, "email": "",
           "votegaUrl": "https://www.votega.org/ga-legislators/ann-one-house-5/"},
          {"id": "legis-102", "name": "Bob Two", "firstName": "Bob", "lastName": "Two",
           "party": "Republican", "chamber": "Senate", "district": 9, "legisGaGovId": 102,
           "status": "Resigned", "statusDate": "2026-03-01",
           "votegaUrl": "https://www.votega.org/ga-legislators/bob-two-senate-9/"},
          {"id": "ocd-person/exec", "name": "Gov", "chamber": "executive", "legisGaGovId": None},
      ]}
FED = {"metadata": {"generatedAt": GEN}, "members": [
    {"bioguideId": "A000001", "firstName": "Cal", "lastName": "Three", "partyName": "Democratic",
     "state": "Georgia", "district": None,
     "terms": {"item": [{"chamber": "House of Representatives"}, {"chamber": "Senate"}]}},
    {"bioguideId": "B000002", "firstName": "Dee", "lastName": "Four", "partyName": "Republican",
     "state": "Georgia", "district": 7, "terms": {"item": [{"chamber": "House of Representatives"}]}},
    {"bioguideId": "Z000009", "firstName": "Out", "lastName": "Ofstate", "state": "Michigan",
     "terms": {"item": [{"chamber": "Senate"}]}},
]}
XWALK = {"metadata": {"mergedVgIds": {"vg-ga-p-000009": "vg-ga-p-000002"}}, "people": [
    {"vgId": "vg-ga-p-000001", "ids": {"legisGaGovId": 101}},
    {"vgId": "vg-ga-p-000009", "ids": {"legisGaGovId": 102}},  # retired: forwards to 000002
    {"vgId": "vg-ga-p-000003", "ids": {"bioguideId": "A000001"}},
    {"vgId": "vg-ga-p-000004", "ids": {"bioguideId": "B000002"}},
]}
URLS = {"us-congress": {"A000001": "/us-congress/cal-three/", "B000002": "/us-congress/dee-four-ga-7/"}}
SLICES = {"ga-votes/ocd-person-aaaa-1111.json", "ga-sponsorship/101.json",
          "federal-votes/A000001.json", "federal-votes/B000002.json", "federal-sponsorship/B000002.json"}

ZIPDOC = {"metadata": {"hudRelease": "2026 Q2", "generatedAt": GEN}, "zips": {
    "30002": {"city": "A", "kind": "standard"}, "30003": {"city": "B", "kind": "po-box"},
    "31001": {"city": "C", "kind": "standard"}}}

OFFICIALS = {"meta": {"last_reviewed": "2026-09-05"}, "jurisdictions": [
    {"id": "newton", "name": "Newton County", "type": "county", "county": "Newton", "body": "Board",
     "partisan": True, "official_url": "https://example.gov", "members": [
         {"name": "Sitting", "role": "Commissioner", "seat": "District 1", "seat_id": "district-1",
          "email": "", "phone": "555", "source": "https://example.gov/1", "leaves_office": "2027-01-01"},
         {"name": "Incoming", "role": "Commissioner", "seat": "District 1", "seat_id": "district-1",
          "email": "", "source": "https://example.gov/2", "takes_office": "2027-01-01"},
         {"name": "Former", "role": "Commissioner", "seat": "District 2", "seat_id": "district-2",
          "source": "https://example.gov/3", "leaves_office": "2026-01-01"},
     ]},
    {"id": "covington", "name": "City of Covington", "type": "city", "county": "Newton",
     "members": [{"name": "Mayor M", "role": "Mayor", "seat": "Mayor", "seat_id": "mayor",
                  "source": "https://example.gov/4"}]},
]}
OFFICERS = {"counties": [
    {"id": "newton", "name": "Newton County", "officers": [
        {"name": "Sheriff S", "role": "Sheriff", "seat": "Countywide", "source": "https://example.gov/5"}]},
    {"id": "ben-hill", "name": "Ben Hill County", "officers": [
        {"name": "Sheriff B", "role": "Sheriff", "seat": "Countywide", "source": "https://example.gov/6"}]},
]}
MCP_TEXT = {"about": {"summary": "VoteGA is nonpartisan.", "principles": ["Nonpartisan."],
                      "covers": ["Who represents a ZIP."], "not_yet": ["Bills."],
                      "license": "CC BY-SA 4.0.", "corrections": "Email us."},
            "glossary": [{"term": "District", "definition": "An area.\n  It has a member."},
                         {"term": "Share", "definition": "A fraction."}]}
OPEN_DATA = {"meta": {"intro": "Reusable data."}, "datasets": [
    {"id": "ga-legislators", "title": "GA Legislators", "summary": "Roster &amp; votes",
     "cadence": "Daily &amp; weekly", "docs": "/about-the-data#ga-legislators",
     "files": [{"name": "data/all.json", "desc": "Roster", "url": "https://github.com/x/y/blob/main/data/all.json"}]},
]}

PLACES = {"places": [
    {"slug": "newton", "name": "Newton County", "type": "county", "fips": "13217", "parentCounty": None},
    {"slug": "covington", "name": "Covington", "type": "city", "fips": None, "parentCounty": "newton"},
    {"slug": "ben-hill", "name": "Ben Hill County", "type": "county", "fips": "13017", "hidden": True},
]}


def build_all():
    county = counties_doc(B.load_json(TRACTS_SRC))
    docs = {
        "members-index.json": M.build_members(GA, FED, XWALK, URLS, SLICES, GEN, 119),
        "counties-index.json": M.build_counties(county, GEN),
        "local-officials-index.json": M.build_local_officials(OFFICIALS, OFFICERS, PLACES,
                                                              GA_COUNTY_FIPS, TODAY, GEN),
        "resources.json": M.build_resources(MCP_TEXT, OPEN_DATA, GEN),
    }
    for p, shard in M.build_zip_shards(ZIPDOC, GEN).items():
        docs[f"zip/{p}.json"] = shard
    return docs


def file_meta(docs):
    actual, claimed = {}, {}
    for name, doc in docs.items():
        raw = B.encode(doc)
        actual[name] = {"bytes": len(raw), "gzipBytes": len(gzip.compress(raw, mtime=0)),
                        "sha256": hashlib.sha256(raw).hexdigest()}
        claimed[name] = B.file_entry(raw, doc["metadata"].get("count"))
    actual["__claimed__"] = claimed
    return actual


SRC = {"ga": GA, "federal": FED, "zipdoc": ZIPDOC, "county_fips": set(GA_COUNTY_FIPS.values()),
       "place_slugs": {"newton", "covington", "ben-hill"}, "jurisdiction_ids": {"newton", "covington"},
       "officer_ids": {"newton", "ben-hill"}, "slices": SLICES, "retired_vgids": {"vg-ga-p-000009"},
       "open_data_ids": {"ga-legislators"}}


def errors_after(mutate):
    docs = build_all()
    meta = file_meta(docs)
    mutate(docs, meta)
    return M.index_errors(docs, meta, SRC)


print("members")
docs = build_all()
rows = {r["key"]: r for r in docs["members-index.json"]["members"]}
check("keys are ga:<gid> and us:<bioguide>; executive and out-of-state rows dropped",
      sorted(rows), ["ga:101", "ga:102", "us:A000001", "us:B000002"])
check("member_slug matches build_member_votes_slices.member_slug",
      M.member_slug("ocd-person/aaaa-1111"), site_member_slug("ocd-person/aaaa-1111"))
check("vote slice named from the roster id", rows["ga:101"]["slices"]["votes"], "ga-votes/ocd-person-aaaa-1111.json")
check("slice null when the file does not exist", rows["ga:102"]["slices"], {"votes": None, "sponsorship": None})
check("merged vgId forwarded to the survivor", rows["ga:102"]["vgId"], "vg-ga-p-000002")
check("departed member: serving false", rows["ga:102"]["serving"], False)
check("blank email is null", rows["ga:101"]["email"], None)
check("federal chamber from the LAST term", rows["us:A000001"]["chamber"], "Senate")
check("senator has no district", rows["us:A000001"]["district"], None)
check("federal votegaUrl is absolute", rows["us:B000002"]["votegaUrl"], "https://www.votega.org/us-congress/dee-four-ga-7/")
check("metadata counts", (docs["members-index.json"]["metadata"]["state"]["count"],
                          docs["members-index.json"]["metadata"]["federal"]["count"]), (2, 2))

print("ZIP shards and counties")
check("one shard per 3-digit prefix", sorted(k for k in docs if k.startswith("zip/")), ["zip/300.json", "zip/310.json"])
check("shard keeps every ZIP", sorted(docs["zip/300.json"]["zips"]), ["30002", "30003"])
check("county index: all 159 counties, 5-digit FIPS", sorted(docs["counties-index.json"]["counties"]) ==
      sorted(GA_COUNTY_FIPS.values()), True)
newton = docs["counties-index.json"]["counties"]["13217"]
check("county shares sum to ~1 per chamber", all(abs(sum(r["share"] for r in newton[ch]) - 1) < 1e-3
                                                for ch in ("state-senate", "state-house", "us-house")), True)

print("local officials")
lo = docs["local-officials-index.json"]
names = [m["name"] for m in lo["places"]["newton"]["members"]]
check("history dropped, sitting and incoming kept", names, ["Sitting", "Incoming"])
check("incoming row keeps its takesOffice", lo["places"]["newton"]["members"][1]["takesOffice"], "2027-01-01")
check("blank email is null", lo["places"]["newton"]["members"][0]["email"], None)
check("city gets its county FIPS from the county name", lo["places"]["covington"]["countyFips"], "13217")
check("sheriff-only county included, kept apart from members",
      (lo["places"]["ben-hill"]["members"], [o["name"] for o in lo["places"]["ben-hill"]["constitutionalOfficers"]]),
      ([], ["Sheriff B"]))
check("hidden place has no page URL", lo["places"]["ben-hill"]["votegaUrl"], None)
check("byCounty", lo["byCounty"], {"13017": ["ben-hill"], "13217": ["covington", "newton"]})
check("lastReviewed carried", lo["metadata"]["lastReviewed"], "2026-09-05")

print("resources")
res = docs["resources.json"]
check("HTML entities unescaped for plain text", res["datasets"]["datasets"][0]["summary"], "Roster & votes")
check("docs path made absolute, exactly as written",
      res["datasets"]["datasets"][0]["docs_url"], "https://www.votega.org/about-the-data#ga-legislators")
check("open-data page URL has no trailing slash (/open-data/ is a 404)", res["datasets"]["page_url"],
      "https://www.votega.org/open-data")
check("absolute file URLs pass through", res["datasets"]["datasets"][0]["files"][0]["url"],
      "https://github.com/x/y/blob/main/data/all.json")
check("whitespace collapsed", res["glossary"][0]["definition"], "An area. It has a member.")
check("about carries the page URL", res["about"]["page_url"], "https://www.votega.org/ai-assistants/")
check("site_url leaves a file path alone", M.site_url("/assets/data/x.json"), "https://www.votega.org/assets/data/x.json")

print("index_errors")
check("clean build has no errors", errors_after(lambda d, m: None), [])


def neg(label, mutate, needle):
    errs = errors_after(mutate)
    hit = any(needle in e for e in errs)
    check(f"catches {label}", hit, True)
    if not hit:
        print("       errors were:", errs)


neg("a hash mismatch", lambda d, m: m["__claimed__"]["members-index.json"].update(sha256="0"), "sha256 does not match")
neg("a file missing from meta.json", lambda d, m: m["__claimed__"].pop("zip/310.json"), "not in meta.json")
neg("an over-budget file", lambda d, m: m["zip/300.json"].update(gzipBytes=M.GZIP_BUDGET + 1), "over the")
neg("an empty string", lambda d, m: d["members-index.json"]["members"][0].update(phone=""), "empty string")
neg("a duplicate key", lambda d, m: d["members-index.json"]["members"].append(
    copy.deepcopy(d["members-index.json"]["members"][0])), "appears twice")
neg("a malformed key", lambda d, m: d["members-index.json"]["members"][0].update(key="ocd-person/x"), "is not ga:")
neg("a missing slice", lambda d, m: d["members-index.json"]["members"][0]["slices"].update(votes="ga-votes/nope.json"),
    "does not exist")
neg("a retired vgId", lambda d, m: d["members-index.json"]["members"][1].update(vgId="vg-ga-p-000009"), "retired vgId")
neg("a dropped roster member", lambda d, m: d["members-index.json"]["members"].pop(0), "GA roster mismatch")
neg("a lost ZIP", lambda d, m: d["zip/300.json"]["zips"].pop("30002"), "do not match ga-zip-districts")
neg("a ZIP under the wrong prefix", lambda d, m: d["zip/310.json"]["zips"].update({"30009": {}}), "wrong prefix")
neg("a lost county", lambda d, m: d["counties-index.json"]["counties"].pop("13217"), "counties differ")
neg("a former official listed", lambda d, m: d["local-officials-index.json"]["places"]["newton"]["members"].append(
    {"name": "Old", "leavesOffice": "2026-01-01", "source": "x"}), "left office")
neg("an official without a source", lambda d, m: d["local-officials-index.json"]["places"]["covington"]["members"][0]
    .update(source=None), "has no source")
neg("a place with no county", lambda d, m: d["local-officials-index.json"]["places"]["covington"]
    .update(countyFips=None), "no valid county FIPS")

neg("HTML in a resource", lambda d, m: d["resources.json"]["glossary"][0].update(definition="ga:<number>"), "HTML at")
neg("a dataset missing from resources", lambda d, m: d["resources.json"]["datasets"]["datasets"].clear(),
    "do not match _data/open_data.yml")
neg("a duplicate glossary term", lambda d, m: d["resources.json"]["glossary"].append(
    dict(d["resources.json"]["glossary"][0])), "duplicate term")
neg("an empty about summary", lambda d, m: d["resources.json"]["about"].update(summary=None), "about.summary")
neg("a missing resources file", lambda d, m: (d.pop("resources.json"), m["__claimed__"].pop("resources.json"),
                                             m.pop("resources.json")), "resources.json is missing")

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nAll MCP index checks passed.")
