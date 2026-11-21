#!/usr/bin/env python3
"""Snapshot who served in each General Assembly session in seat-history scope.

Writes scripts/data/ga-members-by-session.json from legis.ga.gov's
Members/GetMembersBySession (no auth, no quota): for every regular and special session
from SCOPE_START_YEAR on, every member who served, with chamber, district, party and
the service's dateVacated. It is the committed input that both
scripts/build_id_crosswalk.py (to mint vgIds for members no longer on the roster) and
scripts/build_seat_holds.py read, so those builds stay offline and deterministic.

Sessions come from assets/data/ga-legis-sessions.json, never a literal list: a new
biennium or special session is picked up as soon as generate_legis_sessions.py sees it.
A session the service answers with nothing is an error (exit 1, file untouched), because
an empty listing would otherwise read as "nobody served".

Usage: python scripts/fetch_ga_members_by_session.py
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_soap import get_members_by_session  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_FILE = os.path.join(REPO_ROOT, "assets", "data", "ga-legis-sessions.json")
OUTPUT_FILE = os.path.join(REPO_ROOT, "scripts", "data", "ga-members-by-session.json")
SCOPE_START_YEAR = 2023          # docs/seat-history-design.md, "Scope"
KEEP = ("id", "first", "middle", "last", "nickname", "suffix", "party", "chamber",
        "district", "dateVacated")


def session_year(library):
    """'20232024' -> 2023, '2023EX' -> 2023, None/other -> None."""
    m = re.match(r"(\d{4})", library or "")
    return int(m.group(1)) if m else None


def sessions_in_scope(sessions):
    keep = [s for s in sessions if (session_year(s.get("library")) or 0) >= SCOPE_START_YEAR]
    return sorted(keep, key=lambda s: s["id"])


def main():
    with open(SESSIONS_FILE, encoding="utf-8") as f:
        sessions = sessions_in_scope(json.load(f)["sessions"])
    out = {"metadata": {"generatedAt": None, "source": "legis.ga.gov Members/GetMembersBySession",
                        "scopeStartYear": SCOPE_START_YEAR, "sessions": []},
           "sessions": {}}
    for s in sessions:
        rows = get_members_by_session(s["id"])
        if not rows:
            print(f"Error: session {s['id']} ({s['description']}) returned no members", file=sys.stderr)
            return 1
        rows = sorted(({k: r.get(k) for k in KEEP} for r in rows), key=lambda r: r["id"])
        out["sessions"][str(s["id"])] = rows
        out["metadata"]["sessions"].append({"id": s["id"], "description": s["description"],
                                            "library": s["library"], "members": len(rows)})
        print(f"{s['id']} {s['description']}: {len(rows)} members, "
              f"{sum(1 for r in rows if r['dateVacated'])} vacated")
    old = None
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            old = json.load(f)
    if old and old["sessions"] == out["sessions"] and \
            old["metadata"]["sessions"] == out["metadata"]["sessions"]:
        print(f"{OUTPUT_FILE} unchanged")
        return 0
    out["metadata"]["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(OUTPUT_FILE, out, indent=1)
    print(f"Wrote {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
