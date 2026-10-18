#!/usr/bin/env python3
"""Build scripts/data/usps-ga-zips.json from the USPS "Zip Locale Detail" workbook.

The workbook (PostalPro, public) lists post-office facilities, not delivery areas,
so it is used for exactly one thing: which ZIP codes are real Georgia delivery
ZIPs, and which of those are PO-box-only. A PO-box ZIP says nothing about where
someone lives, so generate_ga_zip_districts.py gives it no districts.

Rows are kept when the facility's state is GA *and* USPS files the ZIP under the
Georgia district: a Tennessee ZIP (37316) is served from a Georgia facility and is
not a Georgia ZIP.

    ZIP CLASS CODE  ' ' -> "standard", 'P' -> "po-box"

One-time/manual build; the output is committed.

Usage:
    python scripts/build_usps_ga_zips.py Zip_Locale_Detail.xlsx
"""
import collections
import datetime
import os
import sys

from lib.atomic_io import write_json_atomic

OUT = os.path.join(os.path.dirname(__file__), "data", "usps-ga-zips.json")
CLASS = {"": "standard", "P": "po-box"}


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    import openpyxl  # lazy: only this manual build needs it
    ws = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)["ZIP_Locale"]
    rows = list(ws.iter_rows(values_only=True))
    col = {str(h).strip(): i for i, h in enumerate(rows[0])}
    need = ("DISTRICT NAME", "DELIVERY ZIPCODE", "ZIP CLASS CODE", "PHYSICAL STATE")
    if any(n not in col for n in need):
        sys.exit(f"unexpected header: {rows[0]}")
    kinds = collections.defaultdict(set)
    for r in rows[1:]:
        if str(r[col["PHYSICAL STATE"]]).strip() != "GA":
            continue
        if str(r[col["DISTRICT NAME"]]).strip() != "GEORGIA":
            continue
        code = str(r[col["ZIP CLASS CODE"]] or "").strip()
        if code not in CLASS:
            sys.exit(f"unrecognised ZIP class code {code!r}")
        kinds[str(r[col["DELIVERY ZIPCODE"]]).strip().zfill(5)].add(CLASS[code])
    mixed = {z: k for z, k in kinds.items() if len(k) > 1}
    if mixed:
        sys.exit(f"ZIPs filed under both classes: {mixed}")
    zips = {z: next(iter(k)) for z, k in sorted(kinds.items())}
    write_json_atomic(OUT, {
        "metadata": {
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "source": "USPS PostalPro Zip Locale Detail (Georgia delivery ZIPs)",
            "count": len(zips),
            "standard": sum(1 for v in zips.values() if v == "standard"),
            "poBox": sum(1 for v in zips.values() if v == "po-box"),
        },
        "zips": zips,
    }, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(zips)} ZIPs")


if __name__ == "__main__":
    main()
