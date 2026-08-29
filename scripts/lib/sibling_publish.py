"""Shared helper for publishing generated artifacts to a sibling GitHub repo.

Each `publish_*_*.py` generator builds an in-memory dict of {remote_path: bytes} and
hands it here. With the repo's token env var set, every artifact is PUT via the GitHub
Contents API; without it, the script runs as a DRY RUN, writing the artifacts under
$OUT_DIR (default ./out) so the generators can be exercised locally.

Keeping this in one place means every sibling-repo publisher shares identical, tested
publishing/dry-run behavior — the only per-repo differences are the artifacts themselves.

Every publish also carries the reuse terms (LICENSE + NOTICE.md), injected here rather
than hand-maintained in each sibling repo. Five hand-copied LICENSE files silently drifted
to GPL-3.0 while /open-data promised attribution-only reuse; emitting them from one place
means the license is stated once and cannot diverge again.
"""
import base64
import json
import os
import urllib.error
import urllib.request

# The upstream each sibling repo credits. Keyed by TARGET REPO, not by publisher:
# two publishers write to ga-legislation (bills and ballot measures), and if each
# supplied its own upstream name they would rewrite NOTICE.md against each other on
# every run — the churn this file exists to avoid.
REPO_SOURCES = {
    "Votega/ga-legislators": "the Open States API (Plural Policy)",
    "Votega/ga-legislation": "the Open States API (Plural Policy), the Georgia "
                             "Secretary of State, and the Georgia General Assembly",
    "Votega/ga-federal-legislators": "Congress.gov, the Clerk of the U.S. House, "
                                     "and the U.S. Senate",
    "Votega/ga-races-elections": "the Georgia Secretary of State",
    "Votega/ga-executive-orders": "the Office of the Governor of Georgia "
                                  "(gov.georgia.gov)",
}

# Published under CC BY 4.0: a data license, matching the attribution /open-data asks
# of reusers. LICENSE carries the canonical, unmodified legalcode so GitHub detects the
# license; the attribution string reusers actually need lives in NOTICE.md beside it.
LICENSE_SPDX = "CC-BY-4.0"
LICENSE_NAME = "Creative Commons Attribution 4.0 International"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
_LICENSE_PATH = os.path.join(os.path.dirname(__file__), "LICENSE-CC-BY-4.0.txt")

NOTICE_TEMPLATE = """\
# Reuse and attribution

The data in this repository is published by [VoteGA.org](https://votega.org) under the
[{name}]({url}) license (`{spdx}`). The full legalcode is in [LICENSE](LICENSE).

You are free to share and adapt this data, including commercially, provided you give
appropriate credit.

## How to credit

> Data from [VoteGA.org](https://votega.org), licensed under [CC BY 4.0]({url}).
> Original source: {source}.

## Two things the license does not cover

- **Upstream terms.** VoteGA's license covers the compilation, cleaning, and joins in this
  repository. The underlying facts come from {source}, whose own terms may apply to
  anything you redistribute — verify them independently.
- **Accuracy.** The data is provided as is, with no warranty. Spotted an error? Open an
  issue on this repository, or email admin@votega.org.

## Provenance

Generated and published automatically from <https://github.com/Votega/votega.org>.
Do not edit files here by hand — the next publish overwrites them.
"""


def license_artifacts(repo):
    """Reuse-terms artifacts every sibling repo carries, keyed by target repo."""
    source = REPO_SOURCES.get(repo)
    if source is None:
        raise KeyError(
            f"No upstream source registered for {repo!r}. Add it to "
            "REPO_SOURCES in scripts/lib/sibling_publish.py so the published "
            "NOTICE.md credits the right upstream."
        )
    with open(_LICENSE_PATH, "rb") as f:
        license_bytes = f.read()
    notice = NOTICE_TEMPLATE.format(
        name=LICENSE_NAME, url=LICENSE_URL, spdx=LICENSE_SPDX, source=source
    )
    return {"LICENSE": license_bytes, "NOTICE.md": notice.encode()}


def build_json(obj):
    """Serialize an object to indented UTF-8 JSON bytes (human-readable on GitHub)."""
    return json.dumps(obj, ensure_ascii=False, indent=1).encode()


def _publish(repo, artifacts, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    for remote_path, data in artifacts.items():
        url = f"https://api.github.com/repos/{repo}/contents/{remote_path}"
        sha = None
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
                sha = json.loads(resp.read())["sha"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        body = {
            "message": f"Publish {remote_path} from votega.org",
            "content": base64.b64encode(data).decode(),
        }
        if sha:
            body["sha"] = sha
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="PUT", headers=headers)
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"  published {remote_path}: {result['commit']['sha'][:9]}")


def _dry_run(artifacts, out_dir):
    for remote_path, data in artifacts.items():
        dest = os.path.join(out_dir, remote_path)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        print(f"  wrote {dest} ({len(data):,} bytes)")


def publish_or_dry_run(repo, artifacts, token_env):
    """Publish `artifacts` to `repo` if os.environ[token_env] is set, else dry-run to disk.

    The reuse terms (LICENSE + NOTICE.md) are injected here, so no publisher can omit
    them and all publishers targeting one repo emit byte-identical copies. A caller that
    supplies its own LICENSE or NOTICE.md keeps it.
    """
    for path, data in license_artifacts(repo).items():
        artifacts.setdefault(path, data)
    token = os.environ.get(token_env)
    if token:
        print(f"Publishing {len(artifacts)} artifacts to {repo}:")
        _publish(repo, artifacts, token)
    else:
        out_dir = os.environ.get("OUT_DIR", "out")
        print(f"DRY RUN (no {token_env}) — writing {len(artifacts)} artifacts to {out_dir}/:")
        _dry_run(artifacts, out_dir)
    print("Done.")
