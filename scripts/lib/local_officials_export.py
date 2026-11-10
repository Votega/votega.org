"""Build the officials open-data artifacts from _data/local_officials.yml.

Pure functions over the parsed YAML (no yaml import, no network), so they are
testable with no dependencies. publish_ga_local_government.py loads the file and
calls build_officials_artifacts().

Two datasets from one source:
  officials          the CURRENT board: rows active on `today` (local_terms.is_active).
                     Carries contact fields (email, phone).
  officials-history  EVERY member row, one per person per term: former members,
                     the sitting board, and staged incoming members. No contact
                     fields: a former member's phone and email are not ours to
                     keep republishing.

History is NOT backfilled. The file records a departure only from the day someone
started recording them, so a seat with one holder here has had no earlier holder
RECORDED, which is not the same as having had none. The metadata says so
(`historyStatus: "not-backfilled"`, `historyStartsAt`).

Blank is always None (JSON null / empty CSV cell), never "".
"""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import local_terms as lt  # noqa: E402
from lib.sibling_publish import build_json  # noqa: E402

REPO_RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-local-government/main"
SCHEMA_VERSION = "1.0.0"
OFFICIALS_DIR = "data/officials"
DATASET = "officials"

# Column order is the published contract; new columns are APPENDED only.
HISTORY_COLUMNS = ["jurisdiction", "seat_id", "seat", "name", "role", "title",
                   "party", "takes_office", "leaves_office", "leave_reason",
                   "last_elected", "term_end", "source", "status"]
CURRENT_COLUMNS = HISTORY_COLUMNS + ["email", "phone"]
DATE_FIELDS = ("takes_office", "leaves_office")
INT_FIELDS = ("last_elected", "term_end")

FIELD_DOC = {
    "jurisdiction": "jurisdiction slug (joins data/places.json `placeId`)",
    "seat_id": "stable seat key; every holder of a seat, past and present, shares it",
    "seat": "display label of the seat (may be reworded over time; seat_id never is)",
    "name": "name as the body styles it",
    "role": "canonical function (Mayor, Council Member, Commissioner, ...)",
    "title": "verbatim office label when a body uses a distinctive one",
    "party": "party on a partisan seat; null for nonpartisan municipal seats",
    "takes_office": "ISO date the person began holding the seat; null = held before recording began",
    "leaves_office": "ISO date the hold ENDS, exclusive (first day they no longer hold it); null = still holding",
    "leave_reason": "term-ended | resigned | removed | deceased; null while holding",
    "last_elected": "year of the election that seated them",
    "term_end": "year the current term ends; null when not established",
    "source": "primary-source URL a person confirmed the row against",
    "status": "null for a normal holder; \"Suspended\" = still legally holds the seat while an interim serves",
    "email": "official contact email (current board only)",
    "phone": "official contact phone (current board only)",
}


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
    return None if v in (None, "") else v


def _cell(member, field):
    v = member.get(field)
    if field in DATE_FIELDS:
        d = lt.parse_date(v)
        return d.isoformat() if d else None
    return _blank_to_none(v)


def _row(jurisdiction, member, columns):
    return {c: jurisdiction["id"] if c == "jurisdiction" else _cell(member, c)
            for c in columns}


def _sorted(rows):
    return sorted(rows, key=lambda r: (r["jurisdiction"], r["seat_id"] or "",
                                       r["takes_office"] or "", r["name"] or ""))


def current_rows(jurisdictions, today):
    return _sorted([_row(j, m, CURRENT_COLUMNS)
                    for j in jurisdictions for m in lt.active_members(j, today)])


def history_rows(jurisdictions):
    return _sorted([_row(j, m, HISTORY_COLUMNS)
                    for j in jurisdictions for m in (j.get("members") or [])
                    if isinstance(m, dict)])


def history_starts_at(rows):
    """Earliest dated takes_office/leaves_office in the history, or None."""
    dates = [r[f] for r in rows for f in DATE_FIELDS if r.get(f)]
    return min(dates) if dates else None


def to_csv(rows, columns):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: ("" if r[c] is None else r[c]) for c in columns})
    return buf.getvalue().encode()


def schema_url(path):
    return f"{REPO_RAW_BASE}/{path}"


def _prop(field):
    typ = "integer" if field in INT_FIELDS else "string"
    return {"type": [typ, "null"], "description": FIELD_DOC[field]}


def schema_for(path, title, columns, stability):
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": schema_url(path),
        "title": title,
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": stability,
        "type": "object",
        "required": ["jurisdiction", "seat_id", "name"],
        "properties": {c: _prop(c) for c in columns},
    }


CURRENT_STABILITY = (
    "Stable field names and meanings. The current board is the rows holding a seat "
    "on `metadata.asOf`; a member staged to take office later is not in it. A "
    "blank value is null, never an empty string. Contact fields (email, phone) "
    "appear in this file only. New fields are appended, never reordered.")
HISTORY_STABILITY = (
    "Stable field names and meanings. One row per person per term. HISTORY IS NOT "
    "BACKFILLED: it begins at `metadata.historyStartsAt`, so a seat with a single "
    "holder here means no earlier holder is RECORDED, not that there was none. "
    "No contact fields. New fields are appended, never reordered.")


def build_officials_artifacts(jurisdictions, today, generated_at):
    """-> (artifacts {remote path: bytes}, summary dict). `today` is a date."""
    cur = current_rows(jurisdictions, today)
    hist = history_rows(jurisdictions)
    starts = history_starts_at(hist)
    base = {"generatedAt": generated_at, "publisher": "VoteGA.org",
            "schemaVersion": SCHEMA_VERSION}
    p = {k: f"{OFFICIALS_DIR}/{k}" for k in (
        "officials.json", "officials.csv", "officials.schema.json",
        "officials-history.json", "officials-history.csv",
        "officials-history.schema.json")}
    artifacts = {
        p["officials.json"]: build_json({
            "metadata": {**base, "count": len(cur), "asOf": today.isoformat(),
                         "jurisdictions": len({r["jurisdiction"] for r in cur})},
            "officials": cur}),
        p["officials.csv"]: to_csv(cur, CURRENT_COLUMNS),
        p["officials.schema.json"]: build_json(schema_for(
            p["officials.schema.json"], "VoteGA local official (current board)",
            CURRENT_COLUMNS, CURRENT_STABILITY)),
        p["officials-history.json"]: build_json({
            "metadata": {**base, "count": len(hist),
                         "historyStartsAt": starts,
                         "historyStatus": "not-backfilled",
                         "note": "One row per person per term. History is not "
                                 "backfilled: a seat with one holder has no "
                                 "earlier holder recorded, which is not the same "
                                 "as none. Includes staged incoming members "
                                 "(takes_office in the future)."},
            "officials": hist}),
        p["officials-history.csv"]: to_csv(hist, HISTORY_COLUMNS),
        p["officials-history.schema.json"]: build_json(schema_for(
            p["officials-history.schema.json"],
            "VoteGA local official (one person's term in one seat)",
            HISTORY_COLUMNS, HISTORY_STABILITY)),
    }
    summary = {"current": len(cur), "history": len(hist),
               "historyStartsAt": starts, "paths": p}
    return artifacts, summary
