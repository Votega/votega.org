#!/usr/bin/env python3
"""Offline checks for scripts/only_keys_changed.py, the commit steps' timestamp-only skip.

Exit 0 tells a workflow to skip its commit, so the dangerous mistake is a false 0:
dropping a real data change. Each case builds a throwaway git repository, commits a
JSON file, edits it, and runs the script there. Exits 0 on success, 1 on failure.

Usage:
  python scripts/test_only_keys_changed.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "only_keys_changed.py")
failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                    "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True)


def run(repo, path, *keys):
    return subprocess.run([sys.executable, SCRIPT, path, *keys], cwd=repo,
                          capture_output=True).returncode


def write(repo, path, obj_or_text):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, indent=2))


BASE = {"metadata": {"generatedAt": "2026-11-01", "source": "x", "nested": {"at": "t1"}},
        "items": [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]}


def case(label, edited, keys, want, path="data/file.json"):
    repo = tempfile.mkdtemp()
    try:
        git(repo, "init", "-q")
        write(repo, path, BASE)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        write(repo, path, edited)
        check(label, run(repo, path, *keys), want)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def edit(fn):
    d = json.loads(json.dumps(BASE))
    fn(d)
    return d


def main():
    if not shutil.which("git"):
        print("git not found; skipping")
        return 77

    print("skip the commit (exit 0)")
    case("an unchanged file", BASE, ["metadata.generatedAt"], 0)
    case("only the named key moved",
         edit(lambda d: d["metadata"].update(generatedAt="2026-11-26")), ["metadata.generatedAt"], 0)
    case("only a nested named key moved",
         edit(lambda d: d["metadata"]["nested"].update(at="t2")), ["metadata.nested.at"], 0)
    case("two named keys moved",
         edit(lambda d: (d["metadata"].update(generatedAt="z"), d["metadata"]["nested"].update(at="z"))),
         ["metadata.generatedAt", "metadata.nested.at"], 0)
    case("reformatting alone is not a change", json.dumps(BASE, separators=(",", ":")),
         ["metadata.generatedAt"], 0)

    print("commit (exit 1)")
    case("a data change alongside the timestamp",
         edit(lambda d: (d["metadata"].update(generatedAt="z"), d["items"][0].update(v="changed"))),
         ["metadata.generatedAt"], 1)
    case("a change to a different metadata key",
         edit(lambda d: d["metadata"].update(source="y")), ["metadata.generatedAt"], 1)
    case("a dropped item", edit(lambda d: d["items"].pop()), ["metadata.generatedAt"], 1)
    case("a key path that is not there protects nothing",
         edit(lambda d: d["items"][0].update(v="changed")), ["metadata.missing"], 1)
    case("a sibling key with a similar name still counts",
         edit(lambda d: d["metadata"].update(generatedAtUtc="new")), ["metadata.generatedAt"], 1)
    case("a working file that is not JSON", "{not json", ["metadata.generatedAt"], 1)

    repo = tempfile.mkdtemp()
    try:
        git(repo, "init", "-q")
        write(repo, "seed.txt", "x")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        write(repo, "data/new.json", BASE)
        check("a file HEAD does not have", run(repo, "data/new.json", "metadata.generatedAt"), 1)
        os.remove(os.path.join(repo, "data", "new.json"))
        check("a file that does not exist at all", run(repo, "data/new.json", "metadata.generatedAt"), 1)
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
