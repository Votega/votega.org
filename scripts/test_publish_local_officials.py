#!/usr/bin/env python3
"""Offline invariants of the officials open-data export. No network, no deps.

Pinned: the active-vs-history split (a former and a staged member are in history
only; the current board is exactly local_terms.active_members), contact fields
only in the current files, blanks are None / empty CSV cells and never "", the
schema $id matches its published path, history is declared not-backfilled, and
the record floor refuses a gutted build.

Run: python scripts/test_publish_local_officials.py
"""
import csv
import io
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import local_officials_export as lo  # noqa: E402
from lib import sibling_publish as SP  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)


TODAY = date(2026, 11, 10)
J = [{"id": "demo", "members": [
    {"name": "Old Holder", "role": "Commissioner", "seat": "District 1", "seat_id": "district-1",
     "party": "Republican", "email": "old@x.gov", "phone": "555", "last_elected": 2020,
     "takes_office": date(2021, 1, 1), "leaves_office": date(2025, 1, 1),
     "leave_reason": "term-ended", "source": "https://x"},
    {"name": "Sitting", "role": "Commissioner", "seat": "District 1", "seat_id": "district-1",
     "party": "", "email": "", "phone": "555-1", "last_elected": 2024, "term_end": 2028,
     "takes_office": "2025-01-01", "source": "https://x"},
    {"name": "Staged", "role": "Commissioner", "seat": "District 2", "seat_id": "district-2",
     "email": "s@x.gov", "takes_office": date(2027, 1, 1), "source": "https://x"},
    {"name": "Plain", "role": "Mayor", "seat": "At-large", "seat_id": "mayor", "source": "https://x"},
]}]

arts, summ = lo.build_officials_artifacts(J, TODAY, "2026-11-10T00:00:00Z")
P = summ["paths"]
cur = json.loads(arts[P["officials.json"]])
hist = json.loads(arts[P["officials-history.json"]])
cur_names = {r["name"] for r in cur["officials"]}
hist_names = {r["name"] for r in hist["officials"]}

check(cur_names == {"Sitting", "Plain"}, f"current board wrong: {cur_names}")
check(hist_names == {"Old Holder", "Sitting", "Staged", "Plain"}, f"history must hold every row: {hist_names}")
check(cur["metadata"]["count"] == 2 and hist["metadata"]["count"] == 4, "metadata counts")
check(hist["metadata"]["historyStatus"] == "not-backfilled", "historyStatus declared")
check(hist["metadata"]["historyStartsAt"] == "2021-01-01", "historyStartsAt = earliest recorded date")
check(cur["metadata"]["asOf"] == "2026-11-10", "asOf recorded")

# Contact fields: current board only.
check(all("email" in r and "phone" in r for r in cur["officials"]), "current rows carry contact")
check(all("email" not in r and "phone" not in r for r in hist["officials"]), "history must not carry contact")
hist_csv = list(csv.reader(io.StringIO(arts[P["officials-history.csv"]].decode())))
check("email" not in hist_csv[0] and "phone" not in hist_csv[0], "history CSV has no contact columns")
check(hist_csv[0][:13] == ["jurisdiction", "seat_id", "seat", "name", "role", "title", "party",
                           "takes_office", "leaves_office", "leave_reason", "last_elected",
                           "term_end", "source"], "history column order is the contract")

# The None rule: never "" in JSON; empty CSV cell, never "None".
for label, rows in (("current", cur["officials"]), ("history", hist["officials"])):
    for r in rows:
        for k, v in r.items():
            check(v != "", f"{label} {r['name']}.{k} is an empty string")
sitting = next(r for r in cur["officials"] if r["name"] == "Sitting")
check(sitting["party"] is None and sitting["email"] is None, "blank party/email -> None")
old = next(r for r in hist["officials"] if r["name"] == "Old Holder")
check(old["leaves_office"] == "2025-01-01" and old["takes_office"] == "2021-01-01", "dates are ISO strings")
cur_csv = arts[P["officials.csv"]].decode()
check("None" not in cur_csv and "None" not in arts[P["officials-history.csv"]].decode(), "CSV leaks 'None'")

# Schemas: $id from the published path, versioned.
for key in ("officials.schema.json", "officials-history.schema.json"):
    sch = json.loads(arts[P[key]])
    check(sch["$id"].endswith("/" + P[key]), f"{key} $id must be its published path")
    check(sch.get("schemaVersion") and sch.get("schemaStability"), f"{key} needs version + stability")
check("email" in json.loads(arts[P["officials.schema.json"]])["properties"], "current schema has email")
check("email" not in json.loads(arts[P["officials-history.schema.json"]])["properties"], "history schema has no email")

# The record floor refuses a gutted build.
try:
    SP.min_items(P["officials.json"], "officials", minimum=100)(arts)
    check(False, "floor must reject a 2-row board")
except ValueError:
    pass

if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("ok")
