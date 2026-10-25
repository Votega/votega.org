#!/usr/bin/env python3
"""Which TERMINATED PeachFile committees still belong in ga-campaign-finance.json.

The generator used to ask PeachFile for active committees only (`accountStatus:
"FACT"`). A committee that closes - typically after a lost primary or a decision not
to run - therefore vanished, and its final totals with it: Rep. Bill Werkheiser, still
in office until January, went from $256,995 raised to no finance data at all.

Keeping every terminated committee is wrong too: the file is joined to pages by seat
and by name, and dozens of closed committees from people who are neither in office nor
on a ballot would crowd seats with filers who are not part of the race.

So a terminated committee is kept only when the person still holds or is running for
the seat the committee was registered for:

  * legislative (State Senate / House): a last-name match, in that district, against
    the sitting member or a candidate on the district's active ballot;
  * statewide (Governor, PSC, ...): a full-name match against a candidate on an
    active statewide ballot. No sitting-officeholder rule: those come from other files
    and a closed statewide committee of someone not on the ballot is not this race.

The match is by SEAT plus last name, not by name alone, because the roster and the
filing disagree on first names ("Bill" / "William"). A namesake relative in the same
seat would also match; the cost of that is one extra filer in a bucket, whereas the
alternative (name-only) silently drops real incumbents.

Mirrors build_entity_pages._race_active_candidates for "the race's active ballot"
(the active phase, else general, runoff, primary; withdrawn / disqualified excluded).
Pure functions - the tests drive them with no network.
"""

import re

LEGISLATIVE_CHAMBERS = ("Senate", "House of Representatives")
_SEAT_ID = re.compile(r"^ga-(house|senate)-(\d+)-")
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|esq)\.?\b")


def norm(name):
    """Lowercase letters and single spaces, suffixes dropped ('Griffin Jr.' -> 'griffin')."""
    s = re.sub(r'["\'].*?["\']', "", (name or "").lower())
    s = _SUFFIX.sub("", s)
    return " ".join(re.sub(r"[^a-z\s]", "", s).split())


def last_name(name):
    parts = norm(name).split()
    return parts[-1] if parts else ""


def active_ballot_names(race):
    """Names on the race's active ballot (blank-named incumbents are left to the roster)."""
    phases = {k: v for k, v in (race.get("phases") or {}).items() if isinstance(v, dict)}
    for key in [race.get("activePhase"), "general", "runoff", "primary"]:
        ph = phases.get(key)
        if not ph:
            continue
        groups = list((ph.get("ballots") or {}).values()) if isinstance(ph.get("ballots"), dict) else []
        groups.append(ph.get("candidates") or [])
        names = [c["name"].strip() for g in groups for c in (g or [])
                 if isinstance(c, dict) and (c.get("name") or "").strip()
                 and not c.get("withdrawn") and not c.get("disqualified")]
        if names:
            return names
    return []


def build_scope(races, members):
    """{'legislative': {'<chamber>-<district>': {last names}}, 'statewide': {full names}}."""
    legislative, statewide = {}, set()
    for m in members or []:
        if m.get("chamber") in LEGISLATIVE_CHAMBERS and m.get("district") is not None \
                and m.get("status") in (None, "Suspended"):
            legislative.setdefault(f"{m['chamber']}-{m['district']}", set()).add(
                last_name(m.get("lastName") or m.get("name")))
    for race in races or []:
        names = active_ballot_names(race)
        seat = _SEAT_ID.match(race.get("id") or "")
        if seat:
            chamber = "Senate" if seat.group(1) == "senate" else "House of Representatives"
            legislative.setdefault(f"{chamber}-{int(seat.group(2))}", set()).update(
                last_name(n) for n in names)
        elif race.get("level") == "state":
            statewide.update(norm(n) for n in names)
    legislative = {k: {x for x in v if x} for k, v in legislative.items()}
    return {"legislative": legislative, "statewide": statewide}


def person_key(entry):
    """(district, normalised full name) - who a filing belongs to, within its seat."""
    full = norm(f"{entry.get('firstName') or ''} {entry.get('lastName') or ''}") or         norm(" ".join(reversed((entry.get("filerName") or "").split(",", 1))))
    return (entry.get("district"), full)


def keep_terminated(entry, chamber, scope, active=frozenset()):
    """True when a terminated filer's seat is still held or contested by that person.

    `entry` is the finance-file filer entry; `chamber` is the OFFICES chamber for its
    office (None for statewide). `active` holds person_key() of the ACTIVE filers of
    the same office: a person who already has a live committee in the seat has had
    this one superseded (a closed older committee), and keeping it would put the same
    candidate in the seat twice and turn a clean match into an ambiguous one.
    """
    if person_key(entry) in active:
        return False
    if chamber and entry.get("district"):
        seat = scope["legislative"].get(f"{chamber}-{entry['district']}") or set()
        last = last_name(entry.get("lastName") or entry.get("filerName", "").split(",")[0])
        return bool(last) and last in seat
    full = norm(f"{entry.get('firstName') or ''} {entry.get('lastName') or ''}") or \
        norm(" ".join(reversed((entry.get("filerName") or "").split(",", 1))))
    return bool(full) and full in scope["statewide"]
