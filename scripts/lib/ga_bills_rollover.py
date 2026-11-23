"""Biennium-changeover rules for the GA bills producer (pure; no I/O except one read).

generate_ga_bills_soap.py refuses to write fewer than WRITE_FLOOR bills, because a
sweep that comes back near-empty is almost always a failed sweep. That floor is wrong
for exactly one moment: the first runs after lib/ga_sessions.py is bumped to a new
General Assembly. SESSION_NAMES then holds only the new biennium, nothing is
preserved, and legis.ga.gov may list a handful of prefiled bills, or none, until the
session convenes. Failing there would leave the site presenting the closed biennium as
current.

The changeover is DETECTED, never switched on by a quiet bypass: the committed file
says which biennium it holds (`metadata.biennium`), the config says which one is being
built. A mismatch is a changeover, and it is only honoured when the outgoing
biennium's frozen copy exists (assets/data/ga-bienniums/<tag>/ga-bills.json, written by
freeze_ga_bills.py), because after the run the old bills exist nowhere else on the site.
The run stamps `metadata.rollover`, which is how validate_ga_bills.py knows an empty
file is deliberate.

A special session added INSIDE a biennium changes the session set but not the
biennium, so it is not a changeover (the preserved-session checks still apply to it).
"""
import json
import os
import re

#: Fewest bills a same-session write may hold. Unchanged from the original constant.
WRITE_FLOOR = 100

_BIENNIUM_RE = re.compile(r"^(\d{4})-(\d{4})$")


def biennium_to_tag(biennium):
    """'2025-2026' -> '2025_26'; None for anything else."""
    m = _BIENNIUM_RE.match(biennium or "")
    if not m:
        return None
    start, end = int(m.group(1)), int(m.group(2))
    if end != start + 1:
        return None
    return "%d_%02d" % (start, end % 100)


def detect_changeover(committed_meta, biennium):
    """{'from': <old biennium>, 'to': <new>} when the committed file holds a different
    General Assembly than the config builds; None when it is the same, or when the
    committed file does not say (a file from before `biennium` existed is not evidence)."""
    old = (committed_meta or {}).get("biennium")
    if old and biennium and old != biennium:
        return {"from": old, "to": biennium}
    return None


def frozen_path(root, tag):
    return os.path.join(root, "assets", "data", "ga-bienniums", tag, "ga-bills.json")


def frozen_problem(root, outgoing_biennium):
    """Why the outgoing biennium is NOT safely frozen, or None when it is."""
    tag = biennium_to_tag(outgoing_biennium)
    if tag is None:
        return "cannot derive a freeze tag from biennium %r" % (outgoing_biennium,)
    path = frozen_path(root, tag)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return "no readable frozen copy at %s (%s)" % (path, exc)
    meta = doc.get("metadata") or {}
    if not meta.get("frozen") or meta.get("frozenTag") != tag:
        return "%s is not a freeze of %s (metadata.frozen/frozenTag)" % (path, tag)
    if not doc.get("bills"):
        return "%s holds no bills" % path
    return None


def write_floor(committed_total, changeover):
    """Smallest number of bills the producer may write.

    - changeover: 0. An unfiled session is legitimately empty; the caller has already
      proved the old biennium is frozen and that the SOAP index call itself succeeded.
    - committed file is itself under WRITE_FLOOR (a young post-changeover file): it may
      not SHRINK. Bills only accumulate within a session, so a drop is data loss, while
      growth from 3 to 60 must not trip the fixed 100.
    - otherwise: WRITE_FLOOR.
    """
    if changeover:
        return 0
    if committed_total is not None and committed_total < WRITE_FLOOR:
        return committed_total
    return WRITE_FLOOR


def floor_problem(n_bills, committed_total, changeover):
    """Error text when `n_bills` may not be written, else None."""
    floor = write_floor(committed_total, changeover)
    if n_bills >= floor:
        return None
    return ("only %d bills collected (floor %d) — refusing to write "
            "(SOAP sweep likely failed)." % (n_bills, floor))


def rollover_stamp(changeover, committed_meta, n_bills, now_iso):
    """The `metadata.rollover` value for the new file, or None.

    Set at a changeover, then carried forward while the file is still under
    WRITE_FLOOR, so a second run that is still empty is recognised as deliberate."""
    if changeover:
        return {"from": changeover["from"], "to": changeover["to"], "at": now_iso}
    prior = (committed_meta or {}).get("rollover")
    if prior and n_bills < WRITE_FLOOR:
        return prior
    return None
