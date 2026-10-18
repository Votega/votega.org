#!/usr/bin/env python3
"""Validate ga-zip-districts.json: gate on self-consistency, report on change.

Same two-tier split as validate_agency_actions.py.

  Tier 1 - the file contradicts itself or its inputs, and exits 1:
    * metadata.count != len(zips), or fewer ZIPs than a Georgia file can have;
    * a PO-box ZIP that carries districts (a PO-box ZIP says nothing about where
      anyone lives);
    * a ranked list whose shares do not sum to ~1, are out of order, repeat a
      district, or name a district the plans do not have;
    * a standard ZIP with a state House list but no Senate list (or the reverse):
      both come from the same tracts, so one without the other is a join failure;
    * too few ZIPs with districts (the join to the tract table collapsed).

  Tier 2 - the file differs from the committed one: ZIPs added or removed, a ZIP
  whose largest district changed. HUD refreshes quarterly and can do all of these,
  so they are reported and never gate.

Usage:
    python scripts/validate_ga_zip_districts.py assets/data/ga-zip-districts.json \\
        --baseline-ref HEAD --report-out report.md
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)
TRACT_TABLE = os.path.join(HERE, "data", "ga-tract-districts.json")
KINDS = {"standard", "po-box", "other"}
#: Georgia has ~880 delivery ZIPs; far fewer means the HUD pull or the join broke.
MIN_ZIPS = 800
#: Share of non-PO-box ZIPs that must carry districts.
MIN_COVERAGE = 0.90
SUM_TOLERANCE = 0.001
#: Rounding to five places can move a long list's total by a few ten-thousandths.
LIST_KEYS = ("stateSenate", "stateHouse", "usHouse")
CHAMBER_FOR = {"stateSenate": "s", "stateHouse": "h"}
US_HOUSE_MAX = 14


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path.replace(os.sep, '/')}"],
                              capture_output=True, text=True, check=True).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def valid_districts(tract_table):
    out = {"s": set(), "h": set()}
    for rec in tract_table["tracts"].values():
        for chamber in out:
            out[chamber].update(int(d) for d in rec[chamber])
    return out


def tier1(doc, valid):
    errors = []
    zips = doc.get("zips")
    meta = doc.get("metadata") or {}
    if not isinstance(zips, dict):
        return ["zips is not an object"]
    if meta.get("count") != len(zips):
        errors.append(f"metadata.count {meta.get('count')} != {len(zips)} ZIPs")
    if len(zips) < MIN_ZIPS:
        errors.append(f"only {len(zips)} ZIPs (floor {MIN_ZIPS})")

    open_zips = 0
    for z, e in zips.items():
        if e.get("kind") not in KINDS:
            errors.append(f"{z}: unknown kind {e.get('kind')!r}")
            continue
        if e["kind"] == "po-box":
            if any(e.get(k) for k in LIST_KEYS + ("counties",)):
                errors.append(f"{z}: PO-box ZIP carries districts or counties")
            continue
        open_zips += 1
        for key in LIST_KEYS + ("counties",):
            lst = e.get(key)
            if lst is None:
                continue
            shares = [row["share"] for row in lst]
            if abs(sum(shares) - 1) > SUM_TOLERANCE * max(len(shares), 1):
                errors.append(f"{z}.{key}: shares sum to {sum(shares):.5f}")
            if shares != sorted(shares, reverse=True):
                errors.append(f"{z}.{key}: not ranked largest first")
            ids = [row.get("district", row.get("fips")) for row in lst]
            if len(set(ids)) != len(ids):
                errors.append(f"{z}.{key}: repeated entry")
            if key in CHAMBER_FOR:
                bad = [i for i in ids if i not in valid[CHAMBER_FOR[key]]]
                if bad:
                    errors.append(f"{z}.{key}: no such district(s) {bad}")
            elif key == "usHouse":
                bad = [i for i in ids if not 1 <= i <= US_HOUSE_MAX]
                if bad:
                    errors.append(f"{z}.usHouse: no such district(s) {bad}")
        if bool(e.get("stateSenate")) != bool(e.get("stateHouse")):
            errors.append(f"{z}: state Senate and House lists disagree about whether the ZIP has residents")

    with_d = sum(1 for e in zips.values() if e.get("kind") != "po-box" and e.get("stateHouse"))
    if open_zips and with_d / open_zips < MIN_COVERAGE:
        errors.append(f"only {with_d} of {open_zips} non-PO-box ZIPs have districts "
                      f"(floor {MIN_COVERAGE:.0%}): the HUD or tract join collapsed")
    return errors


def tier2(doc, old):
    """Changes against the committed file; never fatal."""
    if not old:
        return ["No committed baseline to compare against."]
    new_z, old_z = doc["zips"], old.get("zips", {})
    lines = []
    added = sorted(set(new_z) - set(old_z))
    removed = sorted(set(old_z) - set(new_z))
    if added:
        lines.append(f"ZIPs added ({len(added)}): {', '.join(added[:20])}{' ...' if len(added) > 20 else ''}")
    if removed:
        lines.append(f"ZIPs removed ({len(removed)}): {', '.join(removed[:20])}{' ...' if len(removed) > 20 else ''}")
    moved = []
    for z in sorted(set(new_z) & set(old_z)):
        for key in LIST_KEYS:
            a, b = new_z[z].get(key), old_z[z].get(key)
            if a and b and a[0]["district"] != b[0]["district"]:
                moved.append(f"{z} {key}: largest {b[0]['district']} -> {a[0]['district']}")
    if moved:
        lines.append(f"ZIPs whose largest district changed ({len(moved)}): " + "; ".join(moved[:15])
                     + (" ..." if len(moved) > 15 else ""))
    m_new, m_old = doc["metadata"].get("hudRelease"), old.get("metadata", {}).get("hudRelease")
    if m_new != m_old:
        lines.append(f"HUD release: {m_old} -> {m_new}")
    return lines or ["No material change."]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--baseline-ref")
    ap.add_argument("--report-out")
    args = ap.parse_args()

    doc = load(args.path)
    errors = tier1(doc, valid_districts(load(TRACT_TABLE)))
    if errors:
        print("TIER 1 FAILED:")
        for e in errors[:50]:
            print("  -", e)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more")
        sys.exit(1)

    report = ["## ga-zip-districts.json", ""]
    if args.baseline_ref:
        report += [f"- {line}" for line in tier2(doc, baseline(args.path, args.baseline_ref))]
    else:
        report.append("- (no baseline given)")
    text = "\n".join(report) + "\n"
    print(f"OK: {len(doc['zips'])} ZIPs valid")
    print(text)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
