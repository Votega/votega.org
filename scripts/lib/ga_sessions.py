"""Single source of truth for the Georgia General Assembly sessions the site tracks.

Georgia sits in two-year General Assemblies (bienniums). A biennium is one regular
session PLUS any special/extraordinary sessions the Governor convenes within it — all
the work of the SAME sitting membership. Open States exposes each as its own session
identifier, so the generators fetch the ACTIVE session live and PRESERVE the records of
the closed sessions already on file (they never change, so they're never re-fetched).

Both SOAP producers honour that, via preserved_session_ids() below: each fetches
ACTIVE_SESSION, carries the closed sessions forward from its own output file, and ABORTS
rather than publish a file short a session. For votes the carry-forward is a merge, not a
concatenation — ga-member-votes.json is a cross-session compact index and its memberVotes
are keyed by PERSON, so a member's row spans sessions and the union must take the
preserved layer as its base (see generate_ga_votes_soap.py and
scripts/test_votes_incremental.py).

Two derivations therefore freeze for closed sessions, which is what --full-refresh is
for: a crosswalk backfill (an unresolved legisGaGovId resolved later) and result
derivation (the two-thirds constitutional-amendment rule) no longer reach them.

Every bill and vote record is tagged with its `session` id. That lets the site show the
whole biennium in one list (filterable by session) while the publishers split the
combined file back into per-session archive directories.

Update when a special session is convened, or at a biennium changeover:
  - add the new session id -> name to SESSION_NAMES,
  - point ACTIVE_SESSION at whichever session is currently in progress,
  - set UNTAGGED_SESSION to the session that untagged on-file records belong to.

The legis.ga.gov numeric id is NO LONGER a hand-maintained value: Session/GetSessions
publishes every session, `scripts/generate_legis_sessions.py` commits that table to
assets/data/ga-legis-sessions.json (weekly, via update-legis-sessions.yml), and
legis_session_id() resolves against it. A `YYYY_YY` regular-session tag resolves with
no entry at all; only a SPECIAL session needs its name in SESSION_NAMES, because those
descriptions are irregular. LEGIS_SESSIONS below is now just an offline fallback.

Get the Open States identifier from `inspect_ga_sessions.py`. Never guess or probe for
a legis id — the id space is not contiguous (2019-2020 is 27, 2021-2022 is 1029).
See RECURRING-TASKS.md §3.
"""
import json
import os
import re

# id -> human name for every session in the CURRENT biennium (158th GA, 2025-2026).
# Order matters: this is the display/iteration order (regular session first).
SESSION_NAMES = {
    "2025_26": "2025-2026 Regular Session",
    "2026_ss": "2026 Special Session",
}

# The session currently in progress — the ONLY one fetched live. Every other session in
# SESSION_NAMES is closed and preserved from the existing data file.
ACTIVE_SESSION = "2026_ss"

# Records written before multi-session support carried no `session` tag; they all belong
# to the session that was the sole pin at the time. Used once, to migrate the old file.
UNTAGGED_SESSION = "2025_26"

# Label for the biennium as a whole, for UI copy ("the 2025-2026 General Assembly").
BIENNIUM = "2025-2026"

# Our session tag -> legis.ga.gov's numeric session id and `library` string.
#
# This is now a FALLBACK. The authoritative table is assets/data/ga-legis-sessions.json,
# written by scripts/generate_legis_sessions.py from Session/GetSessions, which needs no
# auth and returns all 23 sessions back to 2001-2002. We keep a hardcoded copy of the
# current biennium so this module works with no data file at all (a fresh clone, the test
# suite, a producer run before the table is generated) and never makes a network call on
# import.
#
# Do not extend this by probing GetVotes across a range of ids: the id space is neither
# contiguous nor ordered by era (1, 6, 7, 11, 13-15, 18, 20-27, then 1027+), so a sweep
# finds the recent sessions and silently misses every one before 2021 — 2019-2020 is id
# 27. Run the generator instead.
LEGIS_SESSIONS = {
    "2025_26": {"id": 1033, "library": "20252026"},
    "2026_ss": {"id": 1034, "library": "2026EX"},
    # PRIOR biennium, kept only so a curated bill older than the committed vote
    # artifacts can still be sourced over SOAP (generate_curated_ga_bills.py). It is
    # deliberately absent from SESSION_NAMES, so nothing iterates or fetches it as
    # part of the current biennium.
    "2023_24": {"id": 1031, "library": "20232024"},
}

#: The generated table, newest-first. Read lazily and cached so importing this module
#: costs nothing, and so a producer that regenerates the file mid-run is not surprised.
LEGIS_SESSIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "data", "ga-legis-sessions.json")
_session_table = None


def legis_session_table():
    """`{description: {"id": int, "library": str|None}}` from the generated table.

    Keyed on the legislature's own description ("2025-2026 Regular Session") because that
    is what SESSION_NAMES already spells out for each of our tags — so the two join
    without a second mapping to maintain. Returns {} when the file is absent or unreadable;
    callers fall back to LEGIS_SESSIONS.
    """
    global _session_table
    if _session_table is None:
        table = {}
        try:
            with open(LEGIS_SESSIONS_FILE, encoding="utf-8") as fh:
                for row in (json.load(fh).get("sessions") or []):
                    desc, sid = (row.get("description") or "").strip(), row.get("id")
                    if desc and sid:
                        table[desc] = {"id": sid, "library": row.get("library")}
        except (OSError, json.JSONDecodeError, AttributeError):
            table = {}
        _session_table = table
    return _session_table


def regular_session_description(session_id):
    """A `YYYY_YY` tag -> the legislature's description, e.g. "2023_24" ->
    "2023-2024 Regular Session". '' for anything else.

    This lets a tag for ANY past biennium resolve straight out of the generated table,
    so sourcing an older session does not need a hand-added LEGIS_SESSIONS entry. It is
    not guessing an id — the description is only ever used as a key INTO the table, and
    a description that is not there resolves to nothing.

    Regular sessions only. Special-session descriptions are irregular ("2026 Special
    Session", but "2001 1st Special Session" and "2001 2nd Special Session"), so those
    stay explicit in SESSION_NAMES or LEGIS_SESSIONS.
    """
    m = re.fullmatch(r"(\d{4})_(\d{2})", session_id or "")
    if not m:
        return ""
    start = int(m.group(1))
    end = int(str(start)[:2] + m.group(2))
    # A biennium spans the start year and the next; anything else is not this pattern.
    if end != start + 1:
        return ""
    return f"{start}-{end} Regular Session"


def _legis_session(session_id):
    """Resolve one of our tags to {"id", "library"}.

    Order: an explicit SESSION_NAMES description against the generated table, then the
    derived regular-session description against it, then the hardcoded fallback map.
    """
    table = legis_session_table()
    for desc in (SESSION_NAMES.get(session_id), regular_session_description(session_id)):
        if desc and desc in table:
            return table[desc]
    return LEGIS_SESSIONS.get(session_id)


def legis_session_id(session_id):
    """legis.ga.gov numeric session id for our tag, or None if not mapped."""
    s = _legis_session(session_id)
    return s["id"] if s else None


def legis_session_library(session_id):
    """legis.ga.gov session `library` string for our tag, or None if not mapped.

    None also when the session is mapped for SOAP only (no `library` recorded) —
    callers that need the REST producer must treat that as unmapped."""
    s = _legis_session(session_id)
    return s.get("library") if s else None


def session_name(session_id):
    """Human-readable name for a session id (falls back to the id itself)."""
    return SESSION_NAMES.get(session_id, session_id)


def session_slug(session_id):
    """Archive directory slug for a session. A regular session collapses to its
    biennium span ('2025_26' -> '2025-2026'); a special session keeps its identifier
    ('2026_ss' -> '2026-ss'), since its name carries only one year. Kept here so both
    publishers derive the same slug from the record's session tag."""
    name = SESSION_NAMES.get(session_id, "")
    m = re.search(r"(\d{4})\D+(\d{4})", name)
    return f"{m.group(1)}-{m.group(2)}" if m else session_id.replace("_", "-")


def all_session_ids():
    """Every session in the current biennium, in display order."""
    return list(SESSION_NAMES)


def preserved_session_ids():
    """Closed sessions retained from the existing file (everything but the active one)."""
    return [s for s in SESSION_NAMES if s != ACTIVE_SESSION]


def tag_session(record_session):
    """Normalize a record's session tag: an untagged (None/empty) record predates
    multi-session support and belongs to UNTAGGED_SESSION."""
    return record_session or UNTAGGED_SESSION
