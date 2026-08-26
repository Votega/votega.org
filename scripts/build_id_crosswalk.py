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

SCHEMA_VERSION = 2

MEMBERS_FILE   = "assets/data/ga-members.json"
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

    Keys are `ocd-person/...`, a bioguide id, `peachfile:<filerEntityId>` or
    `fec:<candidateId>` — never a races.json candidate id, which is positional.
    Assignments are append-only: a member who leaves keeps theirs so historical
    references stay resolvable.
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
                "means the same person. Keys are durable upstream ids — ocd-person/... "
                "or a bioguide id for officeholders, peachfile:<filerEntityId> or "
                "fec:<candidateId> for candidates. races.json candidate ids are NEVER "
                "keys: they are positional row indices and shift between exports. "
                "Regenerated by scripts/build_id_crosswalk.py — do not hand-edit."
            ),
            "nextSeq": self.next_seq,
            "assign": dict(sorted(self.assign.items())),
        }
        with open(self.path, "w", encoding="utf-8") as f:
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

    own = xwalk_overrides.get(member["id"])
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
        by_name = fec.get("byNormalizedName", {})
        if norm in by_name:
            return "fec", by_name[norm], {"method": "name-exact", "confidence": "high",
                                          "source": "FEC candidate index"}
        office = cand["office"] or ""
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
        "ocdPersonId": None, "legisGaGovId": None, "bioguideId": None,
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


def add_filing(person, kind, filing_id):
    key = "peachfileFilerEntityIds" if kind == "peachfile" else "fecCandidateIds"
    if filing_id and filing_id not in person["ids"][key]:
        person["ids"][key].append(filing_id)


# ---------------------------------------------------------------------------

def main():
    members   = load(MEMBERS_FILE)["members"]
    federal   = load(FEDERAL_FILE)["members"]
    finance   = load(FINANCE_FILE)
    fec       = load(FEC_FILE)
    races     = load(RACES_FILE)
    overrides = {k: v for k, v in load(OVERRIDES_FILE, {}).items() if not k.startswith("_")}
    xwalk_overrides = {k: v for k, v in load(XWALK_OVERRIDES_FILE, {}).items()
                       if not k.startswith("_")}

    ledger      = Ledger(LEDGER_FILE)
    candidacies = collect_candidacies(races)
    backrefs    = candidate_backrefs(candidacies)
    sought      = offices_sought(candidacies)

    people = {}          # vgId -> record
    unkeyed = []         # records with no durable id, emitted with vgId None
    filing_owner = {}    # "peachfile:x" / "fec:x" -> vgId

    # --- Officeholders -------------------------------------------------------
    for m in members:
        vg = ledger.id_for(m["id"])
        filer, prov = resolve_member_filing(m, finance, overrides, xwalk_overrides,
                                            backrefs, sought)
        ids = blank_ids()
        ids["ocdPersonId"] = m["id"]
        ids["legisGaGovId"] = m.get("legisGaGovId")
        ids["votegaCandidateIds"] = backrefs.get(m["id"], [])
        if filer:
            ids["peachfileFilerEntityIds"] = [filer]
            filing_owner[f"peachfile:{filer}"] = vg

        provenance = {"ocdPersonId": {"method": "authoritative", "source": "Open States"},
                      "peachfileFilerEntityIds": prov}
        if ids["legisGaGovId"] is not None:
            provenance["legisGaGovId"] = {"method": "authoritative", "source": "Open States"}

        people[vg] = {
            "vgId": vg,
            "name": {"full": m.get("name"), "first": m.get("firstName"), "last": m.get("lastName")},
            "role": {
                "level": "state",
                "office": "legislator" if m.get("chamber") in VOTING_CHAMBERS else "statewide-executive",
                "chamber": m.get("chamber"), "district": m.get("district"),
                "party": m.get("party"), "status": m.get("status"),
            },
            "ids": ids, "candidacies": [], "provenance": provenance,
        }

    for m in [x for x in federal if x.get("state") == "Georgia"]:
        vg = ledger.id_for(m["bioguideId"])
        terms = (m.get("terms") or {}).get("item") or []
        fec_id = fec.get("byBioguideId", {}).get(m["bioguideId"])
        ext = external_ids(m)

        ids = blank_ids()
        ids["bioguideId"] = m["bioguideId"]
        ids["govtrackId"] = ext["govtrackId"]
        ids["openSecretsId"] = ext["openSecretsId"]
        ids["votegaCandidateIds"] = backrefs.get(m["bioguideId"], [])
        if fec_id:
            ids["fecCandidateIds"] = [fec_id]
            filing_owner[f"fec:{fec_id}"] = vg

        provenance = {"bioguideId": {"method": "authoritative", "source": "Congress.gov"}}
        us = "unitedstates/congress-legislators (public domain)"
        if fec_id:
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
                if cand["memberId"] in (p["ids"]["ocdPersonId"], p["ids"]["bioguideId"]):
                    owner = vg
                    break
            if owner:
                prov = people[owner]["provenance"].get("peachfileFilerEntityIds") or {}
                filer = (people[owner]["ids"]["peachfileFilerEntityIds"] or [None])[0]
                fecid = (people[owner]["ids"]["fecCandidateIds"] or [None])[0]
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
                "Stable field names and meanings. Changed in version 2: "
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
                "Open States (Plural Policy) — ocdPersonId, legisGaGovId",
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

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    ledger.save()

    cov = payload["metadata"]["coverage"]
    print(f"Wrote {OUTPUT_FILE}: {cov['people']} people "
          f"({cov['officeholders']} officeholders, {cov['candidateOnly']} candidate-only)")
    print(f"  with a stable vgId : {cov['withVgId']}")
    print(f"  unkeyed (no filing): {cov['unkeyed']}")
    print(f"  candidacies        : {cov['candidacies']}")
    if ambiguous:
        print(f"  AMBIGUOUS filings left unresolved: {len(ambiguous)}")
    if ledger.newly_assigned:
        print(f"  newly minted vgIds : {len(ledger.newly_assigned)}")


if __name__ == "__main__":
    main()
