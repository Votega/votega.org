"""Which Governor of Georgia issued an executive order, from the order's date.

The order text cannot say: the signature block is a handwritten signature over a
printed "GOVERNOR", and only a handful of emergency orders name the Governor in the
body (checked 2026-11-25 across 3,647 orders). So the issuer comes from the governor
seat's holders in assets/data/ga-executive-seats.json, which already carries the
January 2027 handover, plus a short fixed table for the years before that seat history.

A handover day is AMBIGUOUS: both the outgoing and incoming Governor can sign orders
that day and an order number carries no time. Such an order is never guessed. It needs
an entry in assets/data/ga-eo-issuers.json (number -> execId, with a `_note` saying how
it was verified), and until then the validator fails the run so a person looks.

A provisional seat holder (projected, not yet sworn in) is never used. An order dated
after the last confirmed Governor's term gets no issuer, and the validator reports it
(promote the seat in ga-executive-seats.json / ga-executive.json).

Stdlib only.
"""
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEATS = os.path.join(ROOT, "assets", "data", "ga-executive-seats.json")
PEOPLE = os.path.join(ROOT, "assets", "data", "ga-executive.json")
OVERRIDES = os.path.join(ROOT, "assets", "data", "ga-eo-issuers.json")
SEAT_ID = "ga-governor"

#: Before the seat history. Dates are the inaugurations.
FIXED = [
    {"execId": None, "name": "Nathan Deal", "start": "2011-01-10", "end": "2019-01-14"},
    {"execId": "exec:ga-kemp-brian", "name": "Brian P. Kemp", "start": "2019-01-14", "end": None},
]
#: The name as the orders' own listings have always given it.
FORMAL_NAMES = {"exec:ga-kemp-brian": "Brian P. Kemp"}


def _d(s):
    return date.fromisoformat(s) if s else None


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        return None


def timeline(seats=None, people=None):
    """[{execId, name, start, end}] in order. start and end are dates (end None = serving)."""
    seats = _load(SEATS) if seats is None else seats
    people = _load(PEOPLE) if people is None else people
    names = {p.get("id"): p.get("name") for p in (people or {}).get("officials") or []}
    fixed = {f["execId"]: f for f in FIXED if f["execId"]}
    out = [dict(f) for f in FIXED if not f["execId"]]
    seat = next((s for s in (seats or {}).get("seats") or [] if s.get("id") == SEAT_ID), None)
    seen = set()
    for h in (seat or {}).get("holders") or []:
        if h.get("provisional") or not h.get("execId"):
            continue
        base = fixed.get(h["execId"], {})
        out.append({"execId": h["execId"],
                    "name": FORMAL_NAMES.get(h["execId"]) or names.get(h["execId"]) or h.get("name")
                            or base.get("name"),
                    "start": h.get("start") or base.get("start"),
                    "end": h.get("end") or base.get("end")})
        seen.add(h["execId"])
    out += [dict(f) for k, f in fixed.items() if k not in seen]
    for t in out:
        t["start"], t["end"] = _d(t["start"]), _d(t["end"])
    return sorted(out, key=lambda t: t["start"] or date.min)


def handover_days(tl):
    """Dates on which a Governor's term ends, so the next one begins.

    Keyed on the END alone: until the successor is sworn in and the seat promoted, the
    successor is provisional and not in the timeline, yet the handover day is just as
    ambiguous."""
    return sorted({t["end"] for t in tl if t["end"]})


def load_overrides(path=None):
    """{number: {execId, _note}} from the hand-verified file; {} when there is none.

    Every entry must say how it was verified: an unexplained override is refused."""
    doc = _load(path or OVERRIDES) or {}
    out = {k: v for k, v in (doc.get("orders") or {}).items() if isinstance(v, dict)}
    bare = sorted(k for k, v in out.items() if not (v.get("_note") or "").strip())
    if bare:
        raise ValueError(f"ga-eo-issuers.json: entries without a _note: {bare}")
    return out


def issuer(order_date, number, tl, overrides):
    """(issuedBy or None, reason). reason is None, "handover" or "no-confirmed-governor"."""
    by_id = {t["execId"]: t for t in tl if t["execId"]}
    o = overrides.get(number)
    if o:
        t = by_id.get(o.get("execId"))
        if not t:
            raise ValueError(f"ga-eo-issuers.json: {number} names {o.get('execId')!r}, "
                             "which is not a confirmed Governor")
        return {"name": t["name"], "execId": t["execId"], "basis": "verified"}, None
    d = _d(order_date)
    if d in handover_days(tl):
        return None, "handover"
    hits = [t for t in tl if t["start"] and t["start"] <= d and (t["end"] is None or d <= t["end"])]
    if len(hits) != 1:
        return None, "no-confirmed-governor"
    t = hits[0]
    return {"name": t["name"], "execId": t["execId"], "basis": "date"}, None


def assign(doc, tl=None, overrides=None):
    """Set issuedBy on every order and metadata.governor(s). Returns True if anything changed."""
    tl = timeline() if tl is None else tl
    overrides = load_overrides() if overrides is None else overrides
    before = json.dumps(doc, sort_keys=True)
    order_names = []
    for o in doc.get("orders") or []:
        who, _reason = issuer(o.get("date"), o.get("number"), tl, overrides)
        o["issuedBy"] = who
        if who and who["name"] not in order_names:
            order_names.append(who["name"])
    meta = doc.setdefault("metadata", {})
    year = meta.get("year")
    if order_names and isinstance(year, int):
        dated = sorted(order_names, key=lambda n: min(t["start"] for t in tl if t["name"] == n))
        meta["governor"] = " / ".join(dated)
    elif isinstance(year, int):
        who, _ = issuer(f"{year}-01-01", None, tl, {})
        if who:
            meta["governor"] = who["name"]
    return json.dumps(doc, sort_keys=True) != before
