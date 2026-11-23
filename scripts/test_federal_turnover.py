#!/usr/bin/env python3
"""The roster run across a Congress turnover (generate_current_members_data.py + lib/federal_turnover).

Drives the real generator main() with the network pieces replaced, so what is pinned is the
decision sequence, not a copy of it:

  (a) a normal in-Congress run writes, stamps the Congress, adds no rollover marker;
  (b) an in-Congress drop of more than 25 still fails and writes nothing;
  (c) a turnover with a full 120th roster, a final 119th freeze, and 50 departures passes and
      is stamped, and the validator accepts it only because of the stamp;
  (d) the early-switch window (new Congress derived, not yet listed) holds: exit 0, nothing
      written; after the grace period the same state fails;
  (e) a turnover with no final freeze (missing, provisional, stale, unreadable) refuses and
      writes nothing; the explicit confirmation lets it through.

Run: python scripts/test_federal_turnover.py   (no network, no repo writes, no pip packages)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import types
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("yaml", types.ModuleType("yaml"))   # the generator imports it; unused here
os.environ["CONGRESS_API_KEY"] = "test"
for k in ("FEDERAL_FREEZE_CONFIRMED", "FEDERAL_ACCEPT_TURNOVER", "FEDERAL_GA_VACANT", "CONGRESS"):
    os.environ.pop(k, None)

import generate_current_members_data as G  # noqa: E402
import validate_current_members as V       # noqa: E402
from lib import federal_turnover as T      # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(bid, state, chamber, district, start, current=True):
    return {"bioguideId": bid, "name": bid, "partyName": "Democratic", "state": state,
            "district": district, "currentMember": current,
            "terms": {"item": [{"chamber": chamber, "startYear": start}]}}


def roster(start, congress_n_filler=520, ga_vacant=(), departed_flags=0):
    """A roster as the list endpoint returns it: GA 2+14, filler elsewhere."""
    ms = [member(f"GS{i}", "Georgia", "Senate", None, start) for i in (1, 2)]
    ms += [member(f"GH{d}", "Georgia", "House of Representatives", d, start)
           for d in range(1, 15) if d not in ga_vacant]
    ms += [member(f"F{i:03d}", "Ohio", "House of Representatives", i, start)
           for i in range(congress_n_filler)]
    for m in ms[-departed_flags:] if departed_flags else []:
        m["currentMember"] = False
    return ms


def doc(members, congress, rollover=None):
    meta = {"generatedAt": "2026-12-01T00:00:00+00:00", "count": len(members),
            "congress": congress}
    if rollover:
        meta["rollover"] = rollover
    return {"metadata": meta, "members": members}


def freeze_fetch(manifest=None, frozen_ga=None, boom=False):
    def fetch(url):
        if boom:
            raise OSError("network down")
        if url.endswith("freeze.json"):
            return manifest
        return {"members": [{"bioguideId": b} for b in (frozen_ga or [])]}
    return fetch


GA_IDS = [f"GS{i}" for i in (1, 2)] + [f"GH{d}" for d in range(1, 15)]
FINAL = {"kind": "final", "congress": 119, "slug": "119th"}


def run_generator(raw, committed, congress, fetch, env=None, flagged=None, today=None):
    """Run main() against a temp dir. Returns (exit_code, output_text, written_doc|None)."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "current-members.json")
        if committed is not None:
            json.dump(committed, open(out, "w", encoding="utf-8"))
        before = open(out, "rb").read() if committed is not None else None
        idx = {"metadata": {"congress": committed["metadata"]["congress"] if committed else congress}}
        json.dump(idx, open(os.path.join(d, "federal-sponsorship-index.json"), "w"))

        G.OUTPUT_FILE, G.CURRENT_CONGRESS = out, congress
        G.get_current_members = lambda: [dict(m) for m in raw]
        G.enrich_member_data = lambda bid, m: (m, True)
        G.get_committee_memberships = lambda: {}
        G.build_profile_enrichment = lambda: {}
        G.write_sponsorship_artifacts = lambda *a, **k: None
        G.SPONSORSHIP.clear()
        G.SPONSORSHIP["GH1"] = {"name": "x"}
        T._http_json = fetch
        T._today = lambda: today or date(2027, 1, 3)
        for k, v in (env or {}).items():
            os.environ[k] = v
        buf, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(buf):
                G.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        finally:
            for k in (env or {}):
                os.environ.pop(k, None)
        after = open(out, "rb").read() if os.path.exists(out) else None
        written = json.loads(after) if (after is not None and after != before) else None
        return code, buf.getvalue(), written


# --- (a) a normal in-Congress run ------------------------------------------------------
print("(a) in-Congress, normal")
committed = doc(roster(2025), 119)
code, text, w = run_generator(roster(2025, departed_flags=3), committed, 119, freeze_fetch())
check("a: exits 0", code, 0)
check("a: wrote the roster", w is not None, True)
check("a: stamped with its Congress", (w or {}).get("metadata", {}).get("congress"), 119)
check("a: no rollover marker", "rollover" in (w or {}).get("metadata", {}), False)
check("a: the 3 departed were dropped", (w or {}).get("metadata", {}).get("count"), 16 + 520 - 3)

# --- (b) in-Congress drop of more than 25 ----------------------------------------------
print("(b) in-Congress, 26 departed")
code, text, w = run_generator(roster(2025, departed_flags=26), committed, 119, freeze_fetch())
check("b: exits 1", code, 1)
check("b: wrote nothing", w, None)
check("b: says so", "implausible" in text, True)
code, text, w = run_generator(roster(2025, departed_flags=25), committed, 119, freeze_fetch())
check("b: exactly 25 is still allowed", code, 0)

# --- (c) turnover, full 120th roster ---------------------------------------------------
print("(c) turnover, full 120th roster")
raw120 = roster(2027, departed_flags=0)
raw120 += [member(f"L{i:02d}", "Texas", "House of Representatives", i, 2025, current=False)
           for i in range(50)]                              # leavers: still listed, flagged off
code, text, w = run_generator(raw120, committed, 120, freeze_fetch(FINAL, GA_IDS))
check("c: exits 0 with 50 departed", code, 0)
meta = (w or {}).get("metadata", {})
check("c: stamped Congress 120", meta.get("congress"), 120)
check("c: carries the rollover marker", bool(meta.get("rollover")), True)
check("c: marker names the 50 departures", (meta.get("rollover") or {}).get("departed"), 50)
check("c: marker records the final freeze", (meta.get("rollover") or {}).get("freeze"),
      {"kind": "final", "slug": "119th"})
new_index = {"metadata": {"congress": 120}}
check("c: validator accepts it with the stamp",
      T.validate_stamp(w, new_index, committed, {"metadata": {"congress": 119}}), [])
unstamped = json.loads(json.dumps(w))
unstamped["metadata"].pop("rollover")
check("c: validator refuses the same file without the stamp",
      any("no metadata.rollover" in e for e in
          T.validate_stamp(unstamped, new_index, committed, {"metadata": {"congress": 119}})), True)
short = roster(2027, ga_vacant=(13,))
code, text, w2 = run_generator(short, committed, 120, freeze_fetch(FINAL, GA_IDS))
check("c: an unannounced Georgia vacancy refuses", (code, w2), (1, None))
code, text, w2 = run_generator(short, committed, 120, freeze_fetch(FINAL, GA_IDS),
                               env={"FEDERAL_GA_VACANT": "GA-13"})
check("c: the same vacancy, declared, passes", code, 0)
check("c: and is recorded", (w2 or {}).get("metadata", {}).get("rollover", {}).get("gaVacant"),
      ["GA-13"])
code, text, w2 = run_generator(roster(2027, congress_n_filler=100), committed, 120,
                               freeze_fetch(FINAL, GA_IDS))
check("c: an implausibly small Congress refuses", (code, w2), (1, None))
check("c: old unstamped file with the old congress is unchanged by a refusal",
      committed["metadata"]["congress"], 119)

# --- (d) the early-switch window -------------------------------------------------------
print("(d) early window: 120th derived, only 119th listed")
code, text, w = run_generator(roster(2025), committed, 120, freeze_fetch(FINAL, GA_IDS),
                              today=date(2027, 1, 3))
check("d: exits 0", code, 0)
check("d: writes nothing", w, None)
check("d: says it is holding", "held" in text.lower() or "keeping the committed roster" in text, True)
code, text, w = run_generator(roster(2025), committed, 120, freeze_fetch(FINAL, GA_IDS),
                              today=date(2027, 1, 12))
check("d: after the grace period it fails", (code, w), (1, None))
code, text, w = run_generator(roster(2025), committed, 120, freeze_fetch(FINAL, GA_IDS),
                              today=date(2027, 1, 12), env={"FEDERAL_ACCEPT_TURNOVER": "1"})
check("d: accept_turnover skips the listing signal but sanity still runs", (code, w), (1, None))
check("d: a half-listed Congress is not enough",
      T.early_window(roster(2027)[:100] + roster(2025)[:400], 120, date(2027, 1, 4))[0], "hold")

# --- (e) turnover with no final freeze -------------------------------------------------
print("(e) turnover without a final freeze")
for label, fetch in (("missing", freeze_fetch(None)),
                     ("provisional", freeze_fetch({**FINAL, "kind": "provisional"}, GA_IDS)),
                     ("stale delegation", freeze_fetch(FINAL, GA_IDS[:-1])),
                     ("wrong Congress", freeze_fetch({**FINAL, "congress": 118}, GA_IDS)),
                     ("unreadable", freeze_fetch(boom=True))):
    code, text, w = run_generator(raw120, committed, 120, fetch)
    check(f"e: {label}: refuses and writes nothing", (code, w), (1, None))
check("e: names the remedy", "freeze-federal-delegation" in text, True)
code, text, w = run_generator(raw120, committed, 120, freeze_fetch(None),
                              env={"FEDERAL_FREEZE_CONFIRMED": "true"})
check("e: explicit confirmation lets it through", code, 0)
check("e: and the marker says it was only confirmed",
      (w or {}).get("metadata", {}).get("rollover", {}).get("freeze", {}).get("confirmed"), True)
code, text, w = run_generator(raw120, doc(raw120, 120), 119, freeze_fetch(FINAL, GA_IDS))
check("e: an older Congress never overwrites a newer committed one", (code, w), (1, None))
legacy = doc(roster(2025), 119)
legacy["metadata"].pop("congress")          # the committed file predates the stamp
check("e: an unstamped committed file is read through the sponsorship index",
      T.committed_congress(legacy, {"metadata": {"congress": 119}}), 119)

# --- validator rules on their own ------------------------------------------------------
print("validator")
old = doc(roster(2025), 119)
gone = doc(roster(2025)[:-30], 119)
check("v: a 30-member drop inside a Congress is refused without a stamp",
      any("disappeared" in e for e in T.validate_stamp(gone, None, old)), True)
check("v: a normal day is clean", T.validate_stamp(old, None, old), [])
check("v: no baseline is not an error", T.validate_stamp(old, None, None), [])
check("v: vacancy tokens parse", T.parse_ga_vacant("ga-1, GA-S"), ({1}, 1))
try:
    T.parse_ga_vacant("GA-15")
    check("v: GA-15 is rejected", False, True)
except ValueError:
    check("v: GA-15 is rejected", True, True)
check("v: tier1 itself is untouched by the new rules", V.tier1(old, None, {}) != [], True)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
