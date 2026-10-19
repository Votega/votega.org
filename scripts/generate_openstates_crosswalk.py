#!/usr/bin/env python3
"""Resolve each Georgia legislator's external identifiers from openstates/people.

    legisGaGovId  ->  ocdPersonId, ballotpediaId

Output: assets/data/ga-openstates-crosswalk.json, a SIDECAR keyed by legisGaGovId. The
roster producer (generate_ga_members_soap.py) merges it into ga-members.json as nullable
slots with provenance, so exactly one script ever writes the roster. Nothing here is
load-bearing for identity: legisGaGovId is the primary key, the roster `id` is an opaque
handle that never changes, and these are cross-references that land whenever they arrive.
See scripts/lib/ga_identity.py.

Source and licence
------------------
The `openstates/people` GitHub repository (data/ga/legislature + data/ga/retired). The
repository is dedicated to the public domain under CC0 1.0 (its LICENSE file, GitHub's
licence metadata and the README all say so), so it is compatible with this site's
CC BY-SA 4.0 data licence and needs no attribution. No API key, no quota, no CORS. The
repo also LEADS the Open States v3 API by days on roster changes, so it is the better
place to notice a newly seated member. This script does not touch the v3 API and must
never be given OPENSTATES_API_KEY.

How a person is matched (verified against the live repo on 2026-10-19)
----------------------------------------------------------------------
* There is NO `other_identifiers` entry carrying the General Assembly's member id, and no
  Wikidata identifier anywhere in the repo. The legisGaGovId appears only as the trailing
  number of a legis.ga.gov profile link (`https://www.legis.ga.gov/members/senate/5097`)
  in a person's `links` / `sources`. That link IS the member's own page, so the join is
  exact, but it is a link, not a declared identifier — recorded in the provenance.
* One legisGaGovId can be claimed by two person files (Derrick Jackson, 4891: a current
  file and a retired duplicate). The rule is deterministic: if exactly one claimant is in
  `legislature/` it wins and the retired duplicates are listed in `review`; if there is
  not exactly one, the member is `ambiguous` and gets NO value rather than a guess.
* A person with two distinct Ballotpedia links (8 files) is `ambiguous` for that slot.
* Two members resolving to the same ocdPersonId / ballotpediaId would be a join error;
  both are demoted to `ambiguous` and null.
* There is no wikidataId slot: the repo does not carry one and no other source we read does,
  so it was dropped rather than published as a permanently empty column.
* An OCD id is passed through only if it has the OCD shape. Never invented or derived.

Failure policy: any fetch failure exits 1 and leaves the file untouched (a partial read
would publish false "no-match"es). A slot that was resolved in the committed sidecar and
comes back null is also fatal — that is an upstream gap or outage, not news.

Usage:
    python scripts/generate_openstates_crosswalk.py [--out PATH] [--roster PATH]
                                                    [--apply-roster]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_identity import (OPENSTATES_SOURCE, apply_to_roster_file,  # noqa: E402
                             is_ocd_id)

OUTPUT_FILE = "assets/data/ga-openstates-crosswalk.json"
ROSTER_FILE = "assets/data/ga-members.json"

REPO = "openstates/people"
DIRS = ("legislature", "retired")
LISTING_URL = "https://api.github.com/repos/" + REPO + "/contents/data/ga/{d}"
COMMIT_URL = "https://api.github.com/repos/" + REPO + "/commits/main"
UA = "votega.org identity resolver (https://votega.org)"
DELAY = 0.05
MIN_DOCS = 200            # the legislature dir alone has ~235; far below that is a bad read

LEGIS_LINK = re.compile(r"legis\.ga\.gov/members/(?:senate|house)/(\d+)", re.I)
BALLOTPEDIA_LINK = re.compile(r"^https?://(?:www\.)?ballotpedia\.org/([^?#]+)", re.I)

MATCH_NOTE = ("matched on the member's legisGaGovId appearing in the person file's "
              "legis.ga.gov profile link; openstates/people declares no such identifier")


# ---------------------------------------------------------------------------- parsing

def person_urls(doc):
    return [l.get("url") for l in (doc.get("links") or []) + (doc.get("sources") or [])
            if isinstance(l, dict) and l.get("url")]


def legis_ids(doc):
    return {int(m.group(1)) for u in person_urls(doc) for m in [LEGIS_LINK.search(u)] if m}


def ballotpedia_ids(doc):
    out = set()
    for u in person_urls(doc):
        m = BALLOTPEDIA_LINK.match(u)
        if m:
            out.add(urllib.parse.unquote(m.group(1)).rstrip("/"))
    return out


# --------------------------------------------------------------------------- resolution

def _prov(confidence, **extra):
    out = {"method": "authoritative", "source": OPENSTATES_SOURCE, "confidence": confidence}
    out.update(extra)
    return out


def resolve_member(legis_id, claims):
    """-> (doc entry or None, ocd provenance, retired duplicates it superseded)."""
    claimants = claims.get(legis_id) or []
    if not claimants:
        return None, _prov("no-match", note="no openstates/people file links this member"), []
    current = [c for c in claimants if c["dir"] == "legislature"]
    pick = None
    if len(claimants) == 1:
        pick = claimants[0]
    elif len(current) == 1:
        pick = current[0]
    if pick is None:
        return None, _prov("ambiguous", candidates=sorted(c["doc"]["id"] for c in claimants),
                           note="more than one person file claims this legisGaGovId and "
                                "none is the sole current one"), []
    superseded = sorted(c["doc"]["id"] for c in claimants if c is not pick)
    return pick, _prov("high", key="legisGaGovId", note=MATCH_NOTE), superseded


def build_sidecar(people_docs, roster, *, generated_at, upstream_commit=None, previous=None):
    """people_docs: [{"dir": "legislature"|"retired", "doc": <parsed person yaml>}].

    Pure function of its inputs — the injected-fetcher tests drive this directly.
    """
    claims = {}
    for entry in people_docs:
        doc = entry["doc"]
        if not is_ocd_id(doc.get("id")):
            continue                      # never carry a value that is not OCD-shaped
        for lid in legis_ids(doc):
            claims.setdefault(lid, []).append(entry)

    members = sorted({m["legisGaGovId"]: m for m in roster
                      if m.get("legisGaGovId") is not None}.items())
    out, review = {}, {"noMatch": [], "ambiguous": [], "supersededRetiredDuplicates": {},
                       "ocdDiffersFromRosterId": [], "duplicateValueDemoted": []}

    for lid, m in members:
        pick, ocd_prov, superseded = resolve_member(lid, claims)
        rec = {"ocdPersonId": None, "ballotpediaId": None, "provenance": {}}
        if pick is not None:
            rec["ocdPersonId"] = pick["doc"]["id"]
            rec["provenance"]["ocdPersonId"] = ocd_prov
            if superseded:
                review["supersededRetiredDuplicates"][str(lid)] = superseded
            if is_ocd_id(m.get("id")) and m["id"] != rec["ocdPersonId"]:
                review["ocdDiffersFromRosterId"].append(
                    f"{m.get('name')} ({lid}): roster id {m['id']}, upstream {rec['ocdPersonId']}")
            bp = sorted(ballotpedia_ids(pick["doc"]))
            if len(bp) == 1:
                rec["ballotpediaId"] = bp[0]
                rec["provenance"]["ballotpediaId"] = _prov("high", note=(
                    "the Ballotpedia page title from the person file's sources"))
            elif len(bp) > 1:
                rec["provenance"]["ballotpediaId"] = _prov("ambiguous", candidates=bp)
                review["ambiguous"].append(f"{m.get('name')} ({lid}): ballotpedia {bp}")
            else:
                rec["provenance"]["ballotpediaId"] = _prov(
                    "no-match", note="the person file carries no Ballotpedia link")
        else:
            rec["provenance"]["ocdPersonId"] = ocd_prov
            rec["provenance"]["ballotpediaId"] = _prov(
                "no-match", note="the person was not resolved, so there is no file to read")
            (review["ambiguous"] if ocd_prov["confidence"] == "ambiguous"
             else review["noMatch"]).append(f"{m.get('name')} ({lid})")
        out[str(lid)] = rec

    # Two members must never share a value: that would credit one person with another's id.
    for slot in ("ocdPersonId", "ballotpediaId"):
        owners = {}
        for lid, rec in out.items():
            if rec[slot]:
                owners.setdefault(rec[slot], []).append(lid)
        for value, lids in owners.items():
            if len(lids) > 1:
                for lid in lids:
                    out[lid][slot] = None
                    out[lid]["provenance"][slot] = _prov(
                        "ambiguous", candidates=sorted(lids),
                        note=f"{value} resolved for {len(lids)} members; none is kept")
                review["duplicateValueDemoted"].append(f"{slot} {value}: legisGaGovIds {sorted(lids)}")

    regressions = []
    for lid, old in ((previous or {}).get("people") or {}).items():
        for slot in ("ocdPersonId", "ballotpediaId"):
            if old.get(slot) and lid in out and not out[lid][slot]:
                regressions.append(f"{lid} {slot}: was {old[slot]}, now null")

    resolved = {s: sum(1 for r in out.values() if r[s]) for s in ("ocdPersonId", "ballotpediaId")}
    sidecar = {
        "metadata": {
            "generatedAt": generated_at,
            "source": "openstates/people (data/ga/legislature + data/ga/retired), CC0 1.0",
            "upstreamCommit": upstream_commit,
            "count": len(out),
            "resolved": resolved,
            "license": "CC0-1.0 — public-domain dedication, compatible with CC BY-SA 4.0 publication",
            "primaryKey": "legisGaGovId",
            "matching": MATCH_NOTE,
        },
        "people": dict(sorted(out.items(), key=lambda kv: int(kv[0]))),
        "review": {k: v for k, v in review.items()},
    }
    return sidecar, regressions


# ------------------------------------------------------------------------------ network

def _get(url, retries=3):
    """GET bytes. Retries 429/5xx; any other failure raises (a partial read is worse than none)."""
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            if e.code == 403 and e.headers.get("x-ratelimit-remaining") == "0":
                raise RuntimeError("GitHub API rate limit exhausted; set GITHUB_TOKEN") from e
            raise
    raise RuntimeError(f"unreachable: {url}")


def fetch_people():
    """(people_docs, commit sha). Raises on any failure."""
    import yaml  # lazy: the offline tests inject people_docs and never reach this

    sha = json.loads(_get(COMMIT_URL)).get("sha")
    docs = []
    for d in DIRS:
        listing = json.loads(_get(LISTING_URL.format(d=d)))
        if not isinstance(listing, list) or len(listing) >= 1000:   # contents API caps at 1,000
            raise RuntimeError(f"unexpected listing for data/ga/{d}")
        for item in sorted(listing, key=lambda x: x["name"]):
            if not item["name"].endswith(".yml"):
                continue
            doc = yaml.safe_load(_get(item["download_url"]))
            if not isinstance(doc, dict) or "id" not in doc:
                raise RuntimeError(f"{item['name']} is not a person file")
            docs.append({"dir": d, "doc": doc})
            time.sleep(DELAY)
    return docs, sha


# -------------------------------------------------------------------------------- main

def main(argv=None, fetcher=fetch_people):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUTPUT_FILE)
    ap.add_argument("--roster", default=ROSTER_FILE)
    ap.add_argument("--apply-roster", action="store_true",
                    help="also merge the result into the roster file now")
    args = ap.parse_args(argv)

    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)["members"]
    previous = None
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            previous = json.load(f)

    try:
        docs, sha = fetcher()
    except Exception as e:                          # noqa: BLE001 — any failure is fatal here
        print(f"Error: could not read {REPO}: {e}. File untouched.", file=sys.stderr)
        return 1
    if len(docs) < MIN_DOCS:
        print(f"Error: only {len(docs)} person files read (floor {MIN_DOCS}); "
              f"refusing to write. File untouched.", file=sys.stderr)
        return 1

    sidecar, regressions = build_sidecar(
        docs, roster, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upstream_commit=sha, previous=previous)
    if regressions:
        print(f"Error: {len(regressions)} previously resolved slot(s) came back null — an "
              f"upstream gap or a partial read, not news. File untouched.", file=sys.stderr)
        for r in regressions[:10]:
            print(f"  {r}", file=sys.stderr)
        return 1

    write_json_atomic(args.out, sidecar, indent=1)
    md = sidecar["metadata"]
    print(f"Wrote {args.out}: {md['count']} members; ocdPersonId {md['resolved']['ocdPersonId']}, "
          f"ballotpediaId {md['resolved']['ballotpediaId']}")
    for k, v in sidecar["review"].items():
        if v:
            print(f"  review.{k}: {len(v)}")
    if args.apply_roster:
        n = apply_to_roster_file(args.roster, args.out)
        print(f"Applied identity slots to {n} roster members in {args.roster}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
