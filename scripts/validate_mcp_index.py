#!/usr/bin/env python3
"""Validate assets/data/mcp/ (built by build_mcp_index.py) against itself and its sources.

Tier 1 only: every check is the index contradicting itself or the committed files it was built
from (meta.json vs the bytes on disk, keys that do not resolve, ZIPs or counties lost in sharding,
a slice path that does not exist, a file over the 150 KB gzip budget). The rules are
lib/mcp_index.grouped_errors().

Exit codes:
  0  every group is good
  1  a core file (what the live tools read) is wrong: the caller must discard the whole index
  3  the core is good; one or more Phase 3 groups failed and their files were REMOVED, with
     meta.json rewritten to match, so what is left can be published

Usage: python scripts/validate_mcp_index.py [--out DIR]
"""
import argparse
import gzip
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import mcp_index as M  # noqa: E402
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402
import build_mcp_index as B  # noqa: E402


def read_out(out_dir):
    docs, actual = {}, {}
    for dirpath, _, names in os.walk(out_dir):
        for n in names:
            path = os.path.join(dirpath, n)
            rel = os.path.relpath(path, out_dir).replace(os.sep, "/")
            with open(path, "rb") as f:
                raw = f.read()
            if rel == "meta.json":
                actual["__claimed__"] = json.loads(raw)["files"]
                continue
            docs[rel] = json.loads(raw)
            actual[rel] = {"bytes": len(raw), "gzipBytes": len(gzip.compress(raw, mtime=0)),
                           "sha256": hashlib.sha256(raw).hexdigest()}
    return docs, actual


DEGRADED = 3


def finish(out_dir, src):
    """Check the index in `out_dir`; drop any failed optional group. -> exit code."""
    docs, actual = read_out(out_dir)
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "rb") as f:
        meta = json.loads(f.read())
    unbuilt = {x["group"]: x["reason"] for x in meta.get("failedGroups") or []}
    grouped = M.grouped_errors(docs, actual,
                               {**src, "load_errors": {**(src.get("load_errors") or {}), **unbuilt}})
    for group, errs in sorted(grouped.items()):
        for e in errs:
            print(f"FAIL [{group}]: {e}")
    if grouped.get("core"):
        print("FAILED: the core indexes are wrong")
        return 1
    failed = {g: unbuilt.get(g) or "; ".join(errs[:3]) for g, errs in grouped.items()}
    if failed:
        for name in docs:
            if M.group_of(name) in failed:
                os.remove(os.path.join(out_dir, *name.split("/")))
        bills_dir = os.path.join(out_dir, "bills")
        if os.path.isdir(bills_dir) and not os.listdir(bills_dir):
            os.rmdir(bills_dir)
        meta = M.prune_meta(meta, failed)
        with open(meta_path + ".tmp", "wb") as f:
            f.write(B.encode(meta))
        os.replace(meta_path + ".tmp", meta_path)
    kept = [k for k in actual if k != "__claimed__" and M.group_of(k) not in failed]
    total = sum(actual[k]["gzipBytes"] for k in kept)
    state = f"DEGRADED (dropped: {', '.join(sorted(failed))})" if failed else "OK"
    print(f"{state}: {len(kept)} index files, {total / 1e3:.0f} KB gzip")
    return DEGRADED if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=B.OUT)
    args = ap.parse_args()
    if not os.path.exists(os.path.join(args.out, "meta.json")):
        print(f"FAIL: {args.out}/meta.json not found (run build_mcp_index.py first)")
        return 1
    officials = B.load_yaml(B.ROOT, "_data", "local_officials.yml")
    officers = B.load_yaml(B.ROOT, "_data", "county_officers.yml")
    places = B.load_yaml(B.ROOT, "_data", "places.yml")
    src = {
        "ga": B.load_json(B.DATA, "ga-members.json"),
        "federal": B.load_json(B.DATA, "current-members.json"),
        "zipdoc": B.load_json(B.DATA, "ga-zip-districts.json"),
        "county_fips": set(GA_COUNTY_FIPS.values()),
        "place_slugs": {p["slug"] for p in places.get("places") or []},
        "jurisdiction_ids": {j["id"] for j in officials.get("jurisdictions") or []},
        "officer_ids": {c["id"] for c in officers.get("counties") or []},
        "slices": B.existing_slices(),
        "open_data_ids": {d["id"] for d in (B.load_yaml(B.ROOT, "_data", "open_data.yml") or {}).get("datasets") or []},
        "retired_vgids": set((B.load_json(B.DATA, "id-crosswalk.json").get("metadata") or {})
                             .get("mergedVgIds") or {}),
        "load_errors": {},
    }
    for key, loader, groups in (
            ("frozen", B.frozen_members, ("former-members", "elections")),
            ("bill_docs", B.bill_docs, ("bills",)),
            ("races", lambda: B.load_json(B.DATA, "races.json"), ("elections",)),
            ("topic_docs", B.topic_docs, ("local-mentions",)),
            ("vote_hashes", B.vote_hashes, ("vote-files",))):
        try:
            src[key] = loader()
        except Exception as e:  # reported against the group(s) that need this source
            for group in groups:
                src["load_errors"][group] = f"{key}: {type(e).__name__}: {e}"
    return finish(args.out, src)


if __name__ == "__main__":
    sys.exit(main())
