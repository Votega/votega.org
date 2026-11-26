#!/usr/bin/env python3
"""Assert the three copies of the GA campaign-finance filer match agree.

A candidate's state money is found by matching their name to a GA Ethics Commission
(PeachFile) filer in their seat. That rule exists three times:

  * scripts/lib/ga_match.py               find_filers()   (crosswalk, review report)
  * assets/scripts/campaign-finance.js    findGaFilers()  (every race and candidate page)
  * tools/ga-finance-overrides-editor.html findFilers()   (the review queue)

If they drift, one candidate's money can appear on another's page, or the editor can
send a different set of cases to review than the site shows. They agree today, so
this pins it. Both JS copies run for real under node; neither is re-implemented in
Python.

Compared: every candidate of every state-level race in races.json against the live
ga-campaign-finance.json, plus fixtures for the cases the rule is built around
(shared surnames, nicknames, apostrophes, suffixes, multi-word surnames, the
districted statewide office).

Usage:
  python scripts/test_ga_finance_match_parity.py

Exits 0 on agreement, 1 on any mismatch, 77 (skip) if node is unavailable.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from lib import ga_match as M  # noqa: E402

FINANCE_FILE = os.path.join(ROOT, "assets", "data", "ga-campaign-finance.json")
RACES_FILE = os.path.join(ROOT, "assets", "data", "races.json")
SITE_JS = os.path.join(ROOT, "assets", "scripts", "campaign-finance.js")
EDITOR = os.path.join(ROOT, "tools", "ga-finance-overrides-editor.html")
SKIP_EXIT = 77


def editor_matching_source():
    """The editor's matching block: the code between the 'Matching logic' banner and
    the next banner line, which defines findFilers and touches no DOM."""
    with open(EDITOR, encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r"// Matching logic[^\n]*\n(?://[^\n]*\n)*(.*?)\n// ─{20,}", html, re.S)
    if not m or "function findFilers" not in m.group(1):
        sys.exit("could not find the editor's matching block in " + EDITOR)
    return m.group(1)


HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [siteJs, editorJs, casesPath] = process.argv.slice(2);
const quiet = { log(){}, warn(){}, error(){} };
const site = { window: {}, console: quiet, fetch: () => Promise.reject(new Error('no network')) };
site.globalThis = site;
vm.createContext(site);
vm.runInContext(fs.readFileSync(siteJs, 'utf8'), site, { filename: 'campaign-finance.js' });
const CF = site.window.CampaignFinance;
if (!CF || typeof CF.findGaFilers !== 'function') {
  console.error('campaign-finance.js did not export findGaFilers'); process.exit(2);
}
const ed = { console: quiet };
vm.createContext(ed);
vm.runInContext(fs.readFileSync(editorJs, 'utf8') + '\nthis.findFilers = findFilers;', ed,
                { filename: 'ga-finance-overrides-editor.html' });
const { datasets, cases } = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const out = cases.map(([ds, name, chamber, district]) => {
  const d = datasets[ds];
  return {
    site: CF.findGaFilers(name, chamber, district, d),
    editor: ed.findFilers(name, chamber, district, d.filers, d.bySeat, d.byOffice || {}),
  };
});
process.stdout.write(JSON.stringify(out));
"""


def fixture_dataset():
    """Filers built to hit every branch of the rule."""
    filers = {
        "h1": {"lastName": "Clark", "firstName": "Heather"},
        "h2": {"lastName": "Clark", "firstName": "Thomas"},
        "h3": {"lastName": "O'Steen", "firstName": "Sam"},
        "h4": {"lastName": "Rivera Holmes", "firstName": "Ana"},
        "h5": {"lastName": "Smith", "firstName": "William"},
        "h6": {"lastName": "Smith", "firstName": "Robert"},
        "s1": {"lastName": "Jones", "firstName": "Pat"},
        "p1": {"lastName": "Echols", "firstName": "Tim", "district": "2"},
        "p2": {"lastName": "Hubbard", "firstName": "Peter", "district": "3"},
        "g1": {"lastName": "Lee", "firstName": "Jordan"},
        "g2": {"lastName": "Lee", "firstName": "J"},
    }
    return {
        "filers": filers,
        "bySeat": {"House of Representatives-100": ["h1", "h2", "h3", "h4"],
                   "House of Representatives-101": ["h5", "h6"],
                   "Senate-5": ["s1", "s1"]},
        "byOffice": {"Public Service Commissioner": ["p1", "p2"],
                     "Governor": ["g1", "g2"]},
    }


FIXTURE_CASES = [
    ("Heather Clark", "Georgia House of Representatives", 100),     # tiebreak resolves
    ("H. Clark", "Georgia House of Representatives", 100),          # initial
    ("Chris Clark", "Georgia House of Representatives", 100),       # tiebreak fails: ambiguous
    ("Sam Osteen", "Georgia House of Representatives", 100),        # apostrophe dropped
    ("Sam O'Steen Jr.", "Georgia House of Representatives", 100),   # suffix
    ("Ana Rivera Holmes", "Georgia House of Representatives", 100),  # multi-word surname
    ("Holmes", "Georgia House of Representatives", 100),            # shorter than the surname
    ('William "Bill" Smith', "Georgia House of Representatives", 101),
    ('Bill Smith', "Georgia House of Representatives", 101),         # nickname without the quote
    ('Rob "Bobby" Smith', "Georgia House of Representatives", 101),
    ("Pat Jones", "Georgia State Senate", 5),                       # duplicate id in the pool
    ("Pat Jones", "Georgia State Senate", 6),                       # empty seat
    ("Tim Echols", "Public Service Commissioner", 2),               # districted statewide
    ("Tim Echols", "Public Service Commissioner", 9),               # no filer in district: all
    ("Jordan Lee", "Governor", None),
    ("Jordan Lee", "U.S. House", 5),                                # unmapped chamber
    ("", "Georgia House of Representatives", 100),
    ("Dr. Heather Clark III", "Georgia House of Representatives", 100),
]


def live_cases():
    with open(RACES_FILE, encoding="utf-8") as fh:
        races = json.load(fh).get("races", [])
    out = []
    for race in races:
        if not str(race.get("level") or "").startswith("state"):
            continue
        for phase in (race.get("phases") or {}).values():
            if not isinstance(phase, dict):
                continue
            ballots = phase.get("ballots") or {}
            pool = [c for v in ballots.values() for c in (v or [])] + (phase.get("candidates") or [])
            for c in pool:
                if isinstance(c, dict) and c.get("name"):
                    out.append((c["name"], race.get("chamber"), race.get("district")))
    return sorted(set(out), key=lambda t: (str(t[1]), str(t[2]), t[0]))


def main():
    if not shutil.which("node"):
        print("SKIP: node not on PATH — cannot run the JS side of the parity check")
        return SKIP_EXIT
    with open(FINANCE_FILE, encoding="utf-8") as fh:
        live = json.load(fh)
    fixture = fixture_dataset()

    cases = [("fixture",) + c for c in FIXTURE_CASES] + [("live",) + c for c in live_cases()]
    tmp = tempfile.mkdtemp(prefix="gamatch-")
    try:
        paths = {n: os.path.join(tmp, n) for n in ("h.js", "editor.js", "cases.json")}
        with open(paths["h.js"], "w", encoding="utf-8") as fh:
            fh.write(HARNESS)
        with open(paths["editor.js"], "w", encoding="utf-8") as fh:
            fh.write(editor_matching_source())
        with open(paths["cases.json"], "w", encoding="utf-8") as fh:
            json.dump({"datasets": {"fixture": fixture, "live": live}, "cases": cases}, fh)
        proc = subprocess.run(["node", paths["h.js"], SITE_JS, paths["editor.js"], paths["cases.json"]],
                              capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            print("node failed:\n" + (proc.stderr or "").strip(), file=sys.stderr)
            return 1
        js = json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    datasets = {"fixture": fixture, "live": live}
    mismatches, outcomes = [], {"none": 0, "one": 0, "ambiguous": 0}
    for (ds, name, chamber, district), got in zip(cases, js):
        d = datasets[ds]
        py = M.find_filers(name, chamber, district, d["filers"], d["bySeat"], d.get("byOffice") or {})
        if not (py == got["site"] == got["editor"]):
            mismatches.append((ds, name, chamber, district, py, got["site"], got["editor"]))
        if ds == "live":
            outcomes["none" if not py else "one" if len(py) == 1 else "ambiguous"] += 1

    # The fixture must actually reach the branches it was written for.
    fx = {c[:2]: r for c, r in ((c, M.find_filers(c[0], c[1], c[2], fixture["filers"],
                                                    fixture["bySeat"], fixture["byOffice"]))
                                for c in FIXTURE_CASES)}
    expect = {
        ("Heather Clark", "Georgia House of Representatives"): ["h1"],
        ("Chris Clark", "Georgia House of Representatives"): ["h1", "h2"],
        ("Sam Osteen", "Georgia House of Representatives"): ["h3"],
        ("Ana Rivera Holmes", "Georgia House of Representatives"): ["h4"],
        ("Holmes", "Georgia House of Representatives"): [],
        ('William "Bill" Smith', "Georgia House of Representatives"): ["h5"],
    }
    for key, want in expect.items():
        if fx.get(key) != want:
            mismatches.append(("fixture-expectation", key[0], key[1], None, fx.get(key), want, want))

    n_live = sum(1 for c in cases if c[0] == "live")
    print(f"Compared {len(cases)} cases ({len(FIXTURE_CASES)} fixtures, {n_live} live state candidates): "
          f"{outcomes['one']} matched, {outcomes['ambiguous']} ambiguous, {outcomes['none']} no filer.")
    if mismatches:
        print(f"\nFAIL: {len(mismatches)} disagreement(s):\n")
        for ds, name, chamber, district, py, site, editor in mismatches[:40]:
            print(f"  [{ds}] {name!r} {chamber} {district}\n"
                  f"      python={py}\n      site  ={site}\n      editor={editor}")
        return 1
    print("All three agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
