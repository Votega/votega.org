#!/usr/bin/env python3
"""Invariants of GA legislator identity: legisGaGovId primary, everything else a slot.

Covers, with no network and no repo writes:

  * the resolver (generate_openstates_crosswalk.py) via an injected fetcher -- the
    join on the legis.ga.gov profile link, the duplicate-file rule, ambiguity, shared
    values, non-OCD upstream ids, the regression/partial-read guards and determinism;
  * the roster slots + provenance (lib/ga_identity.py) -- additive, `id` untouched;
  * the ledger: a cohort of `legis-*` members who LATER acquire OCD ids must not gain a
    second vgId, and `ocdPersonId` can never hold a non-OCD value (end to end through
    build_id_crosswalk.main());
  * the validator checks that catch the above.

The builder under test is scripts/build_id_crosswalk.py unless VOTEGA_TEST_BUILDER names
another file -- that is how the negative controls run these same cases against the
pre-change builder.

Run: python scripts/test_ga_identity.py          (stdlib only)
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import generate_openstates_crosswalk as R  # noqa: E402
import validate_id_crosswalk as V          # noqa: E402
from lib.ga_identity import (apply_identity_slots, is_ocd_id, ledger_keys, ambiguities,
                             pin_patch)  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def ocd(n):
    return "ocd-person/%08x-0000-4000-8000-%012x" % (n, n)


def doc(n, legis=None, ballotpedia=(), extra_links=()):
    links = []
    if legis is not None:
        links.append({"url": "https://www.legis.ga.gov/members/house/%s" % legis})
    links += [{"url": u} for u in extra_links]
    return {"id": ocd(n), "name": "P%d" % n, "links": links,
            "sources": [{"url": "https://ballotpedia.org/%s" % b} for b in ballotpedia]}


def entry(d, where="legislature"):
    return {"dir": where, "doc": d}


def member(legis, mid, name=None):
    return {"id": mid, "name": name or "M%s" % legis, "legisGaGovId": legis,
            "chamber": "House of Representatives", "district": legis % 180 + 1}


GEN = "2026-10-19T00:00:00+00:00"


def resolver_cases():
    print("resolver (injected people, no network)")
    roster = [member(101, ocd(1)), member(102, "legis-102"), member(103, ocd(3)),
              member(104, ocd(4)), member(105, "legis-105"), member(115, ocd(5)), member(116, ocd(6)),
              member(117, ocd(7))]
    docs = [
        entry(doc(1, 101, ["Alpha_One"])),
        entry(doc(2, 102, [])),                                  # no ballotpedia link
        entry(doc(3, 103, ["Gamma", "Gamma_(Georgia)"])),        # two pages
        entry(doc(4, 104), "retired"),
        entry(doc(14, 104), "retired"),                          # two retired claimants
        entry(doc(15, 115, ["Tim_Gamma", "Timothy_Gamma"])),
        entry(doc(16, 116, ["Nab_Islam", "Nab_Islam_Parkes"]), "retired"),
        entry(doc(17, 117, ["Some_Person", "Other_Human"])),      # unrelated: still ambiguous
        entry(doc(9, 999, ["Stray"])),                           # nobody on our roster
    ]
    sc, reg = R.build_sidecar(docs, roster, generated_at=GEN)
    p = sc["people"]
    check("resolves on the legis.ga.gov profile link", p["101"]["ocdPersonId"], ocd(1))
    check("a member Open States HAS now catalogued gets an OCD id", p["102"]["ocdPersonId"], ocd(2))
    check("provenance names the source and confidence",
          (p["101"]["provenance"]["ocdPersonId"]["source"],
           p["101"]["provenance"]["ocdPersonId"]["confidence"]),
          (R.OPENSTATES_SOURCE, "high"))
    check("ballotpedia id is the page title", p["101"]["ballotpediaId"], "Alpha_One")
    check("no ballotpedia link is 'no-match', not a bare null",
          (p["102"]["ballotpediaId"], p["102"]["provenance"]["ballotpediaId"]["confidence"]),
          (None, "no-match"))
    check("a plain and a (Georgia) title are one person: the (Georgia) one is kept",
          (p["103"]["ballotpediaId"], p["103"]["provenance"]["ballotpediaId"]["confidence"],
           p["103"]["provenance"]["ballotpediaId"]["aliases"]),
          ("Gamma_(Georgia)", "medium", ["Gamma"]))
    check("nickname vs full name: the fuller title is kept",
          (p["115"]["ballotpediaId"], p["115"]["provenance"]["ballotpediaId"]["aliases"]),
          ("Timothy_Gamma", ["Tim_Gamma"]))
    check("married name: the longer title is kept",
          (p["116"]["ballotpediaId"], p["116"]["provenance"]["ballotpediaId"]["aliases"]),
          ("Nab_Islam_Parkes", ["Nab_Islam"]))
    check("unrelated titles in one file stay ambiguous, none picked",
          (p["117"]["ballotpediaId"], p["117"]["provenance"]["ballotpediaId"]["confidence"]),
          (None, "ambiguous"))
    check("two Georgia-qualified titles tie, so stay ambiguous",
          R.choose_ballotpedia(["A_B_(Georgia)", "A_C_(Georgia)"]), None)
    check("merged variants are reported for review",
          len(sc["review"]["ballotpediaVariantsMerged"]), 3)
    check("two non-current claimants are ambiguous",
          (p["104"]["ocdPersonId"], p["104"]["provenance"]["ocdPersonId"]["confidence"]),
          (None, "ambiguous"))
    check("an unclaimed member is no-match", p["105"]["provenance"]["ocdPersonId"]["confidence"], "no-match")
    check("upstream people absent from the roster are not carried", "999" in p, False)
    check("no regressions on a first run", reg, [])

    # the Derrick Jackson case: a current file and a retired duplicate claim one id
    dup = [entry(doc(1, 101)), entry(doc(11, 101), "retired")]
    sc2, _ = R.build_sidecar(dup, [member(101, ocd(1))], generated_at=GEN)
    check("the sole CURRENT claimant wins over a retired duplicate",
          sc2["people"]["101"]["ocdPersonId"], ocd(1))
    check("the superseded duplicate is surfaced for review",
          sc2["review"]["supersededRetiredDuplicates"], {"101": [ocd(11)]})
    two_current = [entry(doc(1, 101)), entry(doc(11, 101))]
    sc3, _ = R.build_sidecar(two_current, [member(101, ocd(1))], generated_at=GEN)
    check("two CURRENT claimants are ambiguous", sc3["people"]["101"]["ocdPersonId"], None)

    # never carry a value that is not OCD-shaped
    bad = doc(1, 101)
    bad["id"] = "legis-101"
    sc4, _ = R.build_sidecar([entry(bad)], [member(101, "legis-101")], generated_at=GEN)
    check("a non-OCD upstream id is never accepted", sc4["people"]["101"]["ocdPersonId"], None)

    # two members cannot share a value
    shared = [entry(doc(1, 101, ["Same"])), entry(doc(2, 102, ["Same"]))]
    sc5, _ = R.build_sidecar(shared, [member(101, ocd(1)), member(102, ocd(2))], generated_at=GEN)
    check("a ballotpedia id shared by two members is demoted for both",
          (sc5["people"]["101"]["ballotpediaId"], sc5["people"]["102"]["ballotpediaId"]), (None, None))

    # a previously resolved slot coming back null is a regression, not news
    prev = {"people": {"101": {"ocdPersonId": ocd(1), "ballotpediaId": "Alpha_One"}}}
    _, reg2 = R.build_sidecar([], [member(101, ocd(1))], generated_at=GEN, previous=prev)
    check("a resolved slot that vanishes is reported", len(reg2), 2)


def main_cases():
    print("resolver main(): guards and determinism")
    with tempfile.TemporaryDirectory() as d:
        roster_p, out_p = os.path.join(d, "ga-members.json"), os.path.join(d, "side.json")
        roster = [member(100 + i, ocd(i)) for i in range(1, 6)]
        with open(roster_p, "w") as f:
            json.dump({"members": roster}, f)
        docs = [entry(doc(i, 100 + i, ["P_%d" % i])) for i in range(1, 6)]
        R.MIN_DOCS = 3
        rc = R.main(["--out", out_p, "--roster", roster_p], fetcher=lambda: (docs, "sha1"))
        check("a good run exits 0 and writes", (rc, os.path.exists(out_p)), (0, True))
        first = open(out_p, "rb").read()

        rc = R.main(["--out", out_p, "--roster", roster_p], fetcher=lambda: (docs, "sha2"))
        a, b = json.loads(first), json.loads(open(out_p, "rb").read())
        for x in (a, b):
            for k in ("generatedAt", "upstreamCommit"):
                x["metadata"].pop(k)
        check("a quiet run changes only run-scoped metadata", a == b, True)

        def boom():
            raise RuntimeError("503")
        before = open(out_p, "rb").read()
        rc = R.main(["--out", out_p, "--roster", roster_p], fetcher=boom)
        check("a fetch failure exits 1 and leaves the file untouched",
              (rc, open(out_p, "rb").read() == before), (1, True))
        rc = R.main(["--out", out_p, "--roster", roster_p], fetcher=lambda: (docs[:2], "x"))
        check("a short read is refused (partial = false no-matches)",
              (rc, open(out_p, "rb").read() == before), (1, True))
        rc = R.main(["--out", out_p, "--roster", roster_p],
                    fetcher=lambda: (docs[2:] + [entry(doc(40, 777))], "x"))
        check("a previously resolved member going null is refused",
              (rc, open(out_p, "rb").read() == before), (1, True))


def roster_cases():
    print("roster slots + provenance")
    roster = [member(101, ocd(1)), member(102, "legis-102"),
              {"id": ocd(7), "name": "Gov", "legisGaGovId": None, "chamber": "executive"},
              {"id": "ga-senate-7-vacant", "name": "Vacant", "legisGaGovId": None}]
    ids_before = [m["id"] for m in roster]
    # a legis-* member acquires an OCD id months later; the roster id does not move
    sidecar = {"people": {"102": {"ocdPersonId": ocd(2), "ballotpediaId": "Late_Arrival",
                                  "provenance": {"ocdPersonId": R._prov("high"),
                                                 "ballotpediaId": R._prov("high")}}}}
    apply_identity_slots(roster, sidecar)
    check("ids are byte-identical after applying slots", [m["id"] for m in roster], ids_before)
    check("a late OCD id lands in the slot, not in id",
          (roster[1]["id"], roster[1]["ocdPersonId"]), ("legis-102", ocd(2)))
    check("a carried OCD id fills the slot with its own provenance",
          (roster[0]["ocdPersonId"], roster[0]["idProvenance"]["ocdPersonId"]["method"]),
          (ocd(1), "authoritative"))
    check("a never-looked-up slot is 'unresolved', not a claim",
          roster[0]["idProvenance"]["ballotpediaId"]["method"], "unresolved")
    check("a non-member's slots are out-of-scope",
          (roster[2]["ocdPersonId"], roster[2]["idProvenance"]["ballotpediaId"]["method"]),
          (None, "out-of-scope"))
    fresh = [member(103, "legis-103")]
    apply_identity_slots(fresh, {})
    check("a new member with no upstream record: null + 'unresolved'",
          (fresh[0]["ocdPersonId"], fresh[0]["idProvenance"]["ocdPersonId"]["method"]),
          (None, "unresolved"))
    check("a legis-* handle is never copied into ocdPersonId", is_ocd_id("legis-103"), False)
    check("ledger key order: legisGaGovId first, roster id second",
          ledger_keys(103, "legis-103"), ["legis:103", "legis-103"])
    check("no legisGaGovId means the roster id alone", ledger_keys(None, "ga-senate-7-vacant"),
          ["ga-senate-7-vacant"])


def load_builder():
    path = os.environ.get("VOTEGA_TEST_BUILDER") or os.path.join(HERE, "build_id_crosswalk.py")
    saved = sys.argv
    sys.argv = [path]
    try:
        spec = importlib.util.spec_from_file_location("builder_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


def build(mod, d, members, ledger_assign=None):
    def w(name, obj):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            json.dump(obj, f)
        return p
    mod.MEMBERS_FILE = w("members.json", {"members": members})
    mod.FEDERAL_FILE = w("fed.json", {"members": []})
    mod.EXECUTIVE_FILE = w("exec.json", {"officials": []})   # no statewide officials in this fixture
    mod.FINANCE_FILE = w("fin.json", {"filers": {}, "bySeat": {}, "byOffice": {}})
    mod.FEC_FILE = w("fec.json", {"candidates": {}})
    mod.RACES_FILE = w("races.json", {"races": []})
    mod.OVERRIDES_FILE = w("ov.json", {})
    mod.XWALK_OVERRIDES_FILE = w("xov.json", {})
    mod.LEDGER_FILE = os.path.join(d, "ledger.json")
    if ledger_assign is not None:
        w("ledger.json", {"nextSeq": len(ledger_assign) + 1, "assign": ledger_assign})
    mod.OUTPUT_FILE = os.path.join(d, "out.json")
    mod.main()
    with open(mod.OUTPUT_FILE) as f:
        out = json.load(f)
    with open(mod.LEDGER_FILE) as f:
        led = json.load(f)
    return out, led


def cohort_cases():
    print("ledger: a cohort of legis-* members who later acquire OCD ids")
    mod = load_builder()
    cohort = [member(5000 + i, "legis-%d" % (5000 + i)) for i in range(5)]
    legacy = member(100, ocd(100), "Legacy")
    for m in cohort + [legacy]:
        apply_identity_slots([m], {})
    with tempfile.TemporaryDirectory() as d:
        out1, led1 = build(mod, d, cohort + [legacy], {ocd(100): "vg-ga-p-000001"})
        by1 = {p["ids"]["legisGaGovId"]: p for p in out1["people"] if p["ids"]["legisGaGovId"]}
        vg1 = {k: v["vgId"] for k, v in by1.items()}
        check("a legacy member keeps their existing vgId", vg1[100], "vg-ga-p-000001")
        check("the cohort is minted under legisGaGovId-derived keys",
              sorted(k for k in led1["assign"] if k.startswith("legis:")),
              sorted("legis:%d" % (5000 + i) for i in range(5)))

        # months later: Open States catalogues the cohort. Ids do not move.
        sidecar = {"people": {str(m["legisGaGovId"]): {
            "ocdPersonId": ocd(9000 + i), "provenance": {"ocdPersonId": R._prov("high")}}
            for i, m in enumerate(cohort)}}
        apply_identity_slots(cohort + [legacy], sidecar)
        out2, led2 = build(mod, d, cohort + [legacy])
        by2 = {p["ids"]["legisGaGovId"]: p for p in out2["people"] if p["ids"]["legisGaGovId"]}
        vg2 = {k: v["vgId"] for k, v in by2.items()}
        check("no member gained a second vgId when their OCD id arrived", vg2, vg1)
        check("the ledger did not grow", len(led2["assign"]), len(led1["assign"]))
        check("the arriving ocdPersonId is never a ledger key",
              [k for k in led2["assign"] if k.startswith("ocd-person/") and k != ocd(100)], [])
        check("the validator agrees: one vgId per person",
              V.ledger_identity_errors(out2["people"], led2["assign"]), [])
        check("ocdPersonId is now published for the cohort",
              sorted(by2[k]["ids"]["ocdPersonId"] for k in by2 if k >= 5000),
              sorted(ocd(9000 + i) for i in range(5)))

    print("ocdPersonId purity (defect: roster id published in the OCD field)")
    with tempfile.TemporaryDirectory() as d:
        m = member(7001, "legis-7001")
        apply_identity_slots([m], {})
        out, _ = build(mod, d, [m])
        p = [x for x in out["people"] if x["ids"]["legisGaGovId"] == 7001][0]
        check("a legis-* roster id is NOT published as ocdPersonId", p["ids"]["ocdPersonId"], None)
        check("legisGaGovId provenance no longer claims Open States",
              "Open States" in json.dumps(p["provenance"].get("legisGaGovId")), False)


def validator_cases():
    print("validator")
    ok = {"vgId": "vg1", "name": {"full": "A"},
          "ids": {"legisGaGovId": 1, "rosterId": "legis-1", "ocdPersonId": None}}
    check("a null ocdPersonId passes", V.slot_errors([ok], []), [])
    bad = {"vgId": "vg1", "name": {"full": "A"}, "ids": {"ocdPersonId": "legis-1"}}
    check("a non-OCD ocdPersonId is an error", len(V.slot_errors([bad], [])), 1)
    mem = {"name": "A", "legisGaGovId": 1, "ocdPersonId": None,
           "ballotpediaId": None, "idProvenance": {}}
    check("a roster slot with no provenance is an error", len(V.slot_errors([], [mem])), 2)
    mem["idProvenance"] = {s: {"method": "unresolved"} for s in V.SLOTS}
    check("provenance on every slot passes", V.slot_errors([], [mem]), [])
    mem["ocdPersonId"] = ocd(1)
    check("a value beside 'unresolved' provenance is an error", len(V.slot_errors([], [mem])), 1)
    assign = {"legis:1": "vg1", ocd(9): "vg2"}
    p = {"vgId": "vg1", "name": {"full": "A"},
         "ids": {"legisGaGovId": 1, "rosterId": "legis-1", "ocdPersonId": ocd(9)}}
    check("a slot used as a key with another vgId = two vgIds for one person",
          len(V.ledger_identity_errors([p], assign)), 1)
    check("legacy roster-id key alone still resolves",
          V.ledger_identity_errors([{"vgId": "vg3", "name": {"full": "B"},
                                     "ids": {"legisGaGovId": 2, "rosterId": ocd(2)}}],
                                   {ocd(2): "vg3"}), [])
    check("legisGaGovId key outranks a stale legacy key",
          len(V.ledger_identity_errors([{"vgId": "vg3", "name": {"full": "B"},
                                         "ids": {"legisGaGovId": 2, "rosterId": ocd(2)}}],
                                       {"legis:2": "vg4", ocd(2): "vg3"})), 2)


def pin_cases():
    print("pins and the ambiguity report")
    amb = {"method": "authoritative", "confidence": "ambiguous",
           "candidates": ["Samuel_Park", "Samuel_Park_(Georgia)"]}
    # Ambiguity is reported per KIND, with candidates and the remedy for that kind.
    people = [{"vgId": "vg1", "name": {"full": "Sam Park"},
               "ids": {"rosterId": ocd(1)}, "provenance": {"ballotpediaId": amb}},
              {"vgId": "vg2", "name": {"full": "B"}, "ids": {"rosterId": ocd(2)},
               "provenance": {"peachfileFilerEntityIds": {"confidence": "ambiguous"}}}]
    groups = ambiguities(people)
    check("ambiguities are grouped by provenance key", sorted(groups), ["ballotpediaId", "peachfileFilerEntityIds"])
    check("a row carries the key to write and the candidates",
          groups["ballotpediaId"], [{"key": ocd(1), "name": "Sam Park", "candidates": amb["candidates"]}])
    secs = dict(V.ambiguity_sections(people))
    bp = [v for k, v in secs.items() if "Ballotpedia" in k][0]
    fl = [v for k, v in secs.items() if "PeachFile" in k][0]
    check("the Ballotpedia section points at pinSlots, not finance overrides",
          ("pinSlots" in "\n".join(bp), "ga-campaign-finance" in "\n".join(bp)), (True, False))
    check("the Ballotpedia section prints the candidates inline", "`Samuel_Park_(Georgia)`" in bp[0], True)
    check("the filing section keeps the finance remedy", "ga-campaign-finance" in "\n".join(fl), True)
    check("tier2 stays a report (sections, never an error)", len(V.tier2({}, None, (), people)), 2)

    ov = {ocd(1): {"pinSlots": {"ballotpediaId": "Samuel_Park_(Georgia)"}, "_note": "checked page"}}
    m = member(1, ocd(1))
    apply_identity_slots([m], {"people": {"1": {"ballotpediaId": None,
                                                "provenance": {"ballotpediaId": amb}}}}, ov)
    check("a pin fills the slot", m["ballotpediaId"], "Samuel_Park_(Georgia)")
    check("pin provenance is 'reviewed' and records what was offered",
          (m["idProvenance"]["ballotpediaId"]["method"], m["idProvenance"]["ballotpediaId"]["chosenFrom"]),
          ("reviewed", amb["candidates"]))
    check("a pin never touches the opaque id", m["id"], ocd(1))
    m2 = member(1, ocd(1))
    apply_identity_slots([m2], {}, {})
    check("no overrides = unchanged behaviour", m2["ballotpediaId"], None)

    def raises(o, key=ocd(1)):
        try:
            pin_patch(o, key)
        except ValueError:
            return True
        return False
    check("a pin with no _note is refused", raises({ocd(1): {"pinSlots": {"ballotpediaId": "X"}}}), True)
    check("a non-OCD ocdPersonId pin is refused",
          raises({ocd(1): {"pinSlots": {"ocdPersonId": "legis-1"}, "_note": "n"}}), True)
    check("an unknown slot is refused", raises({ocd(1): {"pinSlots": {"wikidataId": "Q1"}, "_note": "n"}}), True)
    check("a URL is not a bare id",
          raises({ocd(1): {"pinSlots": {"ballotpediaId": "https://ballotpedia.org/X"}, "_note": "n"}}), True)

    out = {"vgId": "vg1", "name": {"full": "A"}, "ids": {"rosterId": ocd(1), "ballotpediaId": None}}
    check("a pin that did not land is a validator error", len(V.pin_errors([out], ov)), 2)
    out["ids"]["ballotpediaId"] = "Samuel_Park_(Georgia)"
    out["provenance"] = {"ballotpediaId": {"method": "reviewed"}}
    check("a landed pin passes", V.pin_errors([out], ov), [])
    check("a pin matching nobody is an error", len(V.pin_errors([], ov)), 1)


for fn in (resolver_cases, main_cases, roster_cases, cohort_cases, validator_cases, pin_cases):
    fn()

print()
if failures:
    print("%d FAILED: %s" % (len(failures), "; ".join(failures)))
    sys.exit(1)
print("All passed")
