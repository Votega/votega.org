#!/usr/bin/env python3
"""Build consumer-friendly race artifacts for the Votega/ga-races-elections repo.

Source: assets/data/races.json (nested: race -> phases -> ballots/candidates).
Artifacts, under races/<cycle>/ (one folder per election cycle, like early-vote/<election>/):
  races.json           Passthrough
  races.csv            One row per race (top-level fields flattened)
  candidates.csv       One row per (race, phase, candidate) — unnests the deep candidate data.
                       candidateId is blank for an incumbent listed by reference; memberId/memberSource
                       carry the member record they point at, and candidateKey is candidateId when there
                       is one, else memberId, so every row has one join key
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

from lib.sibling_publish import build_json, publish_or_dry_run, min_items

REPO = "Votega/ga-races-elections"
TOKEN_ENV = "GA_RACES_TOKEN"

SRC_RACES = "assets/data/races.json"
SRC_FEDERAL = "assets/data/current-members.json"
SRC_STATE = "assets/data/ga-members.json"

RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-races-elections/main"
#: Where these files used to live (the repo root, until 2026-10). The publish workflow removes them from the
#: target repo, because publishing only ever adds files. Do not reuse these names at the root.
LEGACY_ROOT_FILES = ("races.json", "races.csv", "candidates.csv", "races.schema.json", "RACES.md")


def group_by_cycle(races):
    """{cycle: [races]} -- each cycle is published to its own folder, races/<cycle>/.

    races.json may keep a past cycle's races alongside the current one once a new cycle starts
    (see RECURRING-TASKS.md section 2), and the older cycle's folder must keep describing only
    that cycle. A race with no integer cycle is refused: the folder name is part of the URL."""
    out = {}
    for r in races:
        c = r.get("cycle")
        if not isinstance(c, int) or isinstance(c, bool):
            raise ValueError(f"refusing to publish: race {r.get('id')!r} has no integer cycle ({c!r})")
        out.setdefault(c, []).append(r)
    if not out:
        raise ValueError("refusing to publish: races.json holds no races")
    return dict(sorted(out.items()))


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


def member_ref(cand):
    """(memberId, memberSource) for a candidate that is, or points at, a sitting member.

    A federal incumbent is stored as a reference (`memberId` + `memberSource`, no candidate `id`);
    a candidate who also holds a seat carries their own `id` AND `existingMemberId`. Same precedence
    as resolve_name, so the id published here is the one the name was looked up with."""
    mid = cand.get("existingMemberId") or cand.get("memberId")
    src = cand.get("existingMemberSource") or cand.get("memberSource")
    return (mid or "", (src or "") if mid else "")


# Columns are only ever APPENDED, so a consumer reading by position keeps working.
CANDIDATE_COLUMNS = ["raceId", "level", "chamber", "district", "cycle", "phase", "electionDate",
                     "party", "name", "type", "isIncumbent", "candidateId",
                     "memberId", "memberSource", "candidateKey"]


def candidates_csv(races, fed, state):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CANDIDATE_COLUMNS)
    for r in races:
        for phase_name, phase in (r.get("phases") or {}).items():
            if not isinstance(phase, dict):
                continue
            for c in phase_candidates(phase):
                if c.get("withdrawn"):
                    continue
                member_id, member_source = member_ref(c)
                w.writerow([
                    r.get("id"), r.get("level"), r.get("chamber"),
                    "" if r.get("district") is None else r.get("district"),
                    r.get("cycle"), phase_name, phase.get("electionDate"),
                    c.get("party"), resolve_name(c, fed, state), c.get("type"),
                    bool(c.get("isIncumbent") or c.get("type") == "incumbent"),
                    c.get("id"),
                    member_id, member_source,
                    c.get("id") or member_id,
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


def schema(schema_path="races/2026/races.schema.json"):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{RAW_BASE}/{schema_path}",
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
                        "level": {"type": "string", "enum": ["federal", "state", "state-executive", "state-judicial", "local"]},
                        "chamber": {"type": "string"},
                        "district": {"type": ["integer", "null"]},
                        "cycle": {"type": "integer"},
                        "activePhase": {"type": ["string", "null"], "description": "Which phase is current (e.g. primary, general, runoff)."},
                        "status": {"type": ["string", "null"], "enum": ["active", "complete", "certified", None], "description": "Lifecycle of the race. Absent/`active` = still on the ballot. `complete`/`certified` retire it from the active elections directory (kept for history, still on its results page) — used for a contest with no further phase, e.g. a special election that ends at its runoff."},
                        "winner": {"type": ["object", "null"], "description": "The decided result (present once status is complete/certified): {name, candidateId, party, phase}; an incumbent listed only by member id carries memberId in place of candidateId.", "additionalProperties": True},
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
    raw = open(SRC_RACES, "rb").read()
    doc = json.loads(raw)
    races = doc.get("races", [])
    check_active_phase(races)  # refuse to publish a stale/forgotten phase bump
    by_cycle = group_by_cycle(races)
    fed, state = load_name_maps()
    out = {}
    for cycle, cycle_races in by_cycle.items():
        folder = f"races/{cycle}"
        if len(by_cycle) == 1:
            cycle_doc, cycle_json = doc, raw  # one cycle: the source file, byte for byte
        else:
            cycle_doc = {**doc, "races": cycle_races}
            cycle_json = build_json(cycle_doc)
        out.update({
            f"{folder}/races.json": cycle_json,
            f"{folder}/races.csv": races_csv(cycle_races),
            f"{folder}/candidates.csv": candidates_csv(cycle_races, fed, state),
            f"{folder}/races.schema.json": build_json(schema(f"{folder}/races.schema.json")),
            f"{folder}/RACES.md": races_md(cycle_doc),
        })
    return out


def validate(artifacts):
    folders = sorted(p for p in artifacts if p.endswith("/races.json"))
    if not folders:
        raise ValueError("refusing to publish: no races.json artifact was built")
    for path in folders:
        min_items(path, "races")(artifacts)


def main():
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV, validate=validate)


if __name__ == "__main__":
    main()
