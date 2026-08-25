#!/usr/bin/env python3
"""Validate assets/data/id-crosswalk.json before it is committed or published.

The crosswalk's whole value is that a consumer can trust an id mapping without
re-deriving it. So the checks here are aimed at the ways a mapping goes wrong
silently — a dangling reference, or the same upstream id claimed by two people —
rather than at whether the file parses.

The append-only ledger check is the one that matters most over time. A vgId that
was published once and later points at a different person is worse than no
crosswalk at all, because downstream data keyed on it becomes quietly wrong.

Run:
    python scripts/validate_id_crosswalk.py

Exit 0 = valid. Exit 1 = one or more errors (details on stdout).
"""

import json
import os
import subprocess
import sys

CROSSWALK_FILE = "assets/data/id-crosswalk.json"
LEDGER_FILE    = "assets/data/id-crosswalk-ledger.json"
MEMBERS_FILE   = "assets/data/ga-members.json"
FEDERAL_FILE   = "assets/data/current-members.json"
FINANCE_FILE   = "assets/data/ga-campaign-finance.json"
RACES_FILE     = "assets/data/races.json"

#: Coverage below these means something upstream broke — a partial PeachFile pull,
#: a collapsed roster — rather than a legitimate data change. Set well below the
#: observed values (249 state / 228 matched at time of writing) so ordinary churn
#: doesn't trip them, but a collapse does.
MIN_PEOPLE = 200
MIN_PEACHFILE_RESOLVED = 180

errors = []
warnings = []


def err(msg):
    errors.append(f"  {msg}")


def warn(msg):
    warnings.append(f"  {msg}")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git_show(path):
    """The committed version of a file at HEAD, or None if it isn't committed yet."""
    try:
        out = subprocess.run(["git", "show", f"HEAD:{path}"],
                             capture_output=True, check=True)
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def main():
    if not os.path.exists(CROSSWALK_FILE):
        print(f"Error: {CROSSWALK_FILE} does not exist", file=sys.stderr)
        return 1

    data   = load(CROSSWALK_FILE)
    people = data.get("people", [])
    ledger = load(LEDGER_FILE) if os.path.exists(LEDGER_FILE) else {"assign": {}}

    # --- Upstream id universes, to catch dangling references -----------------
    members  = load(MEMBERS_FILE)["members"]
    federal  = load(FEDERAL_FILE)["members"]
    filers   = load(FINANCE_FILE)["filers"]
    races    = load(RACES_FILE)

    ocd_ids  = {m["id"] for m in members}
    bio_ids  = {m["bioguideId"] for m in federal}
    filer_ids = set(filers)
    cand_ids = set()
    for race in races.get("races", []):
        for phase in (race.get("phases") or {}).values():
            for ballot in (phase.get("ballots") or {}).values():
                for cand in ballot:
                    if cand.get("id"):
                        cand_ids.add(cand["id"])

    # --- Structure -----------------------------------------------------------
    if len(people) < MIN_PEOPLE:
        err(f"only {len(people)} people (expected >= {MIN_PEOPLE}) — likely a partial build")
    if data.get("metadata", {}).get("count") != len(people):
        err(f"metadata.count ({data.get('metadata', {}).get('count')}) != len(people) ({len(people)})")

    seen_vg = {}
    for p in people:
        vg = p.get("vgId")
        if not vg:
            err(f"record with no vgId: {p.get('name', {}).get('full')}")
            continue
        if vg in seen_vg:
            err(f"duplicate vgId {vg}: {seen_vg[vg]} and {p['name']['full']}")
        seen_vg[vg] = p["name"]["full"]
        for key in ("name", "role", "ids", "provenance"):
            if key not in p:
                err(f"{vg} is missing required key '{key}'")

    # --- Every external id must resolve upstream -----------------------------
    for p in people:
        vg, ids = p.get("vgId"), p.get("ids", {})
        if ids.get("ocdPersonId") and ids["ocdPersonId"] not in ocd_ids:
            err(f"{vg} references unknown ocdPersonId {ids['ocdPersonId']}")
        if ids.get("bioguideId") and ids["bioguideId"] not in bio_ids:
            err(f"{vg} references unknown bioguideId {ids['bioguideId']}")
        if ids.get("peachfileFilerEntityId") and ids["peachfileFilerEntityId"] not in filer_ids:
            err(f"{vg} references unknown peachfileFilerEntityId {ids['peachfileFilerEntityId']}")
        for cid in ids.get("votegaCandidateIds") or []:
            if cid not in cand_ids:
                err(f"{vg} references unknown votega candidate id {cid}")

    # --- No upstream id may be claimed by two people -------------------------
    # This is the invariant that makes the file safe to join on. Two legislators
    # sharing a PeachFile filer id means one of them is being credited with the
    # other's fundraising.
    for key in ("ocdPersonId", "bioguideId", "fecCandidateId",
                "peachfileFilerEntityId", "legisGaGovId", "govtrackId"):
        owners = {}
        for p in people:
            val = p.get("ids", {}).get(key)
            if val is None:
                continue
            owners.setdefault(val, []).append(p["vgId"])
        for val, vgs in owners.items():
            if len(vgs) > 1:
                names = ", ".join(f"{v} ({seen_vg.get(v)})" for v in vgs)
                err(f"{key} {val} is claimed by {len(vgs)} people: {names}")

    # --- Provenance must accompany every derived id --------------------------
    for p in people:
        ids, prov = p.get("ids", {}), p.get("provenance", {})
        if ids.get("peachfileFilerEntityId") and "peachfileFilerEntityId" not in prov:
            err(f"{p['vgId']} has a peachfileFilerEntityId with no provenance entry")
        amb = (prov.get("peachfileFilerEntityId") or {}).get("confidence") == "ambiguous"
        if amb and ids.get("peachfileFilerEntityId"):
            err(f"{p['vgId']} kept a peachfileFilerEntityId despite an ambiguous match")

    resolved = sum(1 for p in people if p.get("ids", {}).get("peachfileFilerEntityId"))
    if resolved < MIN_PEACHFILE_RESOLVED:
        err(f"only {resolved} PeachFile matches (expected >= {MIN_PEACHFILE_RESOLVED}) "
            f"— likely a partial finance pull")

    # --- Ledger is append-only ----------------------------------------------
    assign = ledger.get("assign", {})
    for p in people:
        key = p["ids"].get("ocdPersonId") or p["ids"].get("bioguideId")
        if key and assign.get(key) != p["vgId"]:
            err(f"{p['vgId']} ({p['name']['full']}) is not the ledger's assignment "
                f"for {key} (ledger says {assign.get(key)})")

    old = git_show(LEDGER_FILE)
    if old:
        for key, vg in (old.get("assign") or {}).items():
            if key not in assign:
                err(f"ledger dropped assignment {key} -> {vg} (the ledger is append-only)")
            elif assign[key] != vg:
                err(f"ledger renumbered {key}: was {vg}, now {assign[key]} "
                    f"(a published vgId must never change meaning)")
    else:
        warnings.append("  ledger has no committed baseline yet — append-only check skipped")

    # --- Report --------------------------------------------------------------
    amb_list = data.get("metadata", {}).get("coverage", {}).get("ambiguousPeachfile") or []
    print(f"{len(people)} people | {resolved} PeachFile matched | {len(amb_list)} ambiguous")
    if amb_list:
        warn(f"{len(amb_list)} ambiguous PeachFile matches left unresolved: {', '.join(amb_list[:5])}"
             f" — resolve in assets/data/ga-campaign-finance-overrides.json")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(w)
    if errors:
        print(f"\n{len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("\nid-crosswalk.json is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
