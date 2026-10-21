"""Propose a race's winner from certified results, as pure functions (no I/O, no yaml).

The candidate pages already act on `status: "certified"` + `winner: {candidateId}` recorded on
a race in races.json (lib/candidate_standing.py), but nothing wrote those. This derives a
PROPOSAL for each race from the shared results data (`_data/election_results/*.json`, the same
files the results pages render), for a person to review and apply; it decides nothing on its own
and refuses anything that is not unambiguous.

Rules, and why each is a rule:
  * Only a CERTIFIED election counts. Counts that can still move decide nothing (the results
    page's own `status:` front matter is the gate, the same one the site shows readers).
  * A result is tied to a race by ELECTION DATE, not by guessing a phase name: races.json calls
    both the June primary runoff and a December general runoff "runoff", but their dates differ.
  * A winner takes a MAJORITY of the votes cast in the contest (Georgia requires one in a general
    election; short of it there is a runoff). A plurality is a "runoff", never a winner. A share
    within half a point of 50% is flagged for a human instead of decided.
  * A candidate is matched to a result row by name WITHIN that race's ballot, and only if exactly
    one candidate fits; zero or several is flagged. Names differ between sources
    ('Michael "Mike" Collins' / 'Mike Collins', 'Everton "EJ" Blair (Dem)' / 'Dr. Everton Blair').
  * A different winner already recorded is a conflict for a person, never overwritten.
"""
from __future__ import annotations

import re

NEAR_MAJORITY = 0.005  # a share this close to 50% is flagged, not decided

_STATEWIDE = {
    "US Senate": ("U.S. Senate", None),
    "Governor": ("Governor", None),
    "Lieutenant Governor": ("Lieutenant Governor", None),
    "Secretary of State": ("Secretary of State", None),
    "Attorney General": ("Attorney General", None),
    "Commissioner of Agriculture": ("Commissioner of Agriculture", None),
    "Commissioner of Insurance": ("Insurance & Fire Safety Commissioner", None),
    "State School Superintendent": ("State School Superintendent", None),
    "Commissioner of Labor": ("Labor Commissioner", None),
    "PSC - District 3": ("Public Service Commissioner", 3),
    "PSC - District 5": ("Public Service Commissioner", 5),
}
_SECTION_CHAMBER = {
    "us-house": "U.S. House",
    "state-senate": "Georgia State Senate",
    "state-house": "Georgia House of Representatives",
}
HANDLED_CHAMBERS = (
    {c for c, _d in _STATEWIDE.values()} | set(_SECTION_CHAMBER.values())
)
_TITLES = {"dr", "mr", "mrs", "ms", "hon", "rev", "sen", "rep"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


# --------------------------------------------------------------------------- #
# names
# --------------------------------------------------------------------------- #
def _tokens(s: str) -> list[str]:
    out = []
    for w in re.split(r"\s+", s.strip()):
        w = re.sub(r"[^a-z0-9]", "", w.lower())
        if w and w not in _TITLES and w not in _SUFFIXES:
            out.append(w)
    return out


def name_variants(name: str) -> set[tuple[str, str]]:
    """{(first, last)} readings of a name: with and without a quoted nickname, no titles,
    suffixes, middle names or trailing '(Dem)'-style parentheticals."""
    base = re.sub(r"\([^)]*\)", " ", name or "")
    nick = re.findall(r'["“]([^"”]+)["”]', base)
    plain = re.sub(r'["“][^"”]*["”]', " ", base)
    out = set()
    t = _tokens(plain)
    if len(t) >= 2:
        out.add((t[0], t[-1]))
        for n in nick:  # a nickname stands in for the first name
            nt = _tokens(n)
            if nt:
                out.add((nt[0], t[-1]))
    elif t:
        out.add((t[0], t[0]))
    return out


def match_candidate(result_name: str, candidates: list[dict]):
    """(candidate, None) for the one candidate this result name fits, else (None, reason)."""
    want = name_variants(result_name)
    hits = [c for c in candidates if want & name_variants(c.get("name") or "")]
    if len(hits) == 1:
        return hits[0], None
    return None, ("no candidate on the ballot fits this name" if not hits
                  else f"{len(hits)} candidates fit this name")


# --------------------------------------------------------------------------- #
# race / phase resolution
# --------------------------------------------------------------------------- #
def phase_candidates(phase: dict, members: dict | None = None) -> list[dict]:
    """A phase's candidates. An incumbent running for re-election is listed with only a member
    id (no name, no candidate id); `members` ({bioguide id: {"name", "party"}}) gives them a name
    to match against, and their `memberId` stays on the copy so a win can be recorded against it."""
    out = []
    for g in list((phase.get("ballots") or {}).values()) + [phase.get("candidates") or []]:
        for c in g or []:
            mid = c.get("memberId") or c.get("existingMemberId")
            if not c.get("name") and mid and (members or {}).get(mid):
                m = members[mid]
                c = {**c, "name": m["name"], "party": c.get("party") or m.get("party"), "memberId": mid}
            if c.get("name") or c.get("id"):
                out.append(c)
    return out


def races_on_date(races: list[dict], election_date: str):
    """[(race, phase_key)] for every race with a phase held on `election_date`."""
    out = []
    for r in races:
        for key, ph in (r.get("phases") or {}).items():
            if isinstance(ph, dict) and ph.get("electionDate") == election_date:
                out.append((r, key))
    return out


def resolve_race(section_id: str, office: str, on_date):
    """The single (race, phase_key) a results row belongs to, or (None, reason)."""
    if section_id == "courts":
        return None, "judicial races are not handled"
    chamber = district = None
    if section_id == "statewide":
        if office not in _STATEWIDE:
            return None, f"no races.json office for {office!r}"
        chamber, district = _STATEWIDE[office]
    elif section_id in _SECTION_CHAMBER:
        chamber = _SECTION_CHAMBER[section_id]
        m = re.search(r"District\s+(\d+)", office or "", re.I)
        if not m:
            return None, f"no district in {office!r}"
        district = int(m.group(1))
    else:
        return None, f"unknown results section {section_id!r}"
    hits = [(r, k) for r, k in on_date
            if r.get("chamber") == chamber and (district is None or r.get("district") == district)]
    if len(hits) == 1:
        return hits[0], None
    return None, ("no race held on that date" if not hits else f"{len(hits)} races fit")


# --------------------------------------------------------------------------- #
# one contest
# --------------------------------------------------------------------------- #
def flatten_office(race_row: dict) -> tuple[list[dict], int]:
    """(candidates, total votes) across every contest of one office. A staged general file
    splits an office into a contest per party; the real export may not, so both are summed."""
    cands, total = [], 0
    for c in race_row.get("contests") or []:
        cands.extend(c.get("candidates") or [])
        total += int(c.get("totalVotes") or 0)
    return cands, total


def decide(cands: list[dict], total: int, ballot: list[dict]) -> dict:
    """Classify one office's result against the race's ballot.

    kind: "winner" | "runoff" | "no-votes" | "flag". `flag` carries a `reason` for a person.
    """
    cands = [c for c in cands if c.get("name")]
    cast = sum(int(c.get("votes") or 0) for c in cands)
    total = max(int(total or 0), cast)  # a total row that undercounts the candidates is wrong
    if total <= 0:
        return {"kind": "no-votes"}
    ranked = sorted(cands, key=lambda c: int(c.get("votes") or 0), reverse=True)
    top = ranked[0]
    tv = int(top.get("votes") or 0)
    if len(ranked) > 1 and tv == int(ranked[1].get("votes") or 0):
        return {"kind": "flag", "reason": f"tie for first at {tv} votes"}
    share = tv / total
    out = {"votes": tv, "total": total, "share": round(share, 4)}
    if len(ranked) > 1 and abs(share - 0.5) < NEAR_MAJORITY:
        return {**out, "kind": "flag", "reason": f"within half a point of a majority ({share:.2%})"}
    if len(ranked) > 1 and share <= 0.5:
        return {**out, "kind": "runoff", "leader": top["name"]}
    cand, why = match_candidate(top["name"], ballot)
    if not cand:
        return {**out, "kind": "flag", "reason": f"winner {top['name']!r}: {why}"}
    if cand.get("withdrawn") or cand.get("disqualified"):
        return {**out, "kind": "flag", "reason": f"{cand.get('name')} is marked withdrawn/disqualified"}
    return {**out, "kind": "winner", "candidate": cand}


# --------------------------------------------------------------------------- #
# the whole proposal
# --------------------------------------------------------------------------- #
def propose(result_sets: list[dict], races: list[dict], members: dict | None = None) -> dict:
    """Walk the results sets in date order and return {proposals, flagged, runoffs, skipped}.

    A result set is {"data_key", "election_date", "status", "sections": [...]}. Only `certified`
    sets decide anything; the rest are counted under `skipped`. A later set supersedes an earlier
    set's "runoff" for the same race (the December runoff after a November general).
    """
    proposals, flagged, runoffs, skipped, unhandled = {}, [], {}, [], []
    for rs in sorted(result_sets, key=lambda s: s["election_date"]):
        if rs.get("status") != "certified":
            n = sum(len(r.get("contests") or []) for s in rs["sections"] for r in s.get("races") or [])
            skipped.append({"data_key": rs["data_key"], "status": rs.get("status"),
                            "election_date": rs["election_date"], "contests": n})
            continue
        on_date = races_on_date(races, rs["election_date"])
        seen = set()
        for sec in rs["sections"]:
            for row in sec.get("races") or []:
                hit, why = resolve_race(sec["id"], row.get("office"), on_date)
                if not hit:
                    if sec["id"] != "courts":
                        flagged.append({"data_key": rs["data_key"], "office": row.get("office"), "reason": why})
                    continue
                race, phase_key = hit
                seen.add(race["id"])
                cands, total = flatten_office(row)
                ballot = phase_candidates(race["phases"][phase_key], members)
                d = decide(cands, total, ballot)
                if d["kind"] == "winner":
                    c = d["candidate"]
                    winner = winner_record(c, phase_key)
                    if not winner:
                        flagged.append({"data_key": rs["data_key"], "raceId": race["id"], "office": row.get("office"),
                                        "reason": f"{c.get('name')} has no candidate id or member id to record"})
                        continue
                    proposals[race["id"]] = {
                        "raceId": race["id"], "phase": phase_key, "dataKey": rs["data_key"], "winner": winner,
                        "votes": d["votes"], "total": d["total"], "share": d["share"],
                    }
                    runoffs.pop(race["id"], None)
                elif d["kind"] == "runoff":
                    runoffs[race["id"]] = {"raceId": race["id"], "leader": d["leader"], "share": d["share"]}
                elif d["kind"] == "flag":
                    flagged.append({"data_key": rs["data_key"], "raceId": race["id"],
                                    "office": row.get("office"), "reason": d["reason"]})
        # a race on the ballot that day with a single candidate and no results row: walkover
        for race, phase_key in on_date:
            if race["id"] in seen or race["id"] in proposals or race.get("winner"):
                continue
            if race.get("chamber") not in HANDLED_CHAMBERS:
                unhandled.append(race["id"])  # judicial races: counted, not guessed at
                continue
            ballot = phase_candidates(race["phases"][phase_key], members)
            live = [c for c in ballot if not (c.get("withdrawn") or c.get("disqualified"))]
            if len(live) == 1 and live[0].get("id"):
                c = live[0]
                flagged.append({"data_key": rs["data_key"], "raceId": race["id"], "office": race.get("chamber"),
                                "reason": f"unopposed ({c.get('name')}) with no results row; confirm before recording"})
    return {"proposals": proposals, "flagged": flagged, "runoffs": runoffs, "skipped": skipped,
            "unhandled": sorted(set(unhandled))}


def winner_record(c: dict, phase_key: str) -> dict | None:
    """The `winner` object recorded on a race: the candidate id, or for an incumbent listed only
    by member id, that `memberId`. None if the candidate has neither (nothing to key the win on)."""
    rec = {"name": c.get("name")}
    if c.get("id"):
        rec["candidateId"] = c["id"]
    elif c.get("memberId"):
        rec["memberId"] = c["memberId"]
    else:
        return None
    rec.update({"party": c.get("party") or None, "phase": phase_key})
    return rec


def _winner_key(w: dict):
    return w.get("candidateId") or w.get("memberId")


def plan_changes(proposals: dict, races: list[dict]) -> tuple[list[dict], list[dict]]:
    """(changes, conflicts): what would be written to races.json, and what already disagrees."""
    by_id = {r["id"]: r for r in races}
    changes, conflicts = [], []
    for rid, p in proposals.items():
        race = by_id.get(rid)
        if not race:
            continue
        cur = race.get("winner") or {}
        if _winner_key(cur) and _winner_key(cur) != _winner_key(p["winner"]):
            conflicts.append({"raceId": rid, "recorded": cur.get("name"), "proposed": p["winner"]["name"]})
        elif _winner_key(cur) == _winner_key(p["winner"]) and race.get("status") == "certified":
            continue  # already recorded
        else:
            changes.append(p)
    return changes, conflicts


def apply_changes(doc: dict, changes: list[dict]) -> list[str]:
    """Record status+winner on each changed race in `doc` (in place); returns the race ids."""
    by_id = {r["id"]: r for r in doc.get("races", [])}
    done = []
    for p in changes:
        race = by_id[p["raceId"]]
        race["status"] = "certified"
        race["winner"] = dict(p["winner"])
        done.append(p["raceId"])
    return done


def parse_front_matter(text: str) -> dict:
    """The few scalar keys a results page carries, without a YAML dependency."""
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            km = re.match(r"^([A-Za-z_]+):\s*(.*?)\s*$", line)
            if km and km.group(2) not in (">-", ">", "|", ""):
                out[km.group(1)] = km.group(2).strip("\"'")
    return out
