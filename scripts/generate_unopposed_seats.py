#!/usr/bin/env python3
"""Count Georgia legislative seats with no major-party opponent in 2026.

A pure derivation of races.json (like build_general_placeholder.py): reads the
236 state House + Senate races and counts how many have candidates from at most
one major party on the general-election ballot — i.e. no contest between
Democrats and Republicans, so the seat is effectively decided.

Georgia publishes no such figure, and a third of the General Assembly runs without
major-party opposition. The number is written to _data/ so Jekyll renders it into
the page at build time and it stays current as races.json is curated — never
hardcoded.

Basis: each seat's **general-phase** ballot (the November field of nominees), not
primary filings. Two seats in 2026 had both parties file in the primary but only
one nominee reach the general ballot; the general basis counts those correctly.
Falls back to a seat's primary ballot only if it has no general ballot at all.

Usage:
  python scripts/generate_unopposed_seats.py           # write _data/ga_unopposed_seats.json
  python scripts/generate_unopposed_seats.py --check    # exit 1 if on-disk file is stale
"""

import json
import sys
from datetime import datetime, timezone

RACES_FILE = "assets/data/races.json"
OUT_FILE = "_data/ga_unopposed_seats.json"

MAJOR_PARTIES = ("Democrat", "Republican")
CHAMBERS = {
    "Georgia House of Representatives": "house",
    "Georgia State Senate": "senate",
}


def ballot_phase(race):
    """The phase whose ballot decides the November contest: general if it has any
    candidates, else primary (a seat not yet advanced past the primary)."""
    phases = race.get("phases", {})
    general = phases.get("general", {})
    if any((general.get("ballots") or {}).values()):
        return general
    return phases.get("primary", {})


def major_parties_present(phase):
    """The set of major parties fielding at least one candidate on this ballot."""
    ballots = phase.get("ballots") or {}
    return {p for p in MAJOR_PARTIES if len(ballots.get(p) or []) >= 1}


def sole_candidate(phase):
    """The lone candidate on the ballot, or None if not exactly one."""
    ballots = phase.get("ballots") or {}
    cands = [c for lst in ballots.values() for c in (lst or [])]
    return cands[0] if len(cands) == 1 else None


def build(races_path=RACES_FILE):
    with open(races_path, encoding="utf-8") as f:
        data = json.load(f)

    seats = []
    chamber_stats = {
        "house": {"total": 0, "unopposed": 0, "republicanSafe": 0, "democraticSafe": 0},
        "senate": {"total": 0, "unopposed": 0, "republicanSafe": 0, "democraticSafe": 0},
    }

    for race in data.get("races", []):
        if race.get("level") != "state":
            continue
        key = CHAMBERS.get(race.get("chamber"))
        if not key:
            continue
        chamber_stats[key]["total"] += 1

        phase = ballot_phase(race)
        present = major_parties_present(phase)
        if len(present) > 1:
            continue  # contested by both major parties

        # No major-party opponent. Record which party holds the seat uncontested
        # (None if neither major party is running — e.g. an independent-only seat).
        chamber_stats[key]["unopposed"] += 1
        held = next(iter(present)) if present else None
        if held == "Republican":
            chamber_stats[key]["republicanSafe"] += 1
        elif held == "Democrat":
            chamber_stats[key]["democraticSafe"] += 1

        lone = sole_candidate(phase)
        seats.append({
            "id": race.get("id"),
            "chamber": key,
            "district": race.get("district"),
            "party": held,
            "candidate": lone.get("name") if lone else None,
        })

    house, senate = chamber_stats["house"], chamber_stats["senate"]
    total = house["total"] + senate["total"]
    unopposed = house["unopposed"] + senate["unopposed"]
    republican_safe = house["republicanSafe"] + senate["republicanSafe"]
    democratic_safe = house["democraticSafe"] + senate["democraticSafe"]

    seats.sort(key=lambda s: (s["chamber"], s["district"] if s["district"] is not None else 9999))

    return {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Derived from races.json (general-election ballot; primary fallback)",
            "cycle": 2026,
            "methodology": "A seat counts as having no major-party opponent when at most one of "
                           "Democrat / Republican fields a candidate on its general-election ballot.",
        },
        "cycle": 2026,
        "total": total,
        "unopposed": unopposed,
        "contested": total - unopposed,
        "unopposedPct": round(unopposed / total * 100, 1) if total else 0,
        "republicanSafe": republican_safe,
        "democraticSafe": democratic_safe,
        "byChamber": {"house": house, "senate": senate},
        "seats": seats,
    }


def main():
    check = "--check" in sys.argv[1:]
    result = build()

    if check:
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                on_disk = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            print(f"{OUT_FILE} missing or invalid — run without --check to build it.", file=sys.stderr)
            sys.exit(1)
        # Compare everything except the timestamp, which moves every run.
        a = {k: v for k, v in result.items() if k != "metadata"}
        b = {k: v for k, v in on_disk.items() if k != "metadata"}
        if a != b:
            print(f"{OUT_FILE} is STALE relative to {RACES_FILE} — regenerate it.", file=sys.stderr)
            sys.exit(1)
        print(f"{OUT_FILE} is up to date ({result['unopposed']} of {result['total']} seats unopposed).")
        return

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_FILE}: {result['unopposed']} of {result['total']} legislative seats "
          f"have no major-party opponent ({result['unopposedPct']}%) — "
          f"{result['republicanSafe']} R-safe, {result['democraticSafe']} D-safe.")


if __name__ == "__main__":
    main()
