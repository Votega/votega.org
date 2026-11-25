#!/usr/bin/env python3
"""One-time backfill: `documentType` and `nomineeCount` on held Senate roll calls.

generate_federal_votes_data.py never re-fetches an official roll call it already
holds, so rows written before those fields existed get them here. For every Senate
row of federal-member-votes.json this adds the two fields; on an en bloc row it
also replaces the title; and it writes federal-en-bloc-nominees.json beside it.
Nothing else changes. Safe to re-run (for example if a weekly run landed first).

    python scripts/backfill_federal_nomination_fields.py [--cache DIR]
    python scripts/build_federal_votes_slices.py

Do NOT use the generator's --full-refresh for this: with senate.gov unreachable it
replaces official rows with Voteview ones.

Fetching. Run it from a computer senate.gov answers. Every vote with no measure
(which includes every nomination) is read from its XML, as is every motion whose
document could be either a measure or an amendment. Where the motion itself fixes
the document (passage of a bill, an amendment vote, ...) the type comes from the
held record, and a sample of each such motion is checked against senate.gov first.
Any refused, wrong or contradicting file stops the run before anything is written.
"""
import argparse
import contextlib
import copy
import io
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_federal_votes_data as G  # noqa: E402
from lib import senate_drop, senate_nominations  # noqa: E402
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.http import fetch_bytes  # noqa: E402

DEFAULT_VOTES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "data", "federal-member-votes.json")

#: Motions that can only be put on the measure itself.
ON_THE_MEASURE = {
    "On Passage of the Bill", "On the Joint Resolution", "On the Concurrent Resolution",
    "On the Resolution", "On the Motion to Proceed", "On Cloture on the Motion to Proceed",
    "On the Motion to Discharge",
}
ON_AN_AMENDMENT = "On the Amendment"
SAMPLES = 3
PAUSE = 0.5


class BackfillError(Exception):
    pass


def derived_type(row):
    """documentType the held record settles on its own, or None to read the XML."""
    if not row.get("billType"):
        return None
    if row.get("motionText") == ON_AN_AMENDMENT:
        return "S.Amdt."
    if row.get("motionText") in ON_THE_MEASURE:
        return G.TYPE_LABEL.get(row["billType"])
    return None


def read_official(vote_id, row, congress, fetch, differences):
    """The generator's own parse of this roll call's official XML."""
    session, number = row["session"], row["rollNumber"]
    raw = fetch(session, number)
    if not raw:
        raise BackfillError(f"{vote_id}: senate.gov gave no file "
                            f"({senate_drop.official_url(congress, session, number)})")
    if not senate_drop._valid(raw, congress, session, number):
        raise BackfillError(f"{vote_id}: the file returned is not this roll call's XML")
    # Only the row is wanted: with no LIS map the parser would warn about both senators.
    with contextlib.redirect_stdout(io.StringIO()):
        meta, _ = G.parse_senate_vote(raw, {})
    for field in ("motionText", "yea", "nay"):
        if meta[field] != row.get(field):
            differences.append(f"{vote_id} {field}: held {row.get(field)!r}, senate.gov {meta[field]!r}")
    return meta, raw


def backfill(votes_doc, fetch, previous_nominees=None):
    """(new monolith, nominee file, report). Pure apart from `fetch(session, number)`."""
    doc = copy.deepcopy(votes_doc)
    congress = (doc.get("metadata") or {}).get("congress")
    provisional = set((doc.get("metadata") or {}).get("senateRollsFromVoteview") or [])
    senate = {k: v for k, v in doc["votes"].items() if v.get("chamber") == "Senate"}

    groups = {}
    for vote_id, row in senate.items():
        if vote_id not in provisional and derived_type(row):
            groups.setdefault(row["motionText"], []).append(vote_id)
    derived = {v for members in groups.values() for v in members}
    for members in groups.values():
        # First, last and evenly between: enough to catch a wrong rule, not a full re-read.
        step = max(len(members) - 1, 1) / (SAMPLES - 1)
        derived -= {members[min(round(i * step), len(members) - 1)] for i in range(SAMPLES)}

    lists, en_bloc, differences = {}, {}, []
    for vote_id, row in senate.items():
        if vote_id in derived:
            row["documentType"], row["nomineeCount"] = derived_type(row), None
            continue
        meta, raw = read_official(vote_id, row, congress, fetch, differences)
        doc_type, count = meta["documentType"], meta["nomineeCount"]
        rule = None if vote_id in provisional else derived_type(row)
        if rule and doc_type != rule:
            raise BackfillError(f"{vote_id}: the derivation rule gives {rule!r} for "
                                f"{row['motionText']!r} but senate.gov says {doc_type!r}")
        row["documentType"] = doc_type
        if vote_id in provisional:
            # A Voteview row is replaced by the generator later; until then it looks
            # like one the generator wrote: no count and no list.
            row["nomineeCount"] = None
            if (count or 0) > 1:
                row["title"] = senate_nominations.EN_BLOC_TITLE
            continue
        row["nomineeCount"] = count
        if (count or 0) > 1:
            entries = senate_nominations.nominees(ET.fromstring(raw))
            if entries is None or len(entries) != count:
                raise BackfillError(f"{vote_id}: {count} nominations but no complete list")
            lists[vote_id] = entries
            row["title"] = meta["title"]
            en_bloc[vote_id] = count

    nominees_doc = senate_nominations.build_nominees_doc(
        doc["votes"], lists, provisional, congress, previous=previous_nominees)
    errors = senate_nominations.problems(doc, nominees_doc)
    if errors:
        raise BackfillError("result does not validate: " + "; ".join(errors))
    report = {"senateRows": len(senate), "derived": len(derived),
              "read": len(senate) - len(derived), "enBloc": en_bloc, "differences": differences}
    return doc, nominees_doc, report


def senate_fetcher(congress, cache=None, pause=PAUSE):
    """Committed hand-saved XML, then the cache, then senate.gov with a pause."""
    def fetch(session, number):
        raw = senate_drop.read_roll(congress, session, number)
        if raw is None and cache:
            raw = senate_drop.read_roll(congress, session, number, cache)
        if raw is not None:
            return raw
        time.sleep(pause)
        raw = fetch_bytes(G.senate_vote_url(congress, session, number),
                          label=G.senate_key(congress, session, number))
        if raw and cache and senate_drop._valid(raw, congress, session, number):
            os.makedirs(cache, exist_ok=True)
            with open(os.path.join(cache, senate_drop.filename(congress, session, number)), "wb") as fh:
                fh.write(raw)
        return raw
    return fetch


def main(argv=None, fetch=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--votes", default=DEFAULT_VOTES)
    ap.add_argument("--cache", help="keep fetched XML here, so a re-run does not fetch it again")
    ap.add_argument("--pause", type=float, default=PAUSE, help="seconds between requests")
    args = ap.parse_args(argv)
    nominees_path = os.path.join(os.path.dirname(args.votes), senate_nominations.NOMINEES_FILE)
    with open(args.votes, encoding="utf-8") as fh:
        votes_doc = json.load(fh)
    previous = None
    if os.path.exists(nominees_path):
        with open(nominees_path, encoding="utf-8") as fh:
            previous = json.load(fh)
    fetch = fetch or senate_fetcher(votes_doc["metadata"]["congress"], args.cache, args.pause)
    try:
        doc, nominees_doc, report = backfill(votes_doc, fetch, previous)
    except BackfillError as exc:
        print(f"backfill stopped, nothing written: {exc}", file=sys.stderr)
        return 1
    # The nominee file first: if the second write fails, the monolith is unchanged.
    write_json_atomic(nominees_path, nominees_doc, separators=(",", ":"))
    write_json_atomic(args.votes, doc, separators=(",", ":"))
    print(f"{report['senateRows']} Senate rows: {report['read']} read from XML, "
          f"{report['derived']} typed from the held record")
    print(f"en bloc roll calls: {len(report['enBloc'])}")
    for vote_id, count in report["enBloc"].items():
        print(f"  {vote_id}: {count} nominees")
    print(f"nominee file: {len(nominees_doc['batches'])} batches, "
          f"{nominees_doc['metadata']['count']} entries")
    if report["differences"]:
        print("held record differs from senate.gov (NOT changed):")
        for line in report["differences"]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
