"""Shape legis.ga.gov roster fields for publication.

Phase 1 of Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md. The Members service is
authoritative about *facts* but not about formatting: `Address1` is free text,
and committee names are the official ones, which include a bare acronym. Both
are rendered straight onto 250 member pages, so the shaping belongs in one
tested place rather than inline in the producer.

Deliberately NOT a general address parser. It fixes the specific, enumerated
defects seen across the whole 251-member listing and leaves everything else
untouched, so an unfamiliar value passes through rather than being mangled.
"""
from __future__ import annotations

import datetime
import json
import os
import re

#: The Coverdell building, spelled five ways across the live listing: "CLOB"
#: (30 members), "Coverdell Legislative Office Bldg." (120), the full form (12),
#: "...Bldg" and "Coverdell Legislative Bldg." (1 each). The State Capitol is a
#: DIFFERENT building and is never folded into this.
CLOB = "Coverdell Legislative Office Building"

_CLOB_FORMS = re.compile(
    r"\bCoverdell\s+(?:Legislative\s+)?(?:Office\s+)?(?:Building|Bldg\.?)"
    r"|\bCLOB\b",
    re.IGNORECASE,
)

#: Published verbatim except for acronyms a reader cannot expand. Keyed by
#: `_key()`, so case and internal spacing do not have to match.
#: Keep this as short as it can possibly be: every entry is a name that stops
#: tracking the official one the moment the General Assembly renames it.
COMMITTEE_ALIASES = {
    "martoc": "Metropolitan Atlanta Rapid Transit Overview Committee",
}

#: The fields no roster source has a concept of: whether a member has left, when,
#: and why. They are the reason the editorial layer exists, so they are the only
#: fields carried over from an `_inject` entry the source has since caught up on.
EDITORIAL_STATUS_FIELDS = ("status", "statusDate", "statusNote")


def _key(name):
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def display_committee(name):
    """The committee name as the site should print it, or None if there isn't one."""
    k = _key(name)
    if not k:
        return None
    return COMMITTEE_ALIASES.get(k) or re.sub(r"\s+", " ", name.strip())


#: How far a source listing may fall below the committed roster before it is treated as
#: a truncated fetch. Real attrition inside a biennium is a handful of seats; an election
#: turnover replaces members rather than removing them, so the listing stays about the
#: same size either way.
LISTING_TOLERANCE = 0.10


def listing_is_too_short(n_listing, n_committed, tolerance=LISTING_TOLERANCE):
    """Is this listing short enough to be a truncated fetch rather than real attrition?

    A roster-count floor cannot catch this on its own. Because any committed member
    absent from the listing is PRESERVED verbatim — the rule that keeps the Lt. Governor,
    who is not a member of either chamber — a truncated listing does not shrink the
    roster, it backfills it with stale records and still passes a 56/180 check. Nothing
    then looks wrong while most of the roster quietly stops updating.

    Returns False when there is no committed roster to compare against: a first run has
    no baseline, and inventing one would block the bootstrap.
    """
    if n_committed <= 0:
        return False
    return n_listing < n_committed * (1 - tolerance)


#: Chambers whose members cast roll-call votes. Duplicated from lib/ga_voters.VOTING_CHAMBERS
#: on purpose: this module stays import-free so the no-pip CI job can load it alone.
VOTING_CHAMBERS = ("Senate", "House of Representatives")

#: Override keys carrying a departure. They say a member LEFT, which is a fact about one
#: biennium's seat, so at a rollover an entry without `_session` is ambiguous.
DEPARTURE_FIELDS = ("status", "statusDate", "statusNote")


def entry_in_scope(entry, session):
    """Does this override entry apply to the roster being built for `session`?

    An entry may name the biennium it belongs to in `_session` (the roster's regular-
    session tag, e.g. "2025_26"). One for ANOTHER biennium is inert here: a Resigned
    `_inject` for a 2025-26 member must not re-seat them in the 2027-28 roster, and the
    tier-1 `_inject` orphan check must not demand them either. An entry with no
    `_session` applies to every biennium (the pre-rollover behaviour), and `session=None`
    applies everything, so every existing caller is unchanged.
    """
    tag = entry.get("_session") if isinstance(entry, dict) else None
    return session is None or tag is None or tag == session


def injects_for_session(overrides, session):
    """The `_inject` entries in scope for `session` — the ones the output must contain."""
    return [e for e in (overrides or {}).get("_inject") or [] if entry_in_scope(e, session)]


def untagged_departures(overrides_file):
    """Labels of override entries that record a departure but name no biennium.

    Safe to leave untagged within one biennium; at a rollover each is a decision (which
    seat did this describe?) that must be made by a human, so the rollover refuses.
    """
    if not os.path.exists(overrides_file):
        return []
    with open(overrides_file, encoding="utf-8") as fh:
        overrides = json.load(fh)
    out = []
    for key, val in overrides.items():
        if key == "_inject":
            out += [f"_inject: {e.get('name') or e.get('id')}" for e in val
                    if isinstance(e, dict) and "_session" not in e]
        elif key.startswith("ocd-person/") or not key.startswith("_"):
            if (isinstance(val, dict) and "_session" not in val
                    and any(f in val for f in DEPARTURE_FIELDS)):
                out.append(f"{key}: {val.get('_name') or ''}".strip())
    return out


def out_of_scope_entries(overrides_file, session):
    """Labels of override entries skipped because they name a different biennium."""
    if not os.path.exists(overrides_file):
        return []
    with open(overrides_file, encoding="utf-8") as fh:
        overrides = json.load(fh)
    out = []
    for key, val in overrides.items():
        if key == "_inject":
            out += [f"_inject: {e.get('name') or e.get('id')}" for e in val
                    if isinstance(e, dict) and not entry_in_scope(e, session)]
        elif isinstance(val, dict) and not key.startswith("_")                 and not entry_in_scope(val, session):
            out.append(key)
    return out


def detect_rollover(committed_meta, tag, legis_session):
    """None for an ordinary run; else which biennium the committed file is from.

    A roster is built for one biennium's regular session, and the committed file records
    which in `metadata`. When the session being built is a different one, the preserve-
    verbatim rule (an absent member is republished as sitting) is wrong: it would carry
    the entire outgoing class across. No committed record at all is a bootstrap, not a
    rollover, so there is nothing to detect.
    """
    was_tag = (committed_meta or {}).get("session")
    was_id = (committed_meta or {}).get("legisSessionId")
    if not was_tag and not was_id:
        return None
    if (was_tag and was_tag != tag) or (was_id and was_id != legis_session):
        return {"from": {"session": was_tag, "legisSessionId": was_id},
                "to": {"session": tag, "legisSessionId": legis_session}}
    return None


def biennium_slug(tag):
    """'2025_26' -> '2025-2026' (the sessions/<slug>/ archive directory), else None."""
    m = re.fullmatch(r"(\d{4})_(\d{2})", tag or "")
    return f"{m.group(1)}-{m.group(1)[:2]}{m.group(2)}" if m else None


def convening_date(year):
    """Second Monday of January — when the Georgia General Assembly convenes (Ga. Const.
    Art. III, Sec. IV, Para. VII). 2027 -> 2027-01-11."""
    first = datetime.date(year, 1, 1)
    first_monday = first + datetime.timedelta(days=(7 - first.weekday()) % 7)
    return first_monday + datetime.timedelta(days=7)


def split_for_rollover(existing, in_listing):
    """(preserved, departing) when the biennium changes.

    `preserved` keeps only what the Members service never carries: anyone outside the
    two voting chambers who holds a legisGaGovId (the Lt. Governor presides over the
    Senate but is not a member). Keyed on chamber, not on lacking an id, for the same
    reason the ordinary rule is keyed on absence: an id-based rule dropped him.
    `departing` is every voting-chamber record the incoming listing does not carry,
    including a Vacant placeholder, which describes a seat of the outgoing biennium.
    """
    absent = [m for m in existing if m.get("legisGaGovId") not in in_listing]
    preserved = [m for m in absent if m.get("chamber") not in VOTING_CHAMBERS]
    departing = [m for m in absent if m.get("chamber") in VOTING_CHAMBERS]
    return preserved, departing


def apply_member_overrides(members, overrides_file, session=None):
    """Apply the editorial layer in place; return (patched, injected) counts.

    `session` scopes the layer to a biennium: an entry whose `_session` names another one
    is skipped (see `entry_in_scope`). Omitted, everything applies.

    This is the only thing that knows a member has left, been suspended, or that
    a seat is empty: the upstream carries no such concept, so without this step
    11 Resigned and 1 Suspended member read as sitting and the majority tracker
    paints their seats as filled. Any roster producer MUST call it.

    Keys are an OCD person id or a full name (case/space-insensitive); `_inject`
    holds whole records the source does not return. An `_inject` entry is keyed
    on the member's real id, so it stops adding a duplicate once the source
    catches up — never give one a synthetic id for a person the source will
    eventually carry. Keys beginning `_` inside a patch are editorial notes and
    are never published.

    When the source DOES start carrying an injected member, the entry is not
    simply discarded: its facts are stale (the live record is better) but its
    `status` fields are editorial and exist nowhere else, so those are merged on
    top. Skipping outright is what silently promoted 11 resigned members back to
    sitting when the roster moved from Open States, which drops departed members,
    to legis.ga.gov, which returns everyone who served the biennium.
    """
    if not os.path.exists(overrides_file):
        return 0, 0
    with open(overrides_file, encoding="utf-8") as fh:
        overrides = json.load(fh)

    by_id = {k: v for k, v in overrides.items()
             if k.startswith("ocd-person/") and entry_in_scope(v, session)}
    by_name = {k.lower().strip(): v for k, v in overrides.items()
               if not k.startswith(("ocd-person/", "_")) and entry_in_scope(v, session)}

    patched = 0
    for member in members:
        patch = by_id.get(member.get("id")) or by_name.get(
            (member.get("name") or "").lower().strip())
        if patch:
            member.update({k: v for k, v in patch.items() if not k.startswith("_")})
            patched += 1

    by_live_id = {m.get("id"): m for m in members if m.get("id")}
    injected = 0
    for entry in overrides.get("_inject", []):
        eid = entry.get("id")
        if not eid or not entry_in_scope(entry, session):
            continue
        live = by_live_id.get(eid)
        if live is None:
            members.append({k: v for k, v in entry.items() if not k.startswith("_")})
            by_live_id[eid] = members[-1]
            injected += 1
            continue
        # The source now carries them. Keep its facts; merge only the editorial
        # status, and only where the live record has none and an explicit patch
        # has not already spoken.
        merged = {k: entry[k] for k in EDITORIAL_STATUS_FIELDS
                  if entry.get(k) is not None and live.get(k) is None}
        if merged:
            live.update(merged)
            patched += 1
    return patched, injected


def _clean_zip(zipcode):
    """'30334-' is a ZIP with an empty +4; '30334-1300' is a real ZIP+4."""
    z = (zipcode or "").strip()
    return z[:-1].strip() if z.endswith("-") else z


def normalize_address(street, city, state, zipcode):
    """One display line — 'room building, City, ST ZIP' — or None.

    Fixes what the source actually gets wrong: the building's five spellings,
    semicolons used as line separators, the empty segments those leave behind,
    runs of whitespace, and a dangling ZIP hyphen. Returns None rather than a
    bare comma when there is nothing to show.
    """
    street = _CLOB_FORMS.sub(CLOB, (street or "").strip())
    tail = " ".join(p for p in ((state or "").strip(), _clean_zip(zipcode)) if p)
    joined = ", ".join(p for p in (street, (city or "").strip(), tail) if p)

    # Semicolons are separators in this source, not punctuation.
    joined = joined.replace(";", ",")
    joined = re.sub(r"\s+", " ", joined)
    # Drop the empty segments that the substitutions above can leave behind
    # ('214 State Capitol ; ; Atlanta' -> three real parts, not five).
    parts = [p.strip() for p in joined.split(",")]
    return ", ".join(p for p in parts if p) or None
