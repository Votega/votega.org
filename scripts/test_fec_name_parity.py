#!/usr/bin/env python3
"""Assert normalizeName() (JS) and normalize_name() (Python) agree.

`campaign-finance.js` and `generate_fec_data.py` each normalize candidate names,
and the JS carries a comment claiming it mirrors the Python. Nothing enforced
that, and they drifted: the JS reduced only the comma form, so display names like
"Tricia R. Pridemore" produced a three-token key that could never match the
two-token keys the Python built from FEC's "LAST, FIRST MIDDLE" data. The name
fallback was dead for most of the federal field as a result.

This runs both real implementations — the JS through node, not a Python
re-implementation of it — over every name in ga-fec-data.json and every federal
candidate name in races.json, and fails on any disagreement.

Addresses CODEBASE-REVIEW-2026-08-18.md finding 1.3.

Usage:
  python scripts/test_fec_name_parity.py

Exits 0 on agreement, 1 on any mismatch, and 77 (skip) if node is unavailable.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

FEC_FILE = "assets/data/ga-fec-data.json"
RACES_FILE = "assets/data/races.json"
JS_FILE = "assets/scripts/campaign-finance.js"

SKIP_EXIT = 77


def normalize_name(name):
    """Imported from generate_fec_data.py so this tests the real function."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from generate_fec_data import normalize_name as impl
    return impl(name)


def collect_names():
    names = []

    with open(FEC_FILE, encoding="utf-8") as fh:
        fec = json.load(fh)
    for entry in (fec.get("candidates") or {}).values():
        if entry.get("name"):
            names.append(entry["name"])

    with open(RACES_FILE, encoding="utf-8") as fh:
        races = json.load(fh)
    for race in races.get("races", []):
        if (race.get("level") or "") != "federal":
            continue
        for phase in (race.get("phases") or {}).values():
            ballots = phase.get("ballots")
            pool = ([c for v in ballots.values() for c in v]
                    if isinstance(ballots, dict) else (phase.get("candidates") or []))
            for cand in pool:
                if cand.get("name"):
                    names.append(cand["name"])

    # Edge cases worth pinning regardless of what the live data happens to contain.
    names += [
        "OSSOFF, T. JONATHAN",
        "BROWN, JAMES M MR",
        'SMITH, JOHN "JACK" QUINCY',
        "Dr. Krista Penn",
        "John Francis Coyne III",
        "Mary-Jane O'Brien",
        "Cher",
        "  spaced   out   name  ",
    ]

    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def js_normalize_all(names):
    """Run the real campaign-finance.js normalizeName over every name via node."""
    harness = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const sandbox = { window: {}, console: { log(){}, warn(){}, error(){} },
                  fetch: () => Promise.reject(new Error('no network')) };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: 'campaign-finance.js' });
const CF = sandbox.window.CampaignFinance;
if (!CF || typeof CF.normalizeName !== 'function') {
  console.error('campaign-finance.js did not export normalizeName');
  process.exit(2);
}
const names = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
process.stdout.write(JSON.stringify(names.map(n => CF.normalizeName(n))));
"""
    tmpdir = tempfile.mkdtemp(prefix="fecparity-")
    try:
        hp = os.path.join(tmpdir, "h.js")
        np_ = os.path.join(tmpdir, "names.json")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(harness)
        with open(np_, "w", encoding="utf-8") as fh:
            json.dump(names, fh)
        proc = subprocess.run(
            ["node", hp, os.path.abspath(JS_FILE), np_],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print("node failed:\n" + (proc.stderr or "").strip(), file=sys.stderr)
            sys.exit(1)
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    if not shutil.which("node"):
        print("SKIP: node not on PATH — cannot run the JS side of the parity check")
        return SKIP_EXIT

    for path in (FEC_FILE, RACES_FILE, JS_FILE):
        if not os.path.exists(path):
            print(f"SKIP: {path} not found (run from the repo root)")
            return SKIP_EXIT

    names = collect_names()
    js = js_normalize_all(names)
    py = [normalize_name(n) for n in names]

    mismatches = [(n, p, j) for n, p, j in zip(names, py, js) if p != j]

    print(f"Compared {len(names)} names "
          f"({FEC_FILE}, federal entries in {RACES_FILE}, plus pinned edge cases)")

    if mismatches:
        print(f"\nFAIL: {len(mismatches)} disagreement(s) between "
              f"normalize_name() and normalizeName():\n")
        for name, p, j in mismatches[:40]:
            print(f"  {name!r}\n      python={p!r}\n      js    ={j!r}")
        if len(mismatches) > 40:
            print(f"  ... and {len(mismatches) - 40} more")
        return 1

    two_token = sum(1 for k in py if len(k.split()) == 2)
    print(f"All agree. {two_token}/{len(py)} reduce to a two-token 'first last' key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
