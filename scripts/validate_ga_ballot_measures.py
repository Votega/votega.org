#!/usr/bin/env python3
"""Validate ga-ballot-measures.json before it is published to Votega/ga-legislation.

Every check here is tier 1: the hand-curated file against ITSELF and against its
own schema. There is no tier 2, and that is the finding, not an omission:

  * Nothing is committed by the publish job, so a refusal discards no data -- the
    source is already in the repo and the sibling just keeps its last publish.
  * No check reads a fact about the world. Ballot measures are curated, never
    regenerated; the schema says measures are never deleted after an election, so
    an empty list is a wiped file (publish_ga_ballot_measures also floors it with
    min_items before any PUT), not a quiet cycle.
  * The status and type vocabularies are read FROM ga-ballot-measures.schema.json
    rather than restated, so adding a kind of measure is one edit in one file. The
    inline heredoc this replaces hardcoded both sets in the workflow.

Checks: every measure carries the schema's required fields; id matches the
schema's slug pattern and is unique; status and type are in the schema's enums;
no key the schema does not declare; and the lifecycle coupling -- a terminal
status (passed/failed) carries a results object, and a results object implies a
terminal status.

Usage:
    python scripts/validate_ga_ballot_measures.py

Exit codes:
    0  consistent
    1  a check failed - the caller must not publish
"""

import json
import os
import re
import sys

SRC = "assets/data/ga-ballot-measures.json"
SCHEMA = "assets/data/ga-ballot-measures.schema.json"
TERMINAL = ("passed", "failed")


def tier1(doc, schema):
    """Return a list of contradictions. Empty means the file is publishable."""
    measures = doc.get("measures")
    if not isinstance(measures, list):
        return ["measures is not a list"]
    if not measures:
        return ["ga-ballot-measures.json has no measures"]

    spec = (schema.get("$defs") or {}).get("measure") or {}
    props = spec.get("properties") or {}
    required = spec.get("required") or []
    status_enum = set((props.get("status") or {}).get("enum") or [])
    type_enum = set((props.get("type") or {}).get("enum") or [])
    pattern = (props.get("id") or {}).get("pattern")

    errors, seen = [], set()
    for i, m in enumerate(measures):
        label = repr(m.get("id")) if m.get("id") else f"#{i}"
        for field in required:
            if not m.get(field):
                errors.append(f"measure {label} missing required field {field!r}")
        mid = m.get("id")
        if mid:
            if pattern and not re.search(pattern, mid):
                errors.append(f"measure {mid!r}: id does not match the schema pattern {pattern}")
            if mid in seen:
                errors.append(f"duplicate measure id {mid!r}")
            seen.add(mid)
        if m.get("status") and status_enum and m["status"] not in status_enum:
            errors.append(f"measure {label} has invalid status {m['status']!r}")
        if m.get("type") and type_enum and m["type"] not in type_enum:
            errors.append(f"measure {label} has invalid type {m['type']!r}")
        if props:
            extra = sorted(set(m) - set(props))
            if extra:
                errors.append(f"measure {label} has key(s) the schema does not declare: {extra}")
        terminal = m.get("status") in TERMINAL
        has_results = isinstance(m.get("results"), dict)
        if terminal and not has_results:
            errors.append(f"measure {label} is {m['status']} but has no results object")
        if has_results and not terminal:
            errors.append(f"measure {label} has results but status is {m.get('status')!r} "
                          f"(expected passed/failed)")
    return errors


def main():
    try:
        with open(SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        with open(SRC, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read {SRC} / {SCHEMA}: {exc}", file=sys.stderr)
        return 1
    errors = tier1(doc, schema)
    if errors:
        print("TIER 1 FAILED - ga-ballot-measures.json contradicts itself or its "
              "schema, refusing to publish:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"ga-ballot-measures.json valid: {len(doc['measures'])} measures")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
