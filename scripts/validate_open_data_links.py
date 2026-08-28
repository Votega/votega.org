#!/usr/bin/env python3
"""Verify every file link in _data/open_data.yml actually resolves.

The /open-data catalog is hand-maintained but points at machine-generated
artifacts in the sibling repos. When a publisher moves a file — as the
sessions/ migration moved ga-bills.json to sessions/<slug>/bills.json — the
catalog keeps advertising the old path and quietly serves 404s from a page
that is in the site navbar. This script closes that loop.

Checks, by URL shape:
  https://github.com/<owner>/<repo>/blob/<ref>/<path>
        -> HEAD the equivalent raw.githubusercontent.com URL
  https://github.com/<owner>/<repo>            (repo root, no file)
        -> HEAD the repo's README on raw
  /assets/data/<file>                          (served from this site)
        -> check the file exists in the working tree

Exits 1 and lists every broken link. Usage:
    python scripts/validate_open_data_links.py [--yaml _data/open_data.yml]
"""
import argparse
import re
import sys
import urllib.error
import urllib.request

BLOB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
REPO = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/?$")
RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
TIMEOUT = 20


def head(url):
    """Return the HTTP status for url, or 0 if the request could not be made."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


def resolve(url, repo_root):
    """Map a catalog URL to (check_description, status, is_remote).

    status 200 == good; status 0 == the request could not be made at all.
    is_remote says whether the check needed the network, so a caller can tell
    "everything verified" from "nothing could be reached".
    """
    m = BLOB.match(url)
    if m:
        owner, repo, ref, path = m.groups()
        raw = RAW.format(owner=owner, repo=repo, ref=ref, path=path)
        return raw, head(raw), True

    m = REPO.match(url)
    if m:
        owner, repo = m.groups()
        raw = RAW.format(owner=owner, repo=repo, ref="main", path="README.md")
        return raw, head(raw), True

    if url.startswith("/"):
        local = repo_root / url.lstrip("/")
        return str(local), 200 if local.is_file() else 404, False

    return url, head(url), True


def main():
    import pathlib

    import yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", default="_data/open_data.yml")
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    catalog = yaml.safe_load((root / args.yaml).read_text())

    broken = []      # resolved, but the file is not there (a real catalog bug)
    unreachable = []  # the request itself failed (network/proxy — not the catalog)
    ok = 0
    remote_ok = 0
    for ds in catalog.get("datasets", []):
        did = ds.get("id", "?")
        urls = [(f.get("name", "?"), f.get("url", "")) for f in ds.get("files", [])]
        if ds.get("repo_url"):
            urls.append(("repo_url", ds["repo_url"]))
        for name, url in urls:
            if not url:
                broken.append((did, name, url, "no url in catalog entry", 0))
                continue
            target, status, is_remote = resolve(url, root)
            if status == 200:
                ok += 1
                remote_ok += is_remote
                print(f"  ok   [200] {did} :: {name}")
            elif status == 0:
                unreachable.append((did, name, url, target, status))
                print(f"  ???  [ERR] {did} :: {name}  (could not reach)")
            else:
                broken.append((did, name, url, target, status))
                print(f"  FAIL [{status}] {did} :: {name}")

    total = ok + len(broken) + len(unreachable)
    print(f"\nChecked {total} link(s) in {args.yaml}: "
          f"{ok} ok, {len(broken)} broken, {len(unreachable)} unreachable.")

    if broken:
        print(f"\n{len(broken)} broken link(s):\n")
        for did, name, url, target, status in broken:
            print(f"  {did} :: {name}")
            print(f"      catalog url: {url}")
            print(f"      resolved to: {target}")
            print(f"      status:      {status}\n")
        print("Fix _data/open_data.yml, or the publisher that moved the file.")
        return 1

    # Never pass vacuously. Local /assets/data checks need no network, so they
    # must not mask a run in which every remote link failed to resolve.
    if remote_ok == 0 and unreachable:
        print("\nERROR: no link could be verified — treating as a failed check "
              "rather than a pass. Check network/proxy access to "
              "raw.githubusercontent.com.")
        return 1

    if unreachable:
        print(f"\nWARNING: {len(unreachable)} link(s) could not be reached "
              f"(network, not the catalog). Not failing, since {ok} other "
              f"link(s) verified fine:")
        for did, name, url, _, _ in unreachable:
            print(f"  {did} :: {name} — {url}")

    print("\nAll reachable catalog links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
