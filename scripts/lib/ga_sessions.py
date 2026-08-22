"""Single source of truth for the Georgia General Assembly sessions the site tracks.

Georgia sits in two-year General Assemblies (bienniums). A biennium is one regular
session PLUS any special/extraordinary sessions the Governor convenes within it — all
the work of the SAME sitting membership. Open States exposes each as its own session
identifier, so the generators fetch the ACTIVE session live and PRESERVE the records of
the closed sessions already on file (they never change, so they're never re-fetched).

Every bill and vote record is tagged with its `session` id. That lets the site show the
whole biennium in one list (filterable by session) while the publishers split the
combined file back into per-session archive directories.

Update when a special session is convened, or at a biennium changeover:
  - add the new session id -> name to SESSION_NAMES,
  - point ACTIVE_SESSION at whichever session is currently in progress,
  - set UNTAGGED_SESSION to the session that untagged on-file records belong to.
Get the exact identifier from `inspect_ga_sessions.py` — don't guess it. See
RECURRING-TASKS.md §3.
"""
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
