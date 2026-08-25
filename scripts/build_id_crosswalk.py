#!/usr/bin/env python3
"""Build assets/data/id-crosswalk.json — one record per Georgia officeholder,
carrying every identifier we hold for them and how each one was arrived at.

Why this file exists
--------------------
VoteGA already joins the same person across five systems that share no key:
Open States (OCD person id), legis.ga.gov (numeric member id), Congress.gov
(bioguide), the FEC (candidate id), and the Georgia Ethics Commission's
PeachFile (filer entity id). Four of those joins are resolved somewhere in this
repo; none of them are *written down*. The PeachFile join in particular is
recomputed from a name heuristic on every page load in the browser, so nothing
outside votega.org can reuse it and nothing inside it can audit it.

This script materialises those joins once, at build time, with provenance.

What is genuinely new here
--------------------------
The federal half is mostly a re-publication: unitedstates/congress-legislators
(public domain) already maps bioguide to FEC, GovTrack and OpenSecrets, and
generate_current_members_data.py already pulls it. We carry those ids so a
consumer needs one file rather than two, and credit the source in `provenance`.

The Georgia half has no upstream equivalent. Nothing published anywhere maps an
Open States person to their PeachFile filing — that mapping only exists as this
repo's heuristic plus 52 hand-reviewed overrides, and this is the first time it
is emitted as data.

Scope (v1): officeholders only — the 249 rows of ga-members.json (245 sitting
legislators plus the four statewide executives that share the file) and
Georgia's federal delegation. Non-incumbent candidates are out of scope; they
get a back-reference from the officeholders they face via `votegaCandidateIds`,
but have no record of their own. See "Phase 2" at the bottom.

Identity
--------
`vgId` is opaque and minted once, then held in a committed ledger keyed on the
person's most durable upstream id. A legislator who moves chamber, changes name,
or loses their Open States record keeps the same vgId — that stability is the
only reason to mint an id of our own rather than reusing OCD's.

Usage:
    python scripts/build_id_crosswalk.py [output_path]
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from lib.ga_match import CHAMBER_TO_PEACHFILE, find_filers, member_scope

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
#: They belong in the crosswalk, but not as "legislator".
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
# Ledger — the only piece of mutable state, and the reason vgIds are stable
# ---------------------------------------------------------------------------

class Ledger:
    """Assigns and remembers vgIds.

    Keyed on the person's most durable upstream id (OCD person id for state,
    bioguide for federal) rather than on name or seat, both of which change.
    Ids are never reused: a member who leaves keeps their assignment so that
    historical references to their vgId stay resolvable.
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

    @property
    def newly_assigned(self):
        return [k for k in self.assign if k not in self._initial]

    def save(self):
        payload = {
            "_comment": (
                "vgId assignments for assets/data/id-crosswalk.json. Append-only: an "
                "entry is never removed or renumbered, so a vgId published once always "
                "means the same person. Keys are the person's most durable upstream id "
                "(ocd-person/... for state, bioguide for federal). Regenerated by "
                "scripts/build_id_crosswalk.py — do not hand-edit."
            ),
            "nextSeq": self.next_seq,
            "assign": dict(sorted(self.assign.items())),
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")


# ---------------------------------------------------------------------------
# Back-references from races.json
# ---------------------------------------------------------------------------

def candidate_backrefs(races):
    """member id -> [votega candidate ids] for candidates already linked to a member.

    races.json carries the link on the candidate row (existingMemberId, or memberId
    on a handful of older entries); this inverts it so a member record can point at
    every ballot line that is them.
    """
    out = {}
    for race in races.get("races", []):
        for phase in (race.get("phases") or {}).values():
            for ballot in (phase.get("ballots") or {}).values():
                for cand in ballot:
                    member_id = cand.get("existingMemberId") or cand.get("memberId")
                    cand_id = cand.get("id")
                    if member_id and cand_id:
                        out.setdefault(member_id, [])
                        if cand_id not in out[member_id]:
                            out[member_id].append(cand_id)
    return out


def candidate_fec_ids(races):
    """member id -> fecCandidateId, for the few rows that carry one inline."""
    out = {}
    for race in races.get("races", []):
        for phase in (race.get("phases") or {}).values():
            for ballot in (phase.get("ballots") or {}).values():
                for cand in ballot:
                    member_id = cand.get("existingMemberId") or cand.get("memberId")
                    if member_id and cand.get("fecCandidateId"):
                        out[member_id] = cand["fecCandidateId"]
    return out


def offices_sought(races):
    """member id -> [(chamber, district)] for every 2026 race they are a candidate in.

    A campaign committee is registered against the office a person is *seeking*, not
    the one they hold, and PeachFile files it that way. Scoping a sitting official to
    their current seat therefore misses anyone running for something else — a state
    representative running for senate, or the three sitting statewide executives on
    the 2026 governor's ballot, whose committees sit under "Governor".

    This re-scopes the search to the right pool. It does not widen the surname net:
    the seat/office scope and the surname requirement both still apply, so the
    ambiguity protection in ga_match.find_filers is untouched.
    """
    out = {}
    for race in races.get("races", []):
        if race.get("level") not in ("state", "state-executive"):
            continue
        scope = (race.get("chamber"), race.get("district"))
        for phase in (race.get("phases") or {}).values():
            for ballot in (phase.get("ballots") or {}).values():
                for cand in ballot:
                    member_id = cand.get("existingMemberId") or cand.get("memberId")
                    if member_id:
                        out.setdefault(member_id, [])
                        if scope not in out[member_id]:
                            out[member_id].append(scope)
    return out


# ---------------------------------------------------------------------------
# PeachFile resolution
# ---------------------------------------------------------------------------

def resolve_peachfile(member, finance, overrides, xwalk_overrides, backrefs, sought):
    """(filerEntityId, provenance) for a ga-members.json row.

    A hand-reviewed override always wins over the heuristic — including an
    explicit `noFiling`, which records that a human checked and found nothing.
    That distinction matters downstream: "nobody looked" and "somebody looked and
    there is no filing" are different claims, and only the second is safe to
    present as fact.
    """
    filers = finance["filers"]
    by_seat = finance["bySeat"]
    by_office = finance.get("byOffice", {})

    # This file's own overrides come first: they are keyed on the person's durable
    # upstream id, so they say something about the *person* rather than about one
    # ballot line, and they are the only place a cross-office filing can be pinned
    # for someone races.json doesn't link to a member record.
    own = xwalk_overrides.get(member["id"])
    if own:
        if own.get("peachfileNoFiling"):
            return None, {"method": "reviewed", "confidence": "confirmed-none",
                          "source": XWALK_OVERRIDES_FILE}
        if own.get("peachfileFilerEntityId"):
            return own["peachfileFilerEntityId"], {
                "method": "reviewed", "confidence": "high",
                "source": XWALK_OVERRIDES_FILE,
                "note": own.get("_note"),
            }

    # Overrides are keyed on races.json candidate ids, so check every ballot line
    # this member appears on, then the member's own id as a fallback.
    keys = list(backrefs.get(member["id"], [])) + [member["id"]]
    for key in keys:
        ov = overrides.get(key)
        if not ov:
            continue
        if ov.get("noFiling"):
            return None, {"method": "reviewed", "confidence": "confirmed-none",
                          "source": OVERRIDES_FILE, "key": key}
        if ov.get("filerEntityId"):
            return ov["filerEntityId"], {"method": "reviewed", "confidence": "high",
                                         "source": OVERRIDES_FILE, "key": key}

    # races.json and ga-members.json spell the chambers differently ("Georgia House
    # of Representatives" vs "House of Representatives"). Both resolve to the same
    # PeachFile pool, so compare on the normalised form — comparing raw strings
    # labelled every legislator as running for a different office than they hold.
    def norm(scope):
        chamber, district = scope
        return CHAMBER_TO_PEACHFILE.get(chamber, chamber), district

    # Offices sought in this cycle come first — that is where the committee is
    # registered — then the seat currently held, which covers officeholders who
    # aren't on any 2026 ballot.
    held = member_scope(member)
    scopes = list(sought.get(member["id"], []))
    if held[0] is not None and norm(held) not in [norm(s) for s in scopes]:
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
            if norm((chamber, district)) != norm(held):
                prov["scope"] = "office-sought"
                prov["note"] = f"matched against {chamber}, the office sought in this cycle"
            return hits[0], prov
        if len(hits) > 1:
            # Never pick one. Ambiguity is reported, not resolved — see ga_match.py.
            return None, {"method": "seat+surname", "confidence": "ambiguous",
                          "candidates": hits,
                          "note": "multiple filings match; resolve in " + OVERRIDES_FILE}
    return None, {"method": "seat+surname", "confidence": "no-match",
                  "note": "no filing matched this person's seat or the office they seek"}


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def external_ids(member):
    """GovTrack / OpenSecrets ids parsed out of current-members.json externalLinks.

    Those links come from unitedstates/congress-legislators, so the ids are
    authoritative — we are just reading them back out of a URL.
    """
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


def build_state_record(member, ledger, finance, overrides, xwalk_overrides, backrefs, sought, fec_inline):
    vg_id = ledger.id_for(member["id"])
    is_legislator = member.get("chamber") in VOTING_CHAMBERS

    filer_id, filer_prov = resolve_peachfile(member, finance, overrides, xwalk_overrides,
                                             backrefs, sought)

    ids = {
        "ocdPersonId":            member["id"],
        "legisGaGovId":           member.get("legisGaGovId"),
        "bioguideId":             None,
        "fecCandidateId":         fec_inline.get(member["id"]),
        "peachfileFilerEntityId": filer_id,
        "govtrackId":             None,
        "openSecretsId":          None,
        "votegaCandidateIds":     backrefs.get(member["id"], []),
    }

    provenance = {
        "ocdPersonId":  {"method": "authoritative", "source": "Open States"},
        "peachfileFilerEntityId": filer_prov,
    }
    if ids["legisGaGovId"] is not None:
        provenance["legisGaGovId"] = {"method": "authoritative", "source": "Open States"}
    if ids["fecCandidateId"]:
        provenance["fecCandidateId"] = {"method": "curated", "source": RACES_FILE}

    return {
        "vgId": vg_id,
        "name": {
            "full":  member.get("name"),
            "first": member.get("firstName"),
            "last":  member.get("lastName"),
        },
        "role": {
            "level":   "state",
            "office":  "legislator" if is_legislator else "statewide-executive",
            "chamber": member.get("chamber"),
            "district": member.get("district"),
            "party":   member.get("party"),
            "status":  member.get("status"),
        },
        "ids": ids,
        "provenance": provenance,
    }


def build_federal_record(member, ledger, fec, backrefs):
    vg_id = ledger.id_for(member["bioguideId"])
    terms = (member.get("terms") or {}).get("item") or []
    chamber = terms[-1].get("chamber") if terms else None

    fec_id = fec.get("byBioguideId", {}).get(member["bioguideId"])
    ext = external_ids(member)

    ids = {
        "ocdPersonId":            None,
        "legisGaGovId":           None,
        "bioguideId":             member["bioguideId"],
        "fecCandidateId":         fec_id,
        "peachfileFilerEntityId": None,  # PeachFile is state-only by statute
        "govtrackId":             ext["govtrackId"],
        "openSecretsId":          ext["openSecretsId"],
        "votegaCandidateIds":     backrefs.get(member["bioguideId"], []),
    }

    provenance = {
        "bioguideId": {"method": "authoritative", "source": "Congress.gov"},
    }
    if fec_id:
        provenance["fecCandidateId"] = {
            "method": "authoritative",
            "source": "unitedstates/congress-legislators (public domain), via ga-fec-data.json",
        }
    for key in ("govtrackId", "openSecretsId"):
        if ids[key] is not None:
            provenance[key] = {
                "method": "authoritative",
                "source": "unitedstates/congress-legislators (public domain)",
            }

    return {
        "vgId": vg_id,
        "name": {
            "full":  member.get("name"),
            "first": member.get("firstName"),
            "last":  member.get("lastName"),
        },
        "role": {
            "level":   "federal",
            "office":  "legislator",
            "chamber": chamber,
            "district": member.get("district"),
            "party":   member.get("partyName"),
            "status":  None,
        },
        "ids": ids,
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------

def coverage(records, level, key):
    """Counts for one identifier at one level.

    `resolved` / `confirmedNone` / `unresolved` are kept apart deliberately: a null
    id because a human checked and found no filing is a different claim from a null
    id because the join didn't land, and collapsing them into "the rest have no
    filing" overstates what we know.
    """
    rows = [r for r in records if r["role"]["level"] == level]
    resolved = confirmed_none = unresolved = 0
    for r in rows:
        if r["ids"][key] is not None:
            resolved += 1
        elif (r["provenance"].get(key) or {}).get("confidence") == "confirmed-none":
            confirmed_none += 1
        else:
            unresolved += 1
    return {"total": len(rows), "resolved": resolved,
            "confirmedNone": confirmed_none, "unresolved": unresolved}


def main():
    members  = load(MEMBERS_FILE)["members"]
    federal  = load(FEDERAL_FILE)["members"]
    finance  = load(FINANCE_FILE)
    fec      = load(FEC_FILE)
    races    = load(RACES_FILE)
    overrides = {k: v for k, v in load(OVERRIDES_FILE, {}).items() if not k.startswith("_")}
    xwalk_overrides = {k: v for k, v in load(XWALK_OVERRIDES_FILE, {}).items()
                       if not k.startswith("_")}

    ledger   = Ledger(LEDGER_FILE)
    backrefs = candidate_backrefs(races)
    sought   = offices_sought(races)
    fec_inline = candidate_fec_ids(races)

    records = [
        build_state_record(m, ledger, finance, overrides, xwalk_overrides,
                           backrefs, sought, fec_inline)
        for m in members
    ]
    # Georgia's delegation only. current-members.json holds all 535+ members of
    # Congress; the other states' rows would add nothing this file's consumers
    # can't get straight from unitedstates/congress-legislators.
    ga_federal = [m for m in federal if m.get("state") == "Georgia"]
    records += [build_federal_record(m, ledger, fec, backrefs) for m in ga_federal]

    records.sort(key=lambda r: r["vgId"])

    ambiguous = [r["vgId"] for r in records
                 if (r["provenance"].get("peachfileFilerEntityId") or {}).get("confidence") == "ambiguous"]

    payload = {
        "metadata": {
            "schemaVersion": 1,
            "schemaStability": (
                "Provisional. Candidate coverage (phase 2) will change "
                "peachfileFilerEntityId from a single id to a list, because a person "
                "who files for two offices in one cycle has one PeachFile filing per "
                "office. That will ship as schemaVersion 2. Field names and meanings "
                "already present are not expected to change otherwise."
            ),
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(records),
            "scope": ("Georgia officeholders: state legislators, statewide executives "
                      "sharing ga-members.json, and the Georgia federal delegation. "
                      "Non-incumbent candidates are not yet included."),
            "sources": [
                "Open States (Plural Policy) — ocdPersonId, legisGaGovId",
                "Congress.gov — bioguideId",
                "unitedstates/congress-legislators (public domain) — fecCandidateId, govtrackId, openSecretsId",
                "Georgia Ethics Commission PeachFile — peachfileFilerEntityId (derived, see provenance)",
                "votega.org races.json — votegaCandidateIds",
            ],
            "provenanceMethods": {
                "authoritative": "the upstream source publishes this id for this person directly",
                "reviewed": "a human confirmed this match; recorded in the overrides file",
                "curated": "hand-entered in this repo's own data",
                "seat+surname": "derived by scripts/lib/ga_match.py — scoped to the seat, surname required",
                "out-of-scope": "this identifier does not apply to this person",
            },
            "coverage": {
                "state": {
                    "peachfileFilerEntityId": coverage(records, "state", "peachfileFilerEntityId"),
                    "legisGaGovId": coverage(records, "state", "legisGaGovId"),
                },
                "federal": {
                    "fecCandidateId": coverage(records, "federal", "fecCandidateId"),
                },
                "ambiguousPeachfile": ambiguous,
            },
        },
        "people": records,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    ledger.save()

    cov = payload["metadata"]["coverage"]
    print(f"Wrote {OUTPUT_FILE}: {len(records)} people "
          f"({len([r for r in records if r['role']['level'] == 'state'])} state, "
          f"{len(ga_federal)} federal)")
    print(f"  PeachFile filer id : {cov['state']['peachfileFilerEntityId']['resolved']}"
          f"/{cov['state']['peachfileFilerEntityId']['total']} state")
    print(f"  legis.ga.gov id    : {cov['state']['legisGaGovId']['resolved']}"
          f"/{cov['state']['legisGaGovId']['total']} state")
    print(f"  FEC candidate id   : {cov['federal']['fecCandidateId']['resolved']}"
          f"/{cov['federal']['fecCandidateId']['total']} federal")
    if ambiguous:
        print(f"  AMBIGUOUS PeachFile matches (left unresolved): {len(ambiguous)}")
    if ledger.newly_assigned:
        print(f"  newly minted vgIds : {len(ledger.newly_assigned)}")


if __name__ == "__main__":
    main()
