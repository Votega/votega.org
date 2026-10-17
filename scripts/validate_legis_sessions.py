#!/usr/bin/env python3
"""Validate ga-legis-sessions.json: gate on self-contradiction, report on change.

  Tier 1 - the file contradicts itself. metadata.count disagreeing with the
  rows, two rows with one SessionId, a row with no id or description, the
  table not in the newest-first order the generator writes it in, a
  defaultSessionId that is not the one row flagged default, a regular-session
  description whose second year is not its first plus one ("2023-2025").

  Tier 2 - the legislature published something we did not expect. A second
  (or no) IsDefault row, a regular-session description that no longer parses as
  'YYYY-YYYY Regular Session' (lib/ga_sessions.regular_session_description()
  keys on exactly that wording), a session that disappeared since last run, a
  new session, a changed description. All of these are upstream wording or
  upstream content; the table should publish what the service says and a human
  should be told.

This replaces the inline heredoc in update-legis-sessions.yml, whose
`len(defaults) == 1` and regular-session-description regex asserts gated on
the legislature's wording, plus `validate_data_update.py --min sessions=20`,
a hand-pinned floor (the generator carried the same MIN_SESSIONS = 20 and is
relaxed with it: an EMPTY response is still fatal there, since there is
nothing to write, but a smaller table is now reported by name here). The table
is read by lib/ga_sessions.py, which falls back to its own hardcoded map for
any id the file lacks, so a short table degrades lookups rather than breaking
them. See docs/audits/2026-10-13-data-pipeline-audit.md 2.6.

Usage:
    python scripts/validate_legis_sessions.py assets/data/ga-legis-sessions.json \
        --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  a tier-1 check failed - the caller must not commit
"""

import argparse
import json
import os
import re
import subprocess
import sys

REGULAR = re.compile(r"(\d{4})-(\d{4}) Regular Session")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, check=True).stdout
        return json.loads(blob.decode("utf-8"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


# -- tier 1: the file against itself -------------------------------------------

def tier1(d):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    rows = d.get("sessions")
    meta = d.get("metadata") or {}
    if not isinstance(rows, list):
        return ["sessions is not a list"]
    if not rows:
        return ["no sessions in the file"]

    errors = []
    if meta.get("count") != len(rows):
        errors.append(f"metadata.count ({meta.get('count')}) != len(sessions) ({len(rows)})")

    ids = [r.get("id") for r in rows]
    if any(not i for i in ids):
        errors.append("a session has no id")
    dupes = sorted({i for i in ids if i and ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate SessionId in the table: {dupes}")
    for r in rows:
        if not r.get("description"):
            errors.append(f"session {r.get('id')} has no description")

    good = [i for i in ids if isinstance(i, int)]
    if good != sorted(good, reverse=True):
        errors.append("sessions are not in newest-first (descending id) order")

    defaults = [r.get("id") for r in rows if r.get("isDefault")]
    want = defaults[0] if len(defaults) == 1 else None
    if meta.get("defaultSessionId") != want:
        errors.append(f"metadata.defaultSessionId ({meta.get('defaultSessionId')}) is not the "
                      f"single IsDefault row ({want})")

    for r in rows:
        m = REGULAR.fullmatch(r.get("description") or "")
        if m and int(m.group(2)) != int(m.group(1)) + 1:
            errors.append(f"session {r.get('id')}: {r['description']!r} does not span "
                          f"consecutive years")
    return errors


# -- tier 2: upstream wording, and the table against last week's ----------------

def tier2(new, old):
    """What the legislature published that we did not expect, as (heading, [lines])."""
    sections = []
    rows = new.get("sessions") or []

    defaults = [r for r in rows if r.get("isDefault")]
    if len(defaults) != 1:
        which = ", ".join(f"{r['id']} ({r['description']})" for r in defaults) or "none"
        sections.append(("IsDefault is not exactly one session",
                         [f"- the service flags {len(defaults)}: {which}. "
                          f"`metadata.defaultSessionId` is null while this holds."]))

    odd = [f"- {r['id']}: {r['description']!r}" for r in rows
           if "Regular" in (r.get("description") or "")
           and not REGULAR.fullmatch(r["description"])]
    if odd:
        sections.append(("Regular-session wording no longer parses as 'YYYY-YYYY Regular Session'",
                         odd + ["- `regular_session_description()` in lib/ga_sessions.py keys on "
                                "that wording, so these ids will not resolve from a `YYYY_YY` tag."]))

    if not old or not isinstance(old.get("sessions"), list):
        return sections

    n = {r.get("id"): r for r in rows}
    o = {r.get("id"): r for r in old["sessions"]}
    dropped = [f"- {i}: {o[i].get('description')}" for i in sorted(set(o) - set(n), reverse=True, key=str)]
    if dropped:
        sections.append(("Sessions dropped - check these first", dropped +
                         [f"- the table went {len(o)} -> {len(n)}; it only ever grows, so this is "
                          f"most likely a truncated response. lib/ga_sessions.py falls back to its "
                          f"hardcoded map for these ids."]))
    added = [f"- {i}: {n[i].get('description')} (library `{n[i].get('library')}`)"
             for i in sorted(set(n) - set(o), reverse=True, key=str)]
    if added:
        sections.append(("New sessions published", added))
    renamed = [f"- {i}: {o[i].get('description')!r} -> {n[i].get('description')!r}"
               for i in sorted(set(n) & set(o), reverse=True, key=str)
               if o[i].get("description") != n[i].get("description")]
    if renamed:
        sections.append(("Descriptions changed", renamed))
    odef, ndef = (old.get("metadata") or {}).get("defaultSessionId"), \
        (new.get("metadata") or {}).get("defaultSessionId")
    if odef != ndef:
        sections.append(("Default session moved", [f"- {odef} -> {ndef}"]))
    return sections


def render(path, sections):
    out = [f"## Legis session table: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("No material change this run.")
    else:
        out.append("Each line is something legis.ga.gov published, so none of them "
                   "blocked the update - the table is committed. They are here because "
                   "every bills and votes producer resolves a SessionId through it.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--baseline-ref", default="HEAD",
                    help="git ref to diff the new file against (default HEAD)")
    ap.add_argument("--report-out", help="write the tier-2 markdown report here")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"FAIL: {args.path} was not generated", file=sys.stderr)
        return 1
    try:
        new = load(args.path)
    except json.JSONDecodeError as exc:
        print(f"FAIL: {args.path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    errors = tier1(new)
    if errors:
        print("TIER 1 FAILED - the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nThis is a generator bug, not a change in the legislature's table. "
              "The rejected file is uploaded as a workflow artifact so it can be "
              "inspected.", file=sys.stderr)
        return 1
    print(f"Tier 1 passed: {len(new['sessions'])} sessions, ids unique, count and "
          f"default agree.")

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} material change(s) - reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
