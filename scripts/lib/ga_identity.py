"""Identity for Georgia legislators: one primary key, everything else a cross-reference.

The primary key is `legisGaGovId` — the General Assembly's own member id: official,
collision-proof, direct from the source, back to 2001 and published by nobody else.
Every other identifier is an ADDITIVE slot that lands whenever it arrives and is never
load-bearing for identity:

    ocdPersonId   Open States' person id (OCD-shaped or null — never anything else)
    wikidataId    Wikidata item (Q-number)
    ballotpediaId Ballotpedia page title

The roster's own `id` is a different thing again: an OPAQUE HANDLE — "the stable string
this member was first assigned, which never changes and which nothing may parse or
interpret". 247 of the roster's values happen to be OCD-shaped and a member Open States
has not catalogued gets `legis-<legisGaGovId>`; neither shape is a promise. Anything
that needs to know whether a person has an OCD id reads `ocdPersonId`, never `id`.

Every slot carries provenance beside it, in the id-crosswalk's own vocabulary
(`method` / `source` / `confidence`), so a null is never a bare claim. The three
meanings of "no value" are kept apart:

    method "authoritative", confidence "no-match"   we looked; the source has no record
    confidence "ambiguous" (+ candidates)           we looked; more than one fits, none picked
    method "unresolved"                             no lookup has run for this slot yet
    method "out-of-scope"                           the slot does not apply to this record

Stdlib only.
"""

import json
import re

#: Exactly the shape Open States issues. A slot contracted to hold an OCD id rejects
#: anything else — including the roster's own `legis-<id>` handle.
OCD_RE = re.compile(r'^ocd-person/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
WIKIDATA_RE = re.compile(r'^Q[1-9]\d*$')

SLOTS = ("ocdPersonId", "wikidataId", "ballotpediaId")

OPENSTATES_SOURCE = "openstates/people (CC0 1.0)"
CARRIED_SOURCE = "Open States (carried in the roster id since before 2026-10)"


def is_ocd_id(value):
    return isinstance(value, str) and bool(OCD_RE.match(value))


def ledger_keys(legis_id, roster_id):
    """The id-crosswalk ledger keys for a roster member, in RESOLUTION ORDER.

    The ledger keys on `legisGaGovId` — never on a slot — so a member who acquires an
    OCD id months after being seated cannot be assigned a second vgId. Existing entries
    are append-only and were keyed on the roster id, so that key is the fallback: the
    first key already in the ledger wins, and a brand-new member is minted under the
    FIRST. A record with no legisGaGovId (a statewide executive, a vacant placeholder)
    can only use its roster id.

    The single implementation: build_id_crosswalk.py resolves with it and
    validate_id_crosswalk.py audits with it.
    """
    keys = []
    if legis_id is not None:
        keys.append(f"legis:{int(legis_id)}")
    if roster_id:
        keys.append(roster_id)
    return keys


def _prov(method, source=None, confidence=None, **extra):
    out = {"method": method}
    if source:
        out["source"] = source
    if confidence:
        out["confidence"] = confidence
    out.update(extra)
    return out


def unresolved(slot):
    return _prov("unresolved", note=f"no lookup has populated {slot} for this member yet")


def out_of_scope():
    return _prov("out-of-scope", note="no legisGaGovId — not a member of the General Assembly "
                                      "(statewide executive or vacant placeholder)")


def resolve_slots(member, entry):
    """(values, provenance) for one roster member, from the resolver's sidecar entry.

    Precedence for ocdPersonId: the resolver's answer (resolved on legisGaGovId) beats
    the value carried in the roster `id`, which beats null. The carried value is a real
    Open States id the roster was keyed on before the migration — it is copied, never
    derived, and only when it is OCD-shaped.
    """
    legis_id = member.get("legisGaGovId")
    if legis_id is None:
        return ({s: None for s in SLOTS}, {s: out_of_scope() for s in SLOTS})

    entry = entry or {}
    eprov = entry.get("provenance") or {}
    values, prov = {}, {}

    for slot in SLOTS:
        value = entry.get(slot)
        valid = (is_ocd_id(value) if slot == "ocdPersonId"
                 else bool(WIKIDATA_RE.match(value)) if slot == "wikidataId" and value
                 else bool(value))
        if value and valid:
            values[slot] = value
            prov[slot] = eprov.get(slot) or _prov("authoritative", OPENSTATES_SOURCE, "high")
            continue
        if slot == "ocdPersonId" and is_ocd_id(member.get("id")):
            values[slot] = member["id"]
            prov[slot] = _prov("authoritative", CARRIED_SOURCE, "high")
            continue
        values[slot] = None
        prov[slot] = eprov.get(slot) or unresolved(slot)
    return values, prov


def apply_identity_slots(members, sidecar):
    """Add the nullable slots + provenance to every member, in place. Returns the count.

    Purely additive: it writes `ocdPersonId`, `wikidataId`, `ballotpediaId` and
    `idProvenance`, and never reads-then-writes `id`. Pure function of (members, sidecar),
    so a quiet run is byte-identical.
    """
    people = (sidecar or {}).get("people") or {}
    for m in members:
        legis_id = m.get("legisGaGovId")
        entry = people.get(str(int(legis_id))) if legis_id is not None else None
        values, prov = resolve_slots(m, entry)
        m.update(values)
        m["idProvenance"] = prov
    return len(members)


def apply_to_roster_file(roster_path, sidecar_path):
    """Apply the sidecar to an on-disk roster. `id` values are asserted unchanged."""
    from lib.atomic_io import write_json_atomic  # lazy: keep import cost out of tests

    with open(roster_path, encoding="utf-8") as f:
        doc = json.load(f)
    try:
        with open(sidecar_path, encoding="utf-8") as f:
            sidecar = json.load(f)
    except FileNotFoundError:
        sidecar = {}
    before = [m.get("id") for m in doc["members"]]
    apply_identity_slots(doc["members"], sidecar)
    assert before == [m.get("id") for m in doc["members"]], "roster ids must never change"
    write_json_atomic(roster_path, doc, indent=2)   # same shape the producer writes
    return len(doc["members"])
