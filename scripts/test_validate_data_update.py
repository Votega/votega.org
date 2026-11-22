#!/usr/bin/env python3
"""Pin validate_data_update's shrink test at the boundary.

`change < limit` let a drop of EXACTLY the limit through: byMember holds 5 GA filers,
so losing one is exactly -20% against the 20% default and slipped past the gate.

Usage:
  python scripts/test_validate_data_update.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_data_update as V  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


print("exceeds_shrink")
check("5 -> 4 is exactly -20%: fails", V.exceeds_shrink(5, 4, 0.20), True)
check("5 -> 5: passes", V.exceeds_shrink(5, 5, 0.20), False)
check("100 -> 81 (-19%): passes", V.exceeds_shrink(100, 81, 0.20), False)
check("100 -> 80 (exact limit): fails", V.exceeds_shrink(100, 80, 0.20), True)
check("100 -> 79 (past limit): fails", V.exceeds_shrink(100, 79, 0.20), True)
check("growth passes", V.exceeds_shrink(100, 150, 0.20), False)
check("float-awkward exact limit: 10 -> 7 at 30%", V.exceeds_shrink(10, 7, 0.30), True)
check("float-awkward exact limit: 3 -> 2 at 1/3", V.exceeds_shrink(3, 2, 1 / 3), True)
check("a negative limit is read by magnitude", V.exceeds_shrink(5, 4, -0.20), True)
check("limit 0: any drop fails", V.exceeds_shrink(10, 9, 0), True)
check("limit 0: no change passes", V.exceeds_shrink(10, 10, 0), False)
check("limit 1 disables the check (even to zero)", V.exceeds_shrink(10, 0, 1.0), False)
check("no prior: nothing to shrink from", V.exceeds_shrink(0, 0, 0.20), False)

print("CLI against a committed baseline")
with tempfile.TemporaryDirectory() as repo:
    def git(*a):
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       check=True, capture_output=True)

    git("init", "-q")
    path = os.path.join(repo, "d.json")
    with open(path, "w") as fh:
        json.dump({"byMember": {str(i): 1 for i in range(5)}}, fh)
    git("add", "d.json")
    git("commit", "-q", "-m", "baseline")
    script = os.path.join(HERE, "validate_data_update.py")

    def run(n, *extra):
        with open(path, "w") as fh:
            json.dump({"byMember": {str(i): 1 for i in range(n)}}, fh)
        return subprocess.run([sys.executable, script, "d.json", "--metric",
                               "filers=len:byMember", *extra],
                              cwd=repo, capture_output=True, text=True).returncode

    check("5 -> 4 filers (exactly -20%) exits 1", run(4), 1)
    check("5 -> 5 filers exits 0", run(5), 0)
    check("5 -> 4 with --max-shrink 0.25 exits 0", run(4, "--max-shrink", "0.25"), 0)
    check("5 -> 3 with --max-shrink 0.25 exits 1", run(3, "--max-shrink", "0.25"), 1)
    check("--min floor still gates independently", run(5, "--min", "filers=6"), 1)

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll passed")
