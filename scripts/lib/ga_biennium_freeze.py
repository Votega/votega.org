"""Freeze a GA biennium's per-member data into assets/data/ga-bienniums/<tag>/.

The live per-member slice builders delete files for members who leave, so this copies
what a legislator page needs into a tree they never touch. File names match the live
files, so a frozen biennium needs only a different root on the client.

All checks run before any write: a refusal leaves the frozen tree untouched. The ledger
is the CLI's concern, not this module's.
"""
import datetime
import json
import os
import shutil

from lib.atomic_io import write_json_atomic

FROZEN_ROOT = "assets/data/ga-bienniums"

MEMBERS = "ga-members.json"
VOTES_INDEX = "ga-votes-index.json"
SPONSOR_INDEX = "ga-sponsorship-index.json"
CURATED = "curated-ga-bill-votes.json"


class FreezeError(Exception):
    pass


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _member_slug(member_id):
    # One implementation; importing that module has no side effects (main is guarded).
    from build_member_votes_slices import member_slug
    return member_slug(member_id)


def freeze(tag, gids, data_dir, out_root, *, overwrite=False, no_votes_ok=(), include_curated=False):
    """Copy `gids`' record and slices for biennium `tag` into out_root/<tag>/.

    Returns {"frozen": [gid], "unchanged": [gid], "replacedIndexes": [name]}.
    """
    gids = [str(g) for g in gids]
    no_votes_ok = {str(g) for g in no_votes_ok}
    dest = os.path.join(out_root, tag)

    live = _load(os.path.join(data_dir, MEMBERS))
    by_gid = {str(m["legisGaGovId"]): m for m in live.get("members", []) if m.get("legisGaGovId") is not None}
    missing = [g for g in gids if g not in by_gid]
    if missing:
        raise FreezeError(f"legisGaGovId not in the live roster: {', '.join(missing)}")

    members_path = os.path.join(dest, MEMBERS)
    frozen_doc = _load(members_path) if os.path.exists(members_path) else {
        "metadata": {"biennium": tag}, "members": []}
    frozen_by_gid = {str(m["legisGaGovId"]): m for m in frozen_doc["members"]}
    no_votes = list(frozen_doc["metadata"].get("noVotes", []))

    sp_live = os.path.join(data_dir, SPONSOR_INDEX)
    sp_members = _load(sp_live).get("members", {}) if os.path.exists(sp_live) else {}

    copies = []
    changed, unchanged = set(), set()
    for g in gids:
        member = by_gid[g]
        diff = False
        if g in frozen_by_gid and frozen_by_gid[g] != member and not overwrite:
            raise FreezeError(f"frozen record for {g} differs from the live roster; pass overwrite to replace it")
        if frozen_by_gid.get(g) != member:
            diff = True

        wanted = [("ga-votes", _member_slug(member["id"]) + ".json"), ("ga-sponsorship", g + ".json")]
        for sub, fname in wanted:
            src = os.path.join(data_dir, sub, fname)
            dst = os.path.join(dest, sub, fname)
            if not os.path.exists(src):
                if sub == "ga-votes":
                    if g not in no_votes_ok:
                        raise FreezeError(f"member {g} has no vote slice at {src}; "
                                          f"pass no_votes_ok to freeze them without votes")
                    if g not in no_votes:
                        no_votes.append(g)
                        diff = True
                elif g in sp_members:
                    raise FreezeError(f"member {g} is in the live sponsorship index but "
                                      f"{sub}/{fname} is missing at {src}; refusing to freeze a "
                                      f"record without its slice")
                continue
            if os.path.exists(dst):
                if _bytes(src) != _bytes(dst):
                    if not overwrite:
                        raise FreezeError(f"frozen slice {sub}/{fname} for {g} differs from live; "
                                          f"pass overwrite to replace it")
                    copies.append((src, dst))
                    diff = True
            else:
                copies.append((src, dst))
                diff = True
        (changed if diff else unchanged).add(g)

    replaced, index_writes = [], []
    live_votes_idx = os.path.join(data_dir, VOTES_INDEX)
    live_sp_idx = os.path.join(data_dir, SPONSOR_INDEX)
    for p in (live_votes_idx, live_sp_idx):
        if not os.path.exists(p):
            raise FreezeError(f"live index missing: {p}")
    fv, fs = os.path.join(dest, VOTES_INDEX), os.path.join(dest, SPONSOR_INDEX)
    if os.path.exists(fv):
        old, new = _load(fv).get("voteIds", []), _load(live_votes_idx).get("voteIds", [])
        if new[:len(old)] != old:
            raise FreezeError("live voteIds no longer starts with the frozen voteIds in order; "
                              "slice positions would shift")
        if _bytes(fv) != _bytes(live_votes_idx):
            index_writes.append((live_votes_idx, fv))
            replaced.append(VOTES_INDEX)
    else:
        index_writes.append((live_votes_idx, fv))
    if os.path.exists(fs):
        old, new = _load(fs).get("members", {}), _load(live_sp_idx).get("members", {})
        gone = sorted(set(old) - set(new))
        if gone:
            raise FreezeError(f"live sponsorship index dropped frozen members: {', '.join(gone)}")
        if _bytes(fs) != _bytes(live_sp_idx):
            index_writes.append((live_sp_idx, fs))
            replaced.append(SPONSOR_INDEX)
    else:
        index_writes.append((live_sp_idx, fs))

    curated_copy = []
    if include_curated:
        src, dst = os.path.join(data_dir, CURATED), os.path.join(dest, CURATED)
        if not os.path.exists(src):
            raise FreezeError(f"curated key votes missing: {src}")
        if os.path.exists(dst):
            if _bytes(src) != _bytes(dst):
                if not overwrite:
                    raise FreezeError(f"frozen {CURATED} differs from live; pass overwrite to replace it")
                curated_copy.append((src, dst))
        else:
            curated_copy.append((src, dst))

    # Every check passed: write.
    for src, dst in copies + index_writes + curated_copy:
        _copy(src, dst)
    if changed:
        for g in changed:
            frozen_by_gid[g] = by_gid[g]
        members = [frozen_by_gid[k] for k in sorted(frozen_by_gid, key=int)]
        meta = {"biennium": tag, "session": live.get("metadata", {}).get("session"),
                "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "count": len(members), "source": "frozen from assets/data/ga-members.json"}
        if no_votes:
            meta["noVotes"] = sorted(no_votes, key=int)
        write_json_atomic(members_path, {"metadata": meta, "members": members}, indent=2)

    return {"frozen": [g for g in gids if g in changed],
            "unchanged": [g for g in gids if g in unchanged],
            "replacedIndexes": replaced}
