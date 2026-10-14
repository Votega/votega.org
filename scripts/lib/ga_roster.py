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


def apply_member_overrides(members, overrides_file):
    """Apply the editorial layer in place; return (patched, injected) counts.

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

    by_id = {k: v for k, v in overrides.items() if k.startswith("ocd-person/")}
    by_name = {k.lower().strip(): v for k, v in overrides.items()
               if not k.startswith(("ocd-person/", "_"))}

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
        if not eid:
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
