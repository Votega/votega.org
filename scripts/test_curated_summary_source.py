#!/usr/bin/env python3
"""Assert which summary a Key Votes card gets, and that AI text is always marked as AI.

generate_curated_ga_bills.pick_summary: the editor's summaryOverride always wins; a
REVIEWED AI summary from ga-bill-summaries.json fills in only when there is none; the
official caption is the last resort. summarySource drives the "AI summary" label on
the legislator page, so a wrong source would show AI text unlabeled.

Usage:
  python scripts/test_curated_summary_source.py

Exits 0 on success, 1 on any failure. Standard library only, no network.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_curated_ga_bills as G  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


REVIEWED = {
    "2025_26|HB 1": {"text": "AI text", "source": "ai"},
    "2025_26|HB 2": {"text": "Editor text", "source": "editor"},
}


def pick_cases():
    e = {"identifier": "HB 1", "session": "2025_26"}
    check("editor override wins over AI",
          G.pick_summary(dict(e, summaryOverride="Mine"), REVIEWED, "caption"), ("Mine", "editor"))
    check("reviewed AI used when there is no override",
          G.pick_summary(e, REVIEWED, "caption"), ("AI text", "ai"))
    check("blank override does not block AI",
          G.pick_summary(dict(e, summaryOverride="  "), REVIEWED, "caption"), ("AI text", "ai"))
    check("AI for the same number in another biennium is not used",
          G.pick_summary({"identifier": "HB 1", "session": "2023_24"}, REVIEWED, "caption"),
          ("caption", "caption"))
    check("an editor entry in the file is not treated as AI",
          G.pick_summary({"identifier": "HB 2", "session": "2025_26"}, REVIEWED, "caption"),
          ("caption", "caption"))
    check("nothing at all gives no summary",
          G.pick_summary({"identifier": "HB 9", "session": "2025_26"}, {}, ""), ("", None))


def load_cases():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"summaries": REVIEWED}, f)
        check("reads the summaries map", G.load_reviewed_summaries(p), REVIEWED)
        check("missing file is an empty map",
              G.load_reviewed_summaries(os.path.join(d, "none.json")), {})
        with open(p, "w", encoding="utf-8") as f:
            f.write("{broken")
        check("unreadable file is an empty map, not a crash", G.load_reviewed_summaries(p), {})


if __name__ == "__main__":
    print("summary precedence"); pick_cases()
    print("loading"); load_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")
