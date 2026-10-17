#!/usr/bin/env python3
"""Assert generate_search_corpus.py fails on a missing SOURCE, not a thin index.

The generator used to refuse to write when it had fewer than 200 records:

    if len(records) < MIN_RECORDS:
        print("FATAL: ... refusing to write a likely-broken index.")
        sys.exit(1)

That is the same `count >= 200` floor the workflow's heredoc carried, sitting
one step upstream — so splitting the validator into tiers changed nothing while
this remained, and because it exits BEFORE the write there was no file for the
workflow's upload-artifact step to rescue either.

It also never caught what it was written for. Each source contributes a few
hundred records at most, so losing one entirely still clears 200: dropping all
236 GA legislators leaves 1,174. The precise check is whether a source FAILED
TO LOAD, which `load()` now records, and that stays fatal — no fact about
Georgia makes ga-members.json absent.

Usage:
  python scripts/test_search_corpus_sources.py

Exits 0 on success, 1 on any failure. No network, and the real data files are
never written to.
"""

import io
import os
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_search_corpus as G  # noqa: E402

# run-script-tests.yml installs no pip packages on purpose, so this module must
# import without pyyaml or this whole suite dies there with ModuleNotFoundError
# while passing locally. It did, once. The check below reproduces that
# environment rather than trusting that the import stayed lazy.
# The finder implements find_spec, NOT the legacy find_module/load_module pair:
# Python 3.12 removed those from the import system, so a find_module-based
# blocker silently blocks nothing and this check passes however the import is
# written. Verified by putting the module-level import back and watching this
# fail.
# Running the suite under a yaml blocker is the only way to catch this locally:
# this machine HAS pyyaml, so every case passes here no matter where the import
# sits, and CI is the first thing to notice. It noticed twice — once for a
# module-level `import yaml`, then again when the lazy import was placed above
# the exists() check in build_places(), so the branch that records a missing
# registry raised ModuleNotFoundError. So the whole suite re-runs itself with
# yaml unavailable rather than only checking that the module imports.
RUN_WITHOUT_YAML = """
import runpy, sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name == "yaml" or name.startswith("yaml."):
            raise ImportError("No module named 'yaml'")
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, %r)
sys.argv = [%r]
runpy.run_path(%r, run_name="__main__")
"""

# Set in the child so it runs the cases without spawning another child.
CHILD_ENV = "VOTEGA_SEARCH_CORPUS_NO_YAML"

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def rerun_without_yaml():
    """Run every case again in a child that cannot import yaml, as CI cannot."""
    me = os.path.abspath(__file__)
    here = os.path.dirname(me)
    env = {**os.environ, CHILD_ENV: "1"}
    proc = subprocess.run(
        [sys.executable, "-c", RUN_WITHOUT_YAML % (here, me, me)],
        capture_output=True, text=True, env=env)
    check("every case still passes with pyyaml unavailable "
          "(run-script-tests.yml installs none)", proc.returncode, 0)
    if proc.returncode != 0:
        for line in (proc.stdout + proc.stderr).strip().splitlines()[-4:]:
            print("       " + line)


def cases():
    # The floor is gone as a gate, and survives only as a threshold to report.
    check("the refuse-to-write floor is gone",
          hasattr(G, "MIN_RECORDS"), False)
    check("a thin-index reporting threshold remains",
          getattr(G, "THIN_INDEX", None), 200)

    # load() must RECORD a miss, not just print it: every caller returns early
    # on None and contributes nothing, so a silent miss is a whole category
    # disappearing from site search.
    G.missing_sources.clear()
    err = io.StringIO()
    with redirect_stderr(err):
        got = G.load("definitely-not-a-real-file.json")
    check("a missing source returns None", got, None)
    check("...and is recorded, not merely printed",
          G.missing_sources, ["definitely-not-a-real-file.json"])
    check("...and still says so on stderr",
          "not found" in err.getvalue(), True)

    # A real source still loads and records nothing.
    G.missing_sources.clear()
    data = G.load("ga-members.json")
    check("a present source loads", bool(data and data.get("members")), True)
    check("...and records no miss", G.missing_sources, [])

    # places.yml bypasses load(), so it needs its own wiring. Point the
    # registry directory at somewhere without one.
    G.missing_sources.clear()
    real_dir = G.JEKYLL_DATA_DIR
    try:
        G.JEKYLL_DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "_no_such_dir"
        with redirect_stderr(io.StringIO()):
            G.build_places([], set())
        check("a missing places.yml is recorded too",
              G.missing_sources, ["places.yml"])
    finally:
        G.JEKYLL_DATA_DIR = real_dir
        G.missing_sources.clear()

    # Guard the fixture: the real registry must exist, or the case above proves
    # nothing about the wiring.
    check("the real places.yml is where the generator looks for it",
          (G.JEKYLL_DATA_DIR / "places.yml").exists(), True)

    # current-members.json and ga-members.json are each read by two builders, so
    # one absent file is recorded twice. The fatal message must not report it as
    # two problems and send a reader hunting for a second one.
    G.missing_sources.clear()
    err = io.StringIO()
    with redirect_stderr(err):
        G.load("ga-members-but-missing.json")
        G.load("ga-members-but-missing.json")
    check("a source read twice is recorded twice", len(G.missing_sources), 2)
    check("...but de-duplicates to one name",
          sorted(set(G.missing_sources)), ["ga-members-but-missing.json"])
    G.missing_sources.clear()


def main():
    child = os.environ.get(CHILD_ENV) == "1"
    print("generate_search_corpus: sources vs record count"
          + (" [pyyaml blocked]" if child else "") + ":")
    cases()
    if not child:
        rerun_without_yaml()
    if failures:
        print(f"\nFAIL: {len(failures)} case(s) failed")
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
