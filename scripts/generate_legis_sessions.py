#!/usr/bin/env python3
"""Generate ga-legis-sessions.json from the legis.ga.gov SOAP Session service.

`Session/GetSessions` takes no parameters and returns every session the legislature has
published — 23 of them, back to 2001-2002 — each with its numeric `SessionId`, description,
`Library` string and `IsDefault` flag. That is the authoritative answer to a question this
project previously had to answer by hand, and badly: `LEGIS_SESSIONS` in
`scripts/lib/ga_sessions.py` was maintained by looking ids up through the legis REST API
(which needs a short-lived token), and the 2023-2024 id had to be found by probing
`GetVotes` across a guessed range.

Probing cannot work in general. The id space is neither contiguous nor ordered by era: it
runs 1, 6, 7, 11, 13-15, 18, 20-27 and then jumps to 1027. A sequential sweep finds the
recent sessions and silently misses every one before 2021 — 2019-2020 is id 27.

Why a committed file rather than a call at import time: `lib/ga_sessions.py` is imported by
every producer and by the test suite, so it must not touch the network. This writes the
table; the lib reads it and falls back to its own hardcoded map when it is absent.

Run it when a new session appears (see RECURRING-TASKS.md), then commit the result:
    python scripts/generate_legis_sessions.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.ga_soap import SESSION_URL, get_sessions

OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-legis-sessions.json"


def main() -> int:
    sessions = get_sessions()
    if not sessions:
        print("Error: GetSessions returned nothing — refusing to overwrite the table",
              file=sys.stderr)
        return 1
    # No count floor: the table only grows, but a short response is validate_legis_sessions.py's
    # to report BY NAME (which ids vanished), not this script's to refuse -- a refusal here
    # discards the whole run, and a floor of 20 is the world's number, not ours.
    missing = [s for s in sessions if not s.get("id") or not s.get("description")]
    if missing:
        print(f"Error: {len(missing)} session(s) missing an id or description",
              file=sys.stderr)
        return 1

    # Newest first, which is the order anyone reading the file cares about.
    sessions.sort(key=lambda s: -s["id"])

    defaults = [s["id"] for s in sessions if s.get("isDefault")]
    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": f"legis.ga.gov SOAP Session/GetSessions ({SESSION_URL})",
            "count": len(sessions),
            # Recorded, but NOT to be read as "the session in progress": IsDefault marks
            # the current REGULAR session, so during a special session it still points at
            # the regular one. ACTIVE_SESSION in lib/ga_sessions.py stays editorial.
            "defaultSessionId": defaults[0] if len(defaults) == 1 else None,
        },
        "sessions": sessions,
    }
    write_json_atomic(OUTPUT_FILE, output, indent=2)

    print(f"Wrote {len(sessions)} sessions to {OUTPUT_FILE}")
    for s in sessions[:4]:
        flag = "  (IsDefault)" if s.get("isDefault") else ""
        print(f"  {s['id']:>5}  {s['description']:<32} {s['library'] or '':<10}{flag}")
    print(f"  ... and {max(0, len(sessions) - 4)} older")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
