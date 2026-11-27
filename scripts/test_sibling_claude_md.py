#!/usr/bin/env python3
"""The CLAUDE.md every sibling repo carries (lib/sibling_publish.claude_md).

Pins: every publish_*.py that writes a Votega/* repo is listed for that repo in
REPO_PUBLISHERS, every listed script exists, every repo with a NOTICE.md source has
publishers and the reverse, the file names its repo and publishers and is the same
bytes whichever publisher writes it, and publish_or_dry_run injects it without
overriding a caller's own copy.

Usage: python scripts/test_sibling_claude_md.py     (no network, no repo writes)
"""
import glob
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import sibling_publish as SP  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


# --- the registry matches the scripts -----------------------------------------
writes = {}
for path in sorted(glob.glob(os.path.join(HERE, "publish_*.py"))):
    m = re.search(r'^REPO\s*=\s*"(Votega/[A-Za-z0-9_.-]+)"', open(path, encoding="utf-8").read(), re.M)
    if m:
        writes.setdefault(m.group(1), []).append(os.path.basename(path))
for repo, scripts in writes.items():
    for script in scripts:
        check("%s lists %s" % (repo, script), script in SP.REPO_PUBLISHERS.get(repo, []), True)
for repo, scripts in SP.REPO_PUBLISHERS.items():
    for script in scripts:
        check("%s exists" % script, os.path.exists(os.path.join(HERE, script)), True)
check("same repos as REPO_SOURCES", sorted(SP.REPO_PUBLISHERS), sorted(SP.REPO_SOURCES))

# --- content ------------------------------------------------------------------
text = SP.claude_md("Votega/ga-legislation").decode()
check("names the repo", text.startswith("# Votega/ga-legislation:"), True)
check("names both publishers", ("`scripts/publish_ga_bills.py`" in text,
                                "`scripts/publish_ga_ballot_measures.py`" in text), (True, True))
check("points at the conventions", "docs/conventions-publishing.md" in text, True)
check("README and CHANGES are hand-maintained", ("`README.md` at the root" in text, "`CHANGES.md` at the root" in text),
      (True, True))
check("credits the upstream", "legis.ga.gov" in text, True)
check("no unfilled placeholder", re.search(r"\{[a-z_]+\}", text), None)
try:
    SP.claude_md("Votega/not-registered")
    check("unregistered repo refused", False, True)
except KeyError:
    pass

# --- injection ------------------------------------------------------------------
os.environ.pop("GITHUB_ACTIONS", None)
with tempfile.TemporaryDirectory() as out:
    os.environ["OUT_DIR"] = out
    SP.publish_or_dry_run("Votega/ga-legislation", {"data/x.json": b"{}"}, "NO_SUCH_TOKEN_ENV")
    check("dry run writes CLAUDE.md", open(os.path.join(out, "CLAUDE.md"), "rb").read(),
          SP.claude_md("Votega/ga-legislation"))
with tempfile.TemporaryDirectory() as out:
    os.environ["OUT_DIR"] = out
    SP.publish_or_dry_run("Votega/ga-legislation", {"data/x.json": b"{}", "CLAUDE.md": b"own"},
                          "NO_SUCH_TOKEN_ENV")
    check("a caller's own copy wins", open(os.path.join(out, "CLAUDE.md"), "rb").read(), b"own")
os.environ.pop("OUT_DIR", None)

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
