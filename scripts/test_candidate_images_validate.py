#!/usr/bin/env python3
"""Assert validate_candidate_images.py gates on self-contradiction and only reports change.

Usage:
  python scripts/test_candidate_images_validate.py

Exits 0 on success, 1 on any failure.
"""

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_candidate_images as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


ROOT = tempfile.mkdtemp()
os.makedirs(os.path.join(ROOT, V.OUTPUT_DIR))
for name in ("a.jpg", "b.jpg"):
    open(os.path.join(ROOT, V.OUTPUT_DIR, name), "wb").write(b"x")


def sound():
    return {
        "metadata": {"count": 2, "sources": ["congress.gov", "legis.ga.gov"]},
        "images": {
            "https://www.congress.gov/img/member/a.jpg": f"{V.OUTPUT_DIR}/a.jpg",
            "https://legis.ga.gov/b.jpg": f"{V.OUTPUT_DIR}/b.jpg",
        },
    }


def has(errs, text):
    return any(text in e for e in errs)


def tier1_cases():
    check("a sound manifest raises nothing", V.tier1(sound(), ROOT), [])

    d = sound(); d["metadata"]["count"] = 5
    check("a count that does not match is tier 1", has(V.tier1(d, ROOT), "metadata.count"), True)

    d = sound(); d["images"]["https://legis.ga.gov/c.jpg"] = f"{V.OUTPUT_DIR}/c.jpg"
    d["metadata"]["count"] = 3
    check("an entry whose file is missing is tier 1", has(V.tier1(d, ROOT), "missing file"), True)

    d = sound(); d["images"]["https://example.com/x.jpg"] = f"{V.OUTPUT_DIR}/a.jpg"
    d["metadata"]["count"] = 3
    check("a non-government source URL is tier 1 (the copyright invariant)",
          has(V.tier1(d, ROOT), "not a declared .gov"), True)

    d = sound(); d["metadata"]["sources"].append("ballotpedia.org")
    check("declaring a non-.gov source is tier 1", has(V.tier1(d, ROOT), "not a .gov host"), True)

    d = sound(); d["images"]["https://legis.ga.gov/b.jpg"] = "elsewhere/b.jpg"
    check("a path outside the portrait folder is tier 1", has(V.tier1(d, ROOT), "outside"), True)

    check("images that is not an object is tier 1", V.tier1({"images": []}, ROOT) != [], True)

    # World moving must NOT gate.
    d = sound(); d["images"] = {}; d["metadata"]["count"] = 0
    check("an empty manifest is NOT tier 1", V.tier1(d, ROOT), [])
    d = sound(); d["metadata"]["failed"] = ["https://legis.ga.gov/z.jpg"]
    check("failed downloads are NOT tier 1", V.tier1(d, ROOT), [])


def tier2_cases():
    old = sound()
    check("no change -> nothing to report", V.tier2(sound(), old, ["a.jpg", "b.jpg"]), [])
    check("no baseline -> nothing to report", V.tier2(sound(), None, None), [])

    d = sound(); d["metadata"]["failed"] = ["https://legis.ga.gov/z.jpg"]
    secs = V.tier2(d, old)
    check("a failed download is reported and named",
          any("could not be cached" in h and "z.jpg" in "".join(l) for h, l in secs), True)

    new = copy.deepcopy(old); del new["images"]["https://legis.ga.gov/b.jpg"]
    secs = V.tier2(new, old)
    check("a dropped portrait is reported and named",
          any("no longer" in h and "legis.ga.gov/b.jpg" in "".join(l) for h, l in secs), True)

    new = copy.deepcopy(old); new["images"]["https://legis.ga.gov/n.jpg"] = f"{V.OUTPUT_DIR}/n.jpg"
    check("a new portrait is reported",
          any("newly cached" in h for h, _ in V.tier2(new, old)), True)

    secs = V.tier2(sound(), old, ["a.jpg", "b.jpg", "stray.jpg"])
    check("an unreferenced file is reported and named",
          any("nothing references" in h and "stray.jpg" in "".join(l) for h, l in secs), True)


if __name__ == "__main__":
    print("tier 1:")
    tier1_cases()
    print("tier 2:")
    tier2_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
