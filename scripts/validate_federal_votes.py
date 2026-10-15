#!/usr/bin/env python3
"""Structural checks on the federal roll-call artifacts, before anything is committed.

validate_data_update.py already guards the COUNTS — it compares each metric against
HEAD and refuses a collapse. This guards the SHAPE, which a count cannot see:
CLAUDE.md's rule is "never commit based on JSON validity alone", and a file whose
every bill field had silently become an empty string, or whose slices had drifted out
of alignment with the index, would pass both a parse and a count check and then
render wrongly on every entity page.

What it enforces:
  * every roll call carries the fields the page renders (chamber, date, motionText);
  * bill and billUrl agree — both present or both null, and never "" (CLAUDE.md:
    optional fields are null, never an empty string);
  * the House/Senate split is plausible, i.e. neither chamber is missing entirely,
    which is what a broken enumerator looks like from the outside;
  * the universe is not a regression to the old enacted-laws frame — a bill-attached
    share near 100% means the roll-call enumeration silently stopped working;
  * every member's compact slice decodes against the index's voteIds, and every
    member with votes in the monolith has a slice file;
  * the Key Votes sidecar resolves every voteId curated-federal-bills.json names,
    and its `indices` really are positions in the full voteIds list — Key Votes is
    the default tab and reads the sidecar alone, so an off-by-one there would show
    every visitor one roll call's tally under another's heading.

Usage:
    python scripts/validate_federal_votes.py \
        assets/data/federal-member-votes.json \
        assets/data/federal-votes-index.json \
        assets/data/federal-votes \
        [assets/data/federal-votes-keyvotes.json assets/data/curated-federal-bills.json]

Exit 0 when every check passes, 1 otherwise (the caller must not commit).
"""

import json
import os
import sys

#: A Congress whose recorded votes are *all* attached to bills would be
#: unprecedented: nominations, procedural motions and quorum calls are a large,
#: structural share of both chambers' records. If the bill-less share is below this,
#: the enumeration has almost certainly fallen back to a legislation-only frame.
MIN_BILL_LESS_SHARE = 0.05

#: Position of `motion` in an index row (its intern-table pointer is per-file, so
#: the sidecar's differs by design); the fields before it must match byte for byte.
#: Mirrors ROW_FIELDS in build_federal_votes_slices.py.
ROW_MOTION = 5

#: Required on every roll call because the page renders them unconditionally.
REQUIRED_FIELDS = ("chamber", "date", "motionText", "yea", "nay", "result")

problems = []
notes = []


def fail(msg):
    problems.append(msg)


def check_keyvotes(keyvotes_path, curated_path, vote_ids, rows, index):
    """The sidecar must carry every curated roll call, with aligned `indices`."""
    try:
        with open(keyvotes_path, encoding="utf-8") as fh:
            side = json.load(fh)
        with open(curated_path, encoding="utf-8") as fh:
            curated = json.load(fh)
    except (OSError, ValueError) as exc:
        fail(f"cannot read the key-votes sidecar or curated bills: {exc}")
        return

    side_ids = side.get("voteIds") or []
    indices = side.get("indices") or []
    side_rows = side.get("rows") or []
    if not (len(side_ids) == len(indices) == len(side_rows)):
        fail(f"key-votes sidecar misaligned: {len(side_ids)} voteIds, "
             f"{len(indices)} indices, {len(side_rows)} rows")
        return

    # The whole point of `indices`: the member slice is keyed on the FULL index's
    # position, so a shifted value here attributes one vote's record to another.
    for vote_id, i in zip(side_ids, indices):
        if not isinstance(i, int) or not 0 <= i < len(vote_ids):
            fail(f"{vote_id}: sidecar index {i!r} is outside the full voteIds list")
        elif vote_ids[i] != vote_id:
            fail(f"{vote_id}: sidecar index {i} points at {vote_ids[i]} in the full "
                 "index — Key Votes would show another roll call's record")
        elif rows[i][:ROW_MOTION] != side_rows[side_ids.index(vote_id)][:ROW_MOTION]:
            fail(f"{vote_id}: sidecar row disagrees with the full index's row")

    # A curated id the monolith does not carry is a curation lag, not a build fault
    # (the page renders "No record"), so it is a note; one the monolith HAS and the
    # sidecar dropped is a fault, because the panel then shows nothing for a vote we
    # hold.
    wanted = []
    for bill in curated.get("bills") or []:
        for _chamber, vote_id in sorted((bill.get("voteIds") or {}).items()):
            if vote_id and vote_id not in wanted:
                wanted.append(vote_id)
    dropped = [v for v in wanted if v in set(vote_ids) and v not in set(side_ids)]
    if dropped:
        fail(f"{len(dropped)} curated voteId(s) exist in the index but are missing "
             f"from the key-votes sidecar: {dropped[:5]}")
    unknown = [v for v in wanted if v not in set(vote_ids)]
    if unknown:
        notes.append(f"{len(unknown)} curated voteId(s) are not in our roll-call "
                     f"data yet (rendered as \"No record\"): {unknown[:5]}")
    stray = [v for v in side_ids if v not in set(wanted)]
    if stray:
        fail(f"{len(stray)} sidecar vote(s) are not curated at all: {stray[:5]}")
    side_fmt = (side.get("metadata") or {}).get("sliceFormat")
    if side_fmt != (index.get("metadata") or {}).get("sliceFormat"):
        fail("key-votes sidecar publishes a different sliceFormat from the index — "
             "the page decodes both with one set of positions")
    notes.append(f"key-votes sidecar: {len(side_ids)} curated roll calls, "
                 f"{os.path.getsize(keyvotes_path) / 1024:.1f}KB")


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    votes_path, index_path, slices_dir = sys.argv[1:4]

    try:
        with open(votes_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.exit(f"FAIL: cannot read {votes_path}: {exc}")

    votes = data.get("votes") or {}
    member_votes = data.get("memberVotes") or {}
    if not votes:
        sys.exit(f"FAIL: {votes_path} has no votes")
    if not member_votes:
        sys.exit(f"FAIL: {votes_path} has no memberVotes")

    # -- per-vote required fields and the bill/billUrl pairing -----------------
    missing = {}
    bad_pairs = []
    empty_strings = []
    bill_less = 0
    by_chamber = {}
    for vote_id, meta in votes.items():
        if not isinstance(meta, dict):
            fail(f"{vote_id}: record is {type(meta).__name__}, not an object")
            continue
        for field in REQUIRED_FIELDS:
            if meta.get(field) in (None, ""):
                missing.setdefault(field, []).append(vote_id)
        bill, url = meta.get("bill"), meta.get("billUrl")
        if bill == "" or url == "":
            empty_strings.append(vote_id)
        if (bill is None) != (url is None):
            bad_pairs.append(vote_id)
        if bill is None:
            bill_less += 1
        chamber = meta.get("chamber") or "?"
        by_chamber[chamber] = by_chamber.get(chamber, 0) + 1

    for field, ids in sorted(missing.items()):
        fail(f"{len(ids)} roll call(s) missing required field {field!r} "
             f"(e.g. {', '.join(ids[:3])})")
    if empty_strings:
        fail(f"{len(empty_strings)} roll call(s) use \"\" for bill/billUrl where null "
             f"is required (e.g. {', '.join(empty_strings[:3])})")
    if bad_pairs:
        fail(f"{len(bad_pairs)} roll call(s) have a bill without a billUrl or vice "
             f"versa (e.g. {', '.join(bad_pairs[:3])})")

    # -- both chambers present, and the frame is still the whole universe ------
    for chamber in ("House", "Senate"):
        if not by_chamber.get(chamber):
            fail(f"no {chamber} roll calls at all — the {chamber} enumerator "
                 "produced nothing")
    share = bill_less / len(votes)
    if share < MIN_BILL_LESS_SHARE:
        fail(f"only {bill_less}/{len(votes)} ({share:.1%}) roll calls have no "
             f"associated measure; below {MIN_BILL_LESS_SHARE:.0%} means the "
             "enumeration has regressed to a legislation-only frame")
    notes.append(f"{len(votes)} roll calls: "
                 + ", ".join(f"{k} {v}" for k, v in sorted(by_chamber.items()))
                 + f"; {bill_less} ({share:.1%}) with no associated measure")

    # -- the slices the page actually fetches ---------------------------------
    try:
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.exit(f"FAIL: cannot read {index_path}: {exc}")

    vote_ids = index.get("voteIds") or []
    rows = index.get("rows") or []
    if len(vote_ids) != len(rows):
        fail(f"index misaligned: {len(vote_ids)} voteIds but {len(rows)} rows")
    if set(vote_ids) != set(votes):
        only_idx = sorted(set(vote_ids) - set(votes))[:3]
        only_mono = sorted(set(votes) - set(vote_ids))[:3]
        fail("index and monolith disagree on which votes exist "
             f"(index-only: {only_idx}, monolith-only: {only_mono})")
    if any(row is None for row in rows):
        fail(f"{sum(1 for r in rows if r is None)} index row(s) are null")

    if not os.path.isdir(slices_dir):
        sys.exit(f"FAIL: {slices_dir} does not exist — slices were not built")
    slice_files = {name[:-5] for name in os.listdir(slices_dir) if name.endswith(".json")}
    expected = {m for m, entries in member_votes.items() if entries}
    if missing_slices := sorted(expected - slice_files):
        fail(f"{len(missing_slices)} member(s) have votes but no slice file: "
             f"{missing_slices[:5]}")
    if orphans := sorted(slice_files - expected):
        fail(f"{len(orphans)} slice file(s) belong to no member in the monolith "
             f"(stale slices would render as a live record): {orphans[:5]}")

    # Decode each slice against the index the page will pair it with: an index that
    # shifted by one would still be valid JSON and still the right length.
    for bioguide in sorted(expected & slice_files):
        with open(os.path.join(slices_dir, bioguide + ".json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        compact = payload.get("compact") or {}
        if payload.get("bioguideId") != bioguide:
            fail(f"{bioguide}: slice names member {payload.get('bioguideId')!r}")
        if not compact:
            fail(f"{bioguide}: slice carries no votes")
            continue
        try:
            decoded = {vote_ids[int(i)] for i in compact}
        except (ValueError, IndexError):
            fail(f"{bioguide}: slice has an index outside the shared voteIds list")
            continue
        monolith = {e.get("voteId") for e in member_votes[bioguide]}
        if decoded != monolith:
            fail(f"{bioguide}: slice decodes to {len(decoded)} votes, monolith has "
                 f"{len(monolith)} — index and slice are out of step")

    # -- the Key Votes sidecar, which is what a page load actually fetches -----
    if len(sys.argv) >= 6:
        keyvotes_path, curated_path = sys.argv[4:6]
        check_keyvotes(keyvotes_path, curated_path, vote_ids, rows, index)

    for note in notes:
        print(f"note: {note}")
    print(f"note: {len(slice_files)} member slices, "
          f"{len(index.get('motions') or [])} distinct motions interned")

    if problems:
        print("")
        for msg in problems:
            print(f"FAIL: {msg}")
        return 1
    print("\nAll federal roll-call structure checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
