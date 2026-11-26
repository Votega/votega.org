"""Race and candidate index files for the VoteGA MCP server (spec §5.1, §5.5). Pure, stdlib only.

  races-index.json       one row per race in races.json; `candidates` is the current ballot
  candidates-index.json  one row per candidate who appears in any phase of any race

A candidate's `key` is the races.json candidate id, or `us:<bioguideId>` / `ga:<legisGaGovId>` for
an incumbent the file lists only by member id. The candidate id is for lookup only (it is
positional); identity across roles is `vgId`. A roster id never appears.

Who is on a ballot and where a candidate stands come from lib/candidate_standing.py, the same
rules the candidate pages use.
"""
from lib.candidate_standing import (active_candidates, all_candidate_ids, all_member_ids, overall,
                                    standing)
from lib.mcp_index import KEY_RE, absolute, blank, vgid_lookup

RACES_MEANING = (
    "`candidates` lists the current ballot of the active phase (`ballotPhase`) as keys into "
    "candidates-index.json. A winner is recorded only for results VoteGA has marked; `status` "
    "'certified' means official.")
CANDIDATES_MEANING = (
    "standing: live (on the current ballot), off-ballot, lost or won (the last two only after a "
    "certified result). `id` is a lookup handle that is not stable identity; use vgId.")


def _entries(race):
    """Every candidate entry in a race, ballot entries tagged with their party."""
    for phase in (race.get("phases") or {}).values():
        if not isinstance(phase, dict):
            continue
        for party, ballot in (phase.get("ballots") or {}).items():
            for c in ballot or []:
                yield {**c, "party": c.get("party") or party}
        for c in phase.get("candidates") or []:
            yield c


def _member_id(c):
    return c.get("existingMemberId") or c.get("memberId")


class _Roster:
    def __init__(self, ga, federal, frozen):
        self.federal = {m["bioguideId"]: m for m in federal.get("members") or [] if m.get("bioguideId")}
        self.state = {}
        for tag in sorted(frozen):  # older first, so newer records (then the live ones) win
            self.state.update({m["id"]: m for m in frozen[tag].values() if m.get("id")})
        self.state.update({m["id"]: m for m in ga.get("members") or [] if m.get("id")})

    def find(self, c):
        """-> (member key or None, roster record or None, 'congress'/'state')."""
        mid = _member_id(c)
        if not mid:
            return None, None, None
        source = c.get("memberSource") or c.get("existingMemberSource") or "congress"
        if source == "congress":
            key = f"us:{mid}"
            return (key if KEY_RE.match(key) else None), self.federal.get(mid), source
        m = self.state.get(mid)
        gid = (m or {}).get("legisGaGovId")
        return (f"ga:{gid}" if gid is not None else None), m, source

    def with_name(self, c):
        """Fill name and party for an entry that carries only a member id (the pages' rule)."""
        if (c.get("name") or "").strip():
            return c
        _, m, source = self.find(c)
        if not m:
            return c
        if source == "congress":
            name = " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x) or m.get("name")
        else:
            name = m.get("name")
        if not name:
            return c
        out = {**c, "name": name}
        if not out.get("party"):
            out["party"] = m.get("partyName") or m.get("party")
        return out


def _key(c, roster):
    return c.get("id") or roster.find(c)[0]


def _standing(race, c, roster):
    """The site's standing rule. A winner recorded by member id matches the entry carrying it."""
    _, active = active_candidates(race, roster.with_name)
    winner = race.get("winner") or {}
    mid = _member_id(c)
    if mid and not winner.get("candidateId") and winner.get("memberId") == mid:
        me = mid
    else:
        me = c.get("id") or roster.with_name(c).get("name")
    return standing(race, active, me, all_candidate_ids(race), all_member_ids(race))


def build_elections(races_doc, ga, federal, frozen, crosswalk, entity_urls, generated_at):
    """-> {"races-index.json": ..., "candidates-index.json": ...}."""
    roster = _Roster(ga, federal, frozen)
    by_gid, by_bio = vgid_lookup(crosswalk)
    merged = (crosswalk.get("metadata") or {}).get("mergedVgIds") or {}
    by_candidate = {}
    for p in crosswalk.get("people") or []:
        vg = p.get("vgId")
        if vg:
            for cid in (p.get("ids") or {}).get("votegaCandidateIds") or []:
                by_candidate.setdefault(cid, merged.get(vg, vg))

    people, states, race_rows = {}, {}, []
    for race in races_doc.get("races") or []:
        rid = race["id"]
        keys_by_mid = {}
        for raw in _entries(race):
            key = _key(raw, roster)
            if key is None:
                continue
            c = roster.with_name(raw)
            member_key, member, source = roster.find(raw)
            mid = _member_id(raw)
            if mid:
                keys_by_mid.setdefault(mid, key)
            row = people.get(key)
            if row is None:
                row = people[key] = {
                    "key": key, "id": raw.get("id"), "memberKey": None, "vgId": None, "name": None,
                    "party": None, "isIncumbent": False, "occupation": None, "county": None,
                    "website": None, "withdrawn": False, "disqualified": False, "standing": None,
                    "raceIds": [], "votegaUrl": None}
            for field in ("name", "party", "occupation", "county", "website"):
                row[field] = row[field] or blank(c.get(field))
            row["memberKey"] = row["memberKey"] or member_key
            row["isIncumbent"] = row["isIncumbent"] or bool(c.get("isIncumbent")
                                                            or c.get("type") == "incumbent")
            row["withdrawn"] = row["withdrawn"] or bool(c.get("withdrawn"))
            row["disqualified"] = row["disqualified"] or bool(c.get("disqualified"))
            kind, _, number = (member_key or "").partition(":")
            row["vgId"] = row["vgId"] or by_candidate.get(raw.get("id")) or (
                by_bio.get(number) if kind == "us" else by_gid.get(number))
            urls = entity_urls.get("candidate") or {}
            page = urls.get(raw.get("id") or mid)
            if not page and source == "congress":
                page = (entity_urls.get("us-congress") or {}).get(mid)
            if not page and member:
                page = member.get("votegaUrl")
            row["votegaUrl"] = row["votegaUrl"] or absolute(page)
            if rid not in row["raceIds"]:
                row["raceIds"].append(rid)
                states.setdefault(key, []).append(_standing(race, raw, roster))

        ballot_phase, active = active_candidates(race, roster.with_name)
        dates = {name: blank(ph.get("electionDate"))
                 for name, ph in (race.get("phases") or {}).items() if isinstance(ph, dict)}
        winner = race.get("winner")
        if winner:
            # a candidateId matching nobody in the race is ignored, as the candidate pages do
            cid = winner.get("candidateId")
            key = (cid if cid in all_candidate_ids(race) else None) if cid \
                else keys_by_mid.get(winner.get("memberId"))
            winner = {
                "key": key,
                "name": blank(winner.get("name")), "party": blank(winner.get("party")),
                "phase": blank(winner.get("phase"))}
        race_rows.append({
            "id": rid, "level": race.get("level"), "office": race.get("chamber"),
            "title": blank(race.get("displayTitle")), "district": race.get("district"),
            "circuit": blank(race.get("circuit")), "seat": blank(race.get("seat")),
            "cycle": race.get("cycle"), "activePhase": blank(race.get("activePhase")),
            "electionDate": dates.get(race.get("activePhase")), "phaseDates": dates,
            "status": blank(race.get("status")), "winner": winner or None,
            "ballotPhase": ballot_phase,
            "candidates": [k for k in (_key(c, roster) for c in active) if k],
            "votegaUrl": absolute((entity_urls.get("race") or {}).get(rid)),
        })

    for key, row in people.items():
        row["standing"] = overall(states.get(key) or [])
    stamp = blank(races_doc.get("updatedAt"))
    candidates = [people[k] for k in sorted(people)]
    return {
        "races-index.json": {
            "metadata": {"generatedAt": generated_at, "count": len(race_rows),
                         "sourceGeneratedAt": stamp, "meaning": RACES_MEANING},
            "races": sorted(race_rows, key=lambda r: r["id"])},
        "candidates-index.json": {
            "metadata": {"generatedAt": generated_at, "count": len(candidates),
                         "sourceGeneratedAt": stamp, "meaning": CANDIDATES_MEANING},
            "candidates": candidates},
    }


def election_errors(docs, races_doc):
    races = docs.get("races-index.json")
    cands = docs.get("candidates-index.json")
    if races is None or cands is None:
        return [f"{name} is missing" for name, d in
                (("races-index.json", races), ("candidates-index.json", cands)) if d is None]
    errs = []
    rrows, crows = races.get("races") or [], cands.get("candidates") or []
    for name, doc, rows in (("races-index.json", races, rrows), ("candidates-index.json", cands, crows)):
        if doc["metadata"].get("count") != len(rows):
            errs.append(f"{name}: metadata.count != number of rows")
    keys = [c.get("key") for c in crows]
    if len(keys) != len(set(keys)):
        errs.append("candidates-index.json: a key appears twice")
    race_ids = [r.get("id") for r in rrows]
    source = [r["id"] for r in races_doc.get("races") or []]
    if sorted(race_ids) != sorted(source):
        errs.append(f"races differ from races.json (missing {sorted(set(source) - set(race_ids))[:5]})")
    want = {c["id"] for r in races_doc.get("races") or [] for c in _entries(r) if c.get("id")}
    have = {c.get("id") for c in crows if c.get("id")}
    if want != have:
        errs.append(f"candidates differ from races.json (missing {sorted(want - have)[:5]}, "
                    f"extra {sorted(have - want)[:5]})")
    for r in rrows:
        refs = list(r.get("candidates") or [])
        if (r.get("winner") or {}).get("key"):
            refs.append(r["winner"]["key"])
        unknown = [k for k in refs if k not in set(keys)]
        if unknown:
            errs.append(f"race {r.get('id')}: no candidate row for {unknown[:5]}")
    for c in crows:
        if c.get("memberKey") is not None and not KEY_RE.match(c["memberKey"]):
            errs.append(f"candidate {c.get('key')}: memberKey {c['memberKey']!r} is not ga:/us:")
        if not c.get("id") and not KEY_RE.match(c.get("key") or ""):
            errs.append(f"candidate {c.get('key')!r}: key is neither a candidate id nor a member key")
        if set(c.get("raceIds") or []) - set(race_ids):
            errs.append(f"candidate {c.get('key')}: names a race that is not in the index")
    return errs
