"""Identity for Georgia legislators: one primary key, everything else a cross-reference.

The primary key is `legisGaGovId` — the General Assembly's own member id: official,
collision-proof, direct from the source, back to 2001 and published by nobody else.
Every other identifier is an ADDITIVE slot that lands whenever it arrives and is never
load-bearing for identity:

    ocdPersonId   Open States' person id (OCD-shaped or null — never anything else)
    ballotpediaId Ballotpedia page title

(There is deliberately no wikidataId slot: no source we read carries one, so it shipped
on every member and was never populated. Add it back with the first source that has it,
not before.)

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

SLOTS = ("ocdPersonId", "ballotpediaId")

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
        valid = is_ocd_id(value) if slot == "ocdPersonId" else bool(value)
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


PINS_FIELD = "pinSlots"
PINS_SOURCE = "assets/data/id-crosswalk-overrides.json"

#: Where a human goes to resolve an ambiguity, by the provenance key it sits on.
PIN_REMEDY = (f"add `\"{PINS_FIELD}\": {{\"<slot>\": \"<value>\"}}` plus a `_note` to the person's entry in "
              f"{PINS_SOURCE} (keyed by roster id)")
FILING_REMEDY = (f"pin `peachfileFilerEntityId` (or `peachfileNoFiling`) in {PINS_SOURCE}, "
                 f"or resolve it in ga-campaign-finance-overrides.json")
REMEDIES = {
    "ballotpediaId": PIN_REMEDY, "ocdPersonId": PIN_REMEDY,
    "peachfileFilerEntityIds": FILING_REMEDY, "fecCandidateIds": FILING_REMEDY,
}
KIND_LABELS = {
    "ballotpediaId": "Ballotpedia page", "ocdPersonId": "Open States person id",
    "peachfileFilerEntityIds": "PeachFile filing", "fecCandidateIds": "FEC filing",
}


def ambiguities(people):
    """{provenance key: [{key, name, candidates}]} for every unresolved ambiguity.

    `key` is what a reviewer writes in the overrides file (roster id, else bioguide id,
    else the vgId). Generic over provenance keys so a new kind of ambiguity is reported
    under its own heading instead of being mislabelled as a filing.
    """
    out = {}
    for p in people:
        ids = p.get("ids") or {}
        key = ids.get("rosterId") or ids.get("bioguideId") or p.get("vgId") or (p.get("name") or {}).get("full")
        for field, prov in (p.get("provenance") or {}).items():
            if isinstance(prov, dict) and prov.get("confidence") == "ambiguous":
                out.setdefault(field, []).append({
                    "key": key, "name": (p.get("name") or {}).get("full"),
                    "candidates": list(prov.get("candidates") or [])})
    return out


def pin_patch(overrides, *keys):
    """The first override entry among `keys` that pins slots -> (pins, note) or (None, None).

    Raises ValueError for an entry that cannot be honoured: an unknown slot, a value of
    the wrong shape (ocdPersonId must stay OCD-shaped), or no `_note` — an unexplained
    pin is indistinguishable from a guess.
    """
    for k in keys:
        entry = (overrides or {}).get(k) if k else None
        if not isinstance(entry, dict) or not entry.get(PINS_FIELD):
            continue
        pins, note = entry[PINS_FIELD], entry.get("_note")
        if not isinstance(pins, dict):
            raise ValueError(f"{k}: {PINS_FIELD} must be an object of slot -> value")
        if not (isinstance(note, str) and note.strip()):
            raise ValueError(f"{k}: {PINS_FIELD} needs a _note recording how it was confirmed")
        for slot, value in pins.items():
            if slot not in SLOTS:
                raise ValueError(f"{k}: cannot pin {slot!r} (pinnable: {', '.join(SLOTS)})")
            if slot == "ocdPersonId" and not is_ocd_id(value):
                raise ValueError(f"{k}: pinned ocdPersonId {value!r} is not an OCD person id")
            if not isinstance(value, str) or not value.strip() or value != value.strip()                     or "/" in value.replace("ocd-person/", "", 1) or " " in value:
                raise ValueError(f"{k}: pinned {slot} {value!r} is not a bare id")
        return pins, note
    return None, None


def apply_slot_pins(values, prov, pins, note):
    """Overwrite slots with human-reviewed values, in place; returns the slots changed.

    Provenance keeps what the resolver offered (`chosenFrom`) so the decision is auditable.
    Slots are never ledger keys, so a pin cannot move anyone's vgId.
    """
    for slot, value in (pins or {}).items():
        offered = (prov.get(slot) or {}).get("candidates")
        values[slot] = value
        prov[slot] = _prov("reviewed", PINS_SOURCE, "high", note=note,
                           **({"chosenFrom": list(offered)} if offered else {}))
    return list(pins or {})


def apply_identity_slots(members, sidecar, overrides=None):
    """Add the nullable slots + provenance to every member, in place. Returns the count.

    Purely additive: it writes `ocdPersonId`, `ballotpediaId` and
    `idProvenance`, and never reads-then-writes `id`. Pure function of (members, sidecar),
    so a quiet run is byte-identical.
    """
    people = (sidecar or {}).get("people") or {}
    for m in members:
        legis_id = m.get("legisGaGovId")
        entry = people.get(str(int(legis_id))) if legis_id is not None else None
        values, prov = resolve_slots(m, entry)
        pins, note = pin_patch(overrides, m.get("id"), values.get("ocdPersonId"))
        apply_slot_pins(values, prov, pins, note)
        m.update(values)
        m["idProvenance"] = prov
    return len(members)


def load_pin_overrides(path=PINS_SOURCE):
    """The overrides file, or {} when absent. Paths are repo-relative like the callers'."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


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
    apply_identity_slots(doc["members"], sidecar, load_pin_overrides())
    assert before == [m.get("id") for m in doc["members"]], "roster ids must never change"
    write_json_atomic(roster_path, doc, indent=2)   # same shape the producer writes
    return len(doc["members"])
