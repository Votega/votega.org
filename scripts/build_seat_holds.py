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
import copy

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_roster import EDITORIAL_STATUS_FIELDS, apply_member_overrides  # noqa: E402
from lib.ga_identity import executive_keys, ledger_keys  # noqa: E402
from lib.seat_holds import (bienniums, derive_executive_holds, derive_holds, derive_vacancy_notes, holds_errors,  # noqa: E402
                             overrides_errors, report, vacancy_note_errors, vacancy_report)
import glob  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(REPO_ROOT, *a)  # noqa: E731
SNAPSHOT_FILE = P("scripts", "data", "ga-members-by-session.json")
SEATS_FILE = P("assets", "data", "seats.json")
ROSTER_FILE = P("assets", "data", "ga-members.json")
MEMBER_OVERRIDES_FILE = P("assets", "data", "ga-members-overrides.json")
OVERRIDES_FILE = P("assets", "data", "seat-hold-overrides.json")
LEDGER_FILE = P("assets", "data", "id-crosswalk-ledger.json")
OUTPUT_FILE = P("assets", "data", "seat-holds.json")
EXEC_SEATS_FILE = P("assets", "data", "ga-executive-seats.json")
EXEC_FILE = P("assets", "data", "ga-executive.json")
SPECIALS_FILE = P("assets", "data", "ga-legislative-specials.json")
EXEC_ORDERS_GLOB = P("assets", "data", "ga-executive-orders-*.json")


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


def roster_members(roster_doc=None, overrides_file=MEMBER_OVERRIDES_FILE):
    """The roster with the editorial layer applied HERE, not trusted from ga-members.json.

    ga-members.json is a generated file: main owns it, the daily update-ga-members run
    rebuilds it from ga-members-overrides.json, and the PR sync workflow copies main's
    copy onto every PR branch. A departure fix made in the overrides would otherwise
    reach the holds only after the next daily run (and a PR could never carry one).
    Applying the overrides with the same single implementation the producer uses makes
    the holds depend on the editorial source, which is the truth."""
    doc = roster_doc or load(ROSTER_FILE)
    members = copy.deepcopy(doc["members"])
    # The producer never writes status (only the overrides do), and the overrides fill a
    # status only where the record has none. So clear it first: that reproduces the
    # fresh source records the producer applies the overrides to, and a corrected status
    # in the overrides then wins over a stale one in the generated file.
    for m in members:
        for k in EDITORIAL_STATUS_FIELDS:
            m[k] = None
    apply_member_overrides(members, overrides_file, session=(doc.get("metadata") or {}).get("session"))
    return members


def load_writs(first_convening):
    """Every executive order from the year before the history starts (a writ can be issued
    before the convening, for a member-elect who was never seated)."""
    orders = []
    for path in sorted(glob.glob(EXEC_ORDERS_GLOB)):
        year = os.path.basename(path)[len("ga-executive-orders-"):-len(".json")]
        if year.isdigit() and int(year) >= int(first_convening[:4]) - 1:
            orders += load(path).get("orders", [])
    return orders


def build(snapshot, seats_doc, roster_members, overrides_doc, ledger, specials_doc=None, writs=None,
          exec_seats_doc=None, officials=None):
    roster = {m["legisGaGovId"]: m for m in roster_members if m.get("legisGaGovId") is not None}
    specials_doc = specials_doc if specials_doc is not None else load(SPECIALS_FILE, {"specials": [], "sources": {}})
    first = bienniums(snapshot)[0][1]
    writs = writs if writs is not None else load_writs(first)
    holds = derive_holds(snapshot, seats_doc, roster, overrides_doc.get("holds", []),
                         vgid_resolver(ledger), specials=specials_doc.get("specials", []))
    exec_seats_doc = exec_seats_doc if exec_seats_doc is not None else load(EXEC_SEATS_FILE)
    officials = officials if officials is not None else load(EXEC_FILE)["officials"]
    assign, merged = ledger.get("assign", {}), ledger.get("merged", {})

    def exec_vgid(o):
        for k in executive_keys(o.get("legacyRosterId"), o.get("legisGaGovId"), o["id"]):
            if k in assign:
                vg = assign[k]
                while vg in merged:
                    vg = merged[vg]
                return vg
        return None
    holds = holds + derive_executive_holds(exec_seats_doc, officials, exec_vgid)
    notes = derive_vacancy_notes(holds, seats_doc, writs, specials_doc.get("specials", []),
                                 specials_doc.get("sources", {}), today="9999-12-31")
    return {
        "metadata": {
            "generatedAt": None,
            "count": len(holds),
            "schemaVersion": 1,
            "historyFrom": {"ga-house": first, "ga-senate": first, "ga-executive": "2023-01-09"},
            "meaning": ("One record per person per continuous time in one seat, in the order "
                        "held. start/end are the first day in and the first day out, each with "
                        "a basis; endedBy says only why THIS hold ended (a win or loss "
                        "elsewhere is the same vgId's next hold). A seat a new map carried over "
                        "keeps one hold across bienniums; a redrawn seat's hold ends "
                        "'redistricted'. Vacancies are the gaps between holds."),
            "sources": [
                "legis.ga.gov Members/GetMembersBySession (scripts/data/ga-members-by-session.json)",
                "assets/data/ga-executive-seats.json + ga-executive.json (statewide executives, Phase 3)",
                "assets/data/seats.json", "assets/data/ga-members.json (status, termStart)",
                "assets/data/seat-hold-overrides.json (hand-reviewed end reasons, with sources)",
                "assets/data/id-crosswalk-ledger.json (vgIds)",
                "assets/data/ga-executive-orders-*.json (writs of election, for vacancyNotes)",
                "assets/data/ga-legislative-specials.json (special elections, for vacancyNotes)",
            ],
        },
        "holds": holds,
        "vacancyNotes": notes,
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
    ov_doc = load(OVERRIDES_FILE, {"holds": []})
    corrections = ov_doc.get("corrections", [])
    bad = overrides_errors(ov_doc.get("holds", []), corrections)
    if bad:
        print("Refusing to build: seat-hold-overrides.json", *bad, sep="\n  ", file=sys.stderr)
        return 1
    try:
        doc = build(load(SNAPSHOT_FILE), seats_doc, roster_members(),
                    load(OVERRIDES_FILE, {"holds": []}), ledger)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    committed = load(OUTPUT_FILE)
    errs = holds_errors(doc, seats_doc, ledger.get("merged"), previous=committed,
                        corrections=corrections) + vacancy_note_errors(doc, seats_doc)
    if errs:
        print("Refusing to write seat-holds.json:", *errs, sep="\n  ", file=sys.stderr)
        return 1
    for line in report(doc, seats_doc) + vacancy_report(doc, seats_doc):
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
