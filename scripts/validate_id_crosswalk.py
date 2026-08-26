#!/usr/bin/env python3
"""Validate assets/data/id-crosswalk.json before it is committed or published.

The crosswalk's value is that a consumer can trust an id mapping without
re-deriving it, so the checks aim at the ways a mapping goes wrong silently — a
dangling reference, one upstream id claimed by two people, a vgId that changes
meaning — rather than at whether the file parses.

Two checks matter most over time:

* **Append-only ledger.** A vgId published once and later pointing at a different
  person is worse than no crosswalk at all, because downstream data keyed on it
  becomes quietly wrong.
* **No positional ledger keys.** races.json candidate ids end in a row index into
  the Secretary of State export and shift between exports (see
  build_legislative_races.py:128 and CODEBASE-REVIEW-2026-08-18.md 5.2). If one
  ever becomes a ledger key, identity silently reassigns on the next re-export.

Run:
    python scripts/validate_id_crosswalk.py

Exit 0 = valid. Exit 1 = one or more errors (details on stdout).
"""

import json
import os
import re
import subprocess
import sys

CROSSWALK_FILE = "assets/data/id-crosswalk.json"
LEDGER_FILE    = "assets/data/id-crosswalk-ledger.json"
OVERRIDES_FILE = "assets/data/id-crosswalk-overrides.json"
MEMBERS_FILE   = "assets/data/ga-members.json"
FEDERAL_FILE   = "assets/data/current-members.json"
FINANCE_FILE   = "assets/data/ga-campaign-finance.json"
FEC_FILE       = "assets/data/ga-fec-data.json"
RACES_FILE     = "assets/data/races.json"

EXPECTED_SCHEMA_VERSION = 2

#: Floors, set well below observed values (749 people / 682 keyed at time of
#: writing) so ordinary churn doesn't trip them but a collapsed input does.
MIN_PEOPLE = 600
MIN_WITH_VGID = 550

#: A races.json candidate id — positional, and therefore never a valid ledger key.
POSITIONAL_ID = re.compile(r'^ga-(house|senate)-\d+-\d{4}-[a-z]+-\d+$')

#: Ledger keys we do accept. The third alternative covers the synthetic member ids
#: ga-members.json injects for seats Open States doesn't track (a vacancy, or a
#: member seated mid-session) — e.g. ga-house-177-vacant, ga-senate-7-carden. Those
#: are member ids, not ballot positions: they have no cycle year and no trailing
#: index, which is what keeps them distinct from POSITIONAL_ID above.
VALID_LEDGER_KEY = re.compile(
    r'^(ocd-person/[0-9a-f-]+|[A-Z]\d{6}|ga-(house|senate)-\d+-[a-z]+|peachfile:\d+|fec:[A-Z0-9]+)$')

errors, warnings = [], []


def err(msg):
    errors.append(f"  {msg}")


def warn(msg):
    warnings.append(f"  {msg}")


def load(path, default=None):
    if not os.path.exists(path):
        if default is None:
            raise SystemExit(f"Error: required input {path} is missing")
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git_show(path):
    try:
        out = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, check=True)
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def main():
    if not os.path.exists(CROSSWALK_FILE):
        print(f"Error: {CROSSWALK_FILE} does not exist", file=sys.stderr)
        return 1

    data   = load(CROSSWALK_FILE)
    people = data.get("people", [])
    meta   = data.get("metadata", {})
    ledger = load(LEDGER_FILE, {"assign": {}})
    assign = ledger.get("assign", {})

    members = load(MEMBERS_FILE)["members"]
    federal = load(FEDERAL_FILE)["members"]
    filers  = load(FINANCE_FILE)["filers"]
    fec     = load(FEC_FILE)
    races   = load(RACES_FILE)

    ocd_ids  = {m["id"] for m in members}
    bio_ids  = {m["bioguideId"] for m in federal}
    filer_ids = set(filers)
    fec_ids  = set(fec.get("candidates", {}))
    cand_ids = set()
    for race in races.get("races", []):
        for phase in (race.get("phases") or {}).values():
            for ballot in (phase.get("ballots") or {}).values():
                for c in ballot:
                    if c.get("id"):
                        cand_ids.add(c["id"])
    race_ids = {r["id"] for r in races.get("races", [])}

    # --- Envelope ------------------------------------------------------------
    if meta.get("schemaVersion") != EXPECTED_SCHEMA_VERSION:
        err(f"schemaVersion is {meta.get('schemaVersion')}, expected {EXPECTED_SCHEMA_VERSION}")
    if meta.get("count") != len(people):
        err(f"metadata.count ({meta.get('count')}) != len(people) ({len(people)})")
    if len(people) < MIN_PEOPLE:
        err(f"only {len(people)} people (expected >= {MIN_PEOPLE}) — likely a partial build")

    with_vgid = sum(1 for p in people if p.get("vgId"))
    if with_vgid < MIN_WITH_VGID:
        err(f"only {with_vgid} people carry a vgId (expected >= {MIN_WITH_VGID})")

    # --- Per-record structure ------------------------------------------------
    seen_vg = {}
    for p in people:
        name = (p.get("name") or {}).get("full")
        vg = p.get("vgId")
        for key in ("name", "ids", "candidacies", "provenance"):
            if key not in p:
                err(f"{vg or name}: missing required key '{key}'")
        if vg:
            if vg in seen_vg:
                err(f"duplicate vgId {vg}: {seen_vg[vg]} and {name}")
            seen_vg[vg] = name
        else:
            # An unkeyed record must say why, or a reader cannot tell a deliberate
            # hole from a build that silently failed to assign.
            if not (p.get("provenance") or {}).get("vgId"):
                err(f"{name}: vgId is null with no provenance.vgId explaining why")
            if not p.get("candidacies"):
                err(f"{name}: vgId is null and no candidacies — nothing identifies this record")
        if p.get("role") is None and not p.get("candidacies"):
            err(f"{vg or name}: no role and no candidacies — record has no reason to exist")

    # --- Every external id must resolve upstream -----------------------------
    for p in people:
        vg, ids = p.get("vgId") or (p.get("name") or {}).get("full"), p.get("ids", {})
        if ids.get("ocdPersonId") and ids["ocdPersonId"] not in ocd_ids:
            err(f"{vg} references unknown ocdPersonId {ids['ocdPersonId']}")
        if ids.get("bioguideId") and ids["bioguideId"] not in bio_ids:
            err(f"{vg} references unknown bioguideId {ids['bioguideId']}")
        for f in ids.get("peachfileFilerEntityIds") or []:
            if f not in filer_ids:
                err(f"{vg} references unknown peachfileFilerEntityId {f}")
        for f in ids.get("fecCandidateIds") or []:
            if f not in fec_ids:
                err(f"{vg} references unknown fecCandidateId {f}")
        for cid in ids.get("votegaCandidateIds") or []:
            if cid not in cand_ids:
                err(f"{vg} references unknown votega candidate id {cid}")
        for c in p.get("candidacies") or []:
            if c.get("raceId") not in race_ids:
                err(f"{vg} has a candidacy in unknown race {c.get('raceId')}")

    # --- No upstream id may be claimed by two people -------------------------
    # The invariant that makes the file safe to join on: two people sharing a
    # filing means one is being credited with the other's fundraising.
    scalar_keys = ("ocdPersonId", "bioguideId", "legisGaGovId", "govtrackId", "openSecretsId")
    list_keys   = ("peachfileFilerEntityIds", "fecCandidateIds", "votegaCandidateIds")
    for key in scalar_keys + list_keys:
        owners = {}
        for p in people:
            val = p.get("ids", {}).get(key)
            vals = val if key in list_keys else ([val] if val is not None else [])
            for v in vals or []:
                owners.setdefault(v, []).append(p.get("vgId") or (p.get("name") or {}).get("full"))
        for v, holders in owners.items():
            if len(set(holders)) > 1:
                err(f"{key} {v} is claimed by {len(set(holders))} people: {', '.join(map(str, set(holders)))}")

    # --- Ambiguous matches must never keep an id -----------------------------
    for p in people:
        for field, prov in (p.get("provenance") or {}).items():
            if not isinstance(prov, dict) or prov.get("confidence") != "ambiguous":
                continue
            if p.get("ids", {}).get(field):
                err(f"{p.get('vgId')} kept {field} despite an ambiguous match")

    # --- Ledger --------------------------------------------------------------
    for key, vg in assign.items():
        if POSITIONAL_ID.match(key):
            err(f"ledger key {key!r} is a positional races.json candidate id — "
                f"those shift between SoS exports and must never key identity")
        elif not VALID_LEDGER_KEY.match(key):
            warn(f"ledger key {key!r} is not a recognised durable-id form")

    # Every keyed record must match the ledger's assignment for its natural key.
    for p in people:
        if not p.get("vgId"):
            continue
        ids = p["ids"]
        natural = ids.get("ocdPersonId") or ids.get("bioguideId")
        if natural:
            if assign.get(natural) != p["vgId"]:
                err(f"{p['vgId']} ({p['name']['full']}) is not the ledger's assignment for "
                    f"{natural} (ledger says {assign.get(natural)})")
            continue
        # Candidate-only: every filing it carries must point at this same vgId.
        keys = [f"peachfile:{f}" for f in ids.get("peachfileFilerEntityIds") or []]
        keys += [f"fec:{f}" for f in ids.get("fecCandidateIds") or []]
        if not keys:
            err(f"{p['vgId']} ({p['name']['full']}) has a vgId but no durable key")
        for k in keys:
            if assign.get(k) != p["vgId"]:
                err(f"ledger key {k} maps to {assign.get(k)}, but the record carrying that "
                    f"filing is {p['vgId']} ({p['name']['full']})")

    old = git_show(LEDGER_FILE)
    if old:
        for key, vg in (old.get("assign") or {}).items():
            if key not in assign:
                err(f"ledger dropped assignment {key} -> {vg} (the ledger is append-only)")
            elif assign[key] != vg:
                err(f"ledger renumbered {key}: was {vg}, now {assign[key]} "
                    f"(a published vgId must never change meaning)")
    else:
        warn("ledger has no committed baseline yet — append-only check skipped")

    # --- sameAs merges must actually merge -----------------------------------
    xov = {k: v for k, v in load(OVERRIDES_FILE, {}).items() if not k.startswith("_")}
    for key, patch in xov.items():
        target = patch.get("sameAs")
        if not target:
            continue
        if key not in assign:
            warn(f"sameAs override {key} -> {target} did not apply (key unused this build)")
        elif assign.get(key) != assign.get(target):
            err(f"sameAs override {key} -> {target} did not merge: "
                f"{assign.get(key)} vs {assign.get(target)}")

    # --- Report --------------------------------------------------------------
    cov = meta.get("coverage", {})
    amb = cov.get("ambiguous") or []
    print(f"{len(people)} people | {with_vgid} keyed | {cov.get('unkeyed')} unkeyed | "
          f"{cov.get('candidacies')} candidacies | {len(amb)} ambiguous")
    if amb:
        warn(f"{len(amb)} ambiguous filing matches left unresolved: {', '.join(map(str, amb[:5]))}"
             f" — resolve in {OVERRIDES_FILE} or ga-campaign-finance-overrides.json")

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
