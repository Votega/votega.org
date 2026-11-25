#!/usr/bin/env python3
"""Former federal members in the search index (rollover decision D8).

A member of a frozen Congress who is no longer sitting stays searchable with a `former`
marker; before the turnover (everyone frozen still sitting) nothing is marked; nobody is
indexed twice.

Usage: python scripts/test_search_corpus_former_federal.py   (exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_search_corpus as G  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(bid, last, district, **kw):
    return dict({"bioguideId": bid, "name": f"{last}, Pat", "firstName": "Pat", "lastName": last,
                 "state": "Georgia", "district": district, "partyName": "Republican",
                 "terms": {"item": [{"chamber": "House of Representatives"}]}}, **kw)


def build(live, frozen):
    saved = G.DATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        G.DATA_DIR = Path(tmp)
        try:
            (G.DATA_DIR / "current-members.json").write_text(json.dumps({"members": live}), encoding="utf-8")
            if frozen:
                d = G.DATA_DIR / "federal-congresses" / "119th"
                d.mkdir(parents=True)
                (d / "freeze.json").write_text(json.dumps({"urls": {}}), encoding="utf-8")
                (d / "current-members.json").write_text(json.dumps({"members": frozen}), encoding="utf-8")
            records = []
            # `load` binds DATA_DIR as a default argument, so point it at the fixture.
            real = G.load
            G.load = lambda name, base=None: real(name, G.DATA_DIR)
            try:
                G.build_ga_federal_delegation(records, set())
            finally:
                G.load = real
            return records
        finally:
            G.DATA_DIR = saved


STAYS, LEAVES, NEW = member("S1", "Stays", 5), member("L1", "Leaves", 1), member("N1", "New", 1)


def marks(records):
    return sorted((r["title"], r.get("former")) for r in records)


if __name__ == "__main__":
    check("no freeze: nobody is former", marks(build([STAYS, LEAVES], None)),
          [("Leaves, Pat", None), ("Stays, Pat", None)])
    check("frozen but still sitting: nobody is former", marks(build([STAYS, LEAVES], [STAYS, LEAVES])),
          [("Leaves, Pat", None), ("Stays, Pat", None)])
    after = build([STAYS, NEW], [STAYS, LEAVES])
    check("after the turnover only the departed member is former", marks(after),
          [("Leaves, Pat", "119th"), ("New, Pat", None), ("Stays, Pat", None)])
    check("the description says Former",
          [r["desc"] for r in after if r.get("former")], ["Former U.S. Representative, District 1, Republican"])
    check("a roster row flagged not sitting is indexed once, as former",
          marks(build([STAYS, dict(LEAVES, currentMember=False)], [STAYS, LEAVES])),
          [("Leaves, Pat", "119th"), ("Stays, Pat", None)])
    print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
    sys.exit(1 if failures else 0)
