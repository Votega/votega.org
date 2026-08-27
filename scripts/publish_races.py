#!/usr/bin/env python3
"""Build consumer-friendly race artifacts for the Votega/ga-races-elections repo.

Source: assets/data/races.json (nested: race -> phases -> ballots/candidates).
Artifacts (repo root, matching the repo's layout):
  races.json           Passthrough
  races.csv            One row per race (top-level fields flattened)
  candidates.csv       One row per (race, phase, candidate) — unnests the deep candidate data
  races.schema.json    JSON Schema for races.json
  RACES.md             Overview: counts by cycle, level, and active phase

Incumbent candidates in races.json reference a member id (no inline name); this resolves
them against current-members.json / ga-members.json, mirroring race.html and the site's
search-corpus builder. Writes artifacts only; the workflow commits them.
"""
import csv
import io
import json
import os
import sys
from collections import Counter

from lib.sibling_publish import build_json, publish_or_dry_run

REPO = "Votega/ga-races-elections"
TOKEN_ENV = "GA_RACES_TOKEN"

SRC_RACES = "assets/data/races.json"
SRC_FEDERAL = "assets/data/current-members.json"
SRC_STATE = "assets/data/ga-members.json"


def load_name_maps():
    fed, state = {}, {}
    if os.path.exists(SRC_FEDERAL):
        for m in json.load(open(SRC_FEDERAL, encoding="utf-8")).get("members", []):
            if m.get("bioguideId"):
                fed[m["bioguideId"]] = m.get("name")
    if os.path.exists(SRC_STATE):
        for m in json.load(open(SRC_STATE, encoding="utf-8")).get("members", []):
            if m.get("id"):
                state[m["id"]] = m.get("name")
    return fed, state


def resolve_name(cand, fed, state):
    if cand.get("name"):
        return cand["name"]
    mid = cand.get("existingMemberId") or cand.get("memberId")
    src = cand.get("existingMemberSource") or cand.get("memberSource")
    if not mid:
        return ""
    return (fed if src == "congress" else state).get(mid, "")


def phase_candidates(phase):
    """Flatten a phase's candidates across both storage shapes (party-keyed `ballots`
    and flat nonpartisan `candidates`), tagging each with its party."""
    out = []
    if phase.get("ballots"):
        for party, ballot in phase["ballots"].items():
            for c in ballot:
                out.append({**c, "party": c.get("party") or party})
    else:
        out.extend(phase.get("candidates") or [])
    return out


# Canonical phase order. activePhase only ever moves forward through this
# sequence, one step per election as its winners are certified.
PHASE_ORDER = {"primary": 0, "special": 1, "runoff": 2, "general": 3}


def derive_active_phase(race):
    """The phase a race is currently in, derived from which phases hold candidates.

    Equals the furthest-along phase that has actually been populated. This works
    because build_legislative_races.py seeds an EMPTY general (candidates: []) dated
    in November, and the certification scripts (update_general_from_primary.py /
    _from_runoff.py) populate the next phase's ballot and bump activePhase together.
    So "latest populated phase, in canonical order" tracks the stored field through
    every state -- including the post-election window before winners are promoted
    (empty general -> still 'primary'), which a pure date-based rule gets wrong.

    Returns None when no phase has any candidate (nothing to assert against).
    """
    phases = race.get("phases") or {}
    populated = [name for name, ph in phases.items() if phase_candidates(ph)]
    if not populated:
        return None
    return sorted(populated, key=lambda n: PHASE_ORDER.get(n, 99))[-1]


def check_active_phase(races):
    """Fail the publish if any race's stored activePhase disagrees with its ballot data.

    This is the automated guard for the manual "advance activePhase after each
    election" step in RECURRING-TASKS.md. It runs on every push to main that touches
    races.json (via publish-races-to-ga-races-elections.yml), so a forgotten bump
    stops being a silent stale-ballot bug on the live site and becomes a red run.

    It does NOT false-fire during the legitimate post-election certification lag,
    because the derivation is populated-aware, not date-based: while the next phase's
    ballot is still empty, both the stored field and the derived value read the old
    phase. Drift only appears once a later phase has candidates but activePhase still
    points elsewhere (or vice-versa: activePhase advanced past an empty phase).
    """
    drift = []
    for r in races:
        want = derive_active_phase(r)
        got = r.get("activePhase")
        if want is not None and got != want:
            drift.append((r.get("id"), got, want))
    if drift:
        print("ERROR: activePhase is out of sync with the ballot data in races.json.")
        print("Most likely an election was certified but the 'advance activePhase'")
        print("step in RECURRING-TASKS.md was missed (or a ballot was populated/emptied")
        print("without updating activePhase).\n")
        for rid, got, want in drift:
            print(f"  {rid}: activePhase={got!r} but its data implies {want!r}")
        print(f"\n{len(drift)} race(s) out of sync. Set activePhase in "
              "assets/data/races.json to match, or populate the intended phase's ballot.")
        sys.exit(1)
    print(f"activePhase check: all {len(races)} races consistent with their ballot data.")


def races_csv(races):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "level", "chamber", "district", "cycle", "activePhase",
                "displayTitle", "incumbentBioguideId"])
    for r in races:
        w.writerow([r.get("id"), r.get("level"), r.get("chamber"),
                    "" if r.get("district") is None else r.get("district"),
                    r.get("cycle"), r.get("activePhase"), r.get("displayTitle"),
                    r.get("incumbentBioguideId")])
    return buf.getvalue().encode()


def candidates_csv(races, fed, state):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["raceId", "level", "chamber", "district", "cycle", "phase", "electionDate",
                "party", "name", "type", "isIncumbent", "candidateId"])
    for r in races:
        for phase_name, phase in (r.get("phases") or {}).items():
            if not isinstance(phase, dict):
                continue
            for c in phase_candidates(phase):
                if c.get("withdrawn"):
                    continue
                w.writerow([
                    r.get("id"), r.get("level"), r.get("chamber"),
                    "" if r.get("district") is None else r.get("district"),
                    r.get("cycle"), phase_name, phase.get("electionDate"),
                    c.get("party"), resolve_name(c, fed, state), c.get("type"),
                    bool(c.get("isIncumbent") or c.get("type") == "incumbent"),
                    c.get("id"),
                ])
    return buf.getvalue().encode()


def races_md(doc):
    races = doc.get("races", [])
    updated = doc.get("updatedAt", "")
    by_cycle = Counter(r.get("cycle") for r in races)
    by_level = Counter(r.get("level") or "?" for r in races)
    by_phase = Counter(r.get("activePhase") or "?" for r in races)
    L = ["# Georgia Races & Elections", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {updated} · {len(races)} races._")
    L.append("")
    L.append("> Data: [`races.json`](races.json) (full, nested — every candidate & phase), "
             "[`races.csv`](races.csv) (one row per race), "
             "[`candidates.csv`](candidates.csv) (one row per candidate, flattened).")
    L.append("")

    def table(title, counter, col):
        out = [f"## {title}", "", f"| {col} | Races |", "|---|---|"]
        for k, n in sorted(counter.items(), key=lambda kv: str(kv[0])):
            out.append(f"| {k} | {n} |")
        out.append("")
        return out

    L += table("By cycle", by_cycle, "Cycle")
    L += table("By level", by_level, "Level")
    L += table("By active phase", by_phase, "Active phase")
    return ("\n".join(L) + "\n").encode()


def schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://raw.githubusercontent.com/Votega/ga-races-elections/main/races.schema.json",
        "title": "Georgia Races & Elections",
        "description": "Curated Georgia election races. Each race carries per-phase ballots; "
                       "partisan races use party-keyed `ballots`, nonpartisan (judicial) races use "
                       "a flat `candidates` array. See races.csv / candidates.csv for flat views.",
        "type": "object",
        "required": ["races"],
        "properties": {
            "updatedAt": {"type": ["string", "null"]},
            "races": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "level", "chamber", "cycle"],
                    "properties": {
                        "id": {"type": "string"},
                        "level": {"type": "string", "enum": ["federal", "state", "state-executive", "state-judicial"]},
                        "chamber": {"type": "string"},
                        "district": {"type": ["integer", "null"]},
                        "cycle": {"type": "integer"},
                        "activePhase": {"type": ["string", "null"], "description": "Which phase is current (e.g. primary, general, runoff)."},
                        "displayTitle": {"type": ["string", "null"]},
                        "incumbentBioguideId": {"type": ["string", "null"]},
                        "phases": {
                            "type": "object",
                            "description": "Keyed by phase name; each phase has electionDate plus ballots{} (partisan) or candidates[] (nonpartisan).",
                        },
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def build_artifacts():
    doc = json.load(open(SRC_RACES, encoding="utf-8"))
    races = doc.get("races", [])
    check_active_phase(races)  # refuse to publish a stale/forgotten phase bump
    fed, state = load_name_maps()
    return {
        "races.json": open(SRC_RACES, "rb").read(),
        "races.csv": races_csv(races),
        "candidates.csv": candidates_csv(races, fed, state),
        "races.schema.json": build_json(schema()),
        "RACES.md": races_md(doc),
    }


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
