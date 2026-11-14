#!/usr/bin/env python3
"""Tier-1 gate for the append-only GA legislator page ledger.

A published /ga-legislators/<slug>/ URL must never 404. This refuses any commit that
would break that promise. Tier 1 (exit 1): removed person/path/biennium vs the base ref,
a path owned by two people, a roster votegaUrl that is not the ledger's current path (or
is not on SITE_URL), a ledger biennium with no frozen record, a person with two different
(chamber, district) records inside one frozen biennium. Tier 2 (printed, never gates):
people added, URLs added (renames), bienniums added.

Usage: python scripts/validate_ga_legislator_ledger.py [--ledger PATH] [--roster PATH]
           [--frozen-root PATH] [--base-ref HEAD]
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_ledger as G  # noqa: E402
from lib.ga_former import DEFAULT_ROOT  # noqa: E402
from lib.ga_biennium_freeze import MEMBERS  # noqa: E402
from lib.ga_legislator_pages import SITE_URL  # noqa: E402


class BaseReadError(Exception):
    pass


def _git(directory, *args):
    try:
        return subprocess.run(["git", "-C", directory, *args], capture_output=True)
    except OSError as e:
        raise BaseReadError(f"cannot run git: {e}")


def read_base_ledger(ledger_path, ref):
    """The ledger at `ref`, via bytes + explicit UTF-8. Missing file at ref = empty ledger;
    any other git failure raises BaseReadError."""
    directory = os.path.dirname(os.path.abspath(ledger_path))
    top = _git(directory, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise BaseReadError(f"{directory} is not in a git repository: "
                            f"{top.stderr.decode('utf-8', 'replace').strip()}")
    toplevel = top.stdout.decode("utf-8").strip()
    rel = os.path.relpath(os.path.realpath(ledger_path), os.path.realpath(toplevel)).replace(os.sep, "/")
    if _git(directory, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode != 0:
        raise BaseReadError(f"base ref {ref!r} does not resolve to a commit")
    exists = _git(directory, "cat-file", "-e", f"{ref}:{rel}")
    if exists.returncode != 0:
        return G.empty_ledger()  # ref is valid, the file is not in it yet
    shown = _git(directory, "show", f"{ref}:{rel}")
    if shown.returncode != 0:
        raise BaseReadError(f"git show {ref}:{rel} failed: {shown.stderr.decode('utf-8', 'replace').strip()}")
    return json.loads(shown.stdout.decode("utf-8"))


def frozen_records(root):
    """{tag: {gid: [(chamber, district), ...distinct]}} read raw, so a gid listed twice in one
    frozen file is seen (load_frozen keys by gid and would collapse it)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for tag in sorted(os.listdir(root)):
        path = os.path.join(root, tag, MEMBERS)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            members = json.load(f).get("members") or []
        by = {}
        for m in members:
            if m.get("legisGaGovId") is None:
                continue
            key = (m.get("chamber"), m.get("district"))
            seen = by.setdefault(str(m["legisGaGovId"]), [])
            if key not in seen:
                seen.append(key)
        out[tag] = by
    return out


def check(ledger, base, members, frozen):
    """Returns (errors, notes)."""
    errors, notes = [], []
    errors += G.append_only_violations(base, ledger)

    owners = {}
    for gid, person in ledger["people"].items():
        for u in person["urls"]:
            owners.setdefault(u["path"], set()).add(gid)
    for path, gids in sorted(owners.items()):
        if len(gids) > 1:
            errors.append(f"path {path} owned by {sorted(gids)}")

    for mem in members:
        url, gid = mem.get("votegaUrl"), mem.get("legisGaGovId")
        if not url or gid is None:
            continue
        if not url.startswith(SITE_URL):
            errors.append(f"member {gid}: votegaUrl {url!r} is not on {SITE_URL}, so the ledger ignores it")
            continue
        cur = G.current_path(ledger, gid)
        if url[len(SITE_URL):] != cur:
            errors.append(f"member {gid}: votegaUrl path {url[len(SITE_URL):]!r} != ledger current path {cur!r}")

    for gid, person in sorted(ledger["people"].items()):
        for tag in person.get("bienniums", []):
            if tag == "current":
                continue
            if gid not in frozen.get(tag, {}):
                errors.append(f"person {gid}: biennium {tag} has no frozen {MEMBERS} record")
    for tag, by in sorted(frozen.items()):
        for gid, recs in sorted(by.items()):
            if len(recs) > 1:
                errors.append(f"person {gid}: {len(recs)} different (chamber, district) records in frozen {tag}: {recs}")

    for gid, person in sorted(ledger["people"].items()):
        old = base["people"].get(gid)
        if old is None:
            notes.append(f"person added {gid}: {person['urls'][0]['path'] if person['urls'] else None}")
            continue
        old_paths = {u["path"] for u in old["urls"]}
        for u in person["urls"]:
            if u["path"] not in old_paths:
                notes.append(f"URL added (rename) {gid}: {u['path']}")
        for b in person.get("bienniums", []):
            if b not in old.get("bienniums", []):
                notes.append(f"biennium added {gid}: {b}")
    return errors, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default=G.LEDGER_PATH)
    ap.add_argument("--roster", default=os.path.join(G.REPO_ROOT, "assets", "data", "ga-members.json"))
    ap.add_argument("--frozen-root", default=DEFAULT_ROOT)
    ap.add_argument("--base-ref", default="HEAD")
    a = ap.parse_args(argv)

    try:
        base = read_base_ledger(a.ledger, a.base_ref)
    except BaseReadError as e:
        print(f"ERROR: cannot read the base ledger: {e}")
        return 1
    try:
        ledger = G.load_ledger(a.ledger)
        with open(a.roster, encoding="utf-8") as f:
            members = json.load(f).get("members") or []
        frozen = frozen_records(a.frozen_root)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    errors, notes = check(ledger, base, members, frozen)
    for n in notes:
        print(f"note: {n}")
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        print(f"\n{len(errors)} tier-1 violation(s); the ledger gate refuses this commit.")
        return 1
    print(f"Ledger OK: {len(ledger['people'])} people, {len(notes)} change note(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
