#!/usr/bin/env python3
"""Pre-overwrite invariants for the in-place races.json mutators.

races.json is the core of the elections section (race pages, candidate finder,
sample ballot, the publish_races sibling feed). Roughly seven scripts read it and
overwrite it in place — promoting primary/runoff winners into the general, fixing
fallback ballots, reconciling candidate profiles, stamping the timestamp. Only
apply_overrides.py guarded its write; the rest would happily persist a smaller or
mangled file if a logic bug dropped a race, wiped a ballot, or flipped a phase by
mistake (PIPELINE-AUDIT.md #3). publish_races' min_items floor only fires at the
publish boundary — after the damaged file is already committed and served.

These checks compare an in-process snapshot taken right after load against the
mutated document right before the write, and raise RacesGuardError (aborting the
run with a clear message) on any violation. Because the writers use atomic writes
(atomic_io), a failed check leaves the on-disk file untouched. The snapshot is the
correct baseline — more precise than git HEAD, which may already differ from what
a manually-run script loaded from an uncommitted working tree.

Usage:
    import copy
    from lib.races_guard import assert_race_set_preserved, assert_phase_transitions

    before = copy.deepcopy(races_data)      # right after json.load
    ...mutate races_data...
    assert_race_set_preserved(before, races_data)
    assert_phase_transitions(before, races_data,
                             allowed={("primary", "general")}, expected_count=updated)
    write_json_atomic(RACES_PATH, races_data, indent=2)
"""

TOP_LEVEL_KEYS = ("_note", "_incumbentIds", "races", "updatedAt")


class RacesGuardError(AssertionError):
    """A races.json mutation violated an invariant; the write must be aborted."""


def _races_by_id(doc):
    return {r["id"]: r for r in doc.get("races", [])}


def phase_candidates(phase_data):
    """Every candidate object on a phase, across both shapes: `ballots` (party ->
    [candidates]) and a flat `candidates` array. Mirrors the helper in
    sync_candidate_profiles.py so the guard sees candidates the same way."""
    if not isinstance(phase_data, dict):
        return
    for cands in (phase_data.get("ballots") or {}).values():
        for c in cands or []:
            if isinstance(c, dict):
                yield c
    for c in phase_data.get("candidates") or []:
        if isinstance(c, dict):
            yield c


def _phase_size(phase_data):
    return sum(1 for _ in phase_candidates(phase_data))


# --------------------------------------------------------------------------- #
# universal — every writer
# --------------------------------------------------------------------------- #
def assert_race_set_preserved(before, after):
    """No race added or dropped, and no top-level key lost. This is the check that
    catches the headline #3 risk — a bug silently shrinking the roster."""
    for key in TOP_LEVEL_KEYS:
        if key in before and key not in after:
            raise RacesGuardError(f"top-level key {key!r} was dropped from races.json")

    before_ids = set(_races_by_id(before))
    after_ids = set(_races_by_id(after))
    if before_ids != after_ids:
        dropped = sorted(before_ids - after_ids)
        added = sorted(after_ids - before_ids)
        parts = []
        if dropped:
            parts.append(f"dropped {len(dropped)}: {dropped[:10]}")
        if added:
            parts.append(f"added {len(added)}: {added[:10]}")
        raise RacesGuardError("race set changed — " + "; ".join(parts))

    n_before, n_after = len(before.get("races", [])), len(after.get("races", []))
    if n_before != n_after:
        # ids equal but counts differ ⇒ a duplicate id appeared.
        raise RacesGuardError(f"race count changed {n_before} -> {n_after} (duplicate id?)")


# --------------------------------------------------------------------------- #
# phase transitions — update_general_from_primary / _runoff
# --------------------------------------------------------------------------- #
def assert_phase_transitions(before, after, *, allowed, expected_count=None,
                             require_populated=True):
    """Every activePhase change must be one of `allowed` (a set of (old, new)
    tuples); unchanged races are fine. Optionally assert the number of changed
    races equals `expected_count`, and that each race that moved to its new phase
    has a non-empty ballot there (a flip that empties the ballot is the failure
    this is guarding)."""
    assert_race_set_preserved(before, after)
    b, a = _races_by_id(before), _races_by_id(after)
    changed = 0
    for rid, rb in b.items():
        ra = a[rid]
        old, new = rb.get("activePhase"), ra.get("activePhase")
        if old == new:
            continue
        if (old, new) not in allowed:
            raise RacesGuardError(
                f"{rid}: unexpected phase transition {old!r} -> {new!r} "
                f"(allowed: {sorted(allowed)})")
        changed += 1
        if require_populated:
            phase = (ra.get("phases") or {}).get(new)
            if _phase_size(phase) == 0:
                raise RacesGuardError(
                    f"{rid}: flipped to {new!r} but that phase has no candidates")
    if expected_count is not None and changed != expected_count:
        raise RacesGuardError(
            f"{changed} races changed phase but the script reported {expected_count}")


# --------------------------------------------------------------------------- #
# no phase movement — fix_general_fallbacks / sync_candidate_profiles
# --------------------------------------------------------------------------- #
def assert_active_phases_unchanged(before, after):
    """No race's activePhase moved. For writers that only edit candidate content."""
    assert_race_set_preserved(before, after)
    b, a = _races_by_id(before), _races_by_id(after)
    moved = [rid for rid, rb in b.items()
             if rb.get("activePhase") != a[rid].get("activePhase")]
    if moved:
        raise RacesGuardError(f"activePhase changed unexpectedly for: {sorted(moved)[:10]}")


def assert_membership_preserved(before, after):
    """Per race, per phase: the candidate roster is unchanged in size, identity
    (the `id` field, which sync never rewrites), and `type`. Guards a field-level
    reconcile that must not add, drop, or re-slot a candidate."""
    assert_race_set_preserved(before, after)
    b, a = _races_by_id(before), _races_by_id(after)
    for rid, rb in b.items():
        ra = a[rid]
        pb, pa = (rb.get("phases") or {}), (ra.get("phases") or {})
        if set(pb) != set(pa):
            raise RacesGuardError(
                f"{rid}: phase set changed {sorted(pb)} -> {sorted(pa)}")
        for phase_name in pb:
            cb = list(phase_candidates(pb[phase_name]))
            ca = list(phase_candidates(pa[phase_name]))
            if len(cb) != len(ca):
                raise RacesGuardError(
                    f"{rid}/{phase_name}: candidate count {len(cb)} -> {len(ca)}")
            ids_b = sorted(c["id"] for c in cb if c.get("id"))
            ids_a = sorted(c["id"] for c in ca if c.get("id"))
            if ids_b != ids_a:
                raise RacesGuardError(
                    f"{rid}/{phase_name}: candidate id set changed")
            types_b = sorted((c.get("id") or "", c.get("type")) for c in cb)
            types_a = sorted((c.get("id") or "", c.get("type")) for c in ca)
            if types_b != types_a:
                raise RacesGuardError(
                    f"{rid}/{phase_name}: a candidate 'type' changed (sync must not touch type)")


# --------------------------------------------------------------------------- #
# single-race edit — set_general_candidates
# --------------------------------------------------------------------------- #
def assert_only_race_changed(before, after, race_id, *, require_populated_phase=None):
    """Exactly the named race may differ; every other race is byte-identical.
    Optionally assert the named race's given phase is non-empty after the edit."""
    assert_race_set_preserved(before, after)
    b, a = _races_by_id(before), _races_by_id(after)
    if race_id not in a:
        raise RacesGuardError(f"target race {race_id!r} not present after edit")
    others = [rid for rid, rb in b.items() if rid != race_id and rb != a[rid]]
    if others:
        raise RacesGuardError(
            f"races other than {race_id!r} changed: {sorted(others)[:10]}")
    if require_populated_phase is not None:
        phase = (a[race_id].get("phases") or {}).get(require_populated_phase)
        if _phase_size(phase) == 0:
            raise RacesGuardError(
                f"{race_id}: {require_populated_phase!r} phase has no candidates after edit")


# --------------------------------------------------------------------------- #
# timestamp-only — stamp_races_updated_at
# --------------------------------------------------------------------------- #
def assert_equal_except(before, after, *ignore_keys):
    """The two documents are identical except for the named top-level keys. Used by
    stamp_races_updated_at, whose only legitimate change is `updatedAt`."""
    b = {k: v for k, v in before.items() if k not in ignore_keys}
    a = {k: v for k, v in after.items() if k not in ignore_keys}
    if b != a:
        differing = sorted({k for k in set(b) | set(a) if b.get(k) != a.get(k)})
        raise RacesGuardError(
            f"races.json changed outside {list(ignore_keys)}: fields differ = {differing}")
