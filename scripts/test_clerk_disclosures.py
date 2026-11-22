#!/usr/bin/env python3
"""Assert lib/clerk_disclosures.audit() on fixtures. Stdlib only, no network.

Usage:
  python scripts/test_clerk_disclosures.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import clerk_disclosures as C  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def row(doc, last, first, dst, typ="P", filed="11/11/2026"):
    return {"DocID": doc, "Last": last, "First": first, "StateDst": dst,
            "FilingType": typ, "FilingDate": filed}


def url(doc, year=2026):
    return f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf"


def members(**docs):
    return {n: {"trades": [{"doc_url": url(d)} for d in ds]} for n, ds in docs.items()}


TODAY = date(2026, 11, 22)


def main():
    check("doc_ref parses a House PTR url", C.doc_ref(url("20035821")), (2026, "20035821"))
    check("doc_ref ignores a Senate link",
          C.doc_ref("https://efd.senate.gov/search/view/ptr/abc/"), None)
    check("parse_index handles a BOM and tabs",
          C.parse_index("﻿Last\tFirst\tDocID\nAllen\tRichard\t1\n")[0]["DocID"], "1")

    ok = C.audit(members(Allen=["1", "2"]),
                 [], [row("1", "Allen", "Richard", "GA12"),
                      row("2", "Allen", "Richard", "GA12")], [2026], TODAY)
    check("all filings match -> verified, nothing flagged",
          (ok["verifiedDocs"], ok["wrongState"], ok["missingCount"], ok["unverifiedCount"]),
          (2, [], 0, 0))

    wrong = C.audit(members(Allen=["1"]), [], [row("1", "Allen", "Richard", "TX05")],
                    [2026], TODAY)
    check("published filing under a non-GA state flagged",
          [(w["docId"], w["stateDst"]) for w in wrong["wrongState"]], [("1", "TX05")])

    # district is never a key: McCormick is GA06 on the form but a GA member
    mc = C.audit(members(McCormick=["5"]), [], [row("5", "McCormick", "Richard", "GA06")],
                 [2026], TODAY)
    check("a wrong district number does not matter, only the state", mc["wrongState"], [])

    missing = C.audit(members(Allen=["1"]), [],
                      [row("1", "Allen", "Richard", "GA12"),
                       row("9", "Newcomer", "Nia", "GA13", filed="11/01/2026"),
                       row("10", "Newcomer", "Nia", "GA13", typ="C"),
                       row("11", "Other", "Ann", "TX05")], [2026], TODAY)
    check("only a GA periodic report absent from the file is 'missing'",
          [m["docId"] for m in missing["missingFilings"]], ["9"])

    unver = C.audit(members(Allen=["1"]), [], [], [2026], TODAY)
    check("in-year filing the index lacks is unverified, not wrong",
          (unver["unverifiedCount"], unver["wrongState"]), (1, []))
    old = C.audit({"Allen": {"trades": [{"doc_url": url("3", 2019)}]}}, [], [], [2026], TODAY)
    check("a filing from an index year we did not fetch is skipped",
          (old["unverifiedCount"], old["verifiedDocs"]), (0, 0))
    sen = C.audit({"Ossoff": {"trades": [{"doc_url": "https://efd.senate.gov/x"}]}},
                  [], [], [2026], TODAY)
    check("senate links are skipped", sen["unverifiedCount"], 0)

    rows = [row("20", "Greene", "Marjorie", "GA14", filed="10/01/2026"),
            row("21", "Greene", "Marjorie", "GA14", filed="06/01/2026")]
    dep = C.audit(members(Allen=["1"]), ["Marjorie Taylor Greene"], rows, [2026], TODAY)
    check("departed filer with a filing inside 90 days is named",
          [(d["name"], d["filings"], d["latest"]) for d in dep["departedRecent"]],
          [("Marjorie Greene", 1, "2026-10-01")])
    check("departed filings are not also reported as missing", dep["missingCount"], 0)

    sfx = C.audit(members(Collins=["1"]), ["Tom Thomas Graves Jr."],
                  [row("30", "Graves", "Tom", "GA14", filed="11/01/2026")], [2026], TODAY)
    check("a generational suffix does not defeat the departed match",
          len(sfx["departedRecent"]), 1)
    check("unavailable() shape", C.unavailable("x")["status"], "unavailable")

    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
