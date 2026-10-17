#!/usr/bin/env python3
"""Assert validate_legis_sessions.py gates on self-contradiction and only reports change.

Usage:
  python scripts/test_legis_sessions_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_legis_sessions as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def sound():
    rows = [
        {"id": 1034, "description": "2026 Special Session", "library": "2026EX", "isDefault": False},
        {"id": 1033, "description": "2025-2026 Regular Session", "library": "20252026", "isDefault": True},
        {"id": 27, "description": "2019-2020 Regular Session", "library": "20192020", "isDefault": False},
    ]
    return {"metadata": {"count": len(rows), "defaultSessionId": 1033}, "sessions": rows}


def has(errs, text):
    return any(text in e for e in errs)


def tier1_cases():
    check("a sound file raises nothing", V.tier1(sound()), [])

    d = sound(); d["metadata"]["count"] = 99
    check("a count that does not match the rows is tier 1", has(V.tier1(d), "metadata.count"), True)

    d = sound(); d["sessions"][2]["id"] = 1033; d["metadata"]["defaultSessionId"] = None
    check("a duplicate SessionId is tier 1", has(V.tier1(d), "duplicate SessionId"), True)

    d = sound(); d["sessions"][0]["description"] = ""
    check("a session with no description is tier 1", has(V.tier1(d), "no description"), True)

    d = sound(); d["sessions"].reverse()
    check("a table out of newest-first order is tier 1", has(V.tier1(d), "newest-first"), True)

    d = sound(); d["metadata"]["defaultSessionId"] = 1034
    check("a defaultSessionId that is not the IsDefault row is tier 1",
          has(V.tier1(d), "defaultSessionId"), True)

    d = sound(); d["sessions"][1]["description"] = "2025-2027 Regular Session"
    check("a regular session spanning more than two years is tier 1",
          has(V.tier1(d), "consecutive years"), True)

    d = sound(); d["sessions"] = []; d["metadata"]["count"] = 0
    check("an empty table is tier 1", V.tier1(d) != [], True)

    # Upstream wording and content must NOT gate. The old heredoc required
    # exactly one default and a parseable regular-session description.
    d = sound(); d["sessions"][0]["isDefault"] = True
    d["metadata"]["defaultSessionId"] = None
    check("two IsDefault rows is NOT tier 1", V.tier1(d), [])

    d = sound(); d["sessions"][1]["isDefault"] = False; d["metadata"]["defaultSessionId"] = None
    check("no IsDefault row is NOT tier 1", V.tier1(d), [])

    d = sound(); d["sessions"][2]["description"] = "2019 to 2020 Regular Session"
    check("reworded regular-session text is NOT tier 1", V.tier1(d), [])

    d = sound(); d["sessions"].pop(); d["metadata"]["count"] = 2
    check("a table of two sessions (the old floor was 20) is NOT tier 1", V.tier1(d), [])


def tier2_cases():
    old = sound()
    check("no change -> nothing to report", V.tier2(sound(), old), [])
    check("no baseline, sound -> nothing to report", V.tier2(sound(), None), [])

    d = sound(); d["sessions"][0]["isDefault"] = True; d["metadata"]["defaultSessionId"] = None
    check("two defaults is reported",
          "IsDefault is not exactly one session" in dict(V.tier2(d, None)), True)

    d = sound(); d["sessions"][2]["description"] = "2019 to 2020 Regular Session"
    secs = dict(V.tier2(d, None))
    key = [k for k in secs if k.startswith("Regular-session wording")]
    check("unparseable regular-session wording is reported and names the id",
          bool(key) and "27" in secs[key[0]][0], True)

    new = copy.deepcopy(old); new["sessions"].pop(); new["metadata"]["count"] = 2
    secs = dict(V.tier2(new, old))
    check("a dropped session is reported by id and description",
          "27: 2019-2020 Regular Session" in "".join(secs.get("Sessions dropped - check these first", [])),
          True)

    new = copy.deepcopy(old)
    new["sessions"].insert(0, {"id": 1035, "description": "2026 2nd Special Session",
                               "library": "2026EX2", "isDefault": False})
    new["metadata"]["count"] = 4
    check("a new session is reported", "New sessions published" in dict(V.tier2(new, old)), True)

    new = copy.deepcopy(old); new["sessions"][0]["description"] = "2026 1st Special Session"
    check("a changed description is reported", "Descriptions changed" in dict(V.tier2(new, old)), True)


if __name__ == "__main__":
    print("tier 1:")
    tier1_cases()
    print("tier 2:")
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
