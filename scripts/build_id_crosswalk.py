#!/usr/bin/env python3
"""Build assets/data/id-crosswalk.json — one record per Georgia officeholder or
candidate, carrying every identifier we hold for them and how each was arrived at.

Why this file exists
--------------------
VoteGA already joins the same person across five systems that share no key:
Open States (OCD person id), legis.ga.gov (numeric member id), Congress.gov
(bioguide), the FEC (candidate id), and the Georgia Ethics Commission's
PeachFile (filer entity id). Those joins were resolved somewhere in this repo
but never written down; the PeachFile one was recomputed from a name heuristic
on every page load, so nothing outside votega.org could reuse it and nothing
inside it could audit it. This script materialises them once, with provenance.

What is genuinely new here
--------------------------
The federal half is largely a re-publication: unitedstates/congress-legislators
(public domain) already maps bioguide to FEC, GovTrack and OpenSecrets. We carry
those so a consumer needs one file rather than two, credited in `provenance`.

The Georgia half has no upstream equivalent. Nothing published anywhere maps an
Open States person — or a 2026 candidate — to their PeachFile filing.

Identity: why the *filing* is the key for candidates
----------------------------------------------------
Officeholders key on an id their upstream owns (OCD person id, bioguide), so a
vgId minted against one is stable by construction.

Candidates have no such id. races.json candidate ids are **positional** — see
make_candidate_id() in build_legislative_races.py, which ends the id with a row
index into the Secretary of State export, and that script's own warning that a
re-ordered source makes `ga-house-15-2026-d-3` point at a different person
(CODEBASE-REVIEW-2026-08-18.md finding 5.2). Minting a permanent vgId from a row
index would silently reassign identity on any re-export. The Secretary of State
publishes no candidate id to fall back on.

So a candidate's ledger key is their **campaign filing** — a PeachFile filer
entity id or an FEC candidate id, both assigned by the regulator and stable.
A candidate with no filing gets **no vgId at all** rather than one derived from a
row index: a visible hole is safer than an id that quietly comes to mean someone
else. Those records still appear, with `vgId: null` and a reason.

This also dedupes for free. Three sitting statewide executives are on the 2026
governor's ballot; their candidate rows resolve to the same filing as their
officeholder record, so the candidacy attaches to the existing person instead of
creating a second one.

A person with two filings in one cycle (one per office sought — Georgia's 2026
ballot has such a case) is merged by an explicit `sameAs` in
id-crosswalk-overrides.json, never by guessing from names.

Usage:
    python scripts/build_id_crosswalk.py [output_path]
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from lib.ga_match import CHAMBER_TO_PEACHFILE, find_filers, member_scope, toks
from lib.atomic_io import write_json_atomic, atomic_write
from lib.ga_identity import (is_ocd_id, ledger_keys, executive_keys, SLOTS as IDENTITY_SLOTS, ambiguities,
                             pin_patch, apply_slot_pins, KIND_LABELS, out_of_scope)

SCHEMA_VERSION = 2

MEMBERS_FILE   = "assets/data/ga-members.json"
EXECUTIVE_FILE = "assets/data/ga-executive.json"
FEDERAL_FILE   = "assets/data/current-members.json"
FINANCE_FILE   = "assets/data/ga-campaign-finance.json"
FEC_FILE       = "assets/data/ga-fec-data.json"
RACES_FILE     = "assets/data/races.json"
OVERRIDES_FILE = "assets/data/ga-campaign-finance-overrides.json"
XWALK_OVERRIDES_FILE = "assets/data/id-crosswalk-overrides.json"
LEDGER_FILE    = "assets/data/id-crosswalk-ledger.json"

OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/id-crosswalk.json"

#: ga-members.json holds four statewide executives alongside the legislature.
VOTING_CHAMBERS = ("Senate", "House of Representatives")

GOVTRACK_RE = re.compile(r'/congress/members/(\d+)')
OPENSECRETS_RE = re.compile(r'/(?:members-of-congress/[^/]*/summary\?cid=|person/)?([NC]\d{8})', re.I)


def load(path, default=None):
    if not os.path.exists(path):
        if default is None:
            raise SystemExit(f"Error: required input {path} is missing")
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class Ledger:
    """Assigns and remembers vgIds, keyed on a durable upstream id.

    Keys are `legis:<legisGaGovId>` (state legislators), a LEGACY roster id
    (`ocd-person/...`, `legis-<id>`, or a synthetic `ga-senate-7-vacant`), a bioguide
    id, `peachfile:<filerEntityId>` or `fec:<candidateId>` — never a races.json
    candidate id, which is positional, and never an identifier SLOT such as a
    later-arriving ocdPersonId. Assignments are append-only: a member who leaves
    keeps theirs so historical references stay resolvable.
    """

    def __init__(self, path):
        self.path = path
        data = load(path, {"nextSeq": 1, "assign": {}})
        self.next_seq = data.get("nextSeq", 1)
        self.assign = dict(data.get("assign", {}))
        self._initial = dict(self.assign)

    def id_for(self, natural_key):
        if natural_key not in self.assign:
            self.assign[natural_key] = f"vg-ga-p-{self.next_seq:06d}"
            self.next_seq += 1
        return self.assign[natural_key]

    def id_for_any(self, keys):
        """vgId for a person known by several keys, in resolution order.

        The first key already in the ledger wins, so a member minted under the legacy
        roster id keeps it; a brand-new member is minted under the FIRST key
        (legisGaGovId-derived). Nothing is aliased or rewritten, which keeps every
        existing entry exactly as published.
        """
        for k in keys:
            if k in self.assign:
                return self.assign[k]
        return self.id_for(keys[0])

    def alias(self, key, vg_id):
        """Point an additional natural key at an already-assigned vgId (a merge)."""
        self.assign.setdefault(key, vg_id)
        return self.assign[key]

    @property
    def newly_assigned(self):
        return [k for k in self.assign if k not in self._initial]

    def save(self):
        payload = {
            "_comment": (
                "vgId assignments for assets/data/id-crosswalk.json. Append-only: an "
                "entry is never removed or renumbered, so a vgId published once always "
                "means the same person. Keys are durable ids — legis:<legisGaGovId> for "
                "state legislators (the primary key; resolved first), then the legacy "
                "roster id (ocd-person/..., legis-<id>) that entries were keyed on before "
                "that, a bioguide id for federal members, peachfile:<filerEntityId> or "
                "fec:<candidateId> for candidates. races.json candidate ids and identifier "
                "slots (ocdPersonId, ballotpediaId) are NEVER keys: the first is "
                "positional, the second arrives late and would mint a second vgId. "
                "Regenerated by scripts/build_id_crosswalk.py — do not hand-edit."
            ),
            "nextSeq": self.next_seq,
            "assign": dict(sorted(self.assign.items())),
        }
        with atomic_write(self.path) as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")


# ---------------------------------------------------------------------------
# races.json traversal
# ---------------------------------------------------------------------------

def walk_candidates(races):
    """Yield (race, phase_name, ballot_name, candidate) for every ballot line."""
    for race in races.get("races", []):
        for phase_name, phase in (race.get("phases") or {}).items():
            for ballot_name, ballot in (phase.get("ballots") or {}).items():
                for cand in ballot:
                    yield race, phase_name, ballot_name, cand


def collect_candidacies(races):
    """candidate id (or member id) -> a merged candidacy record.

    One person on a primary and a runoff ballot for the same seat is one
    candidacy with two phases, not two candidacies.
    """
    out = {}
    for race, phase_name, ballot_name, cand in walk_candidates(races):
        key = cand.get("id") or cand.get("existingMemberId") or cand.get("memberId")
        if not key:
            continue
        entry = out.setdefault(key, {
            "candidateId": cand.get("id"),
            "raceId": race.get("id"),
            "level": race.get("level"),
            "office": race.get("chamber"),
            "district": race.get("district"),
            "cycle": race.get("cycle"),
            "party": cand.get("party"),
            "phases": [],
            "isIncumbent": False,
            "withdrawn": False,
            "disqualified": False,
            "memberId": cand.get("existingMemberId") or cand.get("memberId"),
            "name": cand.get("name"),
        })
        if phase_name not in entry["phases"]:
            entry["phases"].append(phase_name)
        entry["isIncumbent"] = entry["isIncumbent"] or bool(cand.get("isIncumbent")) or cand.get("type") == "incumbent"
        entry["withdrawn"] = entry["withdrawn"] or bool(cand.get("withdrawn"))
        entry["disqualified"] = entry["disqualified"] or bool(cand.get("disqualified"))
        if not entry["name"]:
            entry["name"] = cand.get("name")
        # Take the member link from ANY ballot row that carries it, not just the
        # first one seen. Two 2026 candidates (ga-house-94-2026-d-5,
        # ga-house-130-2026-d-4) are linked on their general row but not on the
        # primary row they won, so reading only the first row made whether they
        # deduped onto their officeholder record depend on dict ordering.
        if not entry["memberId"]:
            entry["memberId"] = cand.get("existingMemberId") or cand.get("memberId")
        if cand.get("fecCandidateId"):
            entry["fecCandidateId"] = cand["fecCandidateId"]
    return out


def candidate_backrefs(candidacies):
    """member id -> [votega candidate ids]."""
    out = {}
    for c in candidacies.values():
        if c["memberId"] and c["candidateId"]:
            out.setdefault(c["memberId"], [])
            if c["candidateId"] not in out[c["memberId"]]:
                out[c["memberId"]].append(c["candidateId"])
    return out


def offices_sought(candidacies):
    """member id -> [(office, district)] for state races they are a candidate in.

    A committee is registered against the office *sought*, not the one held, and
    PeachFile files it that way — so this is the pool to search first.
    """
    out = {}
    for c in candidacies.values():
        if c["level"] not in ("state", "state-executive") or not c["memberId"]:
            continue
        scope = (c["office"], c["district"])
        out.setdefault(c["memberId"], [])
        if scope not in out[c["memberId"]]:
            out[c["memberId"]].append(scope)
    return out


# ---------------------------------------------------------------------------
# Filing resolution
# ---------------------------------------------------------------------------

def norm_scope(scope):
    """races.json and ga-members.json spell chambers differently; both map to one
    PeachFile pool, so compare normalised or every legislator looks like they are
    running for a different office than they hold."""
    chamber, district = scope
    return CHAMBER_TO_PEACHFILE.get(chamber, chamber), district


def resolve_member_filing(member, finance, overrides, xwalk_overrides, backrefs, sought):
    """(filerEntityId, provenance) for a ga-members.json row."""
    filers, by_seat = finance["filers"], finance["bySeat"]
    by_office = finance.get("byOffice", {})

    own = xwalk_overrides.get(member["id"]) or xwalk_overrides.get(member.get("ocdPersonId"))
    if own:
        if own.get("peachfileNoFiling"):
            return None, {"method": "reviewed", "confidence": "confirmed-none",
                          "source": XWALK_OVERRIDES_FILE}
        if own.get("peachfileFilerEntityId"):
            return own["peachfileFilerEntityId"], {
                "method": "reviewed", "confidence": "high",
                "source": XWALK_OVERRIDES_FILE, "note": own.get("_note")}

    for key in list(backrefs.get(member["id"], [])) + [member["id"]]:
        ov = overrides.get(key)
        if not ov:
            continue
        if ov.get("noFiling"):
            return None, {"method": "reviewed", "confidence": "confirmed-none",
                          "source": OVERRIDES_FILE, "key": key}
        if ov.get("filerEntityId"):
            return ov["filerEntityId"], {"method": "reviewed", "confidence": "high",
                                         "source": OVERRIDES_FILE, "key": key}

    held = member_scope(member)
    scopes = list(sought.get(member["id"], []))
    if held[0] is not None and norm_scope(held) not in [norm_scope(s) for s in scopes]:
        scopes.append(held)
    if not scopes:
        return None, {"method": "out-of-scope", "confidence": None,
                      "note": "no PeachFile office mapping for this chamber"}

    for chamber, district in scopes:
        if chamber is None:
            continue
        hits = find_filers(member["name"], chamber, district, filers, by_seat, by_office)
        if len(hits) == 1:
            prov = {"method": "seat+surname", "confidence": "high",
                    "source": "scripts/lib/ga_match.py"}
            if norm_scope((chamber, district)) != norm_scope(held):
                prov["scope"] = "office-sought"
                prov["note"] = f"matched against {chamber}, the office sought in this cycle"
            return hits[0], prov
        if len(hits) > 1:
            return None, {"method": "seat+surname", "confidence": "ambiguous",
                          "candidates": hits,
                          "note": "multiple filings match; resolve in " + OVERRIDES_FILE}
    return None, {"method": "seat+surname", "confidence": "no-match",
                  "note": "no filing matched this person's seat or the office they seek"}


def resolve_candidate_filing(cand, finance, overrides, fec):
    """(kind, id, provenance) for a candidacy with no member record.

    kind is "peachfile" or "fec". Mirrors findFecId()/findGaFilers() in
    assets/scripts/campaign-finance.js, which still serves the live pages.
    """
    cid = cand["candidateId"]
    ov = overrides.get(cid) or {}
    if ov.get("noFiling"):
        return None, None, {"method": "reviewed", "confidence": "confirmed-none",
                            "source": OVERRIDES_FILE, "key": cid}
    if ov.get("filerEntityId"):
        return "peachfile", ov["filerEntityId"], {
            "method": "reviewed", "confidence": "high", "source": OVERRIDES_FILE, "key": cid}

    if cand["level"] in ("state", "state-executive"):
        hits = find_filers(cand["name"], cand["office"], cand["district"],
                           finance["filers"], finance["bySeat"], finance.get("byOffice", {}))
        if len(hits) == 1:
            return "peachfile", hits[0], {"method": "seat+surname", "confidence": "high",
                                          "source": "scripts/lib/ga_match.py"}
        if len(hits) > 1:
            return None, None, {"method": "seat+surname", "confidence": "ambiguous",
                                "candidates": hits,
                                "note": "multiple filings match; resolve in " + OVERRIDES_FILE}
        return None, None, {"method": "seat+surname", "confidence": "no-match"}

    if cand["level"] == "federal":
        if cand.get("fecCandidateId"):
            return "fec", cand["fecCandidateId"], {"method": "curated", "source": RACES_FILE}
        norm = " ".join(toks(cand["name"] or ""))
        office = cand["office"] or ""
        # A normalized name can cover several filings (16 do), and the single-valued
        # byNormalizedName keeps only one — so trusting it was claiming "high" confidence
        # for a pick we did not make. Read the full list, narrow by the office sought, and
        # report ambiguity when more than one survives rather than guessing.
        name_hits = (fec.get("byNormalizedNameAll", {}).get(norm)
                     or ([fec["byNormalizedName"][norm]]
                         if norm in fec.get("byNormalizedName", {}) else []))
        if len(name_hits) > 1:
            want = "S" if "Senate" in office else "H"
            same = [c for c in name_hits
                    if (fec["candidates"].get(c, {}).get("office") or "") == want]
            if same:
                name_hits = same
        if len(name_hits) == 1:
            return "fec", name_hits[0], {"method": "name-exact", "confidence": "high",
                                         "source": "FEC candidate index"}
        if len(name_hits) > 1:
            return None, None, {"method": "name-exact", "confidence": "ambiguous",
                                "candidates": sorted(name_hits),
                                "note": "one normalized name, several FEC filings; "
                                        "resolve in " + OVERRIDES_FILE}
        key = "S" if "Senate" in office else f"H{cand['district']}"
        last = (toks(cand["name"] or "") or [""])[-1]
        pool = fec.get("byDistrict", {}).get(key, [])
        hits = [c for c in pool
                if toks(fec["candidates"][c].get("lastName"))[-1:] == [last]] if last else []
        if len(hits) == 1:
            return "fec", hits[0], {"method": "district+surname", "confidence": "high",
                                    "source": "FEC candidate index"}
        if len(hits) > 1:
            return None, None, {"method": "district+surname", "confidence": "ambiguous",
                                "candidates": hits}
        return None, None, {"method": "district+surname", "confidence": "no-match"}

    # Local races: Georgia municipal filings are not in PeachFile and there is no
    # federal equivalent, so there is nothing to key these on.
    return None, None, {"method": "out-of-scope", "confidence": None,
                        "note": "no campaign finance source covers GA local offices"}


# ---------------------------------------------------------------------------
# Record shapes
# ---------------------------------------------------------------------------

def external_ids(member):
    """GovTrack / OpenSecrets ids parsed out of externalLinks. Those come from
    unitedstates/congress-legislators, so we are just reading a published id
    back out of a URL."""
    ids = {"govtrackId": None, "openSecretsId": None}
    for link in member.get("externalLinks") or []:
        url = link.get("url") or ""
        m = GOVTRACK_RE.search(url)
        if m:
            ids["govtrackId"] = int(m.group(1))
        if "opensecrets.org" in url:
            m = OPENSECRETS_RE.search(url)
            if m:
                ids["openSecretsId"] = m.group(1).upper()
    return ids


def blank_ids():
    return {
        "rosterId": None, "executiveId": None, "ocdPersonId": None, "legisGaGovId": None,
        "ballotpediaId": None, "bioguideId": None,
        "govtrackId": None, "openSecretsId": None,
        "fecCandidateIds": [], "peachfileFilerEntityIds": [],
        "votegaCandidateIds": [],
    }


def candidacy_record(cand, kind, filing_id, prov):
    return {
        "raceId": cand["raceId"],
        "candidateId": cand["candidateId"],
        "cycle": cand["cycle"],
        "level": cand["level"],
        "office": cand["office"],
        "district": cand["district"],
        "party": cand["party"],
        "phases": cand["phases"],
        "isIncumbent": cand["isIncumbent"],
        "withdrawn": cand["withdrawn"],
        "disqualified": cand["disqualified"],
        "peachfileFilerEntityId": filing_id if kind == "peachfile" else None,
        "fecCandidateId": filing_id if kind == "fec" else None,
        "filingProvenance": prov,
    }


def fec_id_for_office(fec, fec_ids, office):
    """The one of a person's FEC filings that belongs to the office being contested.

    A person can hold an H and an S filing in the same cycle, so "their FEC id" is not
    well defined without an office — picking fec_ids[0] would attach a Senate candidacy
    to the House filing purely because 'H' sorts before 'S'.
    """
    if not fec_ids:
        return None
    if len(fec_ids) == 1:
        return fec_ids[0]
    want = "S" if "Senate" in (office or "") else "H"
    same = [c for c in fec_ids
            if ((fec.get("candidates", {}).get(c) or {}).get("office") or "") == want]
    return same[0] if len(same) == 1 else fec_ids[0]


def add_filing(person, kind, filing_id):
    key = "peachfileFilerEntityIds" if kind == "peachfile" else "fecCandidateIds"
    if filing_id and filing_id not in person["ids"][key]:
        person["ids"][key].append(filing_id)


# ---------------------------------------------------------------------------

def executive_member(official, roster_exec):
    """A roster-shaped dict for one ga-executive.json official, so the officeholder loop and
    the filing matcher treat executives like every other officeholder.

    An official with a `legacyRosterId` that still has a roster row keeps that row's fields
    (name, slots, title), so nothing published for the four original executives changes. The
    rest are built from the executive file; their `title` is not an OFFICE_MAP key, so
    ga_match scopes them to no office and they resolve to no filer - finance matching for
    them is deliberately not switched on here.
    """
    base = dict(roster_exec.get(official.get("legacyRosterId")) or {})
    if not base:
        base = {"id": official.get("legacyRosterId") or official["id"], "name": official["name"],
                "firstName": official.get("firstName"), "lastName": official.get("lastName"),
                "party": official.get("party"), "chamber": "executive", "district": None,
                "status": None, "title": official["title"]}
        # The identity slots the roster row used to carry. Only values the official file
        # holds are published; every other slot is "out-of-scope" (no legisGaGovId as a
        # MEMBER), the same wording the roster producer used.
        prov = dict(official.get("idProvenance") or {})
        for slot in IDENTITY_SLOTS:
            base[slot] = official.get(slot)
            prov.setdefault(slot, out_of_scope())
        base["idProvenance"] = prov
    if base.get("legisGaGovId") is None and official.get("legisGaGovId") is not None:
        base["legisGaGovId"] = official["legisGaGovId"]
        base["_legisIdFromExecutiveFile"] = True
    return base


def officeholder_inputs(members, executives):
    """[(roster-shaped member, ga-executive.json official or None)] in output order.

    Legislators come from the roster. Statewide executives come from ga-executive.json; a
    roster row with chamber "executive" that no official claims via `legacyRosterId` stops
    the build rather than silently dropping a person who already holds a published vgId.
    """
    roster_exec = {m["id"]: m for m in members if m.get("chamber") == "executive"}
    claimed = {o["legacyRosterId"] for o in executives if o.get("legacyRosterId")}
    orphans = sorted(set(roster_exec) - claimed)
    if orphans:
        raise SystemExit("Error: ga-members.json has executive row(s) no ga-executive.json "
                         f"entry claims via legacyRosterId: {orphans}")
    ids = [o.get("id") for o in executives]
    if None in ids or len(set(ids)) != len(ids):
        raise SystemExit("Error: every ga-executive.json official needs a unique `id`")
    out = [(m, None) for m in members if m.get("chamber") != "executive"]
    out += [(executive_member(o, roster_exec), o) for o in executives]
    return out


def main():
    members   = load(MEMBERS_FILE)["members"]
    federal   = load(FEDERAL_FILE)["members"]
    finance   = load(FINANCE_FILE)
    fec       = load(FEC_FILE)
    races     = load(RACES_FILE)
    overrides = {k: v for k, v in load(OVERRIDES_FILE, {}).items() if not k.startswith("_")}
    xwalk_overrides = {k: v for k, v in load(XWALK_OVERRIDES_FILE, {}).items()
                       if not k.startswith("_")}

    officeholders_in = officeholder_inputs(members, load(EXECUTIVE_FILE)["officials"])

    ledger      = Ledger(LEDGER_FILE)
    candidacies = collect_candidacies(races)
    backrefs    = candidate_backrefs(candidacies)
    sought      = offices_sought(candidacies)

    people = {}          # vgId -> record
    unkeyed = []         # records with no durable id, emitted with vgId None
    filing_owner = {}    # "peachfile:x" / "fec:x" -> vgId

    # --- Officeholders -------------------------------------------------------
    for m, exec_official in officeholders_in:
        # Primary key is legisGaGovId; the roster id is an opaque handle (the legacy ledger
        # key). `ocdPersonId` is a SLOT, only ever OCD-shaped or null. A statewide executive
        # is keyed by its ga-executive.json entry (see executive_keys).
        if exec_official:
            keys = executive_keys(exec_official.get("legacyRosterId"), m.get("legisGaGovId"),
                                  exec_official["id"])
        else:
            keys = ledger_keys(m.get("legisGaGovId"), m["id"])
        vg = ledger.id_for_any(keys)
        if exec_official:                   # every key an executive answers to lands on one vgId
            for k in keys:
                ledger.alias(k, vg)
        filer, prov = resolve_member_filing(m, finance, overrides, xwalk_overrides,
                                            backrefs, sought)
        ids = blank_ids()
        ids["rosterId"] = exec_official.get("legacyRosterId") if exec_official else m["id"]
        ids["executiveId"] = exec_official["id"] if exec_official else None
        ids["legisGaGovId"] = m.get("legisGaGovId")
        slot_prov = m.get("idProvenance") or {}
        for slot in IDENTITY_SLOTS:
            ids[slot] = m.get(slot)
        if ids["ocdPersonId"] is not None and not is_ocd_id(ids["ocdPersonId"]):
            raise SystemExit(f"Error: {m['name']} has ocdPersonId {ids['ocdPersonId']!r}, "
                             f"which is not an OCD person id. Refusing to publish it.")
        ids["votegaCandidateIds"] = backrefs.get(m["id"], [])
        if filer:
            ids["peachfileFilerEntityIds"] = [filer]
            filing_owner[f"peachfile:{filer}"] = vg

        provenance = {"peachfileFilerEntityIds": prov}
        for slot in IDENTITY_SLOTS:
            if slot_prov.get(slot):
                provenance[slot] = slot_prov[slot]
        # Human-reviewed slot pins (e.g. one of several Ballotpedia slugs). Applied here as
        # well as in the roster producer so a pin lands on the next crosswalk build rather
        # than waiting for the roster to regenerate. Slots are never ledger keys: no vgId moves.
        try:
            pins, pin_note = pin_patch(xwalk_overrides, m["id"], m.get("ocdPersonId"))
        except ValueError as e:
            raise SystemExit(f"Error: bad pinSlots override: {e}")
        apply_slot_pins(ids, provenance, pins, pin_note)
        if ids["legisGaGovId"] is not None:
            if (exec_official and m.get("_legisIdFromExecutiveFile")
                    and exec_official.get("legisGaGovIdBasis") != "members-service"):
                provenance["legisGaGovId"] = {
                    "method": "curated", "confidence": "unreviewed",
                    "source": EXECUTIVE_FILE, "note": exec_official.get("legisGaGovIdNote")}
            else:
                provenance["legisGaGovId"] = {
                    "method": "authoritative",
                    "source": "legis.ga.gov (General Assembly web services, Members)"}

        people[vg] = {
            "vgId": vg,
            "name": {"full": m.get("name"), "first": m.get("firstName"), "last": m.get("lastName")},
            "role": {
                "level": "state",
                "office": "legislator" if m.get("chamber") in VOTING_CHAMBERS else "statewide-executive",
                "chamber": m.get("chamber"), "district": m.get("district"),
                "party": m.get("party"), "status": m.get("status"),
                **({"title": exec_official["title"]} if exec_official else {}),
            },
            "ids": ids, "candidacies": [], "provenance": provenance,
        }

    for m in [x for x in federal if x.get("state") == "Georgia"]:
        vg = ledger.id_for(m["bioguideId"])
        terms = (m.get("terms") or {}).get("item") or []
        # Every FEC filing this person holds, not just the one byBioguideId publishes.
        # A House member running for Senate has two live candidate ids in the cycle, and
        # recording only one both understates `fecCandidateIds` (documented as a list) and
        # leaves the other id unowned — so a candidate record that resolved to the *other*
        # id would miss the merge in filing_owner and mint a second vgId for one person.
        fec_ids = fec.get("byBioguideIdAll", {}).get(m["bioguideId"])
        if not fec_ids:
            one = fec.get("byBioguideId", {}).get(m["bioguideId"])
            fec_ids = [one] if one else []
        ext = external_ids(m)

        ids = blank_ids()
        ids["bioguideId"] = m["bioguideId"]
        ids["govtrackId"] = ext["govtrackId"]
        ids["openSecretsId"] = ext["openSecretsId"]
        ids["votegaCandidateIds"] = backrefs.get(m["bioguideId"], [])
        if fec_ids:
            ids["fecCandidateIds"] = sorted(fec_ids)
            for fid in fec_ids:
                filing_owner[f"fec:{fid}"] = vg

        provenance = {"bioguideId": {"method": "authoritative", "source": "Congress.gov"}}
        try:
            pins, pin_note = pin_patch(xwalk_overrides, m["bioguideId"])
        except ValueError as e:
            raise SystemExit(f"Error: bad pinSlots override: {e}")
        apply_slot_pins(ids, provenance, pins, pin_note)
        us = "unitedstates/congress-legislators (public domain)"
        if fec_ids:
            provenance["fecCandidateIds"] = {"method": "authoritative", "source": us}
        for k in ("govtrackId", "openSecretsId"):
            if ids[k] is not None:
                provenance[k] = {"method": "authoritative", "source": us}

        people[vg] = {
            "vgId": vg,
            "name": {"full": m.get("name"), "first": m.get("firstName"), "last": m.get("lastName")},
            "role": {"level": "federal", "office": "legislator",
                     "chamber": terms[-1].get("chamber") if terms else None,
                     "district": m.get("district"), "party": m.get("partyName"), "status": None},
            "ids": ids, "candidacies": [], "provenance": provenance,
        }

    # --- Candidates ----------------------------------------------------------
    # Officeholders first, above, so a candidacy whose filing already belongs to
    # one attaches to that person instead of creating a duplicate.
    same_as = {k: v["sameAs"] for k, v in xwalk_overrides.items() if v.get("sameAs")}

    for key, cand in sorted(candidacies.items()):
        if cand["memberId"]:                      # already an officeholder record
            owner = None
            for vg, p in people.items():
                if cand["memberId"] in (p["ids"]["rosterId"], p["ids"]["ocdPersonId"],
                                        p["ids"]["bioguideId"]):
                    owner = vg
                    break
            if owner:
                prov = people[owner]["provenance"].get("peachfileFilerEntityIds") or {}
                filer = (people[owner]["ids"]["peachfileFilerEntityIds"] or [None])[0]
                fecid = fec_id_for_office(fec, people[owner]["ids"]["fecCandidateIds"],
                                          cand["office"])
                kind = "peachfile" if filer else ("fec" if fecid else None)
                people[owner]["candidacies"].append(
                    candidacy_record(cand, kind, filer or fecid, prov))
            continue

        kind, filing_id, prov = resolve_candidate_filing(cand, finance, overrides, fec)

        if not filing_id:
            rec = {
                "vgId": None,
                "name": {"full": cand["name"], "first": None, "last": None},
                "role": None,
                "ids": blank_ids(),
                "candidacies": [candidacy_record(cand, None, None, prov)],
                "provenance": {"vgId": {
                    "method": "unkeyed",
                    "note": ("no campaign filing to key on, and races.json candidate ids are "
                             "positional row indices — see this script's header"),
                }},
            }
            rec["ids"]["votegaCandidateIds"] = [cand["candidateId"]] if cand["candidateId"] else []
            unkeyed.append(rec)
            continue

        natural = f"{kind}:{filing_id}"
        natural = same_as.get(natural, natural)   # explicit merge, never inferred

        if natural in filing_owner:
            vg = filing_owner[natural]
        else:
            vg = ledger.id_for(natural)
            filing_owner[natural] = vg
        # A merged key must resolve to the same vgId however it was reached.
        ledger.alias(f"{kind}:{filing_id}", vg)
        filing_owner[f"{kind}:{filing_id}"] = vg

        person = people.get(vg)
        if person is None:
            person = {
                "vgId": vg,
                "name": {"full": cand["name"], "first": None, "last": None},
                "role": None,
                "ids": blank_ids(),
                "candidacies": [],
                "provenance": {},
            }
            people[vg] = person
        add_filing(person, kind, filing_id)
        person["provenance"].setdefault(
            "peachfileFilerEntityIds" if kind == "peachfile" else "fecCandidateIds", prov)
        if cand["candidateId"] and cand["candidateId"] not in person["ids"]["votegaCandidateIds"]:
            person["ids"]["votegaCandidateIds"].append(cand["candidateId"])
        person["candidacies"].append(candidacy_record(cand, kind, filing_id, prov))

    records = sorted(people.values(), key=lambda r: r["vgId"])
    records += sorted(unkeyed, key=lambda r: (r["name"]["full"] or "", r["candidacies"][0]["raceId"]))

    # --- Metadata ------------------------------------------------------------
    def count(pred):
        return sum(1 for r in records if pred(r))

    officeholders = [r for r in records if r["role"]]
    cand_only = [r for r in records if not r["role"]]
    ambiguous = [r["vgId"] or r["name"]["full"] for r in records
                 for p in r["provenance"].values()
                 if isinstance(p, dict) and p.get("confidence") == "ambiguous"]

    payload = {
        "metadata": {
            "schemaVersion": SCHEMA_VERSION,
            "schemaStability": (
                "Stable field names and meanings. Additive since version 2: rosterId, "
                "executiveId (statewide executives, from ga-executive.json) "
                "and ballotpediaId; ocdPersonId is now ONLY an OCD person id "
                "or null (it used to carry the roster id, which can be legis-<id>). "
                "Changed in version 2: "
                "peachfileFilerEntityId and fecCandidateId became the lists "
                "peachfileFilerEntityIds / fecCandidateIds, because a person who files "
                "for two offices in one cycle has one filing per office; and a "
                "candidacies[] array was added. Records may carry vgId: null — see "
                "provenance.vgId for why."
            ),
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(records),
            "scope": ("Georgia officeholders and 2026 ballot candidates: state legislators, "
                      "statewide executives, the Georgia federal delegation, and every "
                      "candidate on a race in races.json."),
            "sources": [
                "legis.ga.gov (General Assembly web services) — legisGaGovId, the primary key for state legislators",
                "openstates/people (CC0 1.0) — ocdPersonId, ballotpediaId (cross-references, resolved on legisGaGovId)",
                "Congress.gov — bioguideId",
                "unitedstates/congress-legislators (public domain) — fecCandidateIds, govtrackId, openSecretsId",
                "Georgia Ethics Commission PeachFile — peachfileFilerEntityIds (derived, see provenance)",
                "votega.org races.json — candidacies, votegaCandidateIds",
            ],
            "provenanceMethods": {
                "authoritative": "the upstream source publishes this id for this person directly",
                "reviewed": "a human confirmed this match; recorded in an overrides file",
                "curated": "hand-entered in this repo's own data",
                "seat+surname": "derived by scripts/lib/ga_match.py — scoped to the seat, surname required",
                "name-exact": "exact match against the FEC candidate name index",
                "district+surname": "FEC candidates in the district, matched on surname",
                "unkeyed": "no durable upstream id exists for this person; vgId is null",
                "out-of-scope": "this identifier does not apply to this person",
                "unresolved": "no lookup has populated this identifier yet; a null here is NOT a claim that none exists",
            },
            "coverage": {
                "people": len(records),
                "officeholders": len(officeholders),
                "candidateOnly": len(cand_only),
                "withVgId": count(lambda r: r["vgId"] is not None),
                "unkeyed": count(lambda r: r["vgId"] is None),
                "withAnyFiling": count(lambda r: r["ids"]["peachfileFilerEntityIds"]
                                       or r["ids"]["fecCandidateIds"]),
                "candidacies": sum(len(r["candidacies"]) for r in records),
                "ambiguous": ambiguous,
            },
        },
        "people": records,
    }

    with atomic_write(OUTPUT_FILE) as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    ledger.save()

    cov = payload["metadata"]["coverage"]
    print(f"Wrote {OUTPUT_FILE}: {cov['people']} people "
          f"({cov['officeholders']} officeholders, {cov['candidateOnly']} candidate-only)")
    print(f"  with a stable vgId : {cov['withVgId']}")
    print(f"  unkeyed (no filing): {cov['unkeyed']}")
    print(f"  candidacies        : {cov['candidacies']}")
    for field, rows in sorted(ambiguities(records).items()):
        print(f"  AMBIGUOUS {KIND_LABELS.get(field, field)} matches left unresolved: {len(rows)}")
    if ledger.newly_assigned:
        print(f"  newly minted vgIds : {len(ledger.newly_assigned)}")


if __name__ == "__main__":
    main()
