"""
Validates assets/data/ga-members-overrides.json before it reaches the daily
member-data workflow. Run locally or via the validate-ga-overrides GitHub Actions
workflow on any push that touches the file.

Exit code 0 = valid. Exit code 1 = one or more errors (details printed to stdout).
"""

import json
import re
import sys
from datetime import datetime

OVERRIDES_PATH = "assets/data/ga-members-overrides.json"

VALID_STATUSES = {"Resigned", "Suspended", "Removed", "Deceased", "Vacant"}
VALID_CHAMBERS = {"House of Representatives", "Senate"}
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OCD_ID_RE = re.compile(r"^ocd-person/[0-9a-f-]{36}$")
RESERVED_KEYS = {"_note", "_inject", "_example_by_id", "_example_by_name"}

errors = []


def err(context, msg):
    errors.append(f"  [{context}] {msg}")


def check_iso_date(context, field, value):
    if not ISO_DATE_RE.match(value):
        err(context, f"{field} must be YYYY-MM-DD, got: {repr(value)}")
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        err(context, f"{field} is not a real date: {repr(value)}")
        return False
    return True


def check_year_consistency(context, date_field, year_field, date_val, year_val):
    """termStart/termStartYear and statusDate must be internally consistent."""
    if not date_val:
        return
    if not ISO_DATE_RE.match(date_val):
        return  # already caught above
    expected_year = int(date_val[:4])
    if year_val is not None and year_val != expected_year:
        err(context, f"{year_field} ({year_val}) does not match year in {date_field} ({date_val})")


def validate_inject_entry(entry, index):
    context = f"_inject[{index}] id={entry.get('id', '?')}"

    required = ["id", "name", "chamber", "district", "status", "statusDate"]
    for field in required:
        if field not in entry:
            err(context, f"missing required field: {field}")

    chamber = entry.get("chamber")
    if chamber and chamber not in VALID_CHAMBERS:
        err(context, f"chamber must be one of {VALID_CHAMBERS}, got: {repr(chamber)}")

    status = entry.get("status")
    if status and status not in VALID_STATUSES:
        err(context, f"status must be one of {VALID_STATUSES}, got: {repr(status)}")

    status_date = entry.get("statusDate", "")
    if status_date:
        check_iso_date(context, "statusDate", status_date)

    term_start = entry.get("termStart", "")
    if term_start:
        if check_iso_date(context, "termStart", term_start):
            check_year_consistency(context, "termStart", "termStartYear",
                                   term_start, entry.get("termStartYear"))

    district = entry.get("district")
    if district is not None and not isinstance(district, int):
        err(context, f"district must be an integer, got: {repr(district)}")

    birth_date = entry.get("birthDate", "")
    if birth_date:
        check_iso_date(context, "birthDate", birth_date)


def validate_override_entry(key, override):
    context = f"override key={repr(key)}"

    # Warn if the key looks like a leftover example entry
    if "REPLACE-WITH-REAL-ID" in key or key.startswith("First Last"):
        err(context, "looks like an un-replaced example entry — remove or update it")

    status = override.get("status")
    if status is not None and status not in VALID_STATUSES:
        err(context, f"status must be one of {VALID_STATUSES}, got: {repr(status)}")

    status_date = override.get("statusDate", "")
    if status_date:
        check_iso_date(context, "statusDate", status_date)

    # If status is set, statusDate is required
    if status and not status_date:
        err(context, "status is set but statusDate is missing")

    term_start = override.get("termStart", "")
    if term_start:
        if check_iso_date(context, "termStart", term_start):
            check_year_consistency(context, "termStart", "termStartYear",
                                   term_start, override.get("termStartYear"))

    birth_date = override.get("birthDate", "")
    if birth_date:
        check_iso_date(context, "birthDate", birth_date)


def main():
    # 1. Parse JSON
    try:
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {OVERRIDES_PATH}")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON — {exc}")
        sys.exit(1)

    # 2. Validate _inject entries
    inject = data.get("_inject", [])
    if not isinstance(inject, list):
        err("_inject", "must be an array")
    else:
        for i, entry in enumerate(inject):
            validate_inject_entry(entry, i)

    # 3. Validate override entries (skip reserved/example keys)
    for key, value in data.items():
        if key in RESERVED_KEYS:
            continue
        if not isinstance(value, dict):
            err(f"key={repr(key)}", "override value must be an object")
            continue
        validate_override_entry(key, value)

    # 4. Report
    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s) in {OVERRIDES_PATH}:\n")
        for e in errors:
            print(e)
        sys.exit(1)

    override_count = sum(1 for k in data if k not in RESERVED_KEYS)
    inject_count = len(inject)
    print(f"OK — {override_count} overrides, {inject_count} injected entries — {OVERRIDES_PATH}")


if __name__ == "__main__":
    main()
