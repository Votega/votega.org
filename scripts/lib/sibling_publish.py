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
import re
import time
import urllib.error
import urllib.request

# Retry the GitHub Contents API on transient failures only, per the project's
# retry convention (CLAUDE.md): HTTP 429 and 5xx are retryable; 4xx (e.g. 404,
# 422) are not and propagate immediately. Without this, a single transient 500
# from the API aborts a multi-file publish partway through — and since LICENSE
# and NOTICE.md are appended last, a mid-run failure would leave them unwritten.
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 5
# urlopen has no timeout by default, so one stalled connection hung the publish for
# as long as the job was allowed to run. Per-socket-operation, not total: generous
# enough for a multi-MB contents-API PUT.
_TIMEOUT_SECONDS = 120


def _urlopen_retry(req):
    """urlopen(req), retrying transient 429/5xx and network errors with backoff.

    Returns the response body bytes. Non-retryable HTTPErrors (404, 422, …) are
    raised on the first occurrence so callers can handle them (e.g. 404 = file
    does not exist yet). The final attempt's error is always raised.
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            # A read timeout surfaces as a bare TimeoutError rather than a URLError.
            if attempt == _MAX_ATTEMPTS - 1:
                raise
        time.sleep(2 ** attempt)

# The upstream each sibling repo credits. Keyed by TARGET REPO, not by publisher:
# two publishers write to ga-legislation (bills and ballot measures), and if each
# supplied its own upstream name they would rewrite NOTICE.md against each other on
# every run — the churn this file exists to avoid.
REPO_SOURCES = {
    # Single upstream since the roster moved off Open States (2026-10, spec Phase 1):
    # the roster, the roll-call votes and the party-unity scorecard all now derive from
    # the General Assembly's own service. Open States is no longer an upstream for any
    # FACT in this repo — the OCD person ids it minted are carried as a cross-reference
    # in the `id` field, which is a reference to their catalogue, not data taken from it.
    "Votega/ga-legislators": "the Georgia General Assembly (legis.ga.gov)",
    # Bills moved to the General Assembly's own service in 2026-10; Open States
    # remains a real upstream only for the frozen topical-subject snapshot
    # (ga-bills-subjects-base.json), so it stays credited but no longer leads.
    "Votega/ga-legislation": "the Georgia General Assembly (legis.ga.gov), the "
                             "Georgia Secretary of State, and the Open States API "
                             "(Plural Policy) for topical subject tags",
    "Votega/ga-federal-legislators": "Congress.gov, the Clerk of the U.S. House, "
                                     "and the U.S. Senate",
    # The early-vote/ folder also carries county Census figures (ACS, compiled by Georgia Civic Data, CC BY 4.0).
    "Votega/ga-races-elections": "the Georgia Secretary of State; the county Census figures in early-vote/ come from "
                                 "the U.S. Census Bureau's American Community Survey, compiled by Georgia Civic Data "
                                 "(georgiacivicdata.org, CC BY 4.0)",
    "Votega/ga-executive-orders": "the Office of the Governor of Georgia "
                                  "(gov.georgia.gov)",
    "Votega/ga-local-government": "the published agendas and minutes of Georgia "
                                  "county and municipal governments",
    # Every figure here is derived: HUD's ZIP crosswalk supplies the ZIP -> tract
    # address shares, and the district and population facts come from the General
    # Assembly's own plan files and the Census Bureau's 2020 block counts.
    "Votega/ga-district-information": "the Georgia General Assembly's Office of Legislative and "
                                      "Congressional Reapportionment (2023 district plans), the "
                                      "U.S. Census Bureau (2020 Census block populations), the U.S. "
                                      "Department of Housing and Urban Development (HUD-USPS ZIP "
                                      "Code Crosswalk) and the U.S. Postal Service",
}

# Published under CC BY-SA 4.0: a data license, matching the attribution + share-alike
# /open-data asks of reusers. LICENSE carries the canonical, unmodified legalcode so
# GitHub detects the license; the attribution string reusers actually need lives in
# NOTICE.md beside it.
LICENSE_SPDX = "CC-BY-SA-4.0"
LICENSE_NAME = "Creative Commons Attribution-ShareAlike 4.0 International"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
_LICENSE_PATH = os.path.join(os.path.dirname(__file__), "LICENSE-CC-BY-SA-4.0.txt")

NOTICE_TEMPLATE = """\
# Reuse and attribution

The data in this repository is published by [VoteGA.org](https://votega.org) under the
[{name}]({url}) license (`{spdx}`). The full legalcode is in [LICENSE](LICENSE).

You are free to share and adapt this data, including commercially, provided you give
appropriate credit and license any adaptations you distribute under the same terms
(CC BY-SA 4.0).

## How to credit

> Source: VoteGA.org (https://www.votega.org), CC BY-SA 4.0.
> Data from [VoteGA.org](https://votega.org), licensed under [CC BY-SA 4.0]({url}).
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


# ---------------------------------------------------------------------------
# Dataset manifests
# ---------------------------------------------------------------------------
# WHY THESE EXIST
#
# Three sibling repos are written by TWO publishers each — ga-legislation
# (bills + ballot measures), ga-local-government (agenda mentions + millage) and
# ga-races-elections (races + early vote) — and the publishers run from different
# workflows on different schedules. There was no safe way for one of them to
# describe the repo as a whole:
#
#   * `latest.json` means different things in different repos. In ga-legislation
#     it is a BILLS pointer (biennium, currentSession, sessions[]); in
#     ga-local-government it is a REPO INDEX (description, coverage, files{}).
#     Same filename, different scope, so "just add your files to latest.json" is
#     not a convention, it is a collision.
#   * ga-races-elections has two publishers and no index at all.
#   * A publisher cannot merge itself into a shared index without a lost update.
#     _put_content reads the SHA then PUTs, and its 409/422 retry RE-READS THE
#     SHA AND OVERWRITES rather than re-merging — so two overlapping runs would
#     silently drop one publisher's entry. Concurrency groups are per-workflow
#     and do not protect two different workflows from each other.
#   * Listing another dataset's paths statically cannot carry its FRESHNESS. A
#     repo index stamped with the publishing job's own clock tells a consumer
#     that every dataset it names is as fresh as the one that just ran, which for
#     a monthly dataset beside a twice-weekly one is simply false.
#
# So: one manifest per dataset, at a path only that dataset's publisher writes.
# Single writer per path means no race, no read-modify-write, and no publisher
# needs to know another exists. A consumer discovers everything in a repo by
# listing `data/*/manifest.json`. The human-readable index stays whatever
# SUMMARY.md / MILLAGE.md / RACES.md the publisher already writes.
#
# `generatedAt` is the DATA's own timestamp and is required. There is deliberately
# NO "publishedAt": NO WALL-CLOCK TIME MAY REACH A PUBLISHED ARTIFACT. An earlier
# draft stamped one, which broke test_publish_early_vote's
# test_two_builds_are_byte_identical — and that test is right about why. A byte
# that moves on every run means every scheduled run PUTs the file again, so the
# sibling repo accumulates commits that say nothing changed. publish_ga_bills
# dodges the same trap by using the source timestamp in its latest.json. When the
# mirror last ran is already recorded — in the sibling repo's git history.

MANIFEST_SCHEMA_VERSION = "1.0.0"

_DATASET_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def manifest_path(dataset):
    """Where a dataset's manifest lives. One writer per path, by construction."""
    if not _DATASET_RE.match(dataset or ""):
        raise ValueError(
            f"dataset must be a lowercase slug (a-z, 0-9, hyphen), got {dataset!r}"
        )
    return f"data/{dataset}/manifest.json"


def add_dataset_manifest(artifacts, repo, dataset, *, title, description,
                         generated_at, files, source=None, row_count=None,
                         schema_version=None, update_cadence=None,
                         coverage=None, extra=None):
    """Add this dataset's manifest to `artifacts` and return its remote path.

    `files` is the dataset's published paths — each a string, or a
    {"path": ..., "description": ...} dict. EVERY path must already be in
    `artifacts`: a manifest that advertises a file this run did not publish is a
    404 for a consumer, so it is refused here rather than discovered later.

    `generated_at` is when the DATA was produced (its source metadata's own
    timestamp), not when this mirror ran. It is required and must be non-empty,
    because a manifest whose only timestamp is the publish time is the exact
    thing this helper replaces.
    """
    path = manifest_path(dataset)
    if path in artifacts:
        raise ValueError(
            f"refusing to build two manifests for {dataset!r}: {path} is already "
            "in this artifact set. One dataset, one manifest, one writer."
        )
    if not (generated_at or "").strip():
        raise ValueError(
            f"{dataset!r}: generated_at is required and must be the DATA's own "
            "timestamp. A manifest carrying only a publish time tells consumers "
            "every dataset in the repo is as fresh as the job that ran last."
        )

    entries, missing = [], []
    for f in files:
        spec = {"path": f} if isinstance(f, str) else dict(f)
        fp = spec.get("path")
        if fp not in artifacts:
            missing.append(fp)
            continue
        spec["bytes"] = len(artifacts[fp])
        entries.append(spec)
    if missing:
        raise ValueError(
            f"refusing to publish {dataset!r}: its manifest lists file(s) this run "
            f"did not build, which would 404 for consumers: {missing}"
        )
    if not entries:
        raise ValueError(f"refusing to publish {dataset!r}: its manifest lists no files")

    doc = {
        "manifestSchemaVersion": MANIFEST_SCHEMA_VERSION,
        "dataset": dataset,
        "title": title,
        "description": description,
        "repo": repo,
        "publisher": "VoteGA.org",
        "generatedAt": generated_at,
        "updateCadence": update_cadence,
        "schemaVersion": schema_version,
        "rowCount": row_count,
        "source": source or REPO_SOURCES.get(repo),
        "license": {"name": LICENSE_NAME, "spdx": LICENSE_SPDX, "url": LICENSE_URL},
        "files": sorted(entries, key=lambda e: e["path"]),
    }
    if coverage:
        doc["coverage"] = coverage
    if extra:
        doc.update(extra)
    artifacts[path] = build_json(doc)
    return path


def _assert_artifacts_sane(artifacts):
    """Universal pre-publish gate: never mirror an empty or corrupt blob to a public repo.

    Publishers `json.load` local disk, transform, and PUT the result to a sibling
    repo with a standing write-PAT. Nothing re-checks the bytes before they go out
    (PIPELINE-AUDIT.md #1), so a broken transform or a truncated source file (the
    class #2's atomic writes guard against) would propagate automatically. This runs
    inside the one path every publisher calls — before both live publish and dry-run,
    so local/CI runs fail the same way — and refuses to push:
      * an empty artifact set,
      * any artifact that is missing/empty bytes,
      * any *.json artifact that does not parse.
    Dataset-specific record floors are the caller's `validate` hook (see min_items)."""
    if not artifacts:
        raise ValueError("refusing to publish: no artifacts were built")
    for path, data in artifacts.items():
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"refusing to publish: artifact {path!r} is {type(data).__name__}, not bytes")
        if len(data) == 0:
            raise ValueError(f"refusing to publish: artifact {path!r} is empty")
        if path.endswith(".json"):
            try:
                json.loads(data)
            except (ValueError, UnicodeDecodeError) as e:
                raise ValueError(f"refusing to publish: artifact {path!r} is not valid JSON: {e}")


def min_items(remote_path, collection="", *, minimum=1):
    """Build a `validate` callback asserting a JSON artifact holds enough records.

    `collection` is a dotted path to a list/dict inside the parsed artifact ("" = the
    whole document). The floor is corpus-independent (default: non-empty), mirroring the
    standalone publish workflows' `len(...) == 0` guard so a transform that emits a
    well-formed-but-empty dataset (valid JSON, so `_assert_artifacts_sane` passes) cannot
    wipe a public repo's content. Only for flat, always-populated datasets — NOT the
    session-partitioned publishers (bills/votes), which emit empty sessions by design."""
    def _validate(artifacts):
        if remote_path not in artifacts:
            raise ValueError(f"refusing to publish: expected artifact {remote_path!r} was not built")
        node = json.loads(artifacts[remote_path])
        for part in filter(None, collection.split(".")):
            node = node[part]
        n = len(node)
        if n < minimum:
            where = collection or "<document>"
            raise ValueError(
                f"refusing to publish: {remote_path} {where} has {n} item(s), need >= {minimum}")
    return _validate


def _get_sha(url, headers):
    """Current blob sha for a Contents API path, or None if the file doesn't exist."""
    try:
        return json.loads(_urlopen_retry(urllib.request.Request(url, headers=headers))).get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _put_content(url, remote_path, data, headers):
    """PUT one file, creating or updating it. Fetches the existing sha first.

    Retries once on 409/422 by re-fetching the sha: the Contents API is eventually
    consistent, so a create can 422 ("sha wasn't supplied") when a stale read missed
    an existing file, and an update can 409 when the sha moved between read and write.
    Re-reading the sha and retrying resolves both. On a fatal error the API's own
    JSON message is printed, since "Unprocessable Entity" alone is undiagnosable.
    """
    for attempt in range(2):
        body = {
            "message": f"Publish {remote_path} from votega.org",
            "content": base64.b64encode(data).decode(),
        }
        sha = _get_sha(url, headers)
        if sha:
            body["sha"] = sha
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="PUT", headers=headers
        )
        try:
            return json.loads(_urlopen_retry(req))
        except urllib.error.HTTPError as e:
            if e.code in (409, 422) and attempt == 0:
                continue  # stale/missing sha — re-read and retry once
            detail = ""
            try:
                detail = " — " + e.read().decode("utf-8", "replace").strip()
            except Exception:
                pass
            print(f"  FAILED {remote_path}: HTTP {e.code}{detail}")
            raise


def _publish(repo, artifacts, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    for remote_path, data in artifacts.items():
        url = f"https://api.github.com/repos/{repo}/contents/{remote_path}"
        result = _put_content(url, remote_path, data, headers)
        print(f"  published {remote_path}: {result['commit']['sha'][:9]}")


def _dry_run(artifacts, out_dir):
    for remote_path, data in artifacts.items():
        dest = os.path.join(out_dir, remote_path)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        print(f"  wrote {dest} ({len(data):,} bytes)")


def publish_or_dry_run(repo, artifacts, token_env, validate=None):
    """Publish `artifacts` to `repo` if os.environ[token_env] is set, else dry-run to disk.

    The reuse terms (LICENSE + NOTICE.md) are injected here, so no publisher can omit
    them and all publishers targeting one repo emit byte-identical copies. A caller that
    supplies its own LICENSE or NOTICE.md keeps it.

    Every artifact is gated before it can leave: `_assert_artifacts_sane` always runs, and
    an optional `validate(artifacts)` callback (see min_items) adds a dataset record floor.
    Both run before publish AND dry-run, so a broken build fails fast everywhere rather than
    mirroring bad data to a public repo. A failing check raises, aborting the publish.
    """
    for path, data in license_artifacts(repo).items():
        artifacts.setdefault(path, data)
    _assert_artifacts_sane(artifacts)
    if validate is not None:
        validate(artifacts)
    token = os.environ.get(token_env)
    if token:
        print(f"Publishing {len(artifacts)} artifacts to {repo}:")
        _publish(repo, artifacts, token)
    else:
        # Guard against a silent dry-run in CI. An API publisher (no OUT_DIR set)
        # that reaches here has lost its token — the step still exits 0, so the
        # sibling repo silently stops updating while the workflow stays green.
        # (GA_LOCAL_GOVERNMENT_TOKEN went empty this way and ga-local-government
        # went stale for three weeks, 2026-09.) Fail loudly instead. Git-based
        # publishers set OUT_DIR on purpose to write artifacts to a checkout and
        # push them separately — that is a real dry-run, so it is allowed. Local
        # runs (no GITHUB_ACTIONS) always dry-run, for testing.
        in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
        out_dir = os.environ.get("OUT_DIR")
        if in_ci and out_dir is None:
            raise RuntimeError(
                f"refusing to dry-run in CI: {token_env} is empty. This publisher "
                f"pushes to {repo} via the GitHub Contents API and needs the token. "
                f"Set the {token_env} secret on this repository, or set OUT_DIR to "
                f"write artifacts to disk on purpose."
            )
        out_dir = out_dir or "out"
        print(f"DRY RUN (no {token_env}) — writing {len(artifacts)} artifacts to {out_dir}/:")
        _dry_run(artifacts, out_dir)
    print("Done.")
