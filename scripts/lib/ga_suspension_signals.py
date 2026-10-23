"""Suspension signals for the General Assembly roster. REPORT ONLY: nothing here edits data.

A suspended legislator keeps the title and the seat but cannot act (Ga. Const. Art. II,
Sec. III), and no replacement is seated unless the member is convicted of a felony. So the
legislature's SOAP service sets no vacancy date during a suspension, and `status` is
editorial (assets/data/ga-members-overrides.json). The Governor's executive orders are the
earliest public record, and a roll-call vote is the earliest sign a suspension has ended.

Three signals, each a list of markdown lines for the daily "GA roster" tracking issue:

  suspension_without_status   an EO suspends a sitting legislator the roster does not mark Suspended
  review_commission_pending   an EO names a legislator's indictment to a review commission, so a
                              suspension may follow (recent orders only: a commission can clear
                              the official, which would otherwise nag forever)
  suspended_but_voting        a member marked Suspended has a recorded Yea/Nay after their
                              statusDate, so the suspension may have been lifted

stdlib only, so scripts/validate_ga_members.py can import it with no install step.
"""

import glob
import json
import os
import re
from datetime import date, datetime, timedelta

CHAMBERS = {"representative": "House of Representatives", "senator": "Senate"}
DEPARTED = {"Resigned", "Removed", "Deceased"}

# "Suspending Representative Sharon Henderson from office as the District 113 Representative
# in the Georgia House of Representatives". Real legislator titles only: sheriffs and county
# commissioners also carry "Suspending ..." and a district number.
_SUSPEND = re.compile(
    r"^Suspending\s+(?P<role>Representative|Senator)\s+(?P<name>.+?)\s+from\s+office",
    re.IGNORECASE)
_DISTRICT = re.compile(r"District\s+(?P<n>\d+)", re.IGNORECASE)
_COMMISSION = re.compile(
    r"Review Commission to (?:examine|review) the indictment of\s+(?P<name>.+?),?\s+"
    r"District\s+(?P<n>\d+)\s+(?P<role>Representative|Senator)\b",
    re.IGNORECASE)

# A review commission reports within weeks; older ones that never led to a suspension are
# resolved, not outstanding.
COMMISSION_WINDOW_DAYS = 90


def _norm(s):
    return re.sub(r"[^a-z ]", "", (s or "").lower().replace("-", " "))


def last_name(name):
    parts = [p for p in _norm(re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name or "", flags=re.I)).split() if p]
    return parts[-1] if parts else ""


def load_orders(pattern):
    orders = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for o in (data.get("orders") if isinstance(data, dict) else data) or []:
            if isinstance(o, dict) and o.get("title"):
                orders.append(o)
    return orders


def _seat_members(members, chamber, district):
    return [m for m in members if m.get("chamber") == chamber and m.get("district") == district]


def _named(candidates, name):
    ln = last_name(name)
    return [m for m in candidates if ln and last_name(m.get("name")) == ln]


def _fmt(o):
    return f"EO {o.get('number', '?')} ({o.get('date', '?')})"


def suspension_without_status(members, orders):
    lines = []
    for o in orders:
        m = _SUSPEND.match(o.get("title", ""))
        d = _DISTRICT.search(o.get("title", ""))
        if not (m and d):
            continue
        chamber = CHAMBERS[m.group("role").lower()]
        district = int(d.group("n"))
        seat = _seat_members(members, chamber, district)
        named = _named(seat, m.group("name"))
        if any(x.get("status") == "Suspended" or x.get("status") in DEPARTED for x in named):
            continue                                  # tracked, or resolved by leaving
        # A human acknowledges an EO that no longer applies (e.g. a reinstatement) by citing
        # its number in the member's statusNote.
        if any(o.get("number") and o["number"] in (x.get("statusNote") or "") for x in named):
            continue
        who = f"**{m.group('name')}** ({chamber}, district {district})"
        if named:
            now = named[0].get("status") or "no status (sitting)"
            lines.append(f"- {_fmt(o)} suspends {who}; the roster shows {now}. If the suspension "
                         f"stands, set `status: Suspended` in ga-members-overrides.json; if it "
                         f"ended, cite the EO number in `statusNote` to acknowledge.")
        else:
            lines.append(f"- {_fmt(o)} suspends {who}, but no member with that surname holds "
                         f"that seat in the roster. Check the seat and the spelling.")
    return lines


def review_commission_pending(members, orders, today=None):
    today = today or date.today()
    lines = []
    for o in orders:
        m = _COMMISSION.search(o.get("title", ""))
        if not m:
            continue
        try:
            when = datetime.strptime(str(o.get("date"))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if today - when > timedelta(days=COMMISSION_WINDOW_DAYS):
            continue
        chamber = CHAMBERS[m.group("role").lower()]
        district = int(m.group("n"))
        named = _named(_seat_members(members, chamber, district), m.group("name"))
        if not named or any(x.get("status") in ({"Suspended"} | DEPARTED) for x in named):
            continue
        lines.append(f"- {_fmt(o)} appoints a review commission on the indictment of "
                     f"**{m.group('name')}** ({chamber}, district {district}). A suspension "
                     f"order may follow; watch the Governor's orders.")
    return lines


def suspended_but_voting(members, member_votes):
    """Members marked Suspended who cast a Yea or Nay after their statusDate."""
    if not member_votes:
        return []
    ids, votes, by_member = (member_votes.get("voteIds") or [], member_votes.get("votes") or {},
                             member_votes.get("memberVotes") or {})
    lines = []
    for m in members:
        since = (m.get("statusDate") or "")[:10]
        if m.get("status") != "Suspended" or not since:
            continue
        cast = []
        for idx, code in (by_member.get(m.get("id")) or {}).items():
            if code not in ("Y", "N"):
                continue
            try:
                v = votes.get(ids[int(idx)])
            except (ValueError, IndexError):
                continue
            if v and str(v.get("date", ""))[:10] > since:
                cast.append(str(v["date"])[:10])
        if cast:
            lines.append(f"- **{m.get('name', '?')}** ({m.get('chamber', '?')}, district "
                         f"{m.get('district', '?')}) is marked Suspended since {since} but has "
                         f"{len(cast)} recorded Yea/Nay vote(s) after that date (latest "
                         f"{max(cast)}). The suspension may have been lifted.")
    return lines


def signal_sections(members, orders, member_votes=None, today=None):
    """(heading, lines) sections for validate_ga_members.render(); empty when nothing to say."""
    out = []
    for heading, lines in (
        ("Suspension order not reflected in the roster", suspension_without_status(members, orders)),
        ("Indictment under review: a suspension may follow", review_commission_pending(members, orders, today)),
        ("Marked Suspended but voting", suspended_but_voting(members, member_votes)),
    ):
        if lines:
            out.append((heading, lines))
    return out


def load_member_votes(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def default_paths(root):
    return (os.path.join(root, "assets", "data", "ga-executive-orders-*.json"),
            os.path.join(root, "assets", "data", "ga-member-votes.json"))
