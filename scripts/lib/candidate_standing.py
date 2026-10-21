"""Where a candidate stands in their race, as pure functions (no yaml, no I/O).

build_entity_pages.py asks this one question per candidate page and acts on the answer:

  live        on the race's current ballot: a full page, indexed, searchable, with a card
  off-ballot  the race has a current ballot and they are not on it (lost a primary, missed a
              runoff, withdrew): the page stays, labelled, noindex, hidden from search
  lost        the race is certified and someone else won: same treatment, different wording
  won         the race is certified and they won: redirect to their officeholder page when
              one exists, else keep the page with a "won" note

Everything is derived from races.json. `status: "certified"` plus `winner: {candidateId}` on
the race is the existing, hand-recorded signal (the pages already read it, and the published
races schema documents it), so a result that is merely unofficial changes nothing: nothing is
retired or redirected on counts that can still move.
"""
from __future__ import annotations

LIVE, OFF_BALLOT, LOST, WON = "live", "off-ballot", "lost", "won"


def _key(c) -> str:
    return c.get("id") or c["name"]


def certified_winner_id(race, all_candidate_ids) -> str | None:
    """The winning candidate's id, only if the race is certified and that id is really in it.

    A winner id that matches nobody in the race (a typo, or a candidate id that moved) is
    ignored rather than obeyed: obeying it would mark every candidate "lost" and nobody "won".
    """
    if not race or race.get("status") != "certified":
        return None
    wid = (race.get("winner") or {}).get("candidateId")
    return wid if wid and wid in all_candidate_ids else None


def standing(race, active, me_key, all_candidate_ids) -> str:
    """One of LIVE / OFF_BALLOT / LOST / WON for the candidate keyed `me_key`.

    `active` is the race's current-ballot candidates; `all_candidate_ids` is every candidate id
    the race has ever carried (any phase), used to validate the recorded winner.
    """
    wid = certified_winner_id(race, all_candidate_ids)
    if wid:
        return WON if me_key == wid else LOST
    if active and not any(_key(c) == me_key for c in active):
        return OFF_BALLOT
    return LIVE


def officeholder_target(candidate_id, people, urls):
    """The clean URL of this candidate's officeholder page, or None if there isn't one yet.

    `people` is id-crosswalk.json's person list. A candidate is tied to an officeholder by the
    crosswalk (their campaign candidate id sits on the same person as a bioguide or roster id),
    never by name. None until the roster actually carries them: a winner is not an officeholder
    until sworn in, so their candidate page keeps serving until the page they would redirect to
    exists.
    """
    for p in people:
        ids = p.get("ids") or {}
        if candidate_id not in (ids.get("votegaCandidateIds") or []):
            continue
        bio, roster = ids.get("bioguideId"), ids.get("rosterId")
        if bio and (urls.get("us-congress") or {}).get(bio):
            return urls["us-congress"][bio]
        if roster and (urls.get("ga-legislator") or {}).get(roster):
            return urls["ga-legislator"][roster]
    return None


def overall(states) -> str:
    """One standing for a person who appears in several races (a special and a full term).

    Still running anywhere keeps the full page; else a win anywhere makes them an officeholder
    (a redirect, or a "won" note); else lost beats merely off-ballot, because it is the stronger,
    certified fact.
    """
    states = set(states)
    for s in (LIVE, WON, LOST, OFF_BALLOT):
        if s in states:
            return s
    return LIVE
