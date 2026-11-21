#!/usr/bin/env python3
"""Validate assets/data/mcp/ (built by build_mcp_index.py) against itself and its sources.

Tier 1 only: every check is the index contradicting itself or the committed files it was built
from (meta.json vs the bytes on disk, keys that do not resolve, ZIPs or counties lost in sharding,
a slice path that does not exist, a file over the 150 KB gzip budget). The rules are
lib/mcp_index.index_errors(). Exits 1 on any error.

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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=B.OUT)
    args = ap.parse_args()
    if not os.path.exists(os.path.join(args.out, "meta.json")):
        print(f"FAIL: {args.out}/meta.json not found (run build_mcp_index.py first)")
        return 1
    docs, actual = read_out(args.out)
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
        "retired_vgids": set((B.load_json(B.DATA, "id-crosswalk.json").get("metadata") or {})
                             .get("mergedVgIds") or {}),
    }
    errs = M.index_errors(docs, actual, src)
    for e in errs:
        print(f"FAIL: {e}")
    total = sum(v["gzipBytes"] for k, v in actual.items() if k != "__claimed__")
    print(f"{'FAILED' if errs else 'OK'}: {len(docs)} index files, {total / 1e3:.0f} KB gzip, "
          f"{len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
