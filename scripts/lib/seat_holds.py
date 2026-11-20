"""Seat holds for the General Assembly: who held each seat, from when to when, and why it ended.

Pure functions only, shared by scripts/build_seat_holds.py, scripts/validate_seat_holds.py
and the offline tests. Rules (docs/seat-history-design.md):

  * A hold is one person's continuous time in one seat. A re-elected member whose seat a
    new map carried over keeps ONE hold across bienniums; a hold on a seat a new map
    redrew ends `redistricted` the day that map takes effect, and the same person's next
    hold (if any) opens on the new seat.
  * `start` is the first day in office, `end` the first day no longer in office; each
    carries a basis. A member seated at a convening starts on the convening date; a
    member who joined mid-term starts on the roster's `termStart` when it is plausible,
    otherwise null with basis "unknown" (reported, never guessed).
  * `endedBy` records only why THIS hold ended. A departure the service dates but does
    not explain comes from ga-members.json `status` (the editorial overrides) or from
    assets/data/seat-hold-overrides.json; a hold with no known reason is an error, not a
    guess.
  * Every hold carries a vgId; the builder never mints one (the crosswalk does).
"""
import calendar
import datetime as dt

ENDED_BY = ("term-limited", "did-not-run", "lost", "resigned", "removed", "deceased",
            "redistricted", "term-ended")
STATUS_ENDED_BY = {"Resigned": "resigned", "Deceased": "deceased", "Removed": "removed"}
SOAP_BODY = {"House": "ga-house", "Senate": "ga-senate"}
SOAP_PARTY = {"Democrat": "Democratic"}
SOAP_SOURCE = "legis.ga.gov Members/GetMembersBySession"


def second_monday_of_january(year):
    """The General Assembly convenes on the second Monday in January (Ga. Const. Art. III,
    Sec. IV, Par. I); every biennium starts in an odd year."""
    first = dt.date(year, 1, 1)
    first_monday = 1 + (calendar.MONDAY - first.weekday()) % 7
    return dt.date(year, 1, first_monday + 7).isoformat()


def bienniums(snapshot):
    """[(start_year, convening date, [session ids, regular first])] from the snapshot."""
    meta = {str(s["id"]): s for s in snapshot["metadata"]["sessions"]}
    groups = {}
    for sid in snapshot["sessions"]:
        lib = meta[sid]["library"] or ""
        year = int(lib[:4])
        start = year if year % 2 == 1 else year - 1
        groups.setdefault(start, []).append(sid)
    out = []
    for start in sorted(groups):
        sids = sorted(groups[start], key=lambda s: (len(meta[s]["library"]) != 8, int(s)))
        if len(meta[sids[0]]["library"]) != 8:
            raise ValueError(f"biennium {start} has no regular session in the snapshot")
        out.append((start, second_monday_of_january(start), sids))
    return out


def seat_in_force(seats_by_key, plan_effective, body, district, on):
    """The seat id for body/district in force on date `on`."""
    hits = []
    for s in seats_by_key.get((body, district), []):
        begins = plan_effective[s["plan"]]
        ends = plan_effective[s["redrawnBy"]] if s["redrawnBy"] else None
        if begins <= on and (ends is None or on < ends):
            hits.append(s["id"])
    if len(hits) != 1:
        raise ValueError(f"{body} district {district} has {len(hits)} seats in force on {on}")
    return hits[0]


def derive_holds(snapshot, seats_doc, roster, overrides, vgid_for):
    """Build the hold list. Raises ValueError on anything it cannot decide.

    roster: {legisGaGovId: ga-members.json record}; overrides: seat-hold-overrides.json
    "holds" list; vgid_for(gid, roster_record_or_None) -> vgId or None.
    """
    seats = seats_doc["seats"]
    plan_effective = {p["id"]: p["effective"] for p in seats_doc["metadata"]["plans"]}
    by_key = {}
    for s in seats:
        if s["plan"]:
            by_key.setdefault((s["body"], s["district"]), []).append(s)
    seat_by_id = {s["id"]: s for s in seats}
    ov = {}
    for o in overrides:
        k = (o["legisGaGovId"], o["seatId"])
        if k in ov:
            raise ValueError(f"two overrides for {k}")
        ov[k] = o
    used = set()

    def reason(gid, seat_id, roster_rec, current):
        if (gid, seat_id) in ov:
            used.add((gid, seat_id))
            return ov[(gid, seat_id)]["endedBy"], "seat-hold-overrides.json"
        if current and roster_rec and roster_rec.get("status") in STATUS_ENDED_BY:
            return STATUS_ENDED_BY[roster_rec["status"]], "ga-members-overrides.json (status)"
        raise ValueError(f"no end reason for legisGaGovId {gid} on {seat_id}: add an entry "
                         "to assets/data/seat-hold-overrides.json")

    holds, open_ = [], {}            # open_: gid -> hold
    terms = bienniums(snapshot)
    last = terms[-1][0]
    for start_year, convening, sids in terms:
        current = start_year == last
        rows = {}
        for sid in sids:                 # regular session first: its row wins
            for r in snapshot["sessions"][sid]:
                rows.setdefault(r["id"], r)
        placed = {}
        for gid, r in rows.items():
            body = SOAP_BODY[r["chamber"]]
            placed[gid] = seat_in_force(by_key, plan_effective, body, r["district"], convening)

        # 1. Close or continue every hold still open from the previous biennium.
        for gid, h in list(open_.items()):
            seat = seat_by_id[h["seatId"]]
            if seat["redrawnBy"] and plan_effective[seat["redrawnBy"]] == convening:
                h.update(end=convening, endBasis="convening", endedBy="redistricted",
                         endedBySource="seat-plan-comparison.json (the seat was redrawn)")
                del open_[gid]
            elif placed.get(gid) == h["seatId"]:
                continue                               # same seat, carried over: one hold
            else:
                why, src = reason(gid, h["seatId"], roster.get(gid), False)
                h.update(end=convening, endBasis="convening", endedBy=why, endedBySource=src)
                del open_[gid]

        # 2. Seat by seat, in the order members held it this biennium.
        by_seat = {}
        for gid, seat_id in placed.items():
            by_seat.setdefault(seat_id, []).append(rows[gid])
        for seat_id, members in sorted(by_seat.items()):
            members.sort(key=lambda r: (r["dateVacated"] is None, r["dateVacated"] or ""))
            if sum(1 for r in members if not r["dateVacated"]) > 1:
                raise ValueError(f"{seat_id}: more than one member without a vacancy in {start_year}")
            prev_end = None
            for i, r in enumerate(members):
                gid = r["id"]
                rec = roster.get(gid)
                party = SOAP_PARTY.get(r["party"], r["party"])
                h = open_.get(gid)
                if h is None:
                    if i == 0:
                        start, basis = convening, "convening"
                    else:
                        ts = (rec or {}).get("termStart")
                        if ts and prev_end and prev_end <= ts and ts[:4] in (str(start_year), str(start_year + 1)):
                            start, basis = ts, "roster-termStart"
                        else:
                            start, basis = None, "unknown"
                    vg = vgid_for(gid, rec)
                    if not vg:
                        raise ValueError(f"legisGaGovId {gid} has no vgId; rebuild the crosswalk "
                                         "after fetch_ga_members_by_session.py")
                    h = {"seatId": seat_id, "vgId": vg, "ids": {"legisGaGovId": gid},
                         "start": start, "startBasis": basis, "end": None, "endBasis": None,
                         "endedBy": None, "party": party, "source": SOAP_SOURCE}
                    holds.append(h)
                    open_[gid] = h
                elif h["party"] != party:
                    h.setdefault("partyHistory", [{"party": h["party"], "from": h["start"]}])
                    h["partyHistory"].append({"party": party, "from": convening})
                    h["party"] = party
                if r["dateVacated"]:
                    why, src = reason(gid, seat_id, rec, current)
                    h.update(end=r["dateVacated"][:10], endBasis="official", endedBy=why,
                             endedBySource=src)
                    del open_[gid]
                    prev_end = h["end"]
                elif current and rec and rec.get("status") == "Suspended":
                    h["suspensions"] = [{"start": rec.get("statusDate"), "startBasis": "official",
                                         "end": None, "endBasis": None, "endedBy": None,
                                         "source": "ga-members-overrides.json (status Suspended)",
                                         "note": rec.get("statusNote")}]
    unused = [k for k in ov if k not in used]
    if unused:
        raise ValueError(f"seat-hold-overrides.json entries match no hold end: {unused}")
    return holds


def overrides_errors(overrides):
    """Every hand-reviewed entry must say how it was confirmed and where."""
    errs = []
    for o in overrides:
        who = f"override {o.get('legisGaGovId')} on {o.get('seatId')}"
        if o.get("endedBy") not in ENDED_BY:
            errs.append(f"{who}: endedBy must be one of {', '.join(ENDED_BY)}")
        if not (o.get("_note") or "").strip():
            errs.append(f"{who}: needs a _note recording how it was confirmed")
        srcs = o.get("_sources") or []
        if not srcs or not all(isinstance(u, str) and u.startswith(("https://", "http://")) for u in srcs):
            errs.append(f"{who}: needs _sources with at least one URL")
    return errs


def _sequence_errors(label, hs):
    """Holds listed in the order they were held must not overlap: each earlier hold has
    ended, by the later one's start when that is known. An unknown start sits after the
    previous hold by construction, which is why the order of the list is the contract."""
    errs = []
    for a, b in zip(hs, hs[1:]):
        if a["end"] is None:
            errs.append(f"{label}: {a['vgId']} on {a['seatId']} is still open but another hold follows it")
        elif b["start"] and a["end"] > b["start"]:
            errs.append(f"{label}: {a['vgId']} on {a['seatId']} overlaps {b['vgId']} on {b['seatId']}")
    return errs


def holds_errors(doc, seats_doc, merged=None, previous=None):
    """Tier 1 for seat-holds.json. Returns strings."""
    errs = []
    holds = doc.get("holds", [])
    if doc.get("metadata", {}).get("count") != len(holds):
        errs.append("metadata.count does not match the number of holds")
    seats = {s["id"]: s for s in seats_doc["seats"]}
    eff = {p["id"]: p["effective"] for p in seats_doc["metadata"]["plans"]}
    merged = merged or {}
    by_seat, by_vg = {}, {}
    for h in holds:
        who = f"{h.get('vgId')} on {h.get('seatId')}"
        s = seats.get(h["seatId"])
        if s is None:
            errs.append(f"{who}: unknown seat")
            continue
        if not h.get("vgId"):
            errs.append(f"{who}: no vgId")
        elif h["vgId"] in merged:
            errs.append(f"{who}: retired vgId (forwards to {merged[h['vgId']]})")
        if h["start"] is None and h.get("startBasis") != "unknown":
            errs.append(f"{who}: null start needs startBasis 'unknown'")
        if s["plan"] and h["start"] and h["start"] < eff[s["plan"]]:
            errs.append(f"{who}: starts before its seat's map took effect")
        if h["end"] is not None:
            if h.get("endedBy") not in ENDED_BY or not h.get("endBasis"):
                errs.append(f"{who}: an end needs an endedBy from the list and an endBasis")
            if h["start"] and h["end"] < h["start"]:
                errs.append(f"{who}: ends before it starts")
        elif h.get("endedBy"):
            errs.append(f"{who}: endedBy without an end")
        redrawn_on = eff.get(s["redrawnBy"]) if s.get("redrawnBy") else None
        if h.get("endedBy") == "redistricted" and h["end"] != redrawn_on:
            errs.append(f"{who}: 'redistricted' but the seat was not redrawn on {h['end']}")
        if redrawn_on and (h["end"] is None or h["end"] > redrawn_on):
            errs.append(f"{who}: runs past the day its seat was redrawn ({redrawn_on})")
        susp = sorted(h.get("suspensions") or [], key=lambda x: x["start"] or "")
        for x in susp:
            if not x.get("start") or (h["start"] and x["start"] < h["start"]) or \
                    (h["end"] and (x["end"] is None or x["end"] > h["end"])):
                errs.append(f"{who}: a suspension lies outside its hold")
        for a, b in zip(susp, susp[1:]):
            if a["end"] is None or a["end"] > b["start"]:
                errs.append(f"{who}: suspensions overlap")
        by_seat.setdefault(h["seatId"], []).append(h)
        by_vg.setdefault(h.get("vgId"), []).append(h)
    for seat_id, hs in by_seat.items():
        if sum(1 for h in hs if h["end"] is None) > seats[seat_id]["capacity"]:
            errs.append(f"{seat_id}: more open holds than its capacity")
        if seats[seat_id]["capacity"] == 1:
            errs += _sequence_errors(seat_id, hs)
    for vg, hs in by_vg.items():
        errs += _sequence_errors(f"person {vg}", hs)
    if previous:
        now = {(h["vgId"], h["seatId"], h["start"]): h for h in holds}
        for old in previous.get("holds", []):
            if old.get("end") is None:
                continue
            new = now.get((old["vgId"], old["seatId"], old["start"]))
            if new is None or any(new.get(k) != old.get(k) for k in ("end", "endBasis", "endedBy")):
                errs.append(f"closed hold {old['vgId']} on {old['seatId']} was removed or changed "
                            "(closed holds are append-only)")
    return errs


def report(doc, seats_doc):
    """Tier 2 lines: unknown starts and seats with no open hold (vacancies)."""
    lines = []
    unknown = [h for h in doc["holds"] if h["start"] is None]
    if unknown:
        lines.append(f"{len(unknown)} hold(s) with an unknown start: "
                     + ", ".join(f"{h['vgId']} on {h['seatId']}" for h in unknown))
    open_seats = {h["seatId"] for h in doc["holds"] if h["end"] is None}
    vacant = [s["id"] for s in seats_doc["seats"]
              if s["body"] in ("ga-house", "ga-senate") and s["redrawnBy"] is None
              and s["id"] not in open_seats]
    if vacant:
        lines.append(f"{len(vacant)} legislative seat(s) with no current holder: {', '.join(vacant)}")
    return lines
