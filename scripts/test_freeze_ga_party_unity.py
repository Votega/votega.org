#!/usr/bin/env python3
"""Tests for freeze_ga_party_unity.py: temp dirs, no network.

Usage: python scripts/test_freeze_ga_party_unity.py   (exit 0 ok, 1 on failure)
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freeze_ga_party_unity as F  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(mid, unity=0.9):
    return {"id": mid, "name": mid, "party": "Republican", "chamber": "Senate", "district": 1,
            "partyUnity": unity}


def live_doc(**over):
    d = {"metadata": {"biennium": "2025-2026", "count": 2, "scoredForUnity": 2},
         "members": [member("a"), member("b", 0.5)]}
    d.update(over)
    return d


def setup(doc):
    root = tempfile.mkdtemp()
    data, out = os.path.join(root, "data"), os.path.join(root, "out")
    os.makedirs(data)
    with open(os.path.join(data, "ga-party-unity.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return data, out


def dest_of(out, tag="2025_26"):
    return os.path.join(out, tag, "ga-party-unity.json")


def refuses(doc, tag="2025_26", **kw):
    data, out = setup(doc)
    try:
        F.freeze_party_unity(tag, data, out, **kw)
    except F.FreezeScorecardError as e:
        return str(e), os.path.exists(dest_of(out, tag))
    return None, os.path.exists(dest_of(out, tag))


check("tag maps to biennium", F.tag_to_biennium("2025_26"), "2025-2026")
for bad in ("2025-26", "2025_27", "x"):
    try:
        F.tag_to_biennium(bad)
        check(f"bad tag {bad}", "accepted", "refused")
    except F.FreezeScorecardError:
        check(f"bad tag {bad}", "refused", "refused")

# happy path: verbatim members + frozen markers
doc = live_doc()
data, out = setup(doc)
state, path = F.freeze_party_unity("2025_26", data, out)
check("written", state, "written")
with open(path, encoding="utf-8") as f:
    got = json.load(f)
check("members verbatim", got["members"], doc["members"])
check("frozen flags", (got["metadata"]["frozen"], got["metadata"]["frozenTag"]), (True, "2025_26"))
check("frozenAt set", bool(got["metadata"].get("frozenAt")), True)
check("biennium kept", got["metadata"]["biennium"], "2025-2026")

# idempotent
check("re-run unchanged", F.freeze_party_unity("2025_26", data, out)[0], "unchanged")

# a changed live file needs --overwrite
changed = copy.deepcopy(doc)
changed["members"][0]["partyUnity"] = 0.1
with open(os.path.join(data, "ga-party-unity.json"), "w", encoding="utf-8") as f:
    json.dump(changed, f)
try:
    F.freeze_party_unity("2025_26", data, out)
    check("differs without --overwrite refuses", "wrote", "refused")
except F.FreezeScorecardError:
    check("differs without --overwrite refuses", "refused", "refused")
check("--overwrite replaces", F.freeze_party_unity("2025_26", data, out, overwrite=True)[0], "written")

# refusals write nothing
msg, wrote = refuses(live_doc(), tag="2027_28")
check("wrong biennium refused", ("freeze BEFORE" in (msg or ""), wrote), (True, False))
msg, wrote = refuses(live_doc(members=[]))
check("empty refused", ("no members" in (msg or ""), wrote), (True, False))
msg, wrote = refuses(live_doc(members=[member("a"), member("a")]))
check("duplicate id refused", ("twice" in (msg or ""), wrote), (True, False))
d = live_doc(); d["metadata"]["count"] = 5
msg, wrote = refuses(d)
check("count mismatch refused", ("count" in (msg or ""), wrote), (True, False))
d = live_doc(); d["metadata"]["scoredForUnity"] = 1
msg, wrote = refuses(d)
check("scored mismatch refused", ("scoredForUnity" in (msg or ""), wrote), (True, False))

# CLI
data, out = setup(live_doc())
check("cli exit 0", F.main(["2025_26", "--data-dir", data, "--out-root", out]), 0)
check("cli refuses wrong tag", F.main(["2027_28", "--data-dir", data, "--out-root", out]), 1)

if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("all ok")
