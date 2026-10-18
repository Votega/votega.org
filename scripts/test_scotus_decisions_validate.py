#!/usr/bin/env python3
"""Assert validate_scotus_decisions.py gates on self-contradiction and lost
rulings, and only reports a quiet term, new decisions or a stale TERMS.

The old gate was `decisions >= 1`, a `--scope-key` on metadata.terms and a 20%
shrink. Stdlib only.

Usage:
  python scripts/test_scotus_decisions_validate.py
"""

import copy
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_scotus_decisions as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def case(term, n, month=6):
    return {"id": n, "name": f"Case {term}-{n}", "docketNumber": f"{n}-1",
            "term": term, "decidedDate": f"{int(term) + 1}-{month:02d}-{n:02d}"}


def sound(per_term=None, terms=("2024", "2025")):
    if per_term is None:
        per_term = {"2024": 5, "2025": 5}
    cases = [case(t, n) for t, k in per_term.items() for n in range(1, k + 1)]
    cases.sort(key=lambda c: c["decidedDate"], reverse=True)
    return {"metadata": {"terms": list(terms), "count": len(cases),
                         "emptyTerms": [], "detailFetchFailed": []},
            "cases": cases}


def t1(fn):
    d = sound()
    fn(d)
    return len(V.tier1(d))


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    check("a freshly added, still-empty term is NOT tier 1 (old floor was decisions>=1)",
          V.tier1(sound({"2024": 5}, terms=("2024", "2026"))), [])
    check("zero cases is NOT tier 1", V.tier1(sound({}, terms=("2026",))), [])
    check("count mismatch", t1(lambda d: d["metadata"].update(count=99)), 1)
    check("case term outside metadata.terms", t1(lambda d: d["cases"][0].update(term="2019")), 1)
    check("duplicate term/docket",
          t1(lambda d: d["cases"][1].update(docketNumber=d["cases"][0]["docketNumber"],
                                            term=d["cases"][0]["term"])), 1)
    check("missing required field", t1(lambda d: d["cases"][2].update(decidedDate=None)), 2)
    check("not in date order", t1(lambda d: d["cases"].reverse()), 1)


def loss_cases():
    print("loss (the one baseline gate)")
    old = sound()
    check("no baseline -> nothing", V.collapse(sound(), None), [])
    check("unchanged -> nothing", V.collapse(sound(), old), [])
    new = sound({"2024": 5, "2025": 4})
    check("a case simply absent, not recorded as failed -> not a gate (tier 2 names it)",
          V.collapse(new, old), [])
    failed = copy.deepcopy(new)
    failed["metadata"]["detailFetchFailed"] = ["2025/5-1"]
    check("recorded failure of a published case -> refuse", len(V.collapse(failed, old)), 1)
    empty = sound({"2024": 5}, terms=("2024", "2025"))
    empty["metadata"]["emptyTerms"] = ["2025"]
    check("term that had cases now empty -> refuse", len(V.collapse(empty, old)), 1)
    half = sound({"2024": 2, "2025": 1})
    check("bulk loss without a recorded failure -> refuse", len(V.collapse(half, old)), 1)
    dropped_term = sound({"2025": 5}, terms=("2025",))
    check("dropping a term from TERMS is a deliberate edit, not a loss",
          V.collapse(dropped_term, old), [])
    failed_new_case = copy.deepcopy(new)
    failed_new_case["metadata"]["detailFetchFailed"] = ["2025/9-1"]
    check("failure of a case never published -> not a gate", V.collapse(failed_new_case, old), [])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    old = sound()
    oct_2026, jul_2026 = datetime.date(2026, 10, 17), datetime.date(2026, 7, 1)
    check("unchanged, July -> nothing", V.tier2(sound(), old, jul_2026), [])
    heads = [h for h, _ in V.tier2(sound(), old, oct_2026)]
    check("October with TERMS stopping at 2025 -> stale-TERMS reminder",
          heads, ["TERMS is missing the current term"])
    current = sound(terms=("2024", "2025", "2026"))
    check("TERMS includes the new term -> no reminder", V.tier2(current, current, oct_2026), [])
    added = sound({"2024": 5, "2025": 6})
    check("new decision named", [h for h, _ in V.tier2(added, old, jul_2026)],
          ["1 new decision(s)"])
    removed = sound({"2024": 5, "2025": 4})
    check("unexplained removal reported", [h for h, _ in V.tier2(removed, old, jul_2026)],
          ["Cases removed with no recorded fetch failure"])
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
