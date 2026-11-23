#!/usr/bin/env python3
"""Offline checks for seat holds (docs/seat-history-design.md, Phase 2).

A two-biennium toy House (three districts; the second map carries district 1 over and
redraws 2 and 3) pins the derivation rules, each tier-1 rule gets a negative control, and
the committed seat-holds.json must validate, match a rebuild and keep the measured facts.
Stdlib only, no network.

Usage: python scripts/test_seat_holds.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.seat_holds import (derive_holds, derive_vacancy_notes, holds_errors, overrides_errors,  # noqa: E402
                             second_monday_of_january, vacancy_gaps, vacancy_note_errors)
import build_seat_holds as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def raises(fn):
    try:
        fn()
        return None
    except ValueError as e:
        return str(e)


SEATS = {
    "metadata": {"plans": [{"id": "ga-house-2021", "effective": "2023-01-09"},
                           {"id": "ga-house-2023", "effective": "2025-01-13"}]},
    "seats": [
        {"id": "ga-house-1@2021", "body": "ga-house", "district": 1, "plan": "ga-house-2021", "redrawnBy": None, "capacity": 1},
        {"id": "ga-house-2@2021", "body": "ga-house", "district": 2, "plan": "ga-house-2021", "redrawnBy": "ga-house-2023", "capacity": 1},
        {"id": "ga-house-3@2021", "body": "ga-house", "district": 3, "plan": "ga-house-2021", "redrawnBy": "ga-house-2023", "capacity": 1},
        {"id": "ga-house-2@2023", "body": "ga-house", "district": 2, "plan": "ga-house-2023", "redrawnBy": None, "capacity": 1},
        {"id": "ga-house-3@2023", "body": "ga-house", "district": 3, "plan": "ga-house-2023", "redrawnBy": None, "capacity": 1},
    ],
}


def row(gid, district, vacated=None, party="Republican"):
    return {"id": gid, "first": "M", "last": str(gid), "chamber": "House", "district": district,
            "party": party, "dateVacated": vacated}


def snapshot(a_rows, b_rows):
    return {"metadata": {"sessions": [
                {"id": 1031, "description": "2023-2024 Regular Session", "library": "20232024"},
                {"id": 1033, "description": "2025-2026 Regular Session", "library": "20252026"}]},
            "sessions": {"1031": a_rows, "1033": b_rows}}


# 10 holds HD1 throughout (carried over); 20 holds HD2 and is re-elected to the redrawn HD2;
# 30 holds HD3 and leaves at the 2025 boundary (redrawn, so 'redistricted');
# in 2025-26, 40 holds HD3 and resigns, and 50 joins after.
A = [row(10, 1), row(20, 2), row(30, 3)]
Bs = [row(10, 1), row(20, 2), row(40, 3, vacated="2025-10-01T00:00:00"), row(50, 3)]
ROSTER = {10: {"id": "r10"}, 20: {"id": "r20"}, 40: {"id": "r40", "status": "Resigned"},
          50: {"id": "r50", "termStart": "2025-12-01"}}


def vg(gid, rec):
    return f"vg-{gid}"


def derive(a=A, b=Bs, roster=ROSTER, overrides=(), vgid=vg, specials=()):
    return derive_holds(snapshot(a, b), SEATS, roster, list(overrides), vgid, specials=list(specials))


SP_40 = {"chamber": "House", "district": 3, "election": "2025-11-04", "runoff": "2025-11-25",
         "runoffHeld": True, "source": "2025"}


def vacancy_cases():
    print("vacancies: computed from holds, with writs and specials as notes")
    hs = derive(specials=[SP_40])
    doc = {"metadata": {"count": len(hs)}, "holds": hs}
    check("a mid-term departure is a vacancy until the joiner starts",
          vacancy_gaps(hs, SEATS), [("ga-house-3@2023", "2025-10-01", "2025-12-01")])
    early = {**ROSTER, 50: {"id": "r50", "termStart": "2025-11-20"}}
    h50 = {(x["vgId"], x["seatId"]): x for x in derive(roster=early, specials=[SP_40])}[("vg-50", "ga-house-3@2023")]
    check("a joiner is never seated before the runoff that decided the seat",
          (h50["start"], h50["startBasis"]), (None, "unknown"))
    # Seat 1 vacant at the 2025 convening: a special decided after it, and no member vacated.
    pre = {"chamber": "House", "district": 1, "election": "2025-01-07", "runoff": "2025-02-04",
           "runoffHeld": True, "source": "2025"}
    late_b = [row(11, 1), row(20, 2), row(40, 3, vacated="2025-10-01T00:00:00"), row(50, 3)]
    roster = {**ROSTER, 11: {"id": "r11", "termStart": "2025-02-10"}}
    gone = [{"legisGaGovId": 10, "seatId": "ga-house-1@2021", "endedBy": "did-not-run"}]
    hs2 = derive(b=late_b, roster=roster, overrides=gone, specials=[pre, SP_40])
    h11 = {(x["vgId"], x["seatId"]): x for x in hs2}[("vg-11", "ga-house-1@2021")]
    check("a seat vacant at the convening seats its first member late, not at the convening",
          (h11["start"], h11["startBasis"]), ("2025-02-10", "roster-termStart"))
    check("and that is a vacancy from the convening",
          ("ga-house-1@2021", "2025-01-13", "2025-02-10") in vacancy_gaps(hs2, SEATS), True)
    writs = [{"date": "2025-09-25", "number": "09.25.25.01", "url": "u",
              "title": "Issuing a Writ of Election to fill the District 3 seat in the Georgia House of Representatives"},
             {"date": "2025-09-25", "number": "x", "url": "u",
              "title": "Issuing a Writ of Election to fill the District 3 seat in the Georgia State Senate"},
             {"date": "2025-09-25", "number": "y", "url": "u",
              "title": "Issuing a Writ of Election to fill the vacancy in Georgia's 3rd Congressional District"}]
    notes = derive_vacancy_notes(hs, SEATS, writs, [SP_40], {"2025": "https://example"}, today="9999-12-31")
    check("a writ issued BEFORE the vacancy still belongs to it; other chambers and Congress do not",
          [(n["kind"], n["date"]) for n in notes],
          [("writ", "2025-09-25"), ("special-election", "2025-11-04"), ("special-runoff", "2025-11-25")])
    no_runoff = derive_vacancy_notes(hs, SEATS, [], [{**SP_40, "runoffHeld": False}], {}, today="9999-12-31")
    check("a runoff that was not held is not recorded", [n["kind"] for n in no_runoff], ["special-election"])
    doc["vacancyNotes"] = notes
    check("derived notes pass", vacancy_note_errors(doc, SEATS), [])

    def bad(mutate):
        d = copy.deepcopy(doc)
        mutate(d["vacancyNotes"])
        return vacancy_note_errors(d, SEATS)
    check("a note on no vacancy", any("matches no vacancy" in e for e in bad(lambda n: n[0].update(**{"from": "2025-06-01"}))), True)
    check("a note dated after the vacancy ended", any("outside" in e for e in bad(lambda n: n[1].update(date="2026-01-01"))), True)
    check("an unknown kind", any("unknown kind" in e for e in bad(lambda n: n[0].update(kind="rumor"))), True)
    check("a runoff with no earlier special", any("runoff" in e for e in bad(lambda n: n.pop(1))), True)


def derivation_cases():
    print("derive_holds")
    check("the legislature convenes on the second Monday of January",
          [second_monday_of_january(y) for y in (2023, 2025, 2027)],
          ["2023-01-09", "2025-01-13", "2027-01-11"])
    hs = derive()
    by = {(h["vgId"], h["seatId"]): h for h in hs}
    h10 = by[("vg-10", "ga-house-1@2021")]
    check("a carried-over seat keeps ONE hold across bienniums",
          (h10["start"], h10["end"], sum(1 for h in hs if h["vgId"] == "vg-10")), ("2023-01-09", None, 1))
    check("a redrawn seat's hold ends 'redistricted' the day the new map takes effect",
          (by[("vg-20", "ga-house-2@2021")]["end"], by[("vg-20", "ga-house-2@2021")]["endedBy"]),
          ("2025-01-13", "redistricted"))
    check("and the same member's next hold opens on the new seat",
          (by[("vg-20", "ga-house-2@2023")]["start"], by[("vg-20", "ga-house-2@2023")]["startBasis"]),
          ("2025-01-13", "convening"))
    check("a member who left at a redraw also ends 'redistricted', not with a guessed reason",
          by[("vg-30", "ga-house-3@2021")]["endedBy"], "redistricted")
    h40 = by[("vg-40", "ga-house-3@2023")]
    check("a dated departure takes its reason from the roster status",
          (h40["end"], h40["endBasis"], h40["endedBy"]), ("2025-10-01", "official", "resigned"))
    check("a mid-term joiner starts on a plausible roster termStart",
          (by[("vg-50", "ga-house-3@2023")]["start"], by[("vg-50", "ga-house-3@2023")]["startBasis"]),
          ("2025-12-01", "roster-termStart"))
    no_ts = {**ROSTER, 50: {"id": "r50"}}
    h50 = {(h["vgId"], h["seatId"]): h for h in derive(roster=no_ts)}[("vg-50", "ga-house-3@2023")]
    check("without one, the start is unknown, never guessed", (h50["start"], h50["startBasis"]), (None, "unknown"))
    early = {**ROSTER, 50: {"id": "r50", "termStart": "2025-01-01"}}
    h50 = {(h["vgId"], h["seatId"]): h for h in derive(roster=early)}[("vg-50", "ga-house-3@2023")]
    check("a termStart before the predecessor left is rejected", h50["startBasis"], "unknown")

    # 10 leaves at the 2025 boundary from a CARRIED-OVER seat: a reason must be supplied.
    gone = [row(60, 1), row(20, 2), row(40, 3, vacated="2025-10-01T00:00:00"), row(50, 3)]
    check("a departure from a carried-over seat with no known reason stops the build",
          bool(raises(lambda: derive(b=gone))), True)
    ov = [{"legisGaGovId": 10, "seatId": "ga-house-1@2021", "endedBy": "did-not-run"}]
    h = {(x["vgId"], x["seatId"]): x for x in derive(b=gone, overrides=ov)}[("vg-10", "ga-house-1@2021")]
    check("an override supplies it", (h["end"], h["endedBy"], h["endedBySource"]),
          ("2025-01-13", "did-not-run", "seat-hold-overrides.json"))
    check("an override that matches no hold end stops the build",
          bool(raises(lambda: derive(overrides=ov))), True)
    check("a member with no vgId stops the build (the builder never mints)",
          bool(raises(lambda: derive(vgid=lambda g, r: None if g == 50 else f"vg-{g}"))), True)
    check("two sitting members on one seat stops the build",
          bool(raises(lambda: derive(b=[row(10, 1), row(11, 1), row(20, 2), row(40, 3)]))), True)
    susp = {**ROSTER, 10: {"id": "r10", "status": "Suspended", "statusDate": "2026-01-22"}}
    h10 = {(x["vgId"], x["seatId"]): x for x in derive(roster=susp)}[("vg-10", "ga-house-1@2021")]
    check("a suspension is a status inside the hold, which stays open",
          (h10["end"], [s["start"] for s in h10.get("suspensions", [])]), (None, ["2026-01-22"]))
    sw = derive(b=[row(10, 1, party="Democrat"), row(20, 2), row(40, 3, vacated="2025-10-01T00:00:00"), row(50, 3)])
    h10 = {(x["vgId"], x["seatId"]): x for x in sw}[("vg-10", "ga-house-1@2021")]
    check("a party switch on a continuing hold is history, not a new hold",
          (h10["party"], [p["party"] for p in h10["partyHistory"]]), ("Democratic", ["Republican", "Democratic"]))


def validation_cases():
    print("holds_errors (tier 1), each with a negative control")
    hs = derive()
    doc = {"metadata": {"count": len(hs)}, "holds": hs}
    check("a correct derivation passes", holds_errors(doc, SEATS), [])

    def broken(mutate, **kw):
        d = copy.deepcopy(doc)
        mutate(d["holds"])
        d["metadata"]["count"] = len(d["holds"])
        return holds_errors(d, SEATS, **kw)

    def first(hs_, seat, vgid=None):
        return next(h for h in hs_ if h["seatId"] == seat and (vgid is None or h["vgId"] == vgid))

    check("'redistricted' on a carried-over seat", any("redistricted" in e for e in broken(
        lambda x: first(x, "ga-house-1@2021").update(end="2025-01-13", endBasis="convening", endedBy="redistricted"))), True)
    check("a hold running past its seat's redraw", any("runs past" in e for e in broken(
        lambda x: first(x, "ga-house-2@2021").update(end=None, endBasis=None, endedBy=None))), True)
    check("an end without a reason", any("endedBy" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-40").update(endedBy=None))), True)
    check("a reason outside the shared list", any("endedBy" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-40").update(endedBy="appointed-elsewhere"))), True)
    check("two holds on one seat overlapping", any("overlaps" in e or "still open" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-40").update(end="2026-01-01"))), True)
    check("a person holding two seats at once", any("person" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-50").update(vgId="vg-10"))), True)
    check("a retired vgId", any("retired" in e for e in broken(lambda x: None, merged={"vg-10": "vg-99"})), True)
    check("a null start not marked unknown", any("unknown" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-50").update(start=None, startBasis="convening"))), True)
    check("a suspension outside its hold", any("suspension" in e for e in broken(
        lambda x: first(x, "ga-house-3@2023", "vg-40").update(
            suspensions=[{"start": "2025-11-01", "end": None}]))), True)
    changed = copy.deepcopy(doc)
    first(changed["holds"], "ga-house-2@2021")["endedBy"] = "lost"
    check("append-only: a closed hold changed",
          any("append-only" in e for e in holds_errors(changed, SEATS, previous=doc)), True)
    fix = [{"legisGaGovId": 20, "seatId": "ga-house-2@2021", "field": "endedBy",
            "from": "redistricted", "to": "lost"}]
    check("append-only: a matching correction lets exactly that change through",
          holds_errors(changed, SEATS, previous=doc, corrections=fix), [])
    wrong_from = [{**fix[0], "from": "resigned"}]
    check("append-only: a correction expecting a different old value does not",
          any("append-only" in e for e in holds_errors(changed, SEATS, previous=doc, corrections=wrong_from)), True)
    check("append-only: an open hold may close later",
          holds_errors(doc, SEATS, previous={"holds": [{**first(hs, "ga-house-1@2021")}]}), [])


def override_cases():
    print("overrides_errors")
    good = {"legisGaGovId": 1, "seatId": "s", "endedBy": "resigned", "_note": "n", "_sources": ["https://x"]}
    check("a sourced, noted entry passes", overrides_errors([good]), [])
    check("no _note", len(overrides_errors([{**good, "_note": " "}])), 1)
    check("no source URL", len(overrides_errors([{**good, "_sources": ["ballotpedia"]}])), 1)
    check("a reason outside the list", len(overrides_errors([{**good, "endedBy": "sought-other-office"}])), 1)
    corr = {"legisGaGovId": 1, "seatId": "s", "field": "endedBy", "from": "resigned", "to": "deceased",
            "_note": "n", "_sources": ["https://x"]}
    check("a sourced correction passes", overrides_errors([], [corr]), [])
    check("a correction with no source", len(overrides_errors([], [{**corr, "_sources": []}])), 1)
    check("a correction to an unknown field", len(overrides_errors([], [{**corr, "field": "party"}])), 1)


def roster_layer_cases():
    print("roster_members (the editorial layer is applied here, not trusted from the generated roster)")
    import json as _json
    import tempfile
    stale = {"metadata": {"session": "2025_26"}, "members": [
        {"id": "ocd-person/a", "name": "A", "legisGaGovId": 1, "status": "Resigned", "statusDate": "2025-10-12"},
        {"id": "ocd-person/b", "name": "B", "legisGaGovId": 2, "status": None}]}
    ov = {"_inject": [{"id": "ocd-person/a", "name": "A", "_session": "2025_26",
                       "status": "Deceased", "statusDate": "2025-10-12"}]}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ov.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(ov, f)
        got = {m["legisGaGovId"]: m["status"] for m in B.roster_members(stale, path)}
    check("a corrected override wins over a stale status in the generated roster",
          got, {1: "Deceased", 2: None})


def committed_cases():
    print("committed artifacts")
    doc0 = B.load(B.OUTPUT_FILE)
    seats0 = B.load(B.SEATS_FILE)
    check("vacancy notes on the committed file validate", vacancy_note_errors(doc0, seats0), [])
    gaps = vacancy_gaps(doc0["holds"], seats0)
    kinds = {}
    for n in doc0["vacancyNotes"]:
        kinds.setdefault((n["seatId"], n["from"]), set()).add(n["kind"])
    check("20 vacancies since 2023, each with a writ and a special election",
          (len(gaps), all({"writ", "special-election"} <= kinds.get((g[0], g[1]), set()) for g in gaps)), (20, True))
    check("four seats were vacant at the 2023 convening (HD 7, 119, 172, SD 11)",
          sorted(g[0] for g in gaps if g[1] == "2023-01-09"),
          ["ga-house-119@2021", "ga-house-172@2021", "ga-house-7@2021", "ga-senate-11@2021"])
    check("the committed overrides are all sourced and noted",
          overrides_errors(B.load(B.OVERRIDES_FILE)["holds"]), [])
    import json as _json
    with open(os.path.join(B.REPO_ROOT, "assets", "data", "ga-members-overrides.json"), encoding="utf-8") as f:
        mo = _json.load(f)
    departures = [e for e in mo.get("_inject", []) if e.get("status") in ("Resigned", "Deceased", "Removed")]
    check("every editorial departure that ends a hold cites a source for its reason",
          [e.get("name") for e in departures
           if not (e.get("_reasonNote") and any(str(u).startswith("https://") for u in e.get("_reasonSources") or []))], [])
    doc = B.load(B.OUTPUT_FILE)
    seats = B.load(B.SEATS_FILE)
    ledger = B.load(B.LEDGER_FILE)
    check("seat-holds.json validates", holds_errors(doc, seats, ledger.get("merged")), [])
    rebuilt = B.build(B.load(B.SNAPSHOT_FILE), seats, B.roster_members(),
                      B.load(B.OVERRIDES_FILE), ledger)
    check("seat-holds.json matches a rebuild (run build_seat_holds.py if this fails)",
          B.same_content(rebuilt, doc), True)
    legis = [h for h in doc["holds"] if "legisGaGovId" in h["ids"]]
    open_ = [h for h in legis if h["end"] is None]
    check("every current legislative seat has exactly one open hold (180 + 56)",
          (len(open_), len({h["seatId"] for h in open_})), (236, 236))
    by = {}
    for h in legis:
        by.setdefault(h["ids"]["legisGaGovId"], []).append(h)
    check("J Collins (HD 71, carried over) ended did-not-run at the 2025 convening",
          [(h["seatId"], h["end"], h["endedBy"]) for h in by[4892]],
          [("ga-house-71@2021", "2025-01-13", "did-not-run")])
    check("Farooq Mughal's HD 105 was redrawn, so his hold ended 'redistricted', under his candidate vgId",
          [(h["seatId"], h["endedBy"], h["vgId"]) for h in by[5043]],
          [("ga-house-105@2021", "redistricted", "vg-ga-p-000395")])
    check("Tish Naghise died in office on 2023-03-08",
          [(h["end"], h["endedBy"]) for h in by[5032]], [("2023-03-08", "deceased")])
    check("Mandi Ballinger died in office on 2025-10-12 (corrected from 'resigned')",
          [(h["end"], h["endedBy"]) for h in by[808]], [("2025-10-12", "deceased")])


def executive_cases():
    print("statewide executives (Phase 3)")
    doc, seats = B.load(B.OUTPUT_FILE), B.load(B.SEATS_FILE)
    ex = [h for h in doc["holds"] if "executiveId" in h["ids"]]
    exec_seats = {s["id"] for s in seats["seats"] if s["body"] == "ga-executive"}
    check("22 executive holds on the 13 statewide seats (13 current + 9 staged)",
          (len(ex), {h["seatId"] for h in ex} == exec_seats), (22, True))
    prov = [h for h in ex if h.get("provisional")]
    check("9 provisional holds, each open, named, starting the day the outgoing hold ends",
          (len(prov), all(h["end"] is None and h["name"] for h in prov),
           all(any(o["seatId"] == h["seatId"] and o["end"] == h["start"] for o in ex) for h in prov)),
          (9, True, True))
    check("history starts 2023-01-09 for executives", doc["metadata"]["historyFrom"]["ga-executive"], "2023-01-09")
    kemp = next(h for h in ex if h["ids"]["executiveId"] == "exec:ga-kemp-brian")
    check("Kemp: before-history start, ended term-limited 2027-01-11, Republican",
          (kemp["start"], kemp["startBasis"], kemp["end"], kemp["endedBy"], kemp["party"]),
          (None, "before-history", "2027-01-11", "term-limited", "Republican"))
    hub = next(h for h in ex if h["ids"]["executiveId"] == "exec:ga-hubbard-peter")
    check("a 2026 winner's start is unknown, not before-history (no source for the predecessor)",
          (hub["start"], hub["startBasis"]), (None, "unknown"))
    ids = [h["vgId"] for h in ex if not h.get("provisional")]
    check("each sitting executive has a distinct vgId", len(set(ids)), 13)
    mc = [h for h in doc["holds"] if h["vgId"] == "vg-ga-p-000115"]
    check("McLaurin's staged Lt. Governor hold may sit beside his open SD 14 hold",
          sorted(h["seatId"] for h in mc if h["end"] is None), ["ga-lt-governor", "ga-senate-14@2021"])
    broken = lambda f: holds_errors((lambda d: (f(d["holds"]), d)[1])(copy.deepcopy(doc)), seats)  # noqa: E731
    check("a provisional hold with an end is rejected", any("provisional" in e for e in broken(
        lambda hs: next(h for h in hs if h.get("provisional")).update(end="2028-01-01", endBasis="reported", endedBy="lost"))), True)
    check("an executive hold ended 'redistricted' is rejected", any("redistricted" in e for e in broken(
        lambda hs: next(h for h in hs if h["ids"].get("executiveId") == "exec:ga-kemp-brian").update(endedBy="redistricted"))), True)


def main():
    derivation_cases()
    validation_cases()
    override_cases()
    roster_layer_cases()
    vacancy_cases()
    committed_cases()
    executive_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll seat-hold checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
