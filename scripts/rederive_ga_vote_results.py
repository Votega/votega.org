#!/usr/bin/env python3
"""Re-derive the Pass/Fail of every roll call in a published GA votes file.

For the closed bienniums under Votega/ga-legislators sessions/<biennium>/votes.json,
which were published before the constitutional-majority rule (lib/ga_vote_rules.py)
and without the two-thirds amendment rule. Re-fetching a biennium would also pick up
unrelated source drift in a permanent file; this changes `result` and nothing else.

Reads the file, looks up which of its resolutions propose a Georgia constitutional
amendment (legis.ga.gov GetLegislationDetail, one call per resolution), recomputes
every `result`, and writes the corrected file plus a JSON report of each change. The
metadata records the rule (`resultRule`) and sets `amendmentRuleApplied`.
Publish the output with `publish_ga_legislators.py correct-results`.

Usage:
  python scripts/rederive_ga_vote_results.py IN.json OUT.json [--report REPORT.json]
  python scripts/rederive_ga_vote_results.py IN.json OUT.json --amendment-ids 1,2,3
      # skip the lookup (tests, or a list already checked)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_vote_results import (amendment_ids_from_soap, legislation_id,  # noqa: E402
                                 rederive_votes, two_thirds_candidate_ids)

RESULT_RULE = ("Pass needs a majority of the chamber's seats (91 House / 29 Senate, Ga. "
               "Const. Art. III, Sec. V, Para. V) and two-thirds (120 / 38) for a resolution "
               "proposing a Georgia constitutional amendment (Art. X, Sec. I, Para. II) or a "
               "bill granting a property-tax exemption put to referendum (Art. VII, Sec. II, "
               "Para. II(a)); see CHANGES.md")


def rederive_doc(doc, amendment_ids):
    """Correct `doc` (a published votes.json) in place. Returns the change rows."""
    votes = doc.get("votes") or {}
    changes = rederive_votes(votes, amendment_ids)
    meta = doc.setdefault("metadata", {})
    meta["amendmentRuleApplied"] = True
    meta["resultRule"] = RESULT_RULE
    rows = []
    for vid, old, new in changes:
        v = votes[vid]
        rows.append({"voteId": vid, "bill": v.get("bill"), "chamber": v.get("chamber"),
                     "date": v.get("date"), "time": v.get("time"),
                     "motionText": v.get("motionText"), "yea": v.get("yea"),
                     "nay": v.get("nay"), "from": old, "to": new,
                     "twoThirds": legislation_id(v) in amendment_ids})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--report", default=None)
    ap.add_argument("--amendment-ids", default=None,
                    help="comma-separated legislationIds; skips the legis.ga.gov lookup")
    args = ap.parse_args(argv)

    with open(args.input, encoding="utf-8") as fh:
        doc = json.load(fh)
    if args.amendment_ids is not None:
        amendment_ids = {int(x) for x in args.amendment_ids.split(",") if x.strip()}
    else:
        lids = two_thirds_candidate_ids(doc.get("votes") or {})
        print("Looking up %d resolutions and property-tax bills on legis.ga.gov" % len(lids))
        try:
            amendment_ids = amendment_ids_from_soap(lids)
        except RuntimeError as exc:
            sys.exit("Error: %s — nothing written." % exc)
    rows = rederive_doc(doc, amendment_ids)

    write_json_atomic(args.output, doc, ensure_ascii=False, separators=(",", ":"))
    if args.report:
        write_json_atomic(args.report, {"session": (doc.get("metadata") or {}).get("session"),
                                        "amendmentIds": sorted(amendment_ids),
                                        "changes": rows}, indent=2)
    print("%s: %d two-thirds bills/resolutions, %d results changed"
          % ((doc.get("metadata") or {}).get("session"), len(amendment_ids), len(rows)))
    for r in rows:
        print("  %s %-7s %-5s %s %d-%d %s -> %s%s"
              % (r["date"], r["bill"], (r["chamber"] or "")[:5], r["voteId"], r["yea"],
                 r["nay"], r["from"], r["to"], "  (two-thirds)" if r["twoThirds"] else ""))
    return rows


if __name__ == "__main__":
    main()
