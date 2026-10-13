#!/usr/bin/env python3
"""One source of truth for the ga-member-votes.json schema (GA state votes).

`memberVotes` used to be `{personId: [{"voteId": "ocd-vote/<uuid>", "vote": "Yea"}, ...]}`.
At ~270k entries that repeated the keys "voteId"/"vote" and a 45-char uuid on every
row, making the file ~19 MB -- the site's largest blob and top client-fetched file.

The compact schema interns each voteId to an index and drops the wrapper:

    voteIds:     ["ocd-vote/<uuid>", ...]           # index -> voteId (stable order)
    votes:       { "ocd-vote/<uuid>": {bill, ...} }  # UNCHANGED, keyed by voteId
    memberVotes: { personId: { "0": "Y", "5": "N" } }# {indexString: code}

That takes the file to ~3.6 MB (81% smaller) with no information loss.

This module is deliberately tolerant of BOTH schemas so every consumer keeps working
during and after the migration: `member_votes_map()` decodes either shape back to the
legacy `[{voteId, vote}]` form that existing code already expects, and
`encode_member_votes()` produces the compact form for writers.

Mirrors the lib/http.py and lib/ga_match.py "consolidate the policy in one place"
pattern. Federal votes (federal-member-votes.json) are 0.14 MB and keep the legacy
schema, so they do not use this module.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`):

    from lib.votes_schema import member_votes_map, encode_member_votes
"""

#: Vote option -> compact code. GA data currently only uses Yea/Nay/Other, but the
#: full Open States option set is mapped so the codec is lossless if that changes.
VOTE_CODES = {
    'Yea': 'Y',
    'Nay': 'N',
    'Not Voting': 'NV',
    'Present': 'P',
    'Absent': 'A',
    'Excused': 'E',
    'Other': 'O',
}
VOTE_DECODE = {code: option for option, code in VOTE_CODES.items()}


def is_compact(data):
    """True if `data` carries the compact schema (a top-level `voteIds` index)."""
    return isinstance(data, dict) and isinstance(data.get('voteIds'), list)


def member_votes_map(data):
    """Return `{personId: [{'voteId':.., 'vote':..}, ...]}` from EITHER schema.

    Decodes the compact form (`memberVotes` values are `{indexString: code}` dicts,
    resolved through the top-level `voteIds` list) and passes the legacy form
    (values already lists of `{voteId, vote}`) through unchanged. Callers can then
    use the same `entry['voteId']` / `entry['vote']` access on any input.
    """
    member_votes = data.get('memberVotes') or {}
    vote_ids = data.get('voteIds') or []
    out = {}
    for person_id, entries in member_votes.items():
        if isinstance(entries, dict):  # compact
            decoded = []
            for i, code in entries.items():
                try:
                    vid = vote_ids[int(i)]
                except (ValueError, IndexError):
                    continue  # malformed index; skip rather than crash
                decoded.append({'voteId': vid, 'vote': VOTE_DECODE.get(code, code)})
            out[person_id] = decoded
        else:  # legacy
            out[person_id] = entries
    return out


def encode_member_votes(member_votes, base_vote_ids):
    """Encode legacy `{personId: [{voteId, vote}]}` into the compact form.

    Args:
        member_votes: the legacy mapping.
        base_vote_ids: the preferred index order -- pass `list(votes.keys())` so
            indices track the (stable, append-only) `votes` dict and quiet
            incremental runs stay byte-identical. Any voteId referenced by a member
            but absent from this base is appended (kept, never dropped).

    Returns `(compact_member_votes, vote_ids)`. Per-member keys are emitted in
    ascending integer order so serialization is deterministic regardless of the
    order entries happened to arrive in.
    """
    vote_ids = list(base_vote_ids)
    idx = {vid: i for i, vid in enumerate(vote_ids)}
    compact = {}
    for person_id, entries in member_votes.items():
        row = {}
        for entry in entries:
            vid = entry.get('voteId')
            if vid is None:
                continue
            if vid not in idx:
                idx[vid] = len(vote_ids)
                vote_ids.append(vid)
            row[idx[vid]] = VOTE_CODES.get(entry.get('vote'), entry.get('vote'))
        compact[person_id] = {str(i): row[i] for i in sorted(row)}
    return compact, vote_ids

def preserved_layer(data, sessions):
    """The closed-session layer of an existing compact file, ready to merge.

    Returns `(votes, member_votes)` where `votes` is the `{voteId: record}` subset whose
    `session` tag is in `sessions` — **in the file's own key order**, which is what keeps
    the compact index append-only — and `member_votes` is the legacy
    `{personId: [{voteId, vote}]}` form filtered to those votes.

    Why the order matters: `encode_member_votes(..., base_vote_ids=list(votes.keys()))`
    assigns index 0..n-1 in the order given. Sessions are fetched regular-first, so a
    file's closed-session votes already occupy the leading indices; preserving that order
    and appending the freshly-fetched active session leaves every preserved index exactly
    where it was, and every preserved member row byte-identical.

    Raises ValueError if `data` is not the compact schema — a legacy-schema file has no
    index to preserve and must be rebuilt with a full refresh rather than merged.
    """
    if not is_compact(data):
        raise ValueError("not the compact schema (no top-level voteIds): "
                         "rebuild with a full refresh instead of merging")
    wanted = set(sessions)
    votes = {vid: rec for vid, rec in (data.get('votes') or {}).items()
             if (rec or {}).get('session') in wanted}
    keep = set(votes)
    member_votes = {}
    for person_id, entries in member_votes_map(data).items():
        rows = [e for e in entries if e.get('voteId') in keep]
        if rows:
            member_votes[person_id] = rows
    return votes, member_votes


def merge_member_votes(preserved, fetched):
    """Union two legacy `{personId: [{voteId, vote}]}` maps, preserved entries first.

    `preserved` is the BASE, not `fetched`: a member who left mid-biennium appears only
    in the preserved layer, and starting from the fetched map would drop their entire
    voting history. A member in both keeps their preserved rows followed by their new
    ones; a voteId present in both is kept once, with the FETCHED value winning, so a
    re-fetch of the active session corrects a row rather than duplicating it.
    """
    out = {person_id: list(entries) for person_id, entries in preserved.items()}
    for person_id, entries in fetched.items():
        rows = out.setdefault(person_id, [])
        by_id = {e.get('voteId'): i for i, e in enumerate(rows)}
        for entry in entries:
            vid = entry.get('voteId')
            if vid in by_id:
                rows[by_id[vid]] = entry
            else:
                by_id[vid] = len(rows)
                rows.append(entry)
    return out
