#!/usr/bin/env python3
"""Tests for lib/ga_ledger.py (append-only GA legislator page ledger).

Usage: python scripts/test_ga_ledger.py   (exit 0 ok, 1 on failure)
"""
import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_ledger as G  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def m(gid, slug, **kw):
    return dict({"legisGaGovId": gid, "id": f"ocd-person/{gid}",
                 "votegaUrl": f"https://www.votega.org/ga-legislators/{slug}/"}, **kw)


def P(slug, b):
    return {"path": f"/ga-legislators/{slug}/", "biennium": b}


def test_seed():
    L = G.empty_ledger()
    G.update_ledger(L, [m(4942, "josh-mclaurin-senate-14")], "2025_26")
    check("seeded", L["people"]["4942"]["urls"], [P("josh-mclaurin-senate-14", "2025_26")])
    check("rosterId", L["people"]["4942"]["rosterId"], "ocd-person/4942")
    check("bienniums empty", L["people"]["4942"]["bienniums"], [])


def test_rename_prepends():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a-senate-1")], "2025_26")
    lines = G.update_ledger(L, [m(1, "a-senate-2")], "2027_28")
    check("rename urls", L["people"]["1"]["urls"], [P("a-senate-2", "2027_28"), P("a-senate-1", "2025_26")])
    check("rename reports change", len(lines) >= 1, True)
    check("current_path", G.current_path(L, "1"), "/ga-legislators/a-senate-2/")


def test_return_to_old_url_moves_it_first():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a")], "2025_26")
    G.update_ledger(L, [m(1, "b")], "2027_28")
    G.update_ledger(L, [m(1, "a")], "2029_30")
    check("moved first, no dup", L["people"]["1"]["urls"], [P("a", "2025_26"), P("b", "2027_28")])


def test_member_without_url_or_gid_ignored():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a", votegaUrl=None), m(None, "b")], "2025_26")
    check("no people", L["people"], {})


def test_url_owned_by_other_person_raises():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a")], "2025_26")
    before = copy.deepcopy(L)
    try:
        G.update_ledger(L, [m(2, "new"), m(2, "a")], "2027_28")
        check("raises", False, True)
    except G.LedgerError as e:
        check("raises names both", "1" in str(e) and "2" in str(e), True)
    check("not mutated", L, before)


def test_person_absent_from_members_is_kept():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a"), m(2, "b")], "2025_26")
    G.update_ledger(L, [m(2, "b")], "2027_28")
    check("kept", sorted(L["people"]), ["1", "2"])
    check("owner_of", G.owner_of(L, "/ga-legislators/a/"), "1")
    check("owner_of none", G.owner_of(L, "/nope/"), None)


def test_append_only_violations():
    old = G.empty_ledger()
    G.update_ledger(old, [m(1, "a"), m(2, "b")], "2025_26")
    G.update_ledger(old, [m(1, "c")], "2027_28")
    G.add_biennium(old, "1", "2025_26")
    check("unchanged", G.append_only_violations(old, copy.deepcopy(old)), [])
    new = copy.deepcopy(old)
    del new["people"]["2"]
    new["people"]["1"]["urls"] = new["people"]["1"]["urls"][:1]
    new["people"]["1"]["bienniums"] = []
    check("3 violations", len(G.append_only_violations(old, new)), 3)


def test_add_biennium_newest_first():
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a")], "2025_26")
    G.add_biennium(L, "1", "2025_26")
    G.add_biennium(L, "1", "2027_28")
    G.add_biennium(L, "1", "2025_26")
    check("order", L["people"]["1"]["bienniums"], ["2027_28", "2025_26"])
    try:
        G.add_biennium(L, "99", "2025_26")
        check("unknown raises", False, True)
    except G.LedgerError:
        check("unknown raises", True, True)


def test_load_save():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "l.json")
    check("absent -> empty", G.load_ledger(p), G.empty_ledger())
    L = G.empty_ledger()
    G.update_ledger(L, [m(1, "a")], "2025_26")
    G.save_ledger(L, p, generated_at="2026-11-13T00:00:00Z")
    R = G.load_ledger(p)
    check("count", R["metadata"], {"generatedAt": "2026-11-13T00:00:00Z", "count": 1})
    check("people roundtrip", R["people"], L["people"])
    G.save_ledger(L, p)
    check("default generatedAt set", bool(G.load_ledger(p)["metadata"]["generatedAt"]), True)


for t in [test_seed, test_rename_prepends, test_return_to_old_url_moves_it_first,
          test_member_without_url_or_gid_ignored, test_url_owned_by_other_person_raises,
          test_person_absent_from_members_is_kept, test_append_only_violations,
          test_add_biennium_newest_first, test_load_save]:
    print(t.__name__)
    t()

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nAll checks passed.")
