#!/usr/bin/env python3
"""Tests for freeze_ga_bills.py: temp dirs, no network.

Usage: python scripts/test_freeze_ga_bills.py   (exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freeze_ga_bills as F  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def bill(ident, lid, session="2025_26"):
    return {"id": f"gga-bill/{lid}", "legislationId": lid, "identifier": ident,
            "session": session, "title": "t", "passageVotes": [{"yea": 1, "nay": 0, "partyTally": {"R": 1}}]}


def live_doc(**over):
    d = {"metadata": {"biennium": "2025-2026", "totalBills": 3,
                      "sessions": [{"id": "2025_26", "billCount": 2}, {"id": "2026_ss", "billCount": 1}]},
         "bills": [bill("HB 943", 100), bill("HB 1", 101), bill("SR 9EX", 102, "2026_ss")]}
    d.update(over)
    return d


def setup(doc):
    root = tempfile.mkdtemp()
    data, out = os.path.join(root, "data"), os.path.join(root, "out")
    os.makedirs(data)
    with open(os.path.join(data, "ga-bills.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return data, out


def refuses(doc, tag="2025_26", **kw):
    data, out = setup(doc)
    try:
        F.freeze_bills(tag, data, out, **kw)
    except F.FreezeBillsError as e:
        return str(e), os.path.exists(os.path.join(out, tag, "ga-bills.json"))
    return None, os.path.exists(os.path.join(out, tag, "ga-bills.json"))


# tag <-> biennium
check("tag maps to biennium", F.tag_to_biennium("2025_26"), "2025-2026")
check("century rollover", F.tag_to_biennium("1999_00"), "1999-2000")
for bad in ("2025-26", "2025_27", "x"):
    try:
        F.tag_to_biennium(bad)
        check(f"bad tag {bad} refused", "accepted", "refused")
    except F.FreezeBillsError:
        check(f"bad tag {bad} refused", "refused", "refused")

# happy path: bills verbatim, metadata marked, same tree as freeze_ga_biennium
data, out = setup(live_doc())
state, path = F.freeze_bills("2025_26", data, out)
check("written", state, "written")
check("path under the biennium tree", path, os.path.join(out, "2025_26", "ga-bills.json"))
with open(path, encoding="utf-8") as f:
    got = json.load(f)
check("bills verbatim (incl. baked party tallies)", got["bills"], live_doc()["bills"])
check("marked frozen", (got["metadata"]["frozen"], got["metadata"]["frozenTag"]), (True, "2025_26"))
check("frozenAt stamped", bool(got["metadata"].get("frozenAt")), True)
check("live metadata kept", got["metadata"]["sessions"], live_doc()["metadata"]["sessions"])

# idempotent: a second run on unchanged bills writes nothing, even when the stamp would differ
before = os.path.getmtime(path)
state2, _ = F.freeze_bills("2025_26", data, out)
check("second run unchanged", state2, "unchanged")
check("file untouched", os.path.getmtime(path), before)

# changed live bills need --overwrite
changed = live_doc()
changed["bills"][0]["title"] = "edited"
with open(os.path.join(data, "ga-bills.json"), "w", encoding="utf-8") as f:
    json.dump(changed, f)
try:
    F.freeze_bills("2025_26", data, out)
    check("differing frozen file refused without overwrite", "accepted", "refused")
except F.FreezeBillsError:
    check("differing frozen file refused without overwrite", "refused", "refused")
check("overwrite replaces", F.freeze_bills("2025_26", data, out, overwrite=True)[0], "written")

# refusals leave nothing on disk
err, wrote = refuses(live_doc(), tag="2027_28")
check("wrong biennium refused (after the bump)", bool(err and "BEFORE" in err), True)
check("  nothing written", wrote, False)

d = live_doc(); d["bills"][0]["session"] = "2099_ss"
err, wrote = refuses(d)
check("unlisted session refused", bool(err), True)
check("  nothing written", wrote, False)

d = live_doc(); d["bills"][1]["legislationId"] = 100
err, wrote = refuses(d)
check("duplicate legislationId refused", bool(err and "twice" in err), True)

d = live_doc(); d["bills"][1].pop("legislationId")
err, _ = refuses(d)
check("missing legislationId refused", bool(err and "no legislationId" in err), True)

d = live_doc(); d["metadata"]["sessions"][0]["billCount"] = 5
err, _ = refuses(d)
check("count disagreement refused", bool(err and "claims 5" in err), True)

err, _ = refuses(live_doc(bills=[]))
check("empty file refused", bool(err), True)

# The on-page ItemList reads only the live file, so it can never list frozen bills.
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "build_render_data.py"), encoding="utf-8") as f:
    src = f.read()
check("render data reads only the live ga-bills.json", '"src": "ga-bills.json"' in src, True)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
