#!/usr/bin/env python3
"""Assert validate_ga_congress_trades.py gates on self-contradiction and loss,
and only reports a quiet or changed delegation.

The old gate was `trades >= 1`, `members >= 1` and a 20% shrink. Each case pins
which side of the line a condition falls on. Stdlib only.

Usage:
  python scripts/test_ga_congress_trades_validate.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_congress_trades as V  # noqa: E402
from generate_ga_congress_trades import derive_counters  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def trade(n, kind="Purchase", late=False):
    return {"transaction_date": f"2026-0{1 + n % 9}-01", "transaction_type": kind,
            "is_late": late, "amount_range_low": 1001, "amount_range_high": 15000}


def member(name, n, bio="B000001"):
    trades = [trade(i, "Purchase" if i % 2 else "Sale (Full)", i % 3 == 0)
              for i in range(n)]
    return {"filerId": f"f_{name}", "bioguideId": bio, "chamber": "house",
            "trades": trades, **derive_counters(trades)}


def sound(counts=None):
    counts = counts or {"A": 10, "B": 6, "C": 4, "D": 3, "E": 2}
    by = {k: member(k, v) for k, v in counts.items()}
    return {"metadata": {"totalTrades": sum(counts.values()),
                         "gaMembers": sorted(by), "delegationSize": 16,
                         "fetchFailed": []},
            "tickerNames": {}, "byMember": by}


def t1(fn):
    d = sound()
    fn(d)
    return len(V.tier1(d))


def tier1_cases():
    print("tier 1 (contradictions gate)")
    check("sound file passes", V.tier1(sound()), [])
    empty = {"metadata": {"totalTrades": 0, "gaMembers": [], "delegationSize": 16},
             "tickerNames": {}, "byMember": {}}
    check("an empty delegation is NOT tier 1 (old floors were trades>=1, members>=1)",
          V.tier1(empty), [])
    check("totalTrades mismatch", t1(lambda d: d["metadata"].update(totalTrades=99)), 1)
    check("gaMembers mismatch", t1(lambda d: d["metadata"].update(gaMembers=["A"])), 1)
    check("tradeCount != trades", t1(lambda d: d["byMember"]["A"].update(tradeCount=3)), 1)
    check("sales counter wrong", t1(lambda d: d["byMember"]["B"].update(sales=99)), 1)
    check("estVolume wrong (a merge that left the volume behind)",
          t1(lambda d: d["byMember"]["C"].update(estVolume=1.0)), 1)
    check("missing field", t1(lambda d: d["byMember"]["D"].pop("filerId")), 1)
    check("more members than seats", t1(lambda d: d["metadata"].update(delegationSize=3)), 1)
    check("byMember not an object", V.tier1({"metadata": {}, "byMember": [], "tickerNames": {}}),
          ["byMember is missing or not an object"])


def collapse_cases():
    print("collapse (the one baseline gate)")
    old = sound()
    check("no baseline -> nothing", V.collapse(sound(), None), [])
    check("unchanged -> nothing", V.collapse(sound(), old), [])
    one_less = sound({"A": 10, "B": 6, "C": 4, "D": 3})
    check("losing one small member, not failed -> not a collapse", V.collapse(one_less, old), [])
    failed = copy.deepcopy(one_less)
    failed["metadata"]["fetchFailed"] = ["E"]
    check("fetch-failed member who had trades -> refuse", len(V.collapse(failed, old)), 1)
    half = sound({"A": 2, "B": 1, "C": 1, "D": 1, "E": 1})
    check("trades more than halved -> refuse", len(V.collapse(half, old)), 1)
    quiet = sound({"A": 9, "B": 6, "C": 4, "D": 3, "E": 1})
    check("a modest drop is fine (old shrink gate was 20%)", V.collapse(quiet, old), [])


def tier2_cases():
    print("tier 2 (reports, never gates)")
    old = sound()
    check("unchanged -> nothing", V.tier2(sound(), old), [])
    new = sound({"A": 10, "B": 6, "C": 4, "D": 3, "F": 1})
    heads = [h for h, _ in V.tier2(new, old)]
    check("added/removed named", heads, ["Members added or removed"])
    nobio = sound()
    nobio["byMember"]["A"]["bioguideId"] = None
    check("null bioguideId reported", [h for h, _ in V.tier2(nobio, old)],
          ["Members with no bioguideId"])
    zero = {"metadata": {}, "byMember": {}, "tickerNames": {}}
    check("no trades reported", [h for h, _ in V.tier2(zero, None)], ["No trades in the file"])
    check("render says no material change",
          "No material change" in V.render("x.json", []), True)


def main():
    tier1_cases()
    collapse_cases()
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
