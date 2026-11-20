#!/usr/bin/env python3
"""Build assets/data/seat-holds.json: who held each General Assembly seat since January 2023.

Phase 2 of docs/seat-history-design.md. Reads only committed files, so it is offline and
deterministic (rules in scripts/lib/seat_holds.py):

  scripts/data/ga-members-by-session.json   who served in each session (fetch_ga_members_by_session.py)
  assets/data/seats.json                    the seat registry (build_seat_registry.py)
  assets/data/ga-members.json               departures (status), suspensions, joiners' termStart
  assets/data/seat-hold-overrides.json      hand-reviewed end reasons no feed provides
  assets/data/id-crosswalk-ledger.json      vgIds (the crosswalk mints them; this never does)

Order when the roster changes: fetch_ga_members_by_session.py, build_id_crosswalk.py,
then this. It refuses to write holds that fail lib/seat_holds.holds_errors, including the
append-only check (a closed hold never changes) against the committed file, and keeps
generatedAt when nothing changed.

Usage:
  python scripts/build_seat_holds.py           # write
  python scripts/build_seat_holds.py --check   # exit 1 if the committed file is stale
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_identity import ledger_keys  # noqa: E402
from lib.seat_holds import bienniums, derive_holds, holds_errors, overrides_errors, report  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(REPO_ROOT, *a)  # noqa: E731
SNAPSHOT_FILE = P("scripts", "data", "ga-members-by-session.json")
SEATS_FILE = P("assets", "data", "seats.json")
ROSTER_FILE = P("assets", "data", "ga-members.json")
OVERRIDES_FILE = P("assets", "data", "seat-hold-overrides.json")
LEDGER_FILE = P("assets", "data", "id-crosswalk-ledger.json")
OUTPUT_FILE = P("assets", "data", "seat-holds.json")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def vgid_resolver(ledger):
    assign, merged = ledger.get("assign", {}), ledger.get("merged", {})

    def resolve(vg):
        while vg in merged:
            vg = merged[vg]
        return vg

    def vgid_for(gid, roster_rec):
        for k in ledger_keys(gid, (roster_rec or {}).get("id")):
            if k in assign:
                return resolve(assign[k])
        return None
    return vgid_for


def build(snapshot, seats_doc, roster_members, overrides_doc, ledger):
    roster = {m["legisGaGovId"]: m for m in roster_members if m.get("legisGaGovId") is not None}
    holds = derive_holds(snapshot, seats_doc, roster, overrides_doc.get("holds", []),
                         vgid_resolver(ledger))
    first = bienniums(snapshot)[0][1]
    return {
        "metadata": {
            "generatedAt": None,
            "count": len(holds),
            "schemaVersion": 1,
            "historyFrom": {"ga-house": first, "ga-senate": first},
            "meaning": ("One record per person per continuous time in one seat, in the order "
                        "held. start/end are the first day in and the first day out, each with "
                        "a basis; endedBy says only why THIS hold ended (a win or loss "
                        "elsewhere is the same vgId's next hold). A seat a new map carried over "
                        "keeps one hold across bienniums; a redrawn seat's hold ends "
                        "'redistricted'. Vacancies are the gaps between holds."),
            "sources": [
                "legis.ga.gov Members/GetMembersBySession (scripts/data/ga-members-by-session.json)",
                "assets/data/seats.json", "assets/data/ga-members.json (status, termStart)",
                "assets/data/seat-hold-overrides.json (hand-reviewed end reasons, with sources)",
                "assets/data/id-crosswalk-ledger.json (vgIds)",
            ],
        },
        "holds": holds,
        "vacancyNotes": [],
    }


def same_content(a, b):
    if a is None or b is None:
        return False
    strip = lambda d: {**d, "metadata": {k: v for k, v in d["metadata"].items() if k != "generatedAt"}}  # noqa: E731
    return strip(a) == strip(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    seats_doc = load(SEATS_FILE)
    ledger = load(LEDGER_FILE)
    bad = overrides_errors(load(OVERRIDES_FILE, {"holds": []}).get("holds", []))
    if bad:
        print("Refusing to build: seat-hold-overrides.json", *bad, sep="\n  ", file=sys.stderr)
        return 1
    try:
        doc = build(load(SNAPSHOT_FILE), seats_doc, load(ROSTER_FILE)["members"],
                    load(OVERRIDES_FILE, {"holds": []}), ledger)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    committed = load(OUTPUT_FILE)
    errs = holds_errors(doc, seats_doc, ledger.get("merged"), previous=committed)
    if errs:
        print("Refusing to write seat-holds.json:", *errs, sep="\n  ", file=sys.stderr)
        return 1
    for line in report(doc, seats_doc):
        print(f"note: {line}")
    if args.check:
        if same_content(doc, committed):
            print(f"{OUTPUT_FILE} is up to date ({doc['metadata']['count']} holds)")
            return 0
        print(f"Error: {OUTPUT_FILE} is stale; run python scripts/build_seat_holds.py", file=sys.stderr)
        return 1
    if same_content(doc, committed):
        print(f"{OUTPUT_FILE} unchanged ({doc['metadata']['count']} holds)")
        return 0
    doc["metadata"]["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(OUTPUT_FILE, doc, indent=1)
    print(f"Wrote {OUTPUT_FILE}: {doc['metadata']['count']} holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
