#!/usr/bin/env python3
"""Normalize a legis.ga.gov leadership `Title` into the badge text the site renders.

SOAP's per-session `Title` (see `lib/ga_soap.get_member`) is terse and chamber-less:
`Chairman, Regulated Industries`, `Majority Leader`. The site's badge wants the clearer
form the overrides file used to carry by hand — `Chairman, House Committee on Regulated
Industries`, `House Majority Leader` — so this adds the chamber context and nothing else.

Validated against all 84 real `Title` values in session 1033: 82 badge, 2 are withheld as
lapsed, 0 need review. See Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md §8.1.

Deliberate non-goals:
  * No restyling of the legislature's own wording. The House says `Chairman`/`Vice-Chairman`
    and the Senate says `Chair`/`Vice-Chair`; that is their usage, not an inconsistency to
    fix. Only chamber context is added.
  * No inventing committees. A committee name that does not validate against
    `GetCommitteesBySession` is passed through as-is rather than wrapped, so a new or
    renamed committee degrades to plain text instead of asserting something false.
"""
from __future__ import annotations

import re

#: Roles that already name their chamber, or sit outside one. Never prefixed.
#: `Governor's Floor Leader` is an executive liaison — three House members and one senator
#: hold it, so a chamber prefix would misdescribe the office.
NO_PREFIX = re.compile(r"^(speaker\b|president\b|governor's floor leader$)", re.I)

#: A trailing parenthetical end-date means the role has lapsed: "Majority Leader (Until
#: 5/15/2025)". Prose, not a structured field — and badging it would assert a role the
#: member no longer holds.
LAPSED = re.compile(r"\(\s*until\b[^)]*\)\s*$", re.I)

#: "Chairman, X" / "Vice-Chair, X" — the comma form, which names a committee.
CHAIR_OF = re.compile(
    r"^(Chair(?:man|woman|person)?|Vice[-\s]?Chair(?:man|woman|person)?)\s*,\s*(.+)$", re.I)

#: The House's Appropriations subcommittees, which GetCommitteesBySession does not return.
APPROPRIATIONS_SUB = re.compile(r"^Appropriations:\s*(.+?)\s*Subcommittee$", re.I)

CHAMBER_WORD = {"House": "House", "House of Representatives": "House", "Senate": "Senate"}


def committee_key(name):
    """Fold a committee name for matching across the two services.

    They disagree on "&" vs "and", and the Committees service is inconsistent with itself
    ("Agriculture & Consumer Affairs" alongside "Industry and Labor"), so neither spelling
    can be trusted as the key.
    """
    s = (name or "").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def committee_index(committees):
    """[{name, type}, ...] -> {(chamber, committee_key): name} for validation."""
    return {(c.get("type"), committee_key(c.get("name"))): c.get("name")
            for c in (committees or []) if c.get("name") and c.get("type")}


def normalize_title(title, chamber, committees=None):
    """-> (badge_text, note).

    `badge_text` is None when the role should not be badged; `note` then says why.
    A non-None `note` alongside a badge means "rendered, but worth a human look".
    `chamber` accepts either the SOAP spelling ("House") or ours
    ("House of Representatives").
    """
    text = (title or "").strip()
    if not text:
        return None, None
    if LAPSED.search(text):
        return None, "lapsed role (title carries an end date)"

    word = CHAMBER_WORD.get(chamber)
    index = committees if isinstance(committees, dict) else committee_index(committees)
    soap_chamber = "Senate" if word == "Senate" else "House"

    m = CHAIR_OF.match(text)
    if m:
        role, committee = m.group(1), m.group(2).strip()

        sub = APPROPRIATIONS_SUB.match(committee)
        if sub and word:
            # "Appropriations: Health Subcommittee" reads badly as "Committee on
            # Appropriations: Health Subcommittee", so it gets its own form.
            return f"{role}, {word} Appropriations {sub.group(1)} Subcommittee", None

        known = index.get((soap_chamber, committee_key(committee)))
        if not known or not word:
            return text, (None if known else
                          f"committee {committee!r} is not in GetCommitteesBySession")
        # Render the committee as the TITLE spells it, not as the Committees service does:
        # titles are uniformly "&", so badges stay internally consistent and we never
        # restyle an official name. The service is used only to validate existence.
        if re.search(r"\bcommittee\b", committee, re.I):
            # Already a committee name ("Special Committee on Resource Management") —
            # wrapping it again reads "Committee on Special Committee on ...".
            return f"{role}, {word} {committee}", None
        return f"{role}, {word} Committee on {committee}", None

    if NO_PREFIX.match(text):
        return text, None
    if word and not text.lower().startswith(word.lower()):
        return f"{word} {text}", None
    return text, None
