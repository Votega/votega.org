#!/usr/bin/env python3
"""
Find `on: push: paths:` triggers that can never fire.

GitHub does not start a workflow run for a commit authored by the default
GITHUB_TOKEN — the recursion guard documented in update-ga-bills.yml. Every
scheduled data workflow in this repo commits with it. So a `paths:` trigger that
watches a file only ever written by one of those workflows is dead code, and it
fails the way dead code in CI always does: silently, looking exactly like
"nothing needed publishing".

It had happened three times before this script existed. The federal-delegation
publisher had run 4 times in two months while its inputs updated daily; the
executive-order publisher was being dispatched by hand after every bot commit;
and deploy-pages had 326 runs without a single one on a bot commit, so the
public site only refreshed when a human happened to push something.

A watched path is reported only when all of these hold, because a partly-dead
trigger is normal and fine:

  * the path is a generated data file (a script is human-edited, so watching it
    is a live trigger)
  * some other workflow commits that path
  * that workflow does not already run the same publish script itself — the
    established fix, used by update-ga-bills.yml and update-ga-votes.yml long
    before this script existed
  * the watching workflow has no schedule of its own to fall back on

So a trigger that fires for human edits and is *also* covered for bot writes is
not a finding. Only an actual gap is.

Usage:
    python scripts/validate_workflow_triggers.py           # report, exit 1 if any
    python scripts/validate_workflow_triggers.py --list    # report, always exit 0
"""

import fnmatch
import re
import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(".github/workflows")

# A path a workflow adds to git. `git add -f assets/data/x.json` and
# `git add assets/data/y-*.json assets/data/dir` both count.
GIT_ADD = re.compile(r"git\s+add\s+(?:-f\s+)?(?P<paths>[^\n;&|]+)")


def workflow_files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def load(path):
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        print(f"  ! {path.name}: unparseable ({exc})", file=sys.stderr)
        return {}


def triggers(doc):
    """`on:` is parsed by PyYAML as the boolean True, not the string 'on'."""
    return doc.get(True) or doc.get("on") or {}


def committed_paths(path, doc):
    """Every path this workflow writes back to the repo."""
    written = set()
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            for match in GIT_ADD.finditer(step.get("run") or ""):
                for token in match.group("paths").split():
                    if token.startswith("-"):
                        continue
                    written.add(token.strip("'\""))
    return written


def is_generated(watched):
    """A script is human-edited, so watching it is a live trigger. A data file
    under assets/data or _data may well not be."""
    return watched.startswith(("assets/data/", "_data/"))


PUBLISH_SCRIPT = re.compile(r"scripts/(publish_[a-z0-9_]+\.py)")


def publish_scripts(doc):
    """The publish scripts a workflow runs."""
    found = set()
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            found |= set(PUBLISH_SCRIPT.findall(step.get("run") or ""))
    return found


def has_schedule(doc):
    return bool(triggers(doc).get("schedule"))


def writes_to_main(doc):
    """A workflow that only runs on pull_request commits to the PR head branch,
    never to main, so it cannot be what a `branches: [main]` trigger missed.
    sync-generated-data-on-pr.yml is the one such writer here."""
    on = triggers(doc)
    return set(on) != {"pull_request"}


def matches(watched, written):
    """Does a committed path satisfy this watched pattern (either direction)?"""
    return (fnmatch.fnmatch(written, watched)
            or fnmatch.fnmatch(watched, written)
            or written.rstrip("/*").startswith(watched.rstrip("/*"))
            or watched.rstrip("/*").startswith(written.rstrip("/*")))


def main():
    list_only = "--list" in sys.argv

    docs = {path: load(path) for path in workflow_files()}
    writers = {path: committed_paths(path, doc) for path, doc in docs.items()}

    findings = []
    for path, doc in docs.items():
        push = (triggers(doc).get("push") or {})
        if not isinstance(push, dict):
            continue
        if has_schedule(doc):
            continue                       # a schedule covers what push misses
        mine = publish_scripts(doc)
        for watched in push.get("paths") or []:
            if not is_generated(watched):
                continue
            uncovered = sorted(
                other.name for other, written in writers.items()
                if other != path
                and writes_to_main(docs[other])
                and any(matches(watched, w) for w in written)
                # Covered when the producer publishes the same artifact itself.
                and not (mine & publish_scripts(docs[other]))
            )
            if uncovered:
                findings.append((path.name, watched, uncovered))

    if not findings:
        print(f"Checked {len(docs)} workflows — every push/paths trigger on a "
              f"bot-written file is covered by an inline publish or a schedule.")
        return 0

    print(f"{len(findings)} push trigger(s) watch a file that another workflow "
          f"commits, with nothing else covering it. A commit authored by "
          f"GITHUB_TOKEN does not fire `push`, so those writes go unpublished:\n")
    for name, watched, culprits in findings:
        print(f"  {name}")
        print(f"      watches: {watched}")
        print(f"      written by: {', '.join(culprits)}")
    print("\nFix by publishing from the producing workflow (see the inline publish "
          "step in update-current-members.yml), or by adding a schedule.")
    return 0 if list_only else 1


if __name__ == "__main__":
    sys.exit(main())
