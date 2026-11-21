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
import re

ENDED_BY = ("term-limited", "did-not-run", "lost", "resigned", "removed", "deceased",
            "redistricted", "term-ended")
STATUS_ENDED_BY = {"Resigned": "resigned", "Deceased": "deceased", "Removed": "removed"}
SOAP_BODY = {"House": "ga-house", "Senate": "ga-senate"}
SOAP_PARTY = {"Democrat": "Democratic"}
SOAP_SOURCE = "legis.ga.gov Members/GetMembersBySession"


def _shift(iso, n):
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=n)).isoformat()


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


def derive_holds(snapshot, seats_doc, roster, overrides, vgid_for, specials=()):
    """Build the hold list. Raises ValueError on anything it cannot decide.

    roster: {legisGaGovId: ga-members.json record}; overrides: seat-hold-overrides.json
    "holds" list; vgid_for(gid, roster_record_or_None) -> vgId or None; specials:
    ga-legislative-specials.json "specials". A seat with more special elections in a
    biennium than members who vacated it that biennium was VACANT AT THE CONVENING (the
    member-elect died or resigned before being seated, so the session listing never
    shows them): its first member is a joiner, not seated at the convening.
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
        next_convening = second_monday_of_january(start_year + 2)
        specials_here = {}
        for sp in specials:
            # Counted by the day the special DECIDED the seat (the runoff, when held): HD 7's
            # special ran 2023-01-03, before the convening, but its runoff on 2023-01-31 left
            # the seat empty when the 2023-24 General Assembly convened.
            decided_on = sp["runoff"] if sp.get("runoffHeld") else sp["election"]
            if convening <= decided_on and sp["election"] < next_convening:
                key = seat_in_force(by_key, plan_effective, SOAP_BODY[sp["chamber"]], sp["district"], convening)
                specials_here[key] = specials_here.get(key, 0) + 1
        by_seat = {}
        for gid, seat_id in placed.items():
            by_seat.setdefault(seat_id, []).append(rows[gid])
        for seat_id, members in sorted(by_seat.items()):
            members.sort(key=lambda r: (r["dateVacated"] is None, r["dateVacated"] or ""))
            if sum(1 for r in members if not r["dateVacated"]) > 1:
                raise ValueError(f"{seat_id}: more than one member without a vacancy in {start_year}")
            vacated = sum(1 for r in members if r["dateVacated"])
            vacant_at_convening = specials_here.get(seat_id, 0) > vacated
            prev_end = convening if vacant_at_convening else None
            for i, r in enumerate(members):
                gid = r["id"]
                rec = roster.get(gid)
                party = SOAP_PARTY.get(r["party"], r["party"])
                h = open_.get(gid)
                if h is None:
                    if i == 0 and not vacant_at_convening:
                        start, basis = convening, "convening"
                    else:
                        ts = (rec or {}).get("termStart")
                        # A joiner cannot be seated before the special election that decided the
                        # seat (the runoff, when one was held). HD 130: the roster said 2026-03-15,
                        # the runoff was 2026-04-07, so that termStart is rejected.
                        decided = [sp["runoff"] if sp.get("runoffHeld") else sp["election"]
                                   for sp in specials
                                   if SOAP_BODY[sp["chamber"]] == seat_by_id[seat_id]["body"]
                                   and sp["district"] == seat_by_id[seat_id]["district"]
                                   and prev_end and sp["election"] >= _shift(prev_end, -90)
                                   and sp["election"] < next_convening]
                        floor = max(decided) if decided else prev_end
                        if ts and prev_end and prev_end <= ts and (floor is None or floor <= ts)                                 and ts[:4] in (str(start_year), str(start_year + 1)):
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


def overrides_errors(overrides, corrections=()):
    """Every hand-reviewed entry must say how it was confirmed and where."""
    errs = []
    for c in corrections:
        who = f"correction {c.get('legisGaGovId')} on {c.get('seatId')}"
        if c.get("field") not in ("end", "endBasis", "endedBy") or "from" not in c or "to" not in c:
            errs.append(f"{who}: needs field (end, endBasis or endedBy), from and to")
        if c.get("field") == "endedBy" and c.get("to") not in ENDED_BY:
            errs.append(f"{who}: 'to' must be one of {', '.join(ENDED_BY)}")
        if not (c.get("_note") or "").strip() or not any(str(u).startswith("https://") for u in c.get("_sources") or []):
            errs.append(f"{who}: needs a _note and _sources")
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


VACANCY_KINDS = ("writ", "special-election", "special-runoff", "appointment-pending", "note")
WRIT_LEAD_DAYS = 90   # a writ can precede the vacancy (Fleming's: 2024-01-03 for a seat he left 01-10)
_WRIT = re.compile(r"writ of election.*?district (\d+)\b.*?georgia (?:state )?(senate|house)", re.I)


def _days(iso, n):
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=n)).isoformat()


def convening_on_or_before(iso):
    """The convening that opened the biennium containing date `iso`."""
    year = int(iso[:4])
    start = year if year % 2 == 1 else year - 1
    conv = second_monday_of_january(start)
    return conv if conv <= iso else second_monday_of_january(start - 2)


def vacancy_gaps(holds, seats_doc):
    """[(seatId, from, to)] for every time a seat had fewer holders than its capacity.

    Read off the holds, which are in the order held: the time between a hold ending (not
    'redistricted': that seat ceased to exist) and the next one starting; a seat vacant at a
    convening (its first holder of the biennium was not seated then); and a seat vacant now.
    `to` is the next holder's start, or None when that is unknown or the seat is still empty."""
    seats = {s["id"]: s for s in seats_doc["seats"]}
    by_seat = {}
    for h in holds:
        by_seat.setdefault(h["seatId"], []).append(h)
    gaps = []
    for seat_id, hs in by_seat.items():
        for i, b in enumerate(hs):
            a = hs[i - 1] if i else None
            if a and a["end"] and a["endedBy"] != "redistricted" and (b["start"] is None or b["start"] > a["end"]):
                gaps.append((seat_id, a["end"], b["start"]))
            elif b["startBasis"] != "convening" and b["start"]:
                conv = convening_on_or_before(b["start"])
                if b["start"] > conv and (a is None or (a["end"] and a["end"] <= conv)):
                    gaps.append((seat_id, conv, b["start"]))
        last = hs[-1]
        if last["end"] and last["endedBy"] != "redistricted" and seats[seat_id].get("redrawnBy") is None:
            gaps.append((seat_id, last["end"], None))
    return sorted(set(gaps), key=lambda g: (g[1], g[0]))


def derive_vacancy_notes(holds, seats_doc, writs, specials, special_sources, today):
    """vacancyNotes for every gap: the governor's writ (from the committed executive orders)
    and the special election and runoff (from ga-legislative-specials.json). A note never
    opens or closes a gap; only holds do."""
    seats = {s["id"]: s for s in seats_doc["seats"]}
    body = {"House": "ga-house", "Senate": "ga-senate"}
    notes = []
    for seat_id, frm, to in vacancy_gaps(holds, seats_doc):
        s = seats[seat_id]
        lo, hi = _days(frm, -WRIT_LEAD_DAYS), to or today
        for o in writs:
            m = _WRIT.search(o.get("title") or "")
            if not m or body["Senate" if m.group(2).lower() == "senate" else "House"] != s["body"]:
                continue
            if int(m.group(1)) == s["district"] and lo <= o["date"] <= hi:
                notes.append({"seatId": seat_id, "from": frm, "kind": "writ", "date": o["date"],
                              "ref": o.get("number"), "url": o.get("url"),
                              "source": f"ga-executive-orders-{o['date'][:4]}.json", "note": o.get("title")})
        for sp in specials:
            if body[sp["chamber"]] != s["body"] or sp["district"] != s["district"]:
                continue
            if not (lo <= sp["election"] <= hi):
                continue
            url = special_sources.get(sp["source"])
            notes.append({"seatId": seat_id, "from": frm, "kind": "special-election", "date": sp["election"],
                          "ref": None, "url": url, "source": "ga-legislative-specials.json", "note": None})
            if sp.get("runoffHeld") and sp.get("runoff"):
                notes.append({"seatId": seat_id, "from": frm, "kind": "special-runoff", "date": sp["runoff"],
                              "ref": None, "url": url, "source": "ga-legislative-specials.json", "note": None})
    return sorted(notes, key=lambda n: (n["from"], n["seatId"], n["date"], n["kind"]))


def vacancy_note_errors(doc, seats_doc):
    """Tier 1: every note sits on a computed gap, with a known kind and a date in range."""
    errs = []
    gaps = {(g[0], g[1]): g[2] for g in vacancy_gaps(doc.get("holds", []), seats_doc)}
    by_gap = {}
    for n in doc.get("vacancyNotes", []):
        who = f"vacancy note {n.get('kind')} on {n.get('seatId')} from {n.get('from')}"
        key = (n.get("seatId"), n.get("from"))
        if key not in gaps:
            errs.append(f"{who}: matches no vacancy in the holds")
            continue
        if n.get("kind") not in VACANCY_KINDS:
            errs.append(f"{who}: unknown kind")
        if n.get("kind") == "note" and not n.get("note"):
            errs.append(f"{who}: a 'note' needs text")
        to = gaps[key]
        if not n.get("date") or n["date"] < _days(n["from"], -WRIT_LEAD_DAYS) or (to and n["date"] > to):
            errs.append(f"{who}: date {n.get('date')} is outside the vacancy")
        by_gap.setdefault(key, {})[n.get("kind")] = n.get("date")
    for key, kinds in by_gap.items():
        if "special-runoff" in kinds and ("special-election" not in kinds or kinds["special-runoff"] <= kinds["special-election"]):
            errs.append(f"{key}: a runoff needs an earlier special election")
    return errs


def vacancy_report(doc, seats_doc):
    lines = []
    noted = {(n["seatId"], n["from"], n["kind"]) for n in doc.get("vacancyNotes", [])}
    for seat_id, frm, to in vacancy_gaps(doc["holds"], seats_doc):
        missing = [k for k in ("writ", "special-election") if (seat_id, frm, k) not in noted]
        if missing:
            lines.append(f"vacancy {seat_id} from {frm}{'' if to else ' (still open)'}: no {' or '.join(missing)} recorded")
    return lines


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


def holds_errors(doc, seats_doc, merged=None, previous=None, corrections=()):
    """Tier 1 for seat-holds.json. Returns strings.

    `corrections` (seat-hold-overrides.json "corrections") is the only way a closed hold
    may change: each names the hold by legisGaGovId + seatId, the field, and the value it
    expects to find (`from`) and to set (`to`), so it applies to exactly that change."""
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
        allowed = {(c["legisGaGovId"], c["seatId"], c["field"]): (c["from"], c["to"]) for c in corrections}
        for old in previous.get("holds", []):
            if old.get("end") is None:
                continue
            new = now.get((old["vgId"], old["seatId"], old["start"]))
            if new is None:
                errs.append(f"closed hold {old['vgId']} on {old['seatId']} was removed "
                            "(closed holds are append-only)")
                continue
            for k in ("end", "endBasis", "endedBy"):
                if new.get(k) == old.get(k):
                    continue
                gid = (old.get("ids") or {}).get("legisGaGovId")
                if allowed.get((gid, old["seatId"], k)) == (old.get(k), new.get(k)):
                    continue
                errs.append(f"closed hold {old['vgId']} on {old['seatId']} changed {k} "
                            f"{old.get(k)!r} -> {new.get(k)!r} without a matching correction "
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
