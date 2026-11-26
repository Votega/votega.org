#!/usr/bin/env python3
"""Offline checks for the MCP index builder (scripts/lib/mcp_index.py, build_mcp_index.py).

Pins: the member keys (ga:<legisGaGovId> / us:<bioguideId>) and that the roster id appears only
as a vote-slice name built by the same transform as build_member_votes_slices; vgId merge
forwards; slices null when no file exists; federal chamber from the LAST term; former members
(frozen-only, never with contact details, the approved departure label copied); bill shards that
lose no bill, with a title word table; races and candidates resolved by the site's own ballot and
standing rules, never keyed on a roster id; local mentions; local officials
filtered by the term rules (history dropped, incoming kept) with blanks as null; ZIP sharding
loses nothing; the county index is counties_doc() over the committed tract table; and every
tier-1 rule in index_errors() with a negative control. Stdlib only, no network.

Usage: python scripts/test_mcp_index.py
"""
import contextlib
import copy
import gzip
import hashlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import mcp_index as M  # noqa: E402
from lib import mcp_bills as MB  # noqa: E402
from lib import mcp_elections as ME  # noqa: E402
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402
import build_mcp_index as B  # noqa: E402
import validate_mcp_index as V  # noqa: E402
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


# ---- former members: 103 and 104 are only in frozen bienniums; 101 is frozen but still serving
def frozen_rec(gid, name, **kw):
    return {"id": f"ocd-person/f-{gid}", "name": name, "chamber": "House of Representatives", "district": 3,
            "legisGaGovId": gid, "status": None, "statusDate": None, "phone": "555", "email": "x@y.gov",
            "address": "Capitol", "officialWebsiteUrl": "https://legis.ga.gov/x",
            "votegaUrl": f"https://www.votega.org/ga-legislators/m{gid}/", **kw}


FROZEN = {"2023_24": {"103": frozen_rec(103, "Gone Early", status="Resigned", statusDate="2023-05-02"),
                      "104": frozen_rec(104, "Gone Late")},
          "2025_26": {"104": frozen_rec(104, "Gone Late"), "101": frozen_rec(101, "Ann One")}}
LABELS = {"metadata": {"session": "2025_26"}, "labels": {"104": {"label": "Did not run for re-election in 2026."},
                                                         "103": {"label": "WRONG SESSION"}}}
FROZEN_SLICES = {"ga-bienniums/2025_26/ga-votes/ocd-person-f-104.json"}


# ---- bills: the live file plus one frozen biennium (which repeats a live bill)
def bill(session, ident, lid, title):
    return {"legislationId": lid, "identifier": ident, "session": session, "billType": "bill", "title": title,
            "abstract": "A BILL", "status": "House Second Readers", "statusDate": "2025-01-15T10:00:00",
            "subjects": ["TAX"], "sponsors": [{"name": "Ann One", "primary": True, "legisGaGovId": 101}],
            "billUrl": f"https://www.legis.ga.gov/legislation/{lid}", "textUrl": "", "passageVotes": [],
            "governorAction": None}


LIVE_BILLS = {"metadata": {"generatedAt": GEN, "activeSession": "2026_ss"}, "bills": [
    bill("2025_26", "HB 1", 11, "Income tax; credit for the taxpayers"),
    bill("2025_26", "SR 2", 12, "Commend Ann One"),
    bill("2026_ss", "HB 1EX", 13, "Ad valorem tax; exemption"),
]}
OLD_BILLS = {"metadata": {"generatedAt": GEN}, "bills": [
    bill("2023_24", "HB 1", 9, "Old tax bill"), bill("2025_26", "HB 1", 11, "STALE COPY")]}

# ---- races and candidates
RACES = {"updatedAt": GEN, "races": [
    {"id": "sen-2026", "level": "federal", "chamber": "U.S. Senate", "cycle": 2026, "activePhase": "general",
     "status": "certified", "winner": {"name": "Cal Three", "memberId": "A000001", "phase": "general"},
     "phases": {"primary": {"electionDate": "2026-05-19", "ballots": {"Republican": [
                    {"id": "c-lost", "name": "Lou Lost", "type": "challenger", "email": "lou@x.com"}]}},
                "general": {"electionDate": "2026-11-03", "ballots": {
                    "Democrat": [{"type": "incumbent", "memberId": "A000001", "memberSource": "congress"}],
                    "Republican": [{"id": "c-beat", "name": "Bea Beaten", "type": "challenger"}]}}}},
    {"id": "house-5-2026", "level": "state", "chamber": "Georgia House of Representatives", "district": 5,
     "cycle": 2026, "activePhase": "general",
     "phases": {"general": {"electionDate": "2026-11-03", "ballots": {"Democrat": [
         {"id": "c-ann", "name": "Ann One", "type": "incumbent", "isIncumbent": True,
          "existingMemberId": "ocd-person/aaaa-1111", "existingMemberSource": "state"},
         {"id": "c-quit", "name": "Quin Quit", "type": "challenger", "withdrawn": True}]}}}},
]}
RACE_URLS = {**URLS, "race": {"sen-2026": "/races/sen-2026/", "house-5-2026": "/races/house-5-2026/"},
             "candidate": {"c-ann": "/candidates/ann-one-ga-house-5/"}}
ELECTION_XWALK = {"metadata": XWALK["metadata"], "people": XWALK["people"] + [
    {"vgId": "vg-ga-p-000007", "ids": {"votegaCandidateIds": ["c-lost"]}}]}


# ---- local topic mentions
def mention(place, date, **kw):
    return {"placeId": place, "placeName": place.title(), "placeType": "county", "date": date, "body": "Board",
            "docType": "agenda", "terms": ["flock"], "confidence": "high", "excerpt": "long text",
            "sourceUrl": f"https://example.gov/{place}/{date}", **kw}


TOPICS = [
    {"metadata": {"topic": "alpr", "label": "ALPR", "generatedAt": GEN},
     "mentions": [mention("newton", "2026-01-05"), mention("covington", "2026-03-01", minutesUrl="")]},
    {"metadata": {"topic": "budget", "label": "Budget", "generatedAt": GEN},
     "mentions": [mention("newton", "2026-02-01")]},
]


def build_all():
    county = counties_doc(B.load_json(TRACTS_SRC))
    docs = {
        "members-index.json": M.build_members(GA, FED, XWALK, URLS, SLICES, GEN, 119),
        "counties-index.json": M.build_counties(county, GEN),
        "local-officials-index.json": M.build_local_officials(OFFICIALS, OFFICERS, PLACES,
                                                              GA_COUNTY_FIPS, TODAY, GEN),
        "resources.json": M.build_resources(MCP_TEXT, OPEN_DATA, GEN),
        "former-members-index.json": M.build_former_members(GA, FROZEN, LABELS, XWALK, FROZEN_SLICES, GEN),
        "local-mentions-index.json": M.build_local_mentions(TOPICS, PLACES, GA_COUNTY_FIPS, GEN),
    }
    docs.update(MB.build_bills([LIVE_BILLS, OLD_BILLS], GEN))
    docs.update(ME.build_elections(RACES, GA, FED, FROZEN, ELECTION_XWALK, RACE_URLS, GEN))
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
       "open_data_ids": {"ga-legislators"}, "frozen": FROZEN, "bill_docs": [LIVE_BILLS, OLD_BILLS],
       "races": RACES, "topic_docs": TOPICS}
SRC["slices"] = SLICES | FROZEN_SLICES


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

print("former members")
former = docs["former-members-index.json"]
frows = {r["key"]: r for r in former["members"]}
check("only people missing from the live roster", sorted(frows), ["ga:103", "ga:104"])
check("newest frozen biennium wins; all served listed, newest first",
      (frows["ga:104"]["biennium"], frows["ga:104"]["bienniums"]), ("2025_26", ["2025_26", "2023_24"]))
check("never contact details", {frows["ga:104"][k] for k in ("phone", "email", "officialWebsiteUrl")}, {None})
check("not serving", frows["ga:104"]["serving"], False)
check("approved label copied for its own session", frows["ga:104"]["departure"], "Did not run for re-election in 2026.")
check("a label from another session is not used", frows["ga:103"]["departure"], "Resigned May 2, 2023")
check("frozen vote slice named", frows["ga:104"]["slices"],
      {"votes": "ga-bienniums/2025_26/ga-votes/ocd-person-f-104.json", "sponsorship": None})
check("no frozen bienniums means no former rows",
      M.build_former_members(GA, {}, LABELS, XWALK, set(), GEN)["members"], [])

print("bills")
cat = docs["bills/sessions.json"]
sess = {x["session"]: x for x in cat["sessions"]}
check("live and frozen sessions listed", sorted(sess), ["2023_24", "2025_26", "2026_ss"])
check("live and active flags", [(s, sess[s]["live"], sess[s]["active"]) for s in sorted(sess)],
      [("2023_24", False, False), ("2025_26", True, False), ("2026_ss", True, True)])
check("Commons slugs", [sess[s]["commonsSlug"] for s in sorted(sess)], ["2023-2024", "2025-2026", "2026-special"])
check("unknown session shape gets no slug", MB.commons_slug("odd"), None)
check("each bill carries its Commons page",
      docs["bills/2025_26-HB-detail.json"]["bills"]["HB 1"]["commonsUrl"],
      "https://georgiacommons.org/bills/2025-2026/hb1")
check("Commons drops the special session's EX suffix",
      docs["bills/2026_ss-HB-detail.json"]["bills"]["HB 1EX"]["commonsUrl"],
      "https://georgiacommons.org/bills/2026-special/hb1")
check("no Commons link for an unknown session shape", MB.commons_url("odd", "HB 1"), None)
check("one shard per session and type", [x["path"] for x in sess["2025_26"]["shards"]],
      ["bills/2025_26-HB.json", "bills/2025_26-SR.json"])
hb = docs["bills/2025_26-HB.json"]
check("the live copy beats the frozen one", [b["title"] for b in hb["bills"]], ["Income tax; credit for the taxpayers"])
check("sponsors are [legisGaGovId, primary] with names alongside",
      (hb["bills"][0]["sponsors"], hb["sponsorNames"]), ([[101, True]], {"101": "Ann One"}))
detail = docs["bills/2025_26-HB-detail.json"]["bills"]["HB 1"]
check("detail carries links and votes; blank is null", (detail["textUrl"], detail["passageVotes"]), (None, []))
tok = docs["bills/2025_26-HB-tokens.json"]
check("one word table per shard", [x["tokensPath"] for x in sess["2025_26"]["shards"]],
      ["bills/2025_26-HB-tokens.json", "bills/2025_26-SR-tokens.json"])
check("word -> bills", sorted(tok["identifiers"][i] for i in tok["tokens"]["tax"]), ["HB 1"])
check("function words and single characters left out",
      MB.tokenize("A Tax of the X; for taxpayers"), ["tax", "taxpayers"])

print("races and candidates")
races = {r["id"]: r for r in docs["races-index.json"]["races"]}
cands = {c["key"]: c for c in docs["candidates-index.json"]["candidates"]}
check("a member-only incumbent is keyed us:<bioguide>; no roster id anywhere",
      (sorted(cands), "ocd-person" in json.dumps([races, cands])),
      (["c-ann", "c-beat", "c-lost", "c-quit", "us:A000001"], False))
check("name and party filled from the roster", (cands["us:A000001"]["name"], cands["us:A000001"]["party"]),
      ("Cal Three", "Democrat"))
check("standing follows the certified winner", [cands[k]["standing"] for k in ("us:A000001", "c-beat", "c-lost")],
      ["won", "lost", "lost"])
check("winner points at a candidate row", races["sen-2026"]["winner"]["key"], "us:A000001")
check("active ballot only; withdrawn left off", races["house-5-2026"]["candidates"], ["c-ann"])
check("withdrawn candidate keeps a row", (cands["c-quit"]["withdrawn"], cands["c-quit"]["standing"]), (True, "off-ballot"))
check("state member resolved to ga:<legisGaGovId> with its vgId",
      (cands["c-ann"]["memberKey"], cands["c-ann"]["vgId"]), ("ga:101", "vg-ga-p-000001"))
check("vgId from the candidate crosswalk", cands["c-lost"]["vgId"], "vg-ga-p-000007")
check("no candidate emails", "lou@x.com" in json.dumps(cands), False)
check("election date of the active phase", races["sen-2026"]["electionDate"], "2026-11-03")
check("page links", (races["sen-2026"]["votegaUrl"], cands["c-ann"]["votegaUrl"], cands["us:A000001"]["votegaUrl"]),
      ("https://www.votega.org/races/sen-2026/", "https://www.votega.org/candidates/ann-one-ga-house-5/",
       "https://www.votega.org/us-congress/cal-three/"))

print("local mentions")
lm = docs["local-mentions-index.json"]
check("newest first", [(x["place"], x["topic"]) for x in lm["mentions"]],
      [("covington", "alpr"), ("newton", "budget"), ("newton", "alpr")])
check("topics read from the files", [(t["slug"], t["count"]) for t in lm["metadata"]["topics"]],
      [("alpr", 2), ("budget", 1)])
check("excerpts are not carried; blank is null",
      ("excerpt" in lm["mentions"][0], lm["mentions"][0]["minutesUrl"]), (False, None))
check("place county resolved through the parent", lm["metadata"]["places"]["covington"]["countyFips"], "13217")

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

def gone(name):
    return lambda d, m: (d.pop(name), m["__claimed__"].pop(name), m.pop(name))


neg("a missing former index", gone("former-members-index.json"), "former-members-index.json is missing")
neg("a former member with a phone", lambda d, m: d["former-members-index.json"]["members"][0].update(phone="1"),
    "contact details")
neg("a sitting member in the former index", lambda d, m: d["former-members-index.json"]["members"][0].update(
    key="ga:101"), "former members differ")
neg("a missing frozen slice", lambda d, m: d["former-members-index.json"]["members"][1]["slices"].update(
    votes="ga-bienniums/x.json"), "does not exist")
neg("a lost bill", lambda d, m: d["bills/2025_26-HB.json"]["bills"].clear(), "bills differ")
neg("a bill in the wrong shard", lambda d, m: d["bills/2025_26-HB.json"]["bills"][0].update(identifier="SB 9"),
    "wrong shard")
neg("a detail file out of step", lambda d, m: d["bills/2025_26-HB-detail.json"]["bills"].clear(), "detail")
neg("a stale word table", lambda d, m: d["bills/2025_26-HB-tokens.json"]["tokens"].pop("tax"), "word table")
neg("a missing shard listed in the catalog", gone("bills/2023_24-HB.json"), "is not built")
neg("a lost race", lambda d, m: d["races-index.json"]["races"].pop(0), "races differ")
neg("a race naming no candidate row", lambda d, m: d["races-index.json"]["races"][0]["candidates"].append("nope"),
    "no candidate row")
neg("a lost candidate", lambda d, m: d["candidates-index.json"]["candidates"].pop(0), "candidates differ")
neg("a roster id used as a member key", lambda d, m: d["candidates-index.json"]["candidates"][0].update(
    memberKey="ocd-person/x"), "memberKey")
neg("a lost mention", lambda d, m: d["local-mentions-index.json"]["mentions"].pop(), "mentions differ")

print("isolation: a new group can fail without taking the live tools' files with it")
check("files sorted into groups", [M.group_of(n) for n in (
    "members-index.json", "zip/300.json", "resources.json", "bills/sessions.json", "races-index.json",
    "candidates-index.json", "former-members-index.json", "local-mentions-index.json")],
    ["core", "core", "core", "bills", "elections", "elections", "former-members", "local-mentions"])

bad_winner = copy.deepcopy(RACES)
bad_winner["races"][0]["winner"] = {"name": "Typo", "candidateId": "c-nobody", "phase": "general"}
typo = ME.build_elections(bad_winner, GA, FED, FROZEN, ELECTION_XWALK, RACE_URLS, GEN)
check("a winner matching nobody has no key, as the pages ignore it",
      {r["id"]: r["winner"] for r in typo["races-index.json"]["races"]}["sen-2026"]["key"], None)
check("and it passes the checks", ME.election_errors(typo, bad_winner), [])


def explode():
    raise KeyError("topic")


with contextlib.redirect_stderr(io.StringIO()):  # the expected traceback
    built, failed = B.build_optional({"bills": lambda: MB.build_bills([LIVE_BILLS], GEN),
                                      "local-mentions": explode})
check("a builder that raises is reported and the others still build",
      ("bills/sessions.json" in built, sorted(failed), "topic" in failed["local-mentions"]),
      (True, ["local-mentions"], True))

CORE_FILES = ["counties-index.json", "local-officials-index.json", "members-index.json", "resources.json",
              "zip/300.json", "zip/310.json"]


def finish(mutate=lambda d: None, failed_groups=(), **src_changes):
    """Write the fixture index to disk, run the validator on it -> (exit code, files left, meta)."""
    d = build_all()
    mutate(d)
    with tempfile.TemporaryDirectory() as root:
        out = os.path.join(root, "mcp")
        B.write_index(out, d, {
            "sources": B.SOURCES, "failedGroups": list(failed_groups),
            "sessions": {"ga": {"session": "2025_26", "activeBillSession": "2026_ss"}},
            "localTopics": d.get("local-mentions-index.json", {}).get("metadata", {}).get("topics", []),
            "sourceStamps": {"ga-members": GEN, "ga-bills": GEN, "races": GEN}}, GEN)
        with contextlib.redirect_stdout(io.StringIO()):
            code = V.finish(out, {**SRC, **src_changes})
        left, actual = V.read_out(out)
        with open(os.path.join(out, "meta.json"), "rb") as f:
            meta = json.load(f)
    return code, sorted(left), meta, actual


ALL = sorted(build_all())
code, left, meta, _ = finish()
check("clean: exit 0, every file kept", (code, left), (0, ALL))

code, left, meta, actual = finish(lambda d: d["races-index.json"]["races"].pop(0))
check("a bad election index: exit 3, only the election files removed",
      (code, left), (3, [n for n in ALL if n not in ("races-index.json", "candidates-index.json")]))
check("meta.json matches what is left", (sorted(meta["files"]), meta["metadata"]["count"]), (left, len(left)))
check("meta.json says which group failed", [x["group"] for x in meta["failedGroups"]], ["elections"])
check("its source stamp and source list go with it",
      ("races" in meta["sourceStamps"], "races-index.json" in meta["sources"]), (False, False))
check("the pruned index validates", M.grouped_errors(
    {n: d for n, d in build_all().items() if n in left}, actual,
    {**SRC, "load_errors": {"elections": "dropped"}}).get("core"), None)

code, left, meta, _ = finish(load_errors={"bills": "ga-bills.json is not JSON"})
check("an unreadable bills source drops bills only",
      (code, [n for n in left if n.startswith("bills/")], set(CORE_FILES) <= set(left)), (3, [], True))
check("no active bill session is claimed",
      (meta["sessions"]["ga"]["activeBillSession"], meta["sessions"]["ga"]["session"]), (None, "2025_26"))

code, left, meta, _ = finish(lambda d: d["local-mentions-index.json"]["mentions"].pop())
check("bad mentions: no topics are advertised",
      (code, "local-mentions-index.json" in left, meta["localTopics"]), (3, False, []))

code, left, meta, _ = finish(races=None)
check("a check that itself crashes drops its group, not the index",
      (code, "races-index.json" in left, set(CORE_FILES) <= set(left)), (3, False, True))

code, left, meta, _ = finish(lambda d: [d.pop(n) for n in ("former-members-index.json",)],
                             failed_groups=[{"group": "former-members", "reason": "build crashed"}])
check("a group the build could not make: exit 3, reason kept once",
      (code, meta["failedGroups"]), (3, [{"group": "former-members", "reason": "build crashed"}]))

code, left, meta, _ = finish(lambda d: d["members-index.json"]["members"].pop(0))
check("a core failure still fails the whole index", (code, left), (1, ALL))

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nAll MCP index checks passed.")
