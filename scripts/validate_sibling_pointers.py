#!/usr/bin/env python3
"""Verify that every file a sibling repo's own index names actually exists there.

The sibling repos (Votega/ga-legislators and the rest) are read by consumers through
their index files: the root latest.json / scorecard-latest.json pointers and the
per-dataset data/**/manifest.json. A publisher builds those pointers from its own
idea of what has been published, and nothing compared the two. latest.json's
rosterArchive is the case that prompted this: it named
sessions/<current biennium>/members.json unconditionally, which after a rollover
would have pointed at a file that does not exist for about two years
(Votega/votega.org#513).

validate_open_data_links.py checks the site's /open-data catalog; this checks what
the repos say about themselves. Both run from the weekly
validate-open-data-links.yml, since the change that breaks a pointer can land in
any repo.

For each repo: one git-trees call for the full file list, then every index file is
read from raw.githubusercontent.com and each string in it that looks like a
repo-relative file path (no scheme, a data or doc extension, no <placeholder>) must
be in the tree, either as written or relative to the index file's folder. A `null`
pointer is fine: that is how a publisher says "nothing here yet".

Exits 1 and lists every dangling path. Never passes vacuously: a run that could not
read any repo fails. Usage:
    python scripts/validate_sibling_pointers.py [repo ...]
Set GITHUB_TOKEN for the trees calls (60 an hour unauthenticated is enough for a
manual run).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

OWNER = "Votega"
REPOS = ["ga-legislators", "ga-federal-legislators", "ga-legislation",
         "ga-executive-orders", "ga-local-government", "ga-races-elections",
         "ga-district-information"]
TIMEOUT = 30
PATHLIKE = re.compile(r"^(?![a-z][a-z0-9+.-]*:)(?!/)[\w.\-/]+\.(json|csv|md|geojson|topojson|txt)$",
                      re.IGNORECASE)
#: Index files: the root pointers, and every dataset manifest.
INDEX = re.compile(r"^(latest\.json|[\w-]+-latest\.json|data/(.+/)?manifest\.json)$")


def strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)
    elif isinstance(obj, str):
        yield obj


def index_files(tree_paths):
    return sorted(p for p in tree_paths if INDEX.match(p))


def dangling(doc, tree_paths, index_path):
    """Path-like strings in doc that name no file in the repo."""
    base = index_path.rsplit("/", 1)[0] + "/" if "/" in index_path else ""
    out = set()
    for s in strings(doc):
        if not PATHLIKE.match(s):
            continue
        if s in tree_paths or (base + s) in tree_paths:
            continue
        out.add(s)
    return sorted(out)


def _get(url, token=None):
    headers = {"User-Agent": "votega-sibling-pointer-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=TIMEOUT) as resp:
        return resp.read()


def check_repo(repo, get=_get, token=None):
    """(index files read, [(index, missing path)]). Raises on a request failure."""
    tree = json.loads(get(f"https://api.github.com/repos/{OWNER}/{repo}/git/trees/main?recursive=1",
                          token))
    if tree.get("truncated"):
        raise RuntimeError(f"{repo}: git tree truncated; cannot check every path")
    paths = {t["path"] for t in tree["tree"] if t["type"] == "blob"}
    problems, read = [], 0
    for idx in index_files(paths):
        doc = json.loads(get(f"https://raw.githubusercontent.com/{OWNER}/{repo}/main/{idx}"))
        read += 1
        problems += [(idx, p) for p in dangling(doc, paths, idx)]
    return read, problems


def main(argv=None, get=_get):
    repos = (argv if argv is not None else sys.argv[1:]) or REPOS
    token = os.environ.get("GITHUB_TOKEN")
    broken, unreachable, read_total = [], [], 0
    for repo in repos:
        try:
            read, problems = check_repo(repo, get, token)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            unreachable.append((repo, exc))
            print(f"  ???  {repo}: {exc}")
            continue
        read_total += read
        print(f"  {'FAIL' if problems else 'ok  '} {repo}: {read} index file(s)"
              + (f", {len(problems)} dangling path(s)" if problems else ""))
        broken += [(repo, idx, p) for idx, p in problems]

    if broken:
        print(f"\n{len(broken)} path(s) named by an index file but not in the repo:\n")
        for repo, idx, p in broken:
            print(f"  {OWNER}/{repo}  {idx}  ->  {p}")
        print("\nFix the publisher that writes that index (scripts/publish_*.py): point it at a "
              "file that exists, or write null until the file is published.")
        return 1
    if unreachable and read_total == 0:
        print("\nERROR: no repo could be read. Treating as a failed check, not a pass.")
        return 1
    if unreachable:
        print(f"\nWARNING: {len(unreachable)} repo(s) could not be read (network, not the data).")
    print(f"\nEvery path in {read_total} index file(s) resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
