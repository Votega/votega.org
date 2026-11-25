"""Meeting Event JSON-LD: Google requires `location`, so a meeting whose body has
no curated location in _data/places.yml must not be emitted as an Event.

Run: python scripts/test_meeting_events.py
"""
import json
import os
import re
import tempfile

import build_entity_pages as bep

PLACE = {"domains": {"meetings": {"schedule": [
    {"body": "City Council", "when": "Mondays, 1 p.m.", "location": "City Hall"},
    {"body": "Planning Commission", "when": "Tuesdays, 6 p.m."},
]}}}


def events_for(bodies):
    meetings = [{"date": "2099-01-%02d" % (i + 1), "body": b, "title": "Regular Meeting"}
                for i, b in enumerate(bodies)]
    original = bep.SRC_DIR
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "local-x-meetings.json"), "w", encoding="utf-8") as fh:
            json.dump({"meetings": meetings}, fh)
        bep.SRC_DIR = tmp
        try:
            ld, fp = bep.build_meeting_events(PLACE, "x", "City of X", "/local/x/", "org")
        finally:
            bep.SRC_DIR = original
    return [json.loads(s) for s in re.findall(r">(\{.*?\})</script>", ld)], fp


def main():
    # Scheduled with a location; scheduled without one; not in the schedule at all.
    events, fp = events_for(["City Council", "Planning Commission", "Zoning Committee"])
    assert len(events) == 1, "only the located meeting is an Event, got %d" % len(events)
    assert events[0]["location"]["name"] == "City Hall"
    assert len(fp) == 1, "fingerprint tracks emitted events only"

    assert events_for(["Zoning Committee"]) == ([], []), "no located meetings, no markup"

    # The cap counts emitted events: unlocated meetings must not use up slots.
    events, _ = events_for(["Zoning Committee"] * 12 + ["City Council"])
    assert len(events) == 1
    print("OK: meeting events require a location")


if __name__ == "__main__":
    main()
