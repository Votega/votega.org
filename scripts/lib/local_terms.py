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


def _overlaps(a, b):
    (a0, a1), (b0, b1) = a, b
    # Half-open [start, end); None start = -inf, None end = +inf.
    a_before_b = a1 is not None and b0 is not None and a1 <= b0
    b_before_a = b1 is not None and a0 is not None and b1 <= a0
    return not (a_before_b or b_before_a)


def seat_conflicts(members):
    """Pairs of rows that hold the same seat_id over overlapping dates — two
    people in one seat at once, which the data must never say. Rows with an
    unparseable date are skipped (the validator reports those separately).
    Returns [(seat_id, row_a, row_b)]."""
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
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if _overlaps(rows[i][1], rows[j][1]):
                    out.append((seat_id, rows[i][0], rows[j][0]))
    return out


def successor(members, outgoing):
    """The staged row that takes `outgoing`'s seat when it leaves, or None."""
    sid, end = outgoing.get("seat_id"), parse_date(outgoing.get("leaves_office"))
    if not sid or end is None:
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
