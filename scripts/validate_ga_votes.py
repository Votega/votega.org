#!/usr/bin/env python3
"""Validate ga-member-votes.json: gate on self-consistency, report on change.

Two kinds of wrong can come out of a vote sweep, and conflating them is how a
validator ends up discarding the truth:

  Tier 1 — the file contradicts itself. A `metadata.totalVotes` that disagrees
  with the records it counts, a per-session `voteCount` that disagrees with the
  records carrying that session id, a session marked preserved with nothing in
  the file, a member row whose index points outside the shared `voteIds` list, a
  duplicate in that list, a vote code the codec does not define, a member row
  that is not a compact map. No fact about the General Assembly can make any of
  these legitimately true — they mean the producer or the preserved/fetched
  merge is broken, and the file must not be committed. These exit 1.

  Tier 2 — the file disagrees with last week's, or with a busy biennium. Fewer
  roll calls than a full session holds, fewer members with a vote record, a
  chamber captioning a result in wording the producer has not seen. Every one of
  these is something the world can legitimately do, and a quiet week is the
  normal case for a weekly job. These are REPORTED, never gated.

The gates this replaces were on the wrong side of that line twice:

  * `assert votes >= 1000` and `assert members >= 150` — floors pinned to the
    shape of a mid-biennium session. They are cleared by the PRESERVED layer
    alone today, which is exactly what makes them dangerous: they look safe
    while the thing they are meant to guard (the incremental fetch of the active
    session) can fail silently under them. Meanwhile a `--full-refresh` run that
    loses one closed session, or the first weeks of a new biennium, trips them
    and discards the whole sweep.
  * `assert result in ('Pass', 'Fail')` — the chambers write their own captions.
    New wording is a gap in the producer's normalization that a human must
    close, not a reason to throw away ~1,500 SOAP calls' worth of record. A
    missing result is still tier 1: the field is required.

See docs/audits/2026-10-13-data-pipeline-audit.md 2.6 for this class of
validator repo-wide, scripts/validate_fec_data.py for the reference
implementation, and the comment above the "Validate output" step of
update-local-government.yml for the first workflow to make the split.

Usage:
    python scripts/validate_ga_votes.py assets/data/ga-member-votes.json \
        --expect-no-overlay --baseline-ref HEAD --report-out report.md

Exit codes:
    0  self-consistent (a tier-2 report may still have been written)
    1  a tier-1 check failed — the caller must not commit
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.votes_schema import VOTE_DECODE  # noqa: E402

# The compact codes a member row may carry: VOTE_DECODE is keyed by code.
VOTE_CODE_SET = set(VOTE_DECODE)

# A healthy biennium holds ~2,400 passage roll calls across ~240 members. These
# are REPORTING thresholds, not gates: the number of roll calls a session holds
# is the General Assembly's business, and a new biennium starts at nearly zero.
VOTES_FLOOR = 1000
MEMBERS_FLOOR = 150

# The result values the producer's caption rule normalizes to. Anything else is
# wording it has not seen — reported so a human can extend the rule.
KNOWN_RESULTS = ("Pass", "Fail")

VOTE_REQUIRED = ("bill", "session", "chamber", "result")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def baseline(path, ref):
    """The committed version of the file, or None when there isn't one."""
    try:
        blob = subprocess.run(["git", "show", f"{ref}:{path}"],
                              capture_output=True, text=True, check=True).stdout
        return json.loads(blob)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def by_session(votes):
    out = {}
    for r in votes.values():
        out[r.get("session")] = out.get(r.get("session"), 0) + 1
    return out


# ── tier 1: the file against itself ────────────────────────────────────────────

def tier1(d, expect_no_overlay=False):
    """Return a list of contradictions. Empty means the file is self-consistent."""
    errors = []
    votes = d.get("votes")
    member_votes = d.get("memberVotes")
    vote_ids = d.get("voteIds")
    meta = d.get("metadata") or {}

    if not votes:
        errors.append("no vote records in the file")
        return errors          # nothing below can say anything useful
    if not isinstance(member_votes, dict) or not member_votes:
        errors.append("no memberVotes in the file")
        return errors

    total = meta.get("totalVotes")
    if total is not None and total != len(votes):
        errors.append(f"metadata.totalVotes ({total}) != len(votes) ({len(votes)})")

    # The compact schema (v2): `voteIds` is the shared ordered index every member
    # row resolves through. A missing, short or duplicated index silently shows
    # one roll call's record under another's heading.
    if not isinstance(vote_ids, list):
        errors.append("voteIds is missing or not a list — the compact schema was not "
                      "written (see scripts/lib/votes_schema.py)")
        return errors
    if len(vote_ids) < len(votes):
        errors.append(f"voteIds holds {len(vote_ids)} entries, fewer than the "
                      f"{len(votes)} vote records it indexes")
    if len(set(vote_ids)) != len(vote_ids):
        errors.append("voteIds contains duplicates, so one index resolves to two "
                      "different roll calls")
    missing = [v for v in votes if v not in set(vote_ids)][:5]
    if missing:
        errors.append(f"vote record(s) absent from the voteIds index, so no member row "
                      f"can reach them: {missing}")

    # Required fields on a vote record. `chamber` in particular must be STORED:
    # inferring it from motionText reads the motion backwards (0-for-270 measured
    # against the official record), and `rollNumber` cannot be derived at all.
    for key in list(votes)[:3000]:
        r = votes[key]
        absent = [f for f in VOTE_REQUIRED if f not in r]
        if absent:
            errors.append(f"vote {key} is missing required field(s): {', '.join(absent)}")
        elif r.get("result") is None:
            errors.append(f"vote {key} has a null result")

    # Per-session integrity. The whole-file floors are cleared by the preserved
    # layer alone, so this is the check that actually catches an incremental run
    # that dropped or truncated a session.
    actual = by_session(votes)
    for row in (meta.get("sessions") or []):
        sid, claimed = row.get("id"), row.get("voteCount")
        if actual.get(sid, 0) != claimed:
            errors.append(f"metadata claims {claimed} votes for session {sid} but the "
                          f"file holds {actual.get(sid, 0)} — the preserved/fetched "
                          f"merge is wrong")
    for sid in (meta.get("sessionsPreserved") or []):
        if actual.get(sid, 0) == 0:
            errors.append(f"session {sid} is marked preserved but has no votes in the file")

    # Every member row must be a compact map whose keys index inside voteIds and
    # whose values are codes the codec defines.
    n = len(vote_ids)
    not_map = [p for p, row in member_votes.items() if not isinstance(row, dict)][:5]
    if not_map:
        errors.append(f"memberVotes row(s) are not {{index: code}} maps (compact "
                      f"schema): {not_map}")
    bad_idx, bad_code = [], []
    for pid, row in member_votes.items():
        if not isinstance(row, dict):
            continue
        for i, code in row.items():
            try:
                inside = 0 <= int(i) < n
            except (TypeError, ValueError):
                inside = False
            if not inside:
                bad_idx.append(f"{pid}[{i}]")
            if code not in VOTE_CODE_SET:
                bad_code.append(f"{pid}[{i}]={code}")
    if bad_idx:
        errors.append(f"{len(bad_idx)} member vote(s) index outside voteIds "
                      f"(e.g. {bad_idx[:3]})")
    if bad_code:
        errors.append(f"{len(bad_code)} member vote(s) carry a code the codec does not "
                      f"define (e.g. {bad_code[:3]}); known codes are "
                      f"{sorted(VOTE_CODE_SET)}")

    # The workflow invokes the producer with --no-overlay, so a populated overlay
    # source means the producer ignored its own flag — the file disagrees with how
    # it was asked to be built.
    if expect_no_overlay and meta.get("passageOverlaySource") is not None:
        errors.append(f"metadata.passageOverlaySource is "
                      f"{meta['passageOverlaySource']!r}, but the producer was run "
                      f"with --no-overlay")
    return errors


# ── tier 2: a thin sweep, new wording, and last week's file ───────────────────

def tier2(new, old=None):
    """Material facts and changes, as (heading, [lines]) sections."""
    sections = []
    votes = new.get("votes") or {}
    member_votes = new.get("memberVotes") or {}
    meta = new.get("metadata") or {}
    actual = by_session(votes)

    # The two conditions the old floors gated on.
    thin = []
    if len(votes) < VOTES_FLOOR:
        thin.append(f"- {len(votes)} passage roll calls in the file "
                    f"(a full biennium runs ~2,400).")
    if len(member_votes) < MEMBERS_FLOOR:
        thin.append(f"- {len(member_votes)} members carry a vote record "
                    f"(a full biennium runs ~240).")
    if thin:
        thin += ["",
                 "A new biennium legitimately starts here, and so does a session that "
                 "has not convened. But check the generate step's own log: these are "
                 "also what a partial SOAP sweep leaves, and the whole-file numbers "
                 "are cleared by the preserved sessions alone."]
        sections.append(("Fewer records than a busy biennium holds", thin))

    # Wording the producer's caption rule has not seen. The chambers write
    # "Passed", "Agreed to", "Adopted"; a new one needs the rule extended, and
    # until then the site shows the raw string.
    unknown = {}
    for key, r in votes.items():
        res = r.get("result")
        if res is not None and res not in KNOWN_RESULTS:
            unknown.setdefault(res, []).append(key)
    if unknown:
        sections.append(("Result wording the producer does not normalize", [
            f"- `{res}` on {len(keys)} roll call(s), e.g. {keys[:3]}"
            for res, keys in sorted(unknown.items())
        ] + ["",
             "Extend the caption rule in generate_ga_votes_soap.py. Until then these "
             "roll calls render their raw caption instead of Pass/Fail."]))

    if not meta.get("paginationComplete", True):
        sections.append(("The sweep reported itself incomplete", [
            "- metadata.paginationComplete is false, so the source had more to give "
            "than this run took. The next run picks it up."]))

    if not old:
        return sections

    old_votes = old.get("votes") or {}
    old_actual = by_session(old_votes)

    if len(votes) < len(old_votes):
        sections.append(("The file lost roll calls", [
            f"- {len(old_votes)} → {len(votes)}. This file is append-only in normal "
            f"operation; records only leave it on a --full-refresh or a session "
            f"rollover."]))

    gone = sorted(s for s in old_actual if s not in actual)
    arrived = sorted(s for s in actual if s not in old_actual)
    if gone or arrived:
        sections.append(("Sessions in the file changed", [
            f"- session {s} is gone (held {old_actual[s]} votes)" for s in gone
        ] + [f"- session {s} is new ({actual[s]} votes)" for s in arrived]))

    shrunk = [f"- session {s}: {old_actual[s]} → {actual[s]}"
              for s in sorted(set(actual) & set(old_actual))
              if actual[s] < old_actual[s]]
    if shrunk:
        sections.append(("A session holds fewer votes than it did", shrunk))

    old_members = len(old.get("memberVotes") or {})
    if len(member_votes) != old_members:
        sections.append(("Members with a vote record changed",
                         [f"- {old_members} → {len(member_votes)}"]))
    return sections


def render(path, sections):
    out = [f"## GA votes: what changed in `{os.path.basename(path)}`", ""]
    if not sections:
        out.append("A full-looking sweep and no material change this run.")
    else:
        out.append("Each line is something the General Assembly or the source can "
                   "legitimately do, so none of them blocked the update — the data is "
                   "committed. They are here because they change what a reader sees on "
                   "a legislator's voting record.")
        out.append("")
        for heading, lines in sections:
            out += [f"### {heading}", ""] + lines + [""]
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--expect-no-overlay", action="store_true",
                    help="the producer was run with --no-overlay, so "
                         "metadata.passageOverlaySource must be null")
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

    errors = tier1(new, args.expect_no_overlay)
    if errors:
        print("TIER 1 FAILED — the file contradicts itself, refusing to commit:\n",
              file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  … and {len(errors) - 40} more", file=sys.stderr)
        print("\nThis is a producer bug, not a change in the record. The rejected file "
              "is uploaded as a workflow artifact so it can be inspected.",
              file=sys.stderr)
        return 1

    size_kb = os.path.getsize(args.path) // 1024
    print(f"Tier 1 passed: {len(new['votes'])} passage roll calls, "
          f"{len(new['memberVotes'])} members with a record, {size_kb} KB. "
          f"Per-session counts agree with metadata, every member row indexes inside "
          f"voteIds with a code the codec defines.")

    sections = tier2(new, baseline(args.path, args.baseline_ref))
    report = render(args.path, sections)
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8") as f:
            f.write(report)
    print()
    print(report)
    if sections:
        print(f"{sum(len(l) for _, l in sections)} reported item(s) — reported, not gated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
