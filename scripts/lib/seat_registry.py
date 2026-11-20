"""The seat registry: every elected seat VoteGA tracks, and the maps that drew them.

Pure functions only (no file or network access), shared by
scripts/build_seat_registry.py, scripts/validate_seats.py and the offline tests.
The rules are in docs/seat-history-design.md ("The identity rule"):

  * A districted seat is its set of census blocks. A new map creates a new seat
    only for a district whose blocks changed (or that was renumbered); a district
    it left untouched keeps its seat, so the seat id keeps the suffix of the map
    that FIRST drew it (`ga-house-15@2021` is today's HD 15).
  * Identity comes from the block-equivalency files, never from district numbers:
    2021 GA-6 is mostly 2023 GA-7.
  * A seat id is written once and never renamed or removed.
"""

BODY_ORDER = ["ga-executive", "us-senate-ga", "us-house-ga", "ga-senate", "ga-house"]


def compare_plans(old, new):
    """Compare two block-equivalency maps ({block GEOID: district int}).

    Returns {"carriedOver": [...], "newlyDrawn": [...], "renumberedIdentical": [[old, new]]}
    for the NEW plan's districts. A district is carried over only when its block set
    is identical to the same-numbered district of the old plan. A new district whose
    blocks equal a DIFFERENTLY numbered old district is newly drawn (the number is part
    of what voters see) and listed in renumberedIdentical for an exact lineage link.
    Raises ValueError when the two plans do not cover the same blocks.
    """
    if set(old) != set(new):
        raise ValueError(f"plans cover different blocks ({len(old)} vs {len(new)}); "
                         "the inputs do not describe the same Census geography")
    old_sets, new_sets = {}, {}
    for block, d in old.items():
        old_sets.setdefault(d, set()).add(block)
    for block, d in new.items():
        new_sets.setdefault(d, set()).add(block)
    old_by_set = {frozenset(s): d for d, s in old_sets.items()}
    carried, drawn, renumbered = [], [], []
    for d in sorted(new_sets):
        if old_sets.get(d) == new_sets[d]:
            carried.append(d)
            continue
        drawn.append(d)
        twin = old_by_set.get(frozenset(new_sets[d]))
        if twin is not None:
            renumbered.append([twin, d])
    moved = sum(1 for b in new if new[b] != old[b])
    return {"carriedOver": carried, "newlyDrawn": drawn, "renumberedIdentical": renumbered,
            "blocks": len(new), "blocksThatChangedDistrict": moved}


def seat_id(body, district, plan):
    return f"{body}-{district}@{plan['suffix']}"


def plans_by_body(plans):
    """{body: [plan, ...]} in effective-date order."""
    out = {}
    for p in sorted(plans, key=lambda p: p["effective"]):
        out.setdefault(p["body"], []).append(p)
    return out


def build_seats(plans_doc, comparison, executive_seats):
    """The full seat list. `comparison` is {new plan id: compare_plans(...) result}."""
    bodies = plans_doc["bodies"]
    seats = {}
    for body, chain in plans_by_body(plans_doc["plans"]).items():
        n = bodies[body]["districts"]
        label = bodies[body]["label"]
        current = {}                                   # district -> seat id in force
        for i, plan in enumerate(chain):
            if i == 0:
                drawn, carried, renumbered = list(range(1, n + 1)), [], []
            else:
                cmp_ = comparison[plan["id"]]
                drawn, carried = cmp_["newlyDrawn"], cmp_["carriedOver"]
                renumbered = cmp_["renumberedIdentical"]
            for d in drawn:
                if d in current:
                    seats[current[d]]["redrawnBy"] = plan["id"]
            redrawn_old = {d: current[d] for d in drawn if d in current}
            for d in drawn:
                sid = seat_id(body, d, plan)
                seats[sid] = {
                    "id": sid, "body": body, "title": f"{label} {d}", "district": d,
                    "plan": plan["id"], "redrawnBy": None, "capacity": 1,
                    "successorSeats": [], "facts": {},
                }
                current[d] = sid
            for old_d, new_d in renumbered:
                seats[redrawn_old[old_d]]["successorSeats"].append({
                    "seatId": seat_id(body, new_d, plan), "blockShare": 1.0,
                    "populationShare": 1.0, "basis": "identical-blocks",
                })
            missing = [d for d in carried if d not in current]
            if missing:
                raise ValueError(f"{plan['id']} carries over districts no earlier plan drew: {missing}")
    for s in plans_doc.get("unmappedSeats", []):
        seats[s["id"]] = {"id": s["id"], "body": s["body"], "title": s["title"], "district": None,
                          "plan": None, "redrawnBy": None, "capacity": 1, "successorSeats": [],
                          "facts": dict(s.get("facts", {}))}
    for s in executive_seats:
        facts = {k: v for k, v in s.items() if k not in ("id", "title", "holders")}
        seats[s["id"]] = {"id": s["id"], "body": "ga-executive", "title": s["title"], "district": None,
                          "plan": None, "redrawnBy": None, "capacity": 1, "successorSeats": [],
                          "facts": facts}

    def order(s):
        return (BODY_ORDER.index(s["body"]), s["district"] or 0, s["plan"] or "", s["id"])
    return sorted(seats.values(), key=order)


def plan_summaries(plans_doc, comparison):
    out = []
    for p in sorted(plans_doc["plans"], key=lambda p: (BODY_ORDER.index(p["body"]), p["effective"])):
        row = {k: p.get(k) for k in ("id", "body", "firstElection", "effective", "effectiveBasis",
                                     "supersededBy", "source")}
        c = comparison.get(p["id"])
        if c:
            row["carriedOver"] = len(c["carriedOver"])
            row["newlyDrawn"] = len(c["newlyDrawn"])
        else:
            row["carriedOver"] = 0
            row["newlyDrawn"] = plans_doc["bodies"][p["body"]]["districts"]
        out.append(row)
    return out


def registry_errors(reg, plans_doc, comparison, executive_seats, previous=None):
    """Tier 1: every way seats.json can contradict itself or its inputs. Returns strings."""
    errs = []
    seats = reg.get("seats", [])
    ids = [s["id"] for s in seats]
    if len(ids) != len(set(ids)):
        errs.append("duplicate seat ids")
    if reg.get("metadata", {}).get("count") != len(seats):
        errs.append("metadata.count does not match the number of seats")
    by_id = {s["id"]: s for s in seats}
    plans = {p["id"]: p for p in plans_doc["plans"]}
    bodies = plans_doc["bodies"]

    # Plans: one chain per body, dates increasing, supersededBy pointing forward.
    for body, chain in plans_by_body(plans_doc["plans"]).items():
        if body not in bodies:
            errs.append(f"plan body {body} is not declared in bodies")
            continue
        for a, b in zip(chain, chain[1:]):
            if a.get("supersededBy") != b["id"]:
                errs.append(f"{a['id']} should be supersededBy {b['id']}")
            if not a["effective"] < b["effective"]:
                errs.append(f"{b['id']} takes effect before {a['id']}")
        if chain[-1].get("supersededBy"):
            errs.append(f"{chain[-1]['id']} is the latest plan but names a successor")
        n = bodies[body]["districts"]
        for p in chain[1:]:
            c = comparison.get(p["id"])
            if not c:
                errs.append(f"{p['id']} has no block comparison")
                continue
            parts = sorted(c["carriedOver"] + c["newlyDrawn"])
            if parts != list(range(1, n + 1)):
                errs.append(f"{p['id']}: carriedOver + newlyDrawn must partition districts 1..{n}")
            for old_d, new_d in c["renumberedIdentical"]:
                if new_d not in c["newlyDrawn"]:
                    errs.append(f"{p['id']}: renumbered district {new_d} must be newly drawn")

    # Seats: shape, plan references, and exactly the districts each body has today.
    current = {}
    for s in seats:
        body = s["body"]
        if s["plan"] is None:
            if s["district"] is not None:
                errs.append(f"{s['id']} has a district but no map")
            if "@" in s["id"]:
                errs.append(f"{s['id']} has a map suffix but no map")
            continue
        p = plans.get(s["plan"])
        if p is None:
            errs.append(f"{s['id']} names unknown plan {s['plan']}")
            continue
        if p["body"] != body:
            errs.append(f"{s['id']} is in {body} but its plan is {p['body']}")
        if s["id"] != seat_id(body, s["district"], p):
            errs.append(f"{s['id']} does not match its body, district and plan")
        if not 1 <= s["district"] <= bodies[body]["districts"]:
            errs.append(f"{s['id']} district is out of range")
        if s["redrawnBy"] is not None:
            r = plans.get(s["redrawnBy"])
            if r is None or r["body"] != body or not r["effective"] > p["effective"]:
                errs.append(f"{s['id']} redrawnBy {s['redrawnBy']} is not a later plan of its body")
            elif s["district"] not in comparison[r["id"]]["newlyDrawn"]:
                errs.append(f"{s['id']} is marked redrawn but {r['id']} carried it over")
        else:
            current.setdefault(body, []).append(s["district"])
        for link in s["successorSeats"]:
            t = by_id.get(link["seatId"])
            if t is None:
                errs.append(f"{s['id']} links to unknown seat {link['seatId']}")
            elif t["plan"] is None or not plans[t["plan"]]["effective"] > p["effective"]:
                errs.append(f"{s['id']} links to {t['id']}, which is not on a later map")
            if not 0 < link.get("blockShare", 0) <= 1:
                errs.append(f"{s['id']} link to {link['seatId']} has no valid blockShare")
    for body, b in bodies.items():
        if sorted(current.get(body, [])) != list(range(1, b["districts"] + 1)):
            errs.append(f"{body}: the seats in force are not exactly districts 1..{b['districts']}")

    exec_ids = {s["id"] for s in executive_seats}
    have_exec = {s["id"] for s in seats if s["body"] == "ga-executive"}
    if exec_ids != have_exec:
        errs.append(f"statewide seats differ from ga-executive-seats.json: "
                    f"missing {sorted(exec_ids - have_exec)}, extra {sorted(have_exec - exec_ids)}")

    # Append-only: a published seat is never removed, and its identity never changes.
    if previous:
        for old in previous.get("seats", []):
            new = by_id.get(old["id"])
            if new is None:
                errs.append(f"seat {old['id']} was removed (seat ids are append-only)")
                continue
            for k in ("body", "district", "plan"):
                if new.get(k) != old.get(k):
                    errs.append(f"seat {old['id']} changed {k}: {old.get(k)!r} -> {new.get(k)!r}")
            if old.get("redrawnBy") and new.get("redrawnBy") != old.get("redrawnBy"):
                errs.append(f"seat {old['id']} changed redrawnBy")
    return errs
