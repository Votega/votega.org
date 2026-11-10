"""Term dates and seat identity for _data/local_officials.yml — the one implementation.

A member row is one person's hold on one seat. Rows are never deleted when a
person leaves: a row with a past `leaves_office` is a FORMER member, kept as
history (for the ga-local-government publish), and a row with a future
`takes_office` is an INCOMING member, staged ahead of their swearing-in. The site
renders only the rows active on the build date; `_includes/entity/place.html`
mirrors `is_active()` in Liquid, so keep the two in step.

Fields (all optional on a row; the validator enforces the rules below):
  seat_id       stable slug for the seat within its jurisdiction ("district-3",
                "post-1-at-large", "mayor"). The history key: every holder of a
                seat carries the same seat_id. Stored, never derived at read time,
                so a respelled display `seat` label cannot split a seat's history.
  takes_office  ISO date the person began (or will begin) holding the seat.
                Blank = held since before history was recorded.
  leaves_office ISO date the hold ENDS, exclusive: the first day they no longer
                hold it, normally the successor's takes_office (both 1 January).
                Blank = still holding it.
  leave_reason  why the hold ended: one of LEAVE_REASONS.

Active on day D  <=>  (takes_office blank or <= D) and (leaves_office blank or > D).

A "Suspended" member still legally holds the seat while an interim serves it
(Newton, 2026), so a Suspended row does not count toward the one-holder-per-seat
rule.

A SHARED seat is one a body fills several of with no post numbers to tell them
apart: Palmetto elects all six council members citywide, top vote-getters win.
The jurisdiction declares it with `seat_capacity: {at-large: 6}`, and every
holder carries `seat_id: at-large`. Numbering them at-large-1..6 would invent
seat identities the city does not have. A shared seat may have up to its
capacity of holders at once, and has no one-to-one successor.
"""

import re
from datetime import date, datetime

LEAVE_REASONS = {"term-ended", "resigned", "removed", "deceased"}
SEAT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NOT_COUNTED_FOR_OCCUPANCY = {"Suspended"}


def parse_date(value):
    """A YAML date (PyYAML parses bare YYYY-MM-DD to datetime.date) or an ISO
    string -> date. Blank -> None. Anything else raises ValueError."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    raise ValueError(f"not a date: {value!r}")


def is_active(member, on):
    """True if the row holds its seat on date `on` (see module docstring)."""
    start = parse_date(member.get("takes_office"))
    end = parse_date(member.get("leaves_office"))
    return (start is None or start <= on) and (end is None or end > on)


def active_members(jurisdiction, on):
    return [m for m in (jurisdiction.get("members") or [])
            if isinstance(m, dict) and is_active(m, on)]


def is_mayor(member):
    return member.get("role") == "Mayor" or (member.get("title") or "").strip().lower() == "mayor"


def suggest_seat_id(member):
    """Draft a seat_id from the display label. Used once to backfill and by the
    drafting tools for new rows; a human may override it. A mayor is always
    `mayor` (usually labelled "At-large", which is not the at-large council seat).
    Returns None when the label is blank: there is nothing to key on."""
    if is_mayor(member):
        return "mayor"
    label = (member.get("seat") or "").strip().lower()
    if not label:
        return None
    label = re.sub(r"at[\s-]*large", "at-large", label)
    slug = re.sub(r"[^a-z0-9]+", "-", label).strip("-")
    return slug or None


def _interval(member):
    return parse_date(member.get("takes_office")), parse_date(member.get("leaves_office"))


def capacity_of(seat_id, capacity=None):
    """How many people may hold `seat_id` at once (1 unless declared shared)."""
    return (capacity or {}).get(seat_id, 1)


def _over_capacity(rows, cap):
    """The rows holding a seat at the busiest moment, if that is more than `cap`.
    Half-open intervals: a leave and a take on the same date do not overlap."""
    events = []
    for m, (start, end) in rows:
        events.append((start or date.min, 1, m))   # starts sort after ends on a tie
        events.append((end or date.max, 0, m))
    events.sort(key=lambda e: (e[0], e[1]))
    held, worst = [], []
    for _, kind, m in events:
        if kind == 1:
            held.append(m)
            if len(held) > cap and len(held) > len(worst):
                worst = list(held)
        else:
            held = [h for h in held if h is not m]
    return worst


def seat_conflicts(members, capacity=None):
    """Seats held by more people at once than they can hold — two people in an
    ordinary seat, or seven in Palmetto's six at-large seats — which the data
    must never say. `capacity` is the jurisdiction's `seat_capacity` map. Rows
    with an unparseable date are skipped (the validator reports those).
    Returns [(seat_id, [rows holding it at the busiest moment])]."""
    by_seat = {}
    for m in members:
        if not isinstance(m, dict) or not m.get("seat_id"):
            continue
        if m.get("status") in NOT_COUNTED_FOR_OCCUPANCY:
            continue
        try:
            iv = _interval(m)
        except ValueError:
            continue
        by_seat.setdefault(m["seat_id"], []).append((m, iv))
    out = []
    for seat_id, rows in by_seat.items():
        worst = _over_capacity(rows, capacity_of(seat_id, capacity))
        if worst:
            out.append((seat_id, worst))
    return out


def successor(members, outgoing, capacity=None):
    """The staged row that takes `outgoing`'s seat when it leaves, or None.
    Always None for a shared seat: which incoming member replaces which
    outgoing one is not a fact the election records."""
    sid, end = outgoing.get("seat_id"), parse_date(outgoing.get("leaves_office"))
    if not sid or end is None or capacity_of(sid, capacity) > 1:
        return None
    for m in members:
        if m is outgoing or not isinstance(m, dict) or m.get("seat_id") != sid:
            continue
        try:
            start = parse_date(m.get("takes_office"))
        except ValueError:
            continue
        if start is not None and start >= end:
            return m
    return None
