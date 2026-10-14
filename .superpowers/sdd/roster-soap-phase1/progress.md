# SDD ledger — plan: Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md (Phase 1)
Pre-flight: single-producer change, no shared interfaces between steps.
Ruling: committees = SOAP verbatim + 1-entry MARTOC expansion — user decision 2026-10-14 — cost if wrong: one alias line.
Ruling: address = normalized in producer (canonical building, fix ; and ZIP) — user decision 2026-10-14 — cost if wrong: a regenerate.
Ruling: new lib/ga_roster.py rather than extending ga_leadership — address shaping is not
  leadership; cost if wrong: one file move.
Ruling: key-form guards run BEFORE apply_member_overrides — _inject may legitimately use a
  synthetic id (CLAUDE.md); cost if wrong: the documented escape hatch breaks.
Ruling: `review` stays in ga-members.json, not a sidecar — it is the human queue and one
  artifact cannot be missed (~2KB in ~500KB); cost if wrong: it ships in published all.json.
Ruling: 2 of the 34 leadershipRole overrides RESTORED (Walker Pro Tem, Merritt caucus) —
  SOAP carries neither; cost if wrong: two stale badges.
Ruling: email falls back to the committed value for the 2 members SOAP lacks — deriving
  first.last@senate.ga.gov would be inventing a public official's contact details.
Ruling: OPENSTATES_API_KEY stays in update-ga-members.yml this phase (spec defers to
  Phase 2, keeps §9 rollback runnable without a workflow edit).
Task 1: complete (commit 56696efb, tests: scripts/test_*.py -> 6/6 suites, 129/129 checks)
Final review: self-review (no subagent tool per user instruction).
Final: fixed truncated-listing backfill — listing_is_too_short RED->GREEN, suite 137/137 (d1111049)
Final: fixed committeeRoles/committees name mismatch — 0 mismatches verified (f1166479)
