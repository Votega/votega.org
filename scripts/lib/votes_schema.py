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
