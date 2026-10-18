#!/usr/bin/env python3
"""
Generate ga-campaign-finance-donors.json: per-candidate donor summaries from the
Georgia Ethics Commission's PeachFile API.

The state counterpart to the FEC "who funds this candidate" panel. It is a SIDECAR to
ga-campaign-finance.json (which every member/candidate page downloads for the totals),
so the donor detail is only fetched by the pages that show it and the main file stays
small. Filers are keyed by filerEntityId, the same key the main file uses, so the page
resolves a candidate with the matcher it already has and then looks the id up here.

Per filer, three summary endpoints keyed on the filer's registration guid (the guid
comes from GetCandidateDetails, which the main generator already pages through):

  PublicTransactionDetails/GetTopDonorsAndPayees  (TCON) -> largest single contributions
  PublicFilerDetails/GetContributionsCategoriesDetails   -> Individual / Business / PAC ...
  PublicFilerDetails/GetContributionsInStateAndOutStateDetail -> in-state / out / unitemized

Things the page must not over-claim (they are also stated in the UI):
  - TopDonorsAndPayees is the largest individual *transactions* (the same giver can
    appear twice), not donors aggregated. It is published as `largest`, not "top donors".
  - The category and in/out-of-state figures cover what PeachFile itemizes in its
    current filing system; they need not sum to the filer's total raised.
  - It carries no occupation/employer. That lives only on the per-transaction grid
    (payeeOccupation/payeeEmployer), which is deliberately out of scope here.

Incremental: a filer whose totalRaised has not moved since the committed file is carried
forward untouched, so a quiet week costs a handful of requests, not ~2,000. A filer that
fails to fetch also keeps its previous entry rather than vanishing. Run with
--full-refresh to refetch everyone.

No API key. The API is CORS origin-locked, so this is build-time only.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
import generate_ga_campaign_finance as base

OUTPUT_FILE = "assets/data/ga-campaign-finance-donors.json"
DELAY = 0.5
TOP_N = 10
# Fraction of filers that may fail before we refuse to publish a thinner file than the
# one already committed. A flaky API is a fact about the Commission; a mostly-empty
# file that replaced a full one is a regression we cause.
MAX_FAILED_FRACTION = 0.25


def clean_name(s):
    return " ".join((s or "").split())


def fetch_summary(guid):
    """One filer's donor summary, or None if any of the three calls failed."""
    top = base.post("/PublicTransactionDetails/GetTopDonorsAndPayees", {
        "filerRegistrationGuid": guid, "transactionTypeCode": "TCON",
        "filingYear": None, "electionTypeCode": ""})
    time.sleep(DELAY)
    cats = base.post("/PublicFilerDetails/GetContributionsCategoriesDetails", {
        "filerRegistrationGuid": guid, "electionTypeCode": ""})
    time.sleep(DELAY)
    geo = base.post("/PublicFilerDetails/GetContributionsInStateAndOutStateDetail", {
        "filerRegistrationGuid": guid, "electionTypeCode": ""})
    time.sleep(DELAY)
    if not all(r and r.get("succeeded", True) and "data" in r for r in (top, cats, geo)):
        return None

    largest = []
    for t in (top["data"] or [])[:TOP_N]:
        name, amt = clean_name(t.get("sourceName")), t.get("transactionAmount")
        if name and amt:
            largest.append({"name": name, "amount": amt,
                            "place": clean_name(t.get("cityState")) or None})

    # Categories arrive keyed by a code ("TIND" ...) with a display label; keep the
    # label so a type the site has never seen still renders instead of being dropped.
    by_type = [{"type": c.get("transactionSourceType"), "code": c.get("transactionSourceTypeCode"),
                "amount": c.get("amount")}
               for c in (cats["data"] or []) if c.get("amount")]
    by_type.sort(key=lambda x: -x["amount"])

    g = (geo["data"] or [{}])[0] if isinstance(geo["data"], list) else (geo["data"] or {})
    return {
        "largest": largest,
        "byType": by_type,
        "inState": g.get("inStateAmount"),
        "outOfState": g.get("outOfStateAmount"),
        "unitemized": g.get("unItemizedAmount"),
    }


def load_previous():
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f).get("filers") or {}
    except (OSError, ValueError):
        return {}


def main():
    full = "--full-refresh" in sys.argv
    cycle = base.target_cycle()
    prev = {} if full else load_previous()
    print(f"Target election cycle: {cycle} | previous entries: {len(prev)}")

    # One row per filer: the candidate list is where the guid lives.
    roster = {}
    for office_id, (label, _chamber) in base.OFFICES.items():
        rows, _complete = base.fetch_office(office_id)
        for r in rows:
            if base.cycle_year(r.get("electionCycleName")) != cycle:
                continue
            fid, guid = r.get("filerEntityId"), r.get("guid")
            if fid is None or not guid:
                continue
            roster[str(fid)] = (guid, r.get("totalContributions"))
        time.sleep(base.DELAY)
    if not roster:
        print("Error: no filers returned — leaving the committed file untouched")
        sys.exit(1)

    filers, fetched, carried, failed, empty = {}, 0, 0, [], 0
    for fid, (guid, raised) in roster.items():
        old = prev.get(fid)
        if not raised:
            empty += 1          # nothing raised -> nothing to break down
            continue
        if old is not None and old.get("raised") == raised:
            filers[fid] = old
            carried += 1
            continue
        summary = fetch_summary(guid)
        if summary is None:
            failed.append(fid)
            if old is not None:
                filers[fid] = old   # stale beats absent
            continue
        summary["raised"] = raised
        filers[fid] = summary
        fetched += 1
        if fetched % 50 == 0:
            print(f"  ...{fetched} fetched")

    attempted = fetched + len(failed)
    if attempted and len(failed) / attempted > MAX_FAILED_FRACTION:
        print(f"Error: {len(failed)}/{attempted} fetches failed — keeping the committed file")
        sys.exit(1)

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "cycle": cycle,
            "source": "Georgia Ethics Commission PeachFile (api-peachfile.ethics.ga.gov)",
            "count": len(filers),
            "fetchedThisRun": fetched,
            "failedFilers": failed,
        },
        "filers": filers,
    }
    write_json_atomic(OUTPUT_FILE, output, separators=(",", ":"))
    print(f"Done. {len(filers)} filers ({fetched} fetched, {carried} carried, "
          f"{empty} with no money, {len(failed)} failed) -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
