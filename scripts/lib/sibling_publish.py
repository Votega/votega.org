"""Shared helper for publishing generated artifacts to a sibling GitHub repo.

Each `publish_*_*.py` generator builds an in-memory dict of {remote_path: bytes} and
hands it here. With the repo's token env var set, every artifact is PUT via the GitHub
Contents API; without it, the script runs as a DRY RUN, writing the artifacts under
$OUT_DIR (default ./out) so the generators can be exercised locally.

Keeping this in one place means every sibling-repo publisher shares identical, tested
publishing/dry-run behavior — the only per-repo differences are the artifacts themselves.
"""
import base64
import json
import os
import urllib.error
import urllib.request


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
    """Publish `artifacts` to `repo` if os.environ[token_env] is set, else dry-run to disk."""
    token = os.environ.get(token_env)
    if token:
        print(f"Publishing {len(artifacts)} artifacts to {repo}:")
        _publish(repo, artifacts, token)
    else:
        out_dir = os.environ.get("OUT_DIR", "out")
        print(f"DRY RUN (no {token_env}) — writing {len(artifacts)} artifacts to {out_dir}/:")
        _dry_run(artifacts, out_dir)
    print("Done.")
