#!/usr/bin/env python3
"""Assert validate_presidential_laws.py gates on self-contradiction and a lost
law, and only reports provenance regressions.

The old gate was a 20% shrink (with --scope-key metadata.congress). A page-two
failure that truncates 300 laws to 250 is -17% and passed. Stdlib only.

Usage:
  python scripts/test_presidential_laws_validate.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_presidential_laws as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def law(n, congress=119, enriched=False):
    d = {"billLabel": f"H.R. {n}", "type": "hr", "number": str(n), "title": f"Law {n}",
         "signingDate": f"2025-{1 + n % 9:02d}-15",
         "congressUrl": f"https://www.congress.gov/bill/{congress}th-congress/house-bill/{n}"}
    if enriched:
        d.update(govinfoPackageId=f"PLAW-{congress}publ{n}", officialTextUrl="u", officialPdfUrl="p")
    return d


def sound(n=8, congress=119, enriched=False):
    laws = sorted((law(i, congress, enriched) for i in range(1, n + 1)),
                  key=lambda x: x["signingDate"], reverse=True)
    return {"metadata": {"congress": congress, "termStart": "2025-01-20", "count": len(laws)},
            "laws": laws}


def t1(fn):
    d = sound()
    fn(d)
    return len(V.tier1(d))


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    check("a new Congress with no laws is NOT tier 1", V.tier1(sound(0, congress=120)), [])
    check("count mismatch", t1(lambda d: d["metadata"].update(count=99)), 1)
    check("signed before termStart", t1(lambda d: d["laws"][0].update(signingDate="2024-01-01")), 2)
    check("duplicate law", t1(lambda d: d["laws"][1].update(number=d["laws"][0]["number"])), 1)
    check("missing field", t1(lambda d: d["laws"][0].update(title="")), 1)
    check("congressUrl for another Congress", t1(lambda d: d["laws"][0].update(
        congressUrl="https://www.congress.gov/bill/118th-congress/house-bill/1")), 1)
    check("package id without its links",
          t1(lambda d: d["laws"][0].update(govinfoPackageId="PLAW-119publ1")), 1)
    check("not newest-first", t1(lambda d: d["laws"].reverse()), 1)


def loss_cases():
    print("loss (the one baseline gate)")
    old = sound(300)
    check("no baseline -> nothing", V.collapse(sound(300), None), [])
    check("unchanged -> nothing", V.collapse(sound(300), old), [])
    check("growth -> nothing", V.collapse(sound(301), old), [])
    check("300 truncated to 250 (-17%, passed the old 20% gate) -> refuse",
          len(V.collapse(sound(250), old)), 1)
    check("new Congress starts empty -> not a loss", V.collapse(sound(0, congress=120), old), [])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    old = sound(5, enriched=True)
    check("unchanged -> nothing", V.tier2(sound(5, enriched=True), old), [])
    check("enrichment stripped is reported, not gated",
          [h for h, _ in V.tier2(sound(5, enriched=False), old)], ["GovInfo provenance lost"])
    check("a law never enriched is not a regression", V.tier2(sound(5), sound(5)), [])
    check("new Congress -> nothing", V.tier2(sound(1, congress=120), old), [])
    check("render with no sections says no material change",
          "No material change" in V.render("x.json", []), True)


def main():
    tier1_cases()
    loss_cases()
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
