#!/usr/bin/env python3
"""
Draft county-commission rosters for counties NOT yet in _data/local_officials.yml,
by merging SAVED SoS results from more than one election (no network).

WHY
    generate_local_officials.py drafts a roster from ONE election, which covers only
    about half of a staggered board. With two saved pulls (the 2024 and 2026
    generals) the two halves line up: for each seat the LATEST election that
    contested it wins. This script does that merge, over files saved by the
    results pulls (data-inputs/sos-results-*/results-*.json), and reuses the
    classification and YAML emission of generate_local_officials.py so a drafted
    block looks like a hand-curated one.

    It never writes _data/. It prints/writes YAML for a person to review and paste,
    plus a review report of what the data cannot settle.

WHAT IT CANNOT KNOW (flagged in the output, see REVIEW FLAGS)
    - changes since the seat's last election: a resignation, death or appointment
      leaves the old winner in the draft, and many specials never reach the SoS
      portal (Tift D5, Morgan D5 in the 2024 reconciliation);
    - contact details, photos, term dates (term_end is last_elected + 4, assumed);
    - sub-50% leaders (a runoff decided the seat; local runoffs are not on the portal);
    - consolidated governments and unusual labels (a countywide chair seat the SoS
      calls "District 7").

USAGE
    python scripts/draft_county_rosters_from_results.py \\
        --results 2024=data-inputs/sos-results-2024/results-2024-general.json \\
        --results 2026=data-inputs/sos-results-2026-general/results-2026-general.json \\
        --counties richmond,glynn --out-dir data-inputs/county-pilot
    python scripts/draft_county_rosters_from_results.py ... --top 10   # largest uncurated
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from generate_local_officials import (  # noqa: E402
    classify, clean_name, emit_places_yaml, emit_yaml, map_party, short_name, slug_of,
)
from lib.atomic_io import atomic_write  # noqa: E402

ROSTER = "_data/local_officials.yml"
PLACES = "_data/places.yml"


def load_results(specs):
    """['2024=path', '2026=path'] -> [(year, meta, counties)] oldest first."""
    out = []
    for spec in specs:
        year, _, path = spec.partition("=")
        d = json.load(open(path, encoding="utf-8"))
        out.append((int(year), d["metadata"], d["counties"]))
    return sorted(out, key=lambda t: t[0])


def curated_ids():
    y = yaml.safe_load(open(ROSTER, encoding="utf-8")) or {}
    return {j.get("id") for j in y.get("jurisdictions", []) if isinstance(j, dict)}


def place_ids():
    y = yaml.safe_load(open(PLACES, encoding="utf-8")) or {}
    return {p.get("slug") for p in y.get("places", []) if isinstance(p, dict)}


def county_size(results, short):
    """A size proxy: the presidential vote total in the earliest general (0 if absent)."""
    for _year, _meta, counties in results:
        c = counties.get(short)
        if not c:
            continue
        for x in c["contests"]:
            if "president" in x["nameClean"].lower():
                return x["voteTotal"] or 0
    return 0


def _seat_id_key(seat):
    return re.sub(r"[^a-z0-9]+", "-", (seat or "").lower()).strip("-")


def draft_county(results, short):
    """Merge the commission seats of one county across the saved elections.
    Returns (members, flags)."""
    seats = {}   # seat key -> member dict (latest election wins)
    flags = []
    for year, meta, counties in results:
        c = counties.get(short)
        if not c:
            continue
        slug = meta["electionSlug"]
        for x in c["contests"]:
            cls = classify(x["nameClean"])
            if not cls or x["type"] != "Candidate" or not x["options"]:
                continue
            if {o["name"].strip().lower() for o in x["options"]} <= {"yes", "no"}:
                continue
            role, title, seat, special = cls
            special = special or bool(re.search(r"\bspec", x["nameClean"], re.I))
            vf = x.get("voteFor") or 1
            winners = x["options"][:vf]
            top = winners[0]
            full = clean_name(top.get("nameBare") or top["name"])
            if full.isupper():  # some counties publish ALL CAPS names
                full = full.title()
            disp = short_name(full)
            m = {
                "name": disp, "role": role, "seat": seat,
                "party": map_party(top.get("partyResolved") or top.get("party")),
                "last_elected": year, "source": meta["source"].replace("{county}", short),
                "_office": x["nameClean"], "_share": round((top["pct"] or 0) / 100, 3),
                "_election": slug, "_incumbent": bool(top.get("incumbent")),
            }
            if year >= date.today().year and not top.get("incumbent"):
                # Elected this year but not seated until Jan 1: the person on the seat
                # today is the outgoing holder, so stage the winner as incoming.
                m["takes_office"] = f"{year + 1}-01-01"
                lost = next((o for o in x["options"][vf:] if o.get("incumbent")), None)
                if lost:
                    lf = clean_name(lost.get("nameBare") or lost["name"])
                    if lf.isupper():
                        lf = lf.title()
                    m["_outgoing"] = {
                        "name": short_name(lf), "role": role, "seat": seat,
                        "party": map_party(lost.get("partyResolved") or lost.get("party")),
                        "last_elected": None, "source": m["source"], "leaves_office": m["takes_office"],
                        "leave_reason": "term-ended", **({"title": title} if title else {}),
                        **({"full_name": lf} if lf != short_name(lf) else {}),
                    }
                else:
                    flags.append(f"{seat}: new winner {disp} takes office {m['takes_office']} but no incumbent "
                                 "was on the ballot, so the CURRENT holder is not in the data: add them from the county page")
            if full != disp:
                m["full_name"] = full
            if title:
                m["title"] = title
            if special:
                m["_special"] = True
            if vf == 1 and len(x["options"]) > 1 and (top["pct"] or 0) <= 50:
                m["_needs_runoff_check"] = True
            if vf > 1:
                flags.append(f"{seat}: vote-for-{vf} contest, only the top finisher drafted")
            key = (role == "Chair" and "chair") or _seat_id_key(seat)
            prev = seats.get(key)
            if prev and prev["name"] != m["name"]:
                flags.append(f"{seat}: {prev['last_elected']} winner {prev['name']} replaced by "
                             f"{year} winner {m['name']} (re-contested)")
            seats[key] = m
    members = []
    for m in sorted(seats.values(), key=lambda m: (m["role"] != "Chair", m["seat"])):
        if m.get("_outgoing"):
            members.append(m["_outgoing"])
        members.append(m)
    # A numbered board with a hole (Districts 2-5 but no 1) means a seat sat out both
    # elections or carries a label the classifier missed: the draft is incomplete.
    nums = sorted({int(n) for m in members for n in re.findall(r"^(?:District|Post|Super District) (\d+)", m["seat"])})
    if nums:
        gaps = [n for n in range(1, nums[-1] + 1) if n not in nums]
        if gaps:
            flags.append("INCOMPLETE: no result for seat number(s) " + ", ".join(map(str, gaps))
                         + " in either election (last elected before 2024 or a label not recognised)")
    return members, flags


def review_flags(members):
    """Per-seat reasons a person should look before trusting a draft row."""
    out = []
    for m in members:
        if m.get("leaves_office"):
            continue  # outgoing holder: shown for context
        why = []
        if m.get("takes_office"):
            why.append(f"winner not yet seated (takes office {m['takes_office']}): outgoing holder is the one on the seat today")
        if m.get("_needs_runoff_check"):
            why.append(f"leader had {int(m['_share'] * 100)}%: a runoff decided it, not on the portal")
        if m.get("_special"):
            why.append("special election")
        if m["last_elected"] == 2024:
            why.append("last on the ballot in 2024: confirm no vacancy, resignation or appointment since")
        if m["party"] == "Nonpartisan":
            why.append("no party on the ballot (independent or nonpartisan)")
        if why:
            out.append((m["seat"], m["name"], why))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", action="append", required=True, metavar="YEAR=PATH")
    ap.add_argument("--counties", help="comma-separated county slugs (e.g. glynn,bulloch)")
    ap.add_argument("--top", type=int, help="the N largest counties not yet in the roster")
    ap.add_argument("--out-dir", help="write <county>.yml, places.yml and report.json here")
    a = ap.parse_args()

    results = load_results(a.results)
    all_short = sorted({s for _y, _m, c in results for s in c})
    have = curated_ids()
    if a.counties:
        wanted = [c.strip() for c in a.counties.split(",") if c.strip()]
        shorts = [f"{c}-county-ga" for c in wanted]
    elif a.top:
        cand = [s for s in all_short if slug_of(s) not in have]
        shorts = sorted(cand, key=lambda s: -county_size(results, s))[:a.top]
    else:
        ap.error("give --counties or --top")
    in_places = place_ids()

    out_dir = Path(a.out_dir) if a.out_dir else None
    report, yaml_chunks, place_chunks = {}, [], []
    for short in shorts:
        slug = slug_of(short)
        if slug in have:
            print(f"{slug}: already curated, skipped", file=sys.stderr)
            continue
        members, flags = draft_county(results, short)
        name = f"{slug.replace('-', ' ').title()} County"
        if not members:
            print(f"{slug}: NO commission seats found in the saved results", file=sys.stderr)
            report[slug] = {"members": 0, "flags": ["no commission seats found"], "review": []}
            continue
        rf = review_flags(members)
        report[slug] = {"members": len([m for m in members if not m.get("leaves_office")]), "flags": flags,
                        "review": [{"seat": s, "name": n, "why": w} for s, n, w in rf]}
        yaml_chunks.append(emit_yaml(slug, name, {"members": members}))
        if slug not in in_places:
            place_chunks.append(emit_places_yaml(slug, name))
        print(f"{slug}: {len([m for m in members if not m.get('leaves_office')])} seats, {len(rf)} to review"
              + (f", {len(flags)} merge notes" if flags else ""), file=sys.stderr)

    if out_dir:
        with atomic_write(out_dir / "roster-drafts.yml") as f:
            f.write("\n\n".join(yaml_chunks) + "\n")
        with atomic_write(out_dir / "places-drafts.yml") as f:
            f.write("\n\n".join(place_chunks) + "\n")
        with atomic_write(out_dir / "report.json") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)
        print(f"wrote drafts for {len(yaml_chunks)} counties -> {out_dir}", file=sys.stderr)
    else:
        print("\n\n".join(yaml_chunks))


if __name__ == "__main__":
    main()
