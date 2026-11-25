#!/usr/bin/env python3
"""
Join a saved SoS county-results pull to _data/local_officials.yml and write one
review file for tools/local-results-review.html.

WHY
    After an election the SoS results API holds the winners of every county
    commission seat. This lines each seat up against the curated roster so a
    person can see, seat by seat, whether the winner is already staged, is a
    re-elected incumbent, is a turnover nobody has staged yet, or needs a runoff
    check. It READS the roster and the saved results; it writes only the review
    JSON (under gitignored data-inputs/). It never edits local_officials.yml.

INPUT
    A results file saved in the shape written by the 2026/2024 pulls:
    data-inputs/sos-results-2026-general/results-2026-general.json
    ({"metadata":{...}, "counties":{"<county>-county-ga":{"contests":[...]}}}).

SCOPE (v1)
    County-commission seats only (classify() in generate_local_officials.py).
    BOE, soil & water, solicitor and city races are not compared yet.

STATUS (per results seat; see STATUSES)
    staged             winner already has an incoming row for the seat
    retained           winner is the current holder (re-elected)
    name-variant       same surname as a current holder, different given name/form
    turnover-unstaged  winner is not on the roster for the seat
    runoff-check       single-seat leader at or under 50%: a runoff may decide it
    unopposed-open     (informational) none; unopposed winners fall under the above
    no-roster          county has no curated roster yet
    not-up             (roster-only) a current seat with no contest in this election

SEATING MODE (--later-results)
    For an EARLIER election (2024) checked against today's roster: a winner who no
    longer holds the seat is only a problem if the seat was not re-contested since.
      matches      the current holder is the winner (and last_elected agrees)
      mismatch     holder differs, or last_elected disagrees, and no later contest explains it
      superseded   the seat was re-contested in the later election (expected change)
      not-covered  a current roster seat in neither election (pre-2024 cohort, odd label)

USAGE
    python scripts/build_local_results_review.py \\
        --results data-inputs/sos-results-2026-general/results-2026-general.json \\
        --out data-inputs/local-results-review/review-2026.json
    # seating mode:
    python scripts/build_local_results_review.py \
        --results data-inputs/sos-results-2024/results-2024-general.json \
        --later-results data-inputs/sos-results-2026-general/results-2026-general.json \
        --out data-inputs/local-results-review/review-2024.json
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from generate_local_officials import (  # noqa: E402
    _cmp_name, _norm, _seat_key, classify, slug_of,
)
from lib import local_terms  # noqa: E402

ROSTER = "_data/local_officials.yml"
STATUSES = ["turnover-unstaged", "runoff-check", "name-variant", "staged",
            "retained", "no-roster", "not-up",
            # seating mode (an earlier election vs today's roster):
            "mismatch", "not-covered", "superseded", "matches"]


def _surname(name):
    toks = _norm(name, loose=True).split()
    return toks[-1] if toks else ""


def _row(m, today):
    """A roster row, reduced to what the reviewer needs."""
    start = local_terms.parse_date(m.get("takes_office"))
    end = local_terms.parse_date(m.get("leaves_office"))
    if end and end <= today:
        state = "former"
    elif start and start > today:
        state = "incoming"
    else:
        state = "current"
    return {
        "name": m.get("name"), "fullName": m.get("full_name"), "role": m.get("role"),
        "seat": m.get("seat"), "party": m.get("party"), "state": state,
        "takesOffice": start.isoformat() if start else None,
        "leavesOffice": end.isoformat() if end else None,
        "lastElected": m.get("last_elected"), "termEnd": m.get("term_end"),
        "source": m.get("source"),
    }


def _results_seats(county_short, county):
    """Commission contests of one county -> seat dicts."""
    seats = []
    for c in county["contests"]:
        cls = classify(c["nameClean"])
        if not cls:
            continue
        role, title, seat, special = cls
        opts = c["options"]
        if not opts or c["type"] != "Candidate":
            continue
        if {o["name"].strip().lower() for o in opts} <= {"yes", "no"}:
            continue  # a referendum about the board (e.g. term limits), not a seat
        vf = c.get("voteFor") or 1
        top = opts[0]
        runoff = bool(vf == 1 and len(opts) > 1 and top["pct"] is not None and top["pct"] <= 50)
        seats.append({
            "contest": c["nameClean"], "role": role, "title": title, "seat": seat,
            "special": special or bool(re.search(r"\bspec", c["nameClean"], re.I)),
            "voteFor": vf, "voteTotal": c["voteTotal"], "runoffCheck": runoff,
            "unopposed": len(opts) == 1,
            "candidates": [{
                "rank": o["rank"], "name": o.get("nameBare") or o["name"], "rawName": o["name"],
                "party": o.get("partyResolved") or o.get("party"), "votes": o["votes"],
                "pct": o["pct"], "incumbent": bool(o.get("incumbent")),
                "note": o.get("partyNote"),
            } for o in opts],
        })
    return seats


def _seat_keys_by_county(results_path):
    res = json.load(open(results_path, encoding="utf-8"))
    out = {}
    for short, county in res["counties"].items():
        out[slug_of(short)] = {_seat_key(s["seat"]): s for s in _results_seats(short, county)}
    return out


def _to_seating(rows, later, later_label, year):
    """Re-label an election-mode build for an EARLIER election ("the seating election")
    against today's roster. A winner who no longer holds the seat is only a problem
    if the seat was not re-contested since; `later` is the later election's seats."""
    out = []
    for r in rows:
        later_seats = later.get(r["county"], {})
        res = r["results"]
        key = _seat_key(res["seat"]) if res else _seat_key((r["roster"][0] or {}).get("seat"))
        later_seat = later_seats.get(key)
        st = r["status"]
        if st == "not-up":
            if later_seat:
                continue  # covered by the later election's review
            r["status"] = "not-covered"
            r["detail"] = "current seat in neither election: elected before the earliest results on the portal, or labelled differently"
        elif st in ("retained", "staged"):
            r["status"] = "matches"
            le = r["roster"][0].get("lastElected") if r["roster"] else None
            if le and str(le) != str(year) and not later_seat:
                r["status"] = "mismatch"
                r["detail"] = f"holder matches the {year} winner but the roster says last_elected {le}"
        elif st == "no-roster":
            pass
        elif st == "turnover-unstaged" and any(
                str(m.get("lastElected") or "").isdigit() and int(m["lastElected"]) > int(year)
                for m in r["roster"]):
            # The roster already records a later election for the seat (typically a
            # special after the winner left), so the change is accounted for.
            m = next(m for m in r["roster"] if str(m.get("lastElected") or "").isdigit()
                     and int(m["lastElected"]) > int(year))
            r["status"] = "superseded"
            r["detail"] = f"roster holder {m['name']} was elected {m['lastElected']} (after the {year} winner left): confirm the source on the roster row"
        elif later_seat:
            w = later_seat["candidates"][0]
            r["status"] = "superseded"
            r["detail"] = f"seat re-contested in {later_label}: winner {w['name']} ({w['pct']}%)"
        elif st == "turnover-unstaged":
            r["status"] = "mismatch"
            r["detail"] = "winner is not on the roster for this seat and it was not re-contested: left office, replaced by a special, or roster out of date"
        out.append(r)
    return out


def build(results_path, roster_path=ROSTER, today=None, later_results=None, later_label=None):
    today = today or date.today()
    res = json.load(open(results_path, encoding="utf-8"))
    roster = yaml.safe_load(open(roster_path, encoding="utf-8")) or {}
    curated = {j["id"]: j for j in roster.get("jurisdictions", []) if isinstance(j, dict)}
    meta = res["metadata"]
    rows = []
    for short, county in sorted(res["counties"].items()):
        slug = slug_of(short)
        j = curated.get(slug)
        mem = [_row(m, today) for m in (j or {}).get("members", [])] if j else []
        seen_keys = set()
        for s in _results_seats(short, county):
            key = _seat_key(s["seat"])
            seen_keys.add(key)
            same_seat = [m for m in mem if _seat_key(m["seat"]) == key]
            winners = s["candidates"][:s["voteFor"]]
            w = winners[0]
            status, detail = "turnover-unstaged", None
            if not j:
                status = "no-roster"
            else:
                wn = _norm(w["name"], loose=True)
                wt = set(wn.split())

                def same_person(m):
                    # Exact, or one name's tokens are inside the other's with the same
                    # surname ("Parker Liles" vs full_name "Benjamin Parker Liles").
                    for n in (m["fullName"], m["name"]):
                        nn = _norm(n, loose=True)
                        if not nn:
                            continue
                        if nn == wn:
                            return True
                        nt = set(nn.split())
                        if (len(wt) >= 2 and len(nt) >= 2 and _surname(n) == _surname(w["name"])
                                and (wt <= nt or nt <= wt)):
                            return True
                    return False

                hit = [m for m in same_seat if same_person(m)]
                elsewhere = [m for m in mem if m["state"] == "current" and same_person(m)] if not hit else []
                if hit:
                    m = hit[0]
                    status = "staged" if m["state"] == "incoming" else "retained"
                elif elsewhere:
                    # Same person holds a seat here under a different label
                    # (results "County Commission Chairman" vs roster "Post 1").
                    status = "retained"
                    detail = f"on the roster as '{elsewhere[0]['seat']}' - seat label differs from results"
                    same_seat = elsewhere
                    seen_keys.add(_seat_key(elsewhere[0]["seat"]))
                elif s["runoffCheck"]:
                    status = "runoff-check"
                elif any(_surname(m["name"]) == _surname(w["name"]) and m["state"] != "former"
                         for m in same_seat):
                    status = "name-variant"
                    detail = "same surname as a current holder; confirm whether it is the same person"
            rows.append({
                "id": f"{slug}|{s['contest']}", "county": slug, "countyShort": short,
                "curated": bool(j), "status": status, "detail": detail,
                "results": s, "roster": [m for m in same_seat if m["state"] != "former"],
                "former": [m for m in same_seat if m["state"] == "former"],
                "sourceUrl": meta["source"].replace("{county}", short),
                "official": county["isOfficialResults"], "asOf": county["asOf"],
            })
        if j:  # current seats with no contest this election
            for m in mem:
                if m["state"] == "current" and m["seat"] and _seat_key(m["seat"]) not in seen_keys:
                    rows.append({
                        "id": f"{slug}|roster|{m['seat']}|{m['name']}", "county": slug,
                        "countyShort": short, "curated": True, "status": "not-up", "detail": None,
                        "results": None, "roster": [m], "former": [],
                        "sourceUrl": None, "official": None, "asOf": None,
                    })
    if later_results:
        rows = _to_seating(rows, _seat_keys_by_county(later_results), later_label or "the later election", meta["electionDate"][:4])
    return {
        "metadata": {
            "mode": "seating" if later_results else "election",
            "election": meta["electionSlug"], "electionDate": meta["electionDate"],
            "resultsFetchedAt": meta["fetchedAt"], "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rosterAsOf": today.isoformat(), "statuses": STATUSES, "rows": len(rows),
            "scope": "county-commission seats only",
        },
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roster", default=ROSTER)
    ap.add_argument("--later-results", help="a LATER election's results file: switches to seating mode, "
                    "where a seat re-contested later is 'superseded', not a mismatch")
    ap.add_argument("--later-label", default="2026")
    a = ap.parse_args()
    out = build(a.results, a.roster, later_results=a.later_results, later_label=a.later_label)
    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    from lib.atomic_io import atomic_write
    with atomic_write(p) as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    c = Counter(r["status"] for r in out["rows"])
    print(f"wrote {p} ({out['metadata']['rows']} rows)")
    for s in STATUSES:
        print(f"  {s:18} {c.get(s, 0)}")


if __name__ == "__main__":
    main()
