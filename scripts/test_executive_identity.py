#!/usr/bin/env python3
"""Assert statewide executives are identified from ga-executive.json, with stable vgIds.

The four executives that the legislator roster happened to carry were minted under their
legacy roster ids; the other nine had no identity at all. They are now keyed from
ga-executive.json's hand-assigned `id`, and what this pins is:

  * the four original vgIds cannot move (the legacy key is tried first),
  * every executive has a distinct vgId, and a respelled name cannot mint a second one,
  * the executive and legislator keys for one person (`legis:<id>`) reach the SAME vgId,
  * a roster executive row no official claims stops the build instead of vanishing,
  * the nine newly keyed officials do not become bare-surname news matches.

Stdlib only. Usage:
  python scripts/test_executive_identity.py
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import types  # noqa: E402

try:
    import yaml  # noqa: F401
except ImportError:
    # run-script-tests.yml installs no pip packages and generate_ga_news imports yaml at
    # module level; the functions under test never call it, so a stub is enough.
    sys.modules["yaml"] = types.ModuleType("yaml")

import build_id_crosswalk as B  # noqa: E402
import generate_ga_news as N  # noqa: E402
from lib.ga_identity import executive_keys  # noqa: E402

ROOT = os.path.dirname(HERE)
failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


# The four vgIds published before executives moved to ga-executive.json. Never change these.
ORIGINAL = {"Brad Raffensperger": "vg-ga-p-000021", "Brian Kemp": "vg-ga-p-000024",
            "Burt Jones": "vg-ga-p-000030", "Chris Carr": "vg-ga-p-000039"}

# --- key order ----------------------------------------------------------------------------
check("legacy roster id first, then legis, then the executive id",
      executive_keys("ocd-person/x", 805, "exec:ga-jones-burt"),
      ["ocd-person/x", "legis:805", "exec:ga-jones-burt"])
check("no legacy id and no legis id -> the executive id alone",
      executive_keys(None, None, "exec:ga-woods-richard"), ["exec:ga-woods-richard"])

# --- ledger behaviour on a scratch ledger ---------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    led = B.Ledger(os.path.join(d, "ledger.json"))
    led.assign["ocd-person/old"] = "vg-ga-p-000024"
    led.next_seq = 700
    keys = executive_keys("ocd-person/old", 271, "exec:ga-kemp-brian")
    check("a person with a legacy key keeps their vgId", led.id_for_any(keys), "vg-ga-p-000024")
    for k in keys:
        led.alias(k, "vg-ga-p-000024")
    check("every key the person answers to lands on that vgId",
          {led.assign[k] for k in keys}, {"vg-ga-p-000024"})
    check("a later lookup by the legislator key reaches the executive's vgId",
          led.id_for_any(["legis:271"]), "vg-ga-p-000024")
    new = executive_keys(None, None, "exec:ga-woods-richard")
    first = led.id_for_any(new)
    check("a new executive is minted once", (first, led.next_seq), ("vg-ga-p-000700", 701))
    check("asking again mints nothing", (led.id_for_any(new), led.next_seq), (first, 701))

# --- the committed data ----------------------------------------------------------------------
officials = load("assets/data/ga-executive.json")["officials"]
ledger = load("assets/data/id-crosswalk-ledger.json")["assign"]
roster = {m["id"]: m for m in load("assets/data/ga-members.json")["members"]
          if m.get("chamber") == "executive"}
ids = [o.get("id") for o in officials]
check("every official has a unique executive id",
      len(ids) == len(set(ids)) and all(i for i in ids), True)
check("executive ids are lower-case slugs",
      all(re.fullmatch(r"exec:[a-z0-9-]+", i) for i in ids), True)
check("13 statewide officials", len(officials), 13)
seats = load("assets/data/ga-executive-seats.json")["seats"]
seat_by_id = {s["id"]: s for s in seats}
check("13 seats with unique ids", (len(seats), len(seat_by_id)), (13, 13))
check("every official points at a seat, one official per seat",
      sorted(o["officeId"] for o in officials), sorted(seat_by_id))
check("each seat's current holder is the official pointing at it",
      all(seat_by_id[o["officeId"]]["holders"][0]["execId"] == o["id"] for o in officials), True)
check("presidesOver lives on the Lt. Governor seat only, never on a person",
      ({s["id"]: s["presidesOver"] for s in seats if s.get("presidesOver")},
       any("presidesOver" in o for o in officials)),
      ({"ga-lt-governor": "Senate"}, False))
check("history is declared not backfilled, so empty start/end dates are not a claim",
      (load("assets/data/ga-executive-seats.json")["metadata"]["historyStatus"],
       all(h["start"] is None and h["end"] is None for s in seats for h in s["holders"])),
      ("not-backfilled", True))
check("the roster's executive rows are each claimed by an official",
      set(roster) <= {o.get("legacyRosterId") for o in officials}, True)

vg = {}
for o in officials:
    keys = executive_keys(o.get("legacyRosterId"), o.get("legisGaGovId"), o["id"])
    vals = {ledger[k] for k in keys if k in ledger}
    check(f"{o['name']}: ledger resolves to exactly one vgId", len(vals), 1)
    check(f"{o['name']}: every key is in the ledger", all(k in ledger for k in keys), True)
    vg[o["name"]] = next(iter(vals)) if vals else None
check("all 13 executives have distinct vgIds", len(set(vg.values())), 13)
for name, want in ORIGINAL.items():
    check(f"{name} keeps {want}", vg.get(name), want)

people = load("assets/data/id-crosswalk.json")["people"]
by_exec = {p["ids"].get("executiveId"): p for p in people if p["ids"].get("executiveId")}
check("the crosswalk publishes all 13 executives", len(by_exec), 13)
check("each published executive record carries its ledger vgId",
      all(by_exec[o["id"]]["vgId"] == vg[o["name"]] for o in officials), True)
mcd = by_exec["exec:ga-mcdonald-lauren"]["vgId"]
house_mcd = [p["vgId"] for p in people if p["ids"].get("legisGaGovId") == 4992]
check("the PSC commissioner is not the House 26 member of the same name",
      (mcd not in house_mcd, bool(house_mcd)), (True, True))

# --- a roster executive nobody claims stops the build ------------------------------------
try:
    B.officeholder_inputs([{"id": "ocd-person/orphan", "chamber": "executive", "name": "X"}],
                          officials)
    check("an unclaimed roster executive stops the build", "no error", "SystemExit")
except SystemExit:
    check("an unclaimed roster executive stops the build", "SystemExit", "SystemExit")
try:
    B.officeholder_inputs([], [dict(officials[0]), dict(officials[0])])
    check("a duplicate executive id stops the build", "no error", "SystemExit")
except SystemExit:
    check("a duplicate executive id stops the build", "SystemExit", "SystemExit")

# --- the roster no longer carries executives: everything must still resolve ----------------
from lib.ga_match import member_scope  # noqa: E402

no_rows = B.officeholder_inputs([], officials)
check("with no roster rows all 13 officials still come through", len(no_rows), 13)
by_name = {o["name"]: m for m, o in no_rows}
check("the four keep their legacy roster id as the member id",
      {n: by_name[n]["id"] for n in ORIGINAL},
      {o["name"]: o["legacyRosterId"] for o in officials if o["name"] in ORIGINAL})
check("a new official's member id is its executive id",
      by_name["Richard Woods"]["id"], "exec:ga-woods-richard")
jones = by_name["Burt Jones"]
check("Burt Jones keeps the OCD id and provenance the roster row carried",
      (jones["ocdPersonId"], jones["idProvenance"]["ocdPersonId"]["method"]),
      ("ocd-person/ddfab174-3a42-42c0-946e-0ce3169c4d1b", "authoritative"))
check("an executive with no slot value is out-of-scope, never a bare null",
      by_name["Brian Kemp"]["idProvenance"]["ocdPersonId"]["method"], "out-of-scope")
check("finance scope: the four still map to their office",
      {n: member_scope(by_name[n])[0] for n in ORIGINAL},
      {"Brad Raffensperger": "Secretary of State", "Brian Kemp": "Governor",
       "Burt Jones": "Lieutenant Governor", "Chris Carr": "Attorney General"})
check("finance scope: the nine others map to no office (matching stays off)",
      sorted({member_scope(m)[0] for m, o in no_rows if o["name"] not in ORIGINAL}), [None])

# --- news: only the four constitutional offices are bare-surname eligible -------------------
def person(vgid, first, last, title):
    return {"vgId": vgid, "name": {"full": f"{first} {last}", "first": first, "last": last},
            "role": {"level": "state", "office": "statewide-executive", "title": title}}


_, sole, _ = N.build_entity_index([
    person("vg-1", "Brian", "Kemp", "Governor"),
    person("vg-2", "Jason", "Shaw", "Public Service Commission - District 1 (Chairman)"),
    {**person("vg-3", "Old", "Record", None), "role": {"level": "state",
                                                       "office": "statewide-executive"}},
])
check("a governor is still a bare-surname match", "kemp" in sole, True)
check("a PSC commissioner is not", "shaw" in sole, False)
check("a record with no title (older crosswalk) keeps the old rule", "record" in sole, True)

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed.")
sys.exit(1 if failures else 0)
