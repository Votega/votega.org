#!/usr/bin/env python3
"""Passage classification for GA roll calls — one testable home for the logic that
decides which legis.ga.gov roll calls are "passage" votes (design §5.3).

legis.ga.gov exposes EVERY roll call (final passage, local-calendar batches,
procedural motions). The site shows passage only, so the legis vote producer must
reproduce that set. Two signals:

  * Open States passage overlay (authoritative): the existing OS ga-member-votes.json
    is already the passage set, so a legis roll call whose (bill, date) matches an OS
    entry is passage — and the match carries the authoritative result (Pass/Fail).
  * Native legis fields: each legislation.votes[] row has a `caption` motion.
    `native_is_passage()` encodes the rule; the `--classify-report` diagnostic
    calibrates it against the OS labels (same evidence-first method used to pin the
    memberVoted map).

Caption vocabulary learned from the 2025_26 calibration (2026-10-03) and extended
from the full caption universe (2026-10-04, cross-checked against the SOAP source):
  passage motions   : "PASSAGE", "PASSAGE BY SUBSTITUTE", "PASSAGE AS AMENDED",
                      "AGREE TO SENATE SUBSTITUTE", "AGREE TO SENATE SUB AS AM",
                      "AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE" (final action /
                      concurrence — all start with PASSAGE or AGREE TO).
  local batches     : "LOCAL CALENDAR", "LOCAL CONSENT CALENDAR", "SUPPLEMENTAL LOCAL
                      CALENDAR" — en-masse passage of local (single county/city) bills.
  resolution adopt. : "ADOPT", "ADOPTION", "ADOPTION BY SUBSTITUTE", "ADOPT CONFERENCE
                      COMMITTEE REPORT", "ADOPTION OF CONSTITUTIONAL AMENDMENT" — a
                      resolution's final action (GA "adopts" resolutions).
  procedural motions: "ADOPTION OF (THE/AN) AMENDMENT #N BY ..." (floor amendments),
                      "MOTION TO TABLE/ENGROSS", "MOTION FOR THE PREVIOUS QUESTION",
                      "RECONSIDER", "SHALL THE RULING OF THE CHAIR BE SUSTAINED".
NOTE: the `isRollCall` field was a red herring — it is False on EVERY roll call
(passage and procedural alike), so it is NOT used. The caption is the signal.
"""

import json
import re

#: Final-action captions, anchored at the start:
#:   passage / agree to  — a bill's passage or concurrence in the other chamber's changes
#:   adopt(ion)          — a RESOLUTION's final action (GA "adopts" resolutions, incl.
#:                         "ADOPT CONFERENCE COMMITTEE REPORT" and "ADOPTION OF
#:                         CONSTITUTIONAL AMENDMENT") — the floor-AMENDMENT adoptions are
#:                         carved back out by PROCEDURAL_CAPTION below.
PASSAGE_CAPTION = re.compile(r"^\s*(passage|agree\s+to|adopt)", re.IGNORECASE)

#: Local/consent-calendar batches — the mechanism by which LOCAL legislation (bills
#: affecting a single county/city) is passed en masse, so each is a real passage vote.
#: Matched anywhere (not anchored) to catch "Supplemental Local Calendar",
#: "Local Calendar Without HBs 851 & 852", "Supplemental Local Consent Calendar", etc.
LOCAL_CALENDAR = re.compile(r"local\s+(consent\s+)?calendar", re.IGNORECASE)

#: Procedural motions that must NOT count as passage even if they match the above
#: (floor-amendment adoptions, table/engross motions, chair rulings, reconsiderations).
#: "adoption of (the|a|an)? amend…" carves floor-amendment adoptions back out of the
#: broadened `adopt` rule — including "ADOPTION OF THE AMENDMENT BY THE SENATOR…".
PROCEDURAL_CAPTION = re.compile(
    r"^\s*(adoption of (the\s+|an?\s+)?amend|motion to|motion for|shall the ruling|"
    r"previous question|point of order|reconsider)",
    re.IGNORECASE)


def normalize_bill(identifier):
    """Collapse a bill identifier for cross-source matching: 'HB 9EX' -> 'HB9EX'."""
    return re.sub(r"\s+", "", (identifier or "")).upper()


def native_is_passage(caption):
    """Caption-only native rule: a final-action vote (bill passage/concurrence, local-
    calendar batch, or resolution adoption), not a procedural motion. A procedural
    caption disqualifies it even if it matches a final-action pattern (e.g. a floor
    amendment's adoption). (No isRollCall — it is uniformly False and carries no signal.)"""
    cap = caption or ""
    if PROCEDURAL_CAPTION.search(cap):
        return False
    return bool(PASSAGE_CAPTION.search(cap) or LOCAL_CALENDAR.search(cap))


def classify(caption, bills, date, os_index):
    """Decide whether a roll call is passage. Overlay-primary (design §5.3):

    * If any of the roll call's bundled `bills` has a (bill, date) in the OS passage
      index, it is passage and we borrow OS's authoritative result (source "overlay").
    * Else if the caption reads as passage, it is passage with no result yet
      (source "native" — fills gaps OS missed; result comes later).
    * Else it is not passage.

    Returns (is_passage: bool, result: str|None, source: str|None).
    """
    for bill in bills:
        hit = os_index.get((normalize_bill(bill), date))
        if hit:
            return True, hit.get("result"), "overlay"
    if native_is_passage(caption):
        return True, None, "native"
    return False, None, None


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
