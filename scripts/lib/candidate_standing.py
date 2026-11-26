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


def certified_winner_id(race, all_candidate_ids, all_member_ids=()) -> str | None:
    """The recorded winner's key, only if the race is certified and that key is really in it.

    The key is the winner's candidate id, or for an incumbent listed only by member id, that
    member id. One that matches nobody in the race (a typo, or an id that moved) is ignored
    rather than obeyed: obeying it would mark every candidate "lost" and nobody "won".
    """
    if not race or race.get("status") != "certified":
        return None
    w = race.get("winner") or {}
    if w.get("candidateId"):
        return w["candidateId"] if w["candidateId"] in all_candidate_ids else None
    mid = w.get("memberId")
    return mid if mid and mid in all_member_ids else None


def _groups(phase):
    """A phase's candidate lists, across both storage shapes (party ballots and a flat list)."""
    return list((phase.get("ballots") or {}).values()) + [phase.get("candidates") or []]


def active_candidates(race, with_name=lambda c: c):
    """(phase_key, candidates) for the race's active phase (else the latest with candidates).

    `with_name` fills a nameless entry (an incumbent listed only by member id) from a roster;
    withdrawn and disqualified candidates are not on the ballot.
    """
    phases = {k: v for k, v in (race.get("phases") or {}).items() if isinstance(v, dict)}
    order = [race.get("activePhase")] + ["general", "runoff", "primary"]
    for key in order:
        ph = phases.get(key)
        if not ph:
            continue
        out, seen = [], set()
        for g in _groups(ph):
            for c in (g or []):
                c = with_name(c)
                cn = (c.get("name") or "").strip()
                k = c.get("id") or cn
                if cn and k not in seen and not c.get("withdrawn") and not c.get("disqualified"):
                    seen.add(k)
                    out.append(c)
        if out:
            return key, out
    return None, []


def all_candidate_ids(race) -> set:
    """Every candidate id the race has carried in any phase (validates a recorded winner)."""
    return {c["id"] for ph in (race.get("phases") or {}).values() if isinstance(ph, dict)
            for g in _groups(ph) for c in (g or []) if c.get("id")}


def all_member_ids(race) -> set:
    """Member ids of incumbents the race lists (a recorded winner may be keyed on one)."""
    return {c.get("memberId") or c.get("existingMemberId")
            for ph in (race.get("phases") or {}).values() if isinstance(ph, dict)
            for g in _groups(ph) for c in (g or [])
            if c.get("memberId") or c.get("existingMemberId")}


def standing(race, active, me_key, all_candidate_ids, all_member_ids=()) -> str:
    """One of LIVE / OFF_BALLOT / LOST / WON for the candidate keyed `me_key`.

    `active` is the race's current-ballot candidates; `all_candidate_ids` is every candidate id
    the race has ever carried (any phase), used to validate the recorded winner.
    """
    wid = certified_winner_id(race, all_candidate_ids, all_member_ids)
    if wid:
        # An incumbent listed only by member id has no candidate page (they go to their member
        # page), so every candidate that does have one lost to them.
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
