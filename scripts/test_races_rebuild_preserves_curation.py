#!/usr/bin/env python3
"""A rebuild of races.json must not erase curated candidate data.

build_legislative_races.py rebuilds every primary ballot from the Secretary of State
export, which has none of the bios, photos, websites, emails or display names added
since. Run alone it wiped ~190 fields (89 bios, 43 photos, 21 websites, 5 emails, 34
display names) from the primary copies, and the repair step it relied on,
sync_candidate_profiles.py, crashed whenever it had a name change to make (it reused
the variable `before`, the guard's snapshot, as a loop variable). What must hold:

  * the guard refuses a rebuild that empties a set editorial field;
  * it does not call a re-ordered export "loss": an id that now names someone else is
    skipped, and a value that merely changes is allowed;
  * carry_forward_editorial puts the previous value back for a primary-only candidate
    and never lends a bio to a different person at the same positional id;
  * sync_candidate_profiles writes successfully when names need reconciling.

Run: python scripts/test_races_rebuild_preserves_curation.py   (no network, no repo writes)
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legislative_races as B  # noqa: E402
import sync_candidate_profiles as S  # noqa: E402
from lib.races_guard import RacesGuardError, assert_editorial_fields_preserved  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def doc(*cands, phase="primary"):
    return {"races": [{"id": "ga-house-1-2026", "phases": {
        phase: {"ballots": {"Democrat": list(cands)}}}}]}


def raises(fn):
    try:
        fn()
    except RacesGuardError:
        return True
    return False


old = doc({"id": "ga-house-1-2026-d-1", "name": "Matt Barton", "bio": "Bio",
           "imageUrl": "https://x/y.jpg", "website": "https://barton.org",
           "existingMemberId": "ocd-person/1"})

# --- the guard
gutted = doc({"id": "ga-house-1-2026-d-1", "name": "Madison Fain Barton"})
check("guard refuses to empty set fields", raises(lambda: assert_editorial_fields_preserved(old, gutted)), True)

changed = doc({"id": "ga-house-1-2026-d-1", "name": "Matt Barton", "bio": "Bio",
               "imageUrl": "https://other/z.jpg", "website": "https://barton.org/new",
               "existingMemberId": "ocd-person/1"})
check("guard allows a changed value", raises(lambda: assert_editorial_fields_preserved(old, changed)), False)

reordered = doc({"id": "ga-house-1-2026-d-1", "name": "Someone Else"})
check("guard skips an id that now names another person",
      raises(lambda: assert_editorial_fields_preserved(old, reordered)), False)

# --- carry forward
rebuilt = doc({"id": "ga-house-1-2026-d-1", "name": "Madison Fain Barton",
               "imageUrl": "https://roster/portrait.jpg", "website": "https://typo.org"})
n = B.carry_forward_editorial(old, rebuilt)
c = rebuilt["races"][0]["phases"]["primary"]["ballots"]["Democrat"][0]
check("carry: bio restored", c.get("bio"), "Bio")
check("carry: curated photo beats the roster portrait", c.get("imageUrl"), "https://x/y.jpg")
check("carry: curated website beats the source's", c.get("website"), "https://barton.org")
check("carry: counts the fields carried", n, 3)
check("carry: leaves the member link to the other steps", "existingMemberId" in c, False)

other = doc({"id": "ga-house-1-2026-d-1", "name": "Someone Else"})
B.carry_forward_editorial(old, other)
check("carry: does not lend a bio to a different person",
      "bio" in other["races"][0]["phases"]["primary"]["ballots"]["Democrat"][0], False)

after_carry = copy.deepcopy(rebuilt)
check("guard passes after carry + member link",
      raises(lambda: assert_editorial_fields_preserved(
          {"races": [{"id": "ga-house-1-2026", "phases": {"primary": {"ballots": {"Democrat": [
              {"id": "ga-house-1-2026-d-1", "name": "Matt Barton", "bio": "Bio"}]}}}}]},
          after_carry)), False)

# --- sync_candidate_profiles used to crash when it had a name change to write
two_phase = {"races": [{"id": "ga-house-9-2026", "activePhase": "general", "phases": {
    "primary": {"ballots": {"Republican": [
        {"id": "ga-house-9-2026-r-1", "name": "Madison Fain Barton"}]}},
    "general": {"candidates": [
        {"id": "ga-house-9-2026-r-1", "name": "Matt Barton"}]}}}]}
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "races.json"
    p.write_text(json.dumps(two_phase), encoding="utf-8")
    original = S.RACES
    S.RACES = p
    argv = sys.argv
    sys.argv = [argv[0]]
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            rc = S.main()
    except Exception as e:  # noqa: BLE001
        rc = f"crashed: {type(e).__name__}: {e}"
    finally:
        S.RACES = original
        sys.argv = argv
    check("sync writes when a name needs reconciling", rc, 0)
    written = json.loads(p.read_text(encoding="utf-8"))
    primary = written["races"][0]["phases"]["primary"]["ballots"]["Republican"][0]
    check("sync: the latest phase's display name wins", primary["name"], "Matt Barton")

if failures:
    print(f"\n{len(failures)} failed")
    sys.exit(1)
print("\nall passed")
