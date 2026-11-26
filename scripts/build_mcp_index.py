#!/usr/bin/env python3
"""Build the MCP server's index files into assets/data/mcp/ (gitignored, built at deploy).

Spec: docs/superpowers/specs/2026-10-23-mcp-server-design.md §5.1, §12.2. Phase 1 builds the core
indexes the Phase 2 tools read (members, ZIP shards, counties, local officials), the Phase 3
indexes (former members, bills, races, candidates, local mentions; executive orders are left out
for now), the MCP
resources (resources.json, from _data/mcp.yml and _data/open_data.yml) and meta.json;
the rules live in scripts/lib/mcp_index.py. Run scripts/validate_mcp_index.py afterwards.

The core files are what the live tools read: if one cannot be built, the run fails. The Phase 3
groups (lib/mcp_index.OPTIONAL_GROUPS) are built one at a time; a group that raises is left out
and listed in meta.json `failedGroups`, and the validator reports it.

The output directory is replaced as a whole (built in a temp dir, then swapped in), so a failed
run never leaves a mix of old and new files.

Usage: python scripts/build_mcp_index.py [--out DIR] [--today YYYY-MM-DD]
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import mcp_bills as MB  # noqa: E402
from lib import mcp_elections as ME  # noqa: E402
from lib import mcp_index as M  # noqa: E402
from lib.congress_session import current_congress  # noqa: E402
from lib.ga_county_fips import GA_COUNTY_FIPS  # noqa: E402
from lib.ga_former import load_frozen  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "assets", "data")
OUT = os.path.join(DATA, "mcp")
SLICE_DIRS = ("ga-votes", "ga-sponsorship", "federal-votes", "federal-sponsorship")

#: index file -> the datasets (data_freshness.yml keys, or a source label) it is built from
SOURCES = {
    "members-index.json": ["ga-members", "current-members", "id-crosswalk"],
    "zip/": ["ga-zip-districts"],
    "counties-index.json": ["ga-tract-districts"],
    "local-officials-index.json": ["local-officials", "county-officers"],
    "resources.json": ["_data/mcp.yml", "_data/open_data.yml"],
    "former-members-index.json": ["ga-bienniums", "ga-departure-labels"],
    "bills/": ["ga-bills", "ga-bienniums"],
    "races-index.json": ["races"],
    "candidates-index.json": ["races", "id-crosswalk", "entity-urls"],
    "local-mentions-index.json": ["local-topics"],
}


def load_json(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return json.load(f)


def load_yaml(*parts):
    import yaml  # lazily: the offline test job installs no packages
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return yaml.safe_load(f)


def existing_slices():
    out = set()
    for d in SLICE_DIRS:
        path = os.path.join(DATA, d)
        if os.path.isdir(path):
            out.update(f"{d}/{n}" for n in os.listdir(path) if n.endswith(".json"))
    for d in ("ga-votes", "ga-sponsorship"):
        for path in glob.glob(os.path.join(DATA, "ga-bienniums", "*", d, "*.json")):
            out.add(os.path.relpath(path, DATA).replace(os.sep, "/"))
    return out


def frozen_members():
    return load_frozen(os.path.join(DATA, "ga-bienniums"))


def bill_docs():
    """The live bills file first, then each frozen biennium's, newest first."""
    frozen = sorted(glob.glob(os.path.join(DATA, "ga-bienniums", "*", "ga-bills.json")), reverse=True)
    return [load_json(DATA, "ga-bills.json")] + [load_json(p) for p in frozen]


def topic_docs():
    return [load_json(p) for p in sorted(glob.glob(os.path.join(DATA, "local-topics-*.json")))]


def stamp_of(doc):
    if not isinstance(doc, dict):
        return None
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return meta.get("generatedAt") or doc.get("updatedAt") or doc.get("generatedAt")


def dataset_dates():
    """data_freshness.yml datasets -> {window, cadence, generatedAt, checkedAt} for get_data_freshness."""
    table = (load_yaml(ROOT, "_data", "data_freshness.yml") or {}).get("datasets") or {}
    out = {}
    for name, rule in sorted(table.items()):
        rule = rule or {}
        src = os.path.join(DATA, f"{name}.json")
        checked = os.path.join(ROOT, "_data", "freshness", f"{name}.json")
        generated = None
        if os.path.exists(src):
            try:
                generated = stamp_of(load_json(src))
            except (OSError, ValueError):
                generated = None
        out[name] = {
            "generatedAt": generated,
            "checkedAt": load_json(checked).get("checkedAt") if os.path.exists(checked) else None,
            "windowDays": rule.get("window_days"),
            "review": rule.get("review"),
            "neverFlagged": bool(rule.get("never")),
            "cadence": rule.get("cadence"),
        }
    return out


def encode(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode("utf-8")


def file_entry(raw, count):
    return {"bytes": len(raw), "gzipBytes": len(gzip.compress(raw, mtime=0)),
            "sha256": hashlib.sha256(raw).hexdigest(), "count": count}


def build_optional(builders):
    """{group: zero-argument builder returning {file name: doc}} -> (docs, {group: reason})."""
    docs, failed = {}, {}
    for group, builder in builders.items():
        try:
            docs.update(builder())
        except Exception as e:  # one group's bad input must not cost the others their files
            traceback.print_exc()
            failed[group] = f"{type(e).__name__}: {e}"
    return docs, failed


def write_index(out_dir, docs, extra, generated_at):
    """Write every doc and meta.json into a temp dir, then swap it in. -> meta.json's `files`."""
    tmp = tempfile.mkdtemp(prefix=".mcp-", dir=os.path.dirname(out_dir))
    try:
        files = {}
        for name, doc in sorted(docs.items()):
            raw = encode(doc)
            path = os.path.join(tmp, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
            files[name] = file_entry(raw, doc["metadata"].get("count"))
        meta = {
            "metadata": {"generatedAt": generated_at, "count": len(files), "phase": 3,
                         "spec": "docs/superpowers/specs/2026-10-23-mcp-server-design.md",
                         "license": "CC BY-SA 4.0 (VoteGA data); see https://www.votega.org/open-data"},
            "files": files,
            **extra,
        }
        if extra.get("failedGroups"):
            meta = M.prune_meta(meta, {x["group"]: x["reason"] for x in extra["failedGroups"]})
        with open(os.path.join(tmp, "meta.json"), "wb") as f:
            f.write(encode(meta))
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.replace(tmp, out_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return files


def build(out_dir, today):
    """-> (meta.json `files`, {failed group: reason})."""
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    from publish_ga_district_information import TRACTS_SRC, counties_doc

    ga = load_json(DATA, "ga-members.json")
    federal = load_json(DATA, "current-members.json")
    crosswalk = load_json(DATA, "id-crosswalk.json")
    entity_urls = load_json(DATA, "entity-urls.json")
    zipdoc = load_json(DATA, "ga-zip-districts.json")
    tracts = load_json(TRACTS_SRC)
    officials = load_yaml(ROOT, "_data", "local_officials.yml")
    officers = load_yaml(ROOT, "_data", "county_officers.yml")
    places = load_yaml(ROOT, "_data", "places.yml")
    mcp_text = load_yaml(ROOT, "_data", "mcp.yml")
    open_data = load_yaml(ROOT, "_data", "open_data.yml")
    congress = current_congress()

    docs = {
        "members-index.json": M.build_members(ga, federal, crosswalk, entity_urls, existing_slices(),
                                              generated_at, congress),
        "counties-index.json": M.build_counties(counties_doc(tracts), generated_at),
        "local-officials-index.json": M.build_local_officials(officials, officers, places,
                                                              GA_COUNTY_FIPS, today, generated_at),
        "resources.json": M.build_resources(mcp_text, open_data, generated_at),
    }
    for prefix, shard in M.build_zip_shards(zipdoc, generated_at).items():
        docs[f"zip/{prefix}.json"] = shard

    stamps = {
        "ga-members": stamp_of(ga), "current-members": stamp_of(federal),
        "id-crosswalk": stamp_of(crosswalk), "ga-zip-districts": stamp_of(zipdoc),
        "ga-tract-districts": stamp_of(tracts),
    }

    # Each Phase 3 group reads its own sources, so a bad file only costs that group.
    def former():
        return {"former-members-index.json": M.build_former_members(
            ga, frozen_members(), load_json(DATA, "ga-departure-labels.json"), crosswalk,
            existing_slices(), generated_at)}

    def mentions():
        return {"local-mentions-index.json": M.build_local_mentions(
            topic_docs(), places, GA_COUNTY_FIPS, generated_at)}

    def bills():
        sources = bill_docs()
        built = MB.build_bills(sources, generated_at)
        stamps["ga-bills"] = stamp_of(sources[0])
        return built

    def elections():
        races = load_json(DATA, "races.json")
        built = ME.build_elections(races, ga, federal, frozen_members(), crosswalk, entity_urls,
                                   generated_at)
        stamps["races"] = stamp_of(races)
        return built

    optional, failed = build_optional({"former-members": former, "local-mentions": mentions,
                                       "bills": bills, "elections": elections})
    docs.update(optional)

    catalog = (docs.get("bills/sessions.json") or {}).get("sessions") or []
    topics = (docs.get("local-mentions-index.json") or {}).get("metadata", {}).get("topics") or []
    files = write_index(out_dir, docs, {
        "sources": SOURCES,
        "failedGroups": [{"group": g, "reason": r} for g, r in sorted(failed.items())],
        "sessions": {
            "ga": {"session": (ga.get("metadata") or {}).get("session"),
                   "activeBillSession": next((x["session"] for x in catalog if x["active"]), None)},
            "federal": {"congress": congress},
        },
        "localTopics": topics,
        "datasets": dataset_dates(),
        "localOfficialsLastReviewed": docs["local-officials-index.json"]["metadata"]["lastReviewed"],
        "sourceStamps": stamps,
    }, generated_at)
    return files, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--today", default=datetime.now(timezone.utc).date().isoformat(),
                    help="the as-of date for local officials (default: today, UTC)")
    args = ap.parse_args()
    files, failed = build(os.path.abspath(args.out), args.today)
    for group, reason in sorted(failed.items()):
        print(f"WARNING: the {group} indexes were not built: {reason}")
    total = sum(f["gzipBytes"] for f in files.values())
    biggest = max(files.items(), key=lambda kv: kv[1]["gzipBytes"])
    print(f"MCP indexes: {len(files)} files + meta.json in {args.out}; "
          f"{total / 1e3:.0f} KB gzip total; largest {biggest[0]} "
          f"({biggest[1]['gzipBytes'] / 1e3:.1f} KB gzip, {biggest[1]['bytes'] / 1e3:.0f} KB raw)")
    for name in ("members-index.json", "former-members-index.json", "counties-index.json",
                 "local-officials-index.json", "local-mentions-index.json", "races-index.json",
                 "candidates-index.json"):
        f = files.get(name)
        if f is None:
            continue
        print(f"  {name}: {f['count']} rows, {f['bytes'] / 1e3:.0f} KB raw, {f['gzipBytes'] / 1e3:.1f} KB gzip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
