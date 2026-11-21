"""Build the Phase 0 benchmark files the spike Worker serves from its private assets.

Throwaway, spike-only: approximates the shapes build_mcp_index.py will emit (spec §5.1,
§12.3) from the committed site data, so Worker CPU time can be measured on realistic
inputs. Output goes to mcp/bench-data/ (gitignored). Run from the repo root:

    python mcp/bench/make_bench_data.py
"""
import gzip
import json
import os
import shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "assets", "data")
OUT = os.path.join(ROOT, "mcp", "bench-data")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def write(name, obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(raw)
    return f"{name}: {len(raw) / 1e3:.0f} KB raw, {len(gzip.compress(raw)) / 1e3:.0f} KB gzip"


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    report = []

    # Bills, sharded by session and bill type (spec §12.3), as compact positional rows.
    bills = load("ga-bills.json")["bills"]
    subjects = sorted({s for b in bills for s in (b.get("subjects") or [])})
    statuses = sorted({b.get("status") or "" for b in bills})
    si, sti = {s: i for i, s in enumerate(subjects)}, {s: i for i, s in enumerate(statuses)}
    shards = {}
    for b in bills:
        kind = (b.get("identifier") or "XX").split()[0]
        shards.setdefault(f"{b['session']}-{kind}", []).append([
            b["legislationId"], b["identifier"], b.get("title") or "", sti[b.get("status") or ""],
            b.get("statusDate"), [s.get("legisGaGovId") for s in b.get("sponsors") or []],
            [si[s] for s in b.get("subjects") or []]])
    for key, rows in sorted(shards.items()):
        report.append(write(f"bills-{key}.json", {"subjects": subjects, "statuses": statuses, "rows": rows}))
    report.append(write("bills-all.json", {"subjects": subjects, "statuses": statuses,
                                           "rows": [r for k in sorted(shards) for r in shards[k]]}))

    # ZIP districts, sharded by 3-digit prefix (spec §5.1).
    zips = load("ga-zip-districts.json")["zips"]
    by3 = {}
    for z, e in zips.items():
        by3.setdefault(z[:3], {})[z] = e
    largest = max(by3, key=lambda k: len(json.dumps(by3[k])))
    report.append(write("zip-largest.json", by3[largest]) + f" (prefix {largest}, {len(by3[largest])} ZIPs)")

    # Federal votes: the full index as the site publishes it, plus one member slice.
    for name in ("federal-votes-index.json",):
        shutil.copy(os.path.join(DATA, name), os.path.join(OUT, name))
        report.append(f"{name}: {os.path.getsize(os.path.join(OUT, name)) / 1e3:.0f} KB raw (copied)")
    slice_dir = os.path.join(DATA, "federal-votes")
    first = sorted(os.listdir(slice_dir))[0]
    shutil.copy(os.path.join(slice_dir, first), os.path.join(OUT, "federal-votes-slice.json"))

    # The full GA roster, for reference (the largest file a members tool might read whole).
    shutil.copy(os.path.join(DATA, "ga-members.json"), os.path.join(OUT, "ga-members.json"))
    report.append(f"ga-members.json: {os.path.getsize(os.path.join(OUT, 'ga-members.json')) / 1e3:.0f} KB raw (copied)")

    print("\n".join(report))


if __name__ == "__main__":
    main()
