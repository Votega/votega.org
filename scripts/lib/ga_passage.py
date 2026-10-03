#!/usr/bin/env python3
"""Passage classification for GA roll calls — one testable home for the logic that
decides which legis.ga.gov roll calls are "passage" votes (design §5.3).

legis.ga.gov exposes EVERY roll call (final passage, local-calendar batches,
procedural motions). The site shows passage only, so the legis vote producer must
reproduce that set. Two signals:

  * Open States passage overlay (authoritative): the existing OS ga-member-votes.json
    is already the passage set, so a legis roll call whose (bill, date) matches an OS
    entry is passage — and the match carries the authoritative result (Pass/Fail).
  * Native legis fields (future-proof): each legislation.votes[] row has `isRollCall`
    and a `caption` motion. `native_is_passage()` encodes a first-guess rule; the
    `--classify-report` diagnostic calibrates it against the OS labels before we rely
    on it (same evidence-first method used to pin the memberVoted map).

The caption patterns below are a STARTING POINT, to be tightened from the
calibration report's caption breakdown (the real passage captions aren't yet known
— the only live caption seen so far is "Local Calendar").
"""

import json
import re

#: Motions that ARE final passage of a measure.
PASSAGE_CAPTION = re.compile(
    r"\b(passage|adopt(?:ion)?|agree)\b", re.IGNORECASE)

#: Motions that are procedural / not final passage (override PASSAGE on overlap).
PROCEDURAL_CAPTION = re.compile(
    r"(local calendar|motion to|table|recommit|reconsider|previous question|"
    r"postpone|adjourn|amendment|committee substitute report|point of order)",
    re.IGNORECASE)


def normalize_bill(identifier):
    """Collapse a bill identifier for cross-source matching: 'HB 9EX' -> 'HB9EX'."""
    return re.sub(r"\s+", "", (identifier or "")).upper()


def native_is_passage(is_roll_call, caption):
    """First-guess native rule: a recorded roll call whose caption reads as passage
    and not as a procedural motion. Calibrate against the overlay before relying."""
    cap = caption or ""
    return (bool(is_roll_call)
            and bool(PASSAGE_CAPTION.search(cap))
            and not PROCEDURAL_CAPTION.search(cap))


def load_os_passage_index(path, session):
    """Index the Open States passage set for one session as
    {(normalize_bill(bill), 'YYYY-MM-DD'): {result, yea, nay, osVoteId}}.

    OS ga-member-votes.json already contains only passage votes (its producer
    filters motion_classification == ['passage']), so every entry is a passage key.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    index = {}
    for vote_id, meta in (data.get("votes") or {}).items():
        if meta.get("session") != session:
            continue
        key = (normalize_bill(meta.get("bill")), (meta.get("date") or "")[:10])
        index[key] = {
            "result": meta.get("result"),
            "yea": meta.get("yea"),
            "nay": meta.get("nay"),
            "osVoteId": vote_id,
        }
    return index
