# Scope: incremental fetch for the GA votes producer

Follow-up to the data pipeline audit §1. `generate_ga_bills_soap.py` now fetches only
`ACTIVE_SESSION`; `generate_ga_votes_soap.py` still sweeps every session each run. This
is a scoping document — no code changed.

## Verdict

**Feasible, and the payoff is larger than the bills fix. One correction to the audit:
the compact index does NOT have to be rebuilt.** I said it would, and that was the
stated reason for deferring. `lib/votes_schema.encode_member_votes` was written for this
case — its `base_vote_ids` parameter exists so "indices track the (stable, append-only)
`votes` dict and quiet incremental runs stay byte-identical"
(`scripts/lib/votes_schema.py:79-83`). The codec is ready; what is missing is the merge
in the producer.

The real difficulty is not the index. It is that `memberVotes` is keyed by **person**,
not by session, so one member's row spans both sessions and has to be merged per member
rather than carried forward wholesale.

## The win

| | today | active-only | cut |
|---|---|---|---|
| `GetVote` calls / run | ~1,522 | ~25 | **98.4%** |
| `GetVotes` listings | 4 (2 chambers × 2 sessions) | 2 | 50% |
| `GetLegislationForSession` title index | 2 | 1 | 50% |

Vote records: 2,154 closed (`2025_26`) + 264 active (`2026_ss`) = 2,418, from 1,522
distinct roll calls. The closed regular session is 98.4% of the fetch and cannot change.

Secondary win: **index stability propagates downstream.**
`build_member_votes_slices.py:113` passes `voteIds` straight into
`ga-votes-index.json` and writes per-member `{index: code}` shards, so stable preserved
indices mean the 1.14 MB index and the preserved portion of all 246 shards
(3.13 MB) stop churning too — not just `ga-member-votes.json` itself.

## Verified before writing this

Against the committed `ga-member-votes.json` (2,418 votes, 246 members):

- Full decode → re-encode round-trip with `base_vote_ids = list(votes.keys())` is
  **byte-identical** — `voteIds`, `memberVotes`, and the minified serialization.
- Closed-session indices occupy positions **0..2153 contiguously** (sessions iterate in
  `SESSION_NAMES` order, regular before special), so the active session already sits at
  the tail. Preservation is an append, not a reshuffle.
- Partitioning to preserved-only keeps **all 2,154 voteIds at their original index
  positions** and leaves **242/242 member rows byte-stable**.

So the merge is sound at the codec level. The risk is in the producer's bookkeeping.

## The merge

1. Read the prior output. Decode with `member_votes_map()` → `{personId: [{voteId, vote}]}`.
2. Partition the prior `votes` dict by its `session` tag, **preserving insertion order**,
   into the closed-session layer.
3. Filter each member's decoded entries to voteIds in that layer.
4. Fetch `ACTIVE_SESSION` live → new `votes_meta`, new `member_votes`.
5. Merge: `votes_meta = preserved | new`; per member, **union** preserved and new entries.
6. `encode_member_votes(merged, list(merged_votes.keys()))` — preserved first, then new,
   so preserved indices are unchanged and new votes append.

## Hazards, ranked

**1. Twelve members would vanish.** 12 of 246 members have votes *only* in the closed
session — members who left at the biennium's midpoint. They cannot appear in an
active-session fetch. A merge that starts from the active fetch's member set and layers
preserved data onto it silently drops their **entire voting history**. The merge must
union person ids, with preserved as the base. This is the one hazard that loses published
data, and it is invisible in testing unless you assert the member count.

**2. No test covers the votes codec or producer.** `scripts/test_*.py` is five files;
none reference `votes_schema`, `encode_member_votes`, or `generate_ga_votes_soap`. The
bills change could be verified by diffing a real run against the committed file; here the
round-trip and merge invariants need actual assertions. Write them first:
round-trip identity, preserved index positions, member-set union, per-member entry union.
(Pipeline-wide, nothing runs the existing five either — audit §2.6.)

**3. Six downstream steps consume this file** in `update-ga-votes.yml`: slice builder →
bills enrichment → publish bills → publish votes → party unity → publish scorecard.
All read the decoded form through `member_votes_map()`, so a correct merge is transparent
to them — but a wrong one propagates into two sibling repos before anything notices.

**4. Validation can't catch a truncated merge.** The gate asserts
`passageOverlaySource is None` and structural shape; nothing asserts per-session vote
counts or member count. `metadata.sessions[].voteCount` and `sessionsFetched` already
exist and are the natural assertions to add — the bills fix leaned on an analogous
per-session count check.

## Semantic changes to accept deliberately

These are consequences of not re-fetching, not bugs. Each is a reason to keep a
`--full-refresh` hatch, as the bills producer now has.

- **Crosswalk backfills stop reaching closed sessions.** Rows are resolved
  `legisGaGovId → ocdPersonId` via `id-crosswalk.json`, and the documented remedy for an
  unresolved member is to backfill the crosswalk id. Today a full sweep re-resolves
  every row; incrementally, a backfill would only affect the active session.
  Currently `unresolvedRows: 0`, so nothing is pending — but this is the mechanism by
  which a fix would silently not apply.
- **Result derivation freezes for closed sessions.** `derive_result` consults
  `load_amendment_ids(ga-bills.json)` for the two-thirds constitutional-amendment rule.
  A change to that rule, or to the bills abstracts it reads, would no longer reach
  closed-session roll calls.
- **Per-run stats become active-only.** `resolvedRows`, `sentinelRowsDropped`,
  `attendanceSkipped`, `passageByNative`, `droppedNonPassage` are counters over fetched
  rows. They must either be recomputed over the merged file or relabelled; leaving them
  as-is makes the metadata read as a catastrophic drop.
- **Mixed classification regimes.** The workflow runs `--no-overlay` (native caption
  rule). Preserved records keep whatever rule classified them. Already true across runs,
  but preservation makes it durable.

## One structural note

`DEFAULT_OUTPUT` is `ga-member-votes.soap.json`, while `OS_VOTES_FILE` — the passage
overlay the producer *reads* — is `ga-member-votes.json`
(`scripts/generate_ga_votes_soap.py:77-79`). The workflow passes the real path
explicitly **and** `--no-overlay`, so in CI the file is written but not read as an
overlay. An incremental run must read that same file for the preserved layer, so the
read-vs-overlay distinction needs to stay explicit: preserve-read always, overlay-read
only without `--no-overlay`. Harmless, easy to conflate.

## Sequencing: do this before retiring the monolith

Audit §4.2 recommends eventually retiring `ga-member-votes.json` (repoint the four
build-time consumers at `ga-votes-index.json` + the shards). That raises a fair question:
is incremental work wasted if the file is going away?

No, and the order should be **incremental first**:

- Incremental fetch changes the output **schema not at all**. It is invisible to all six
  downstream steps — the smallest possible blast radius for a 98.4% fetch cut.
- Retiring the monolith changes *who reads what*, touching four consumers and two sibling
  repos. Much wider blast radius, no effect on fetch cost.
- The merge logic lives in the producer either way. Whatever the authoritative output
  becomes, the producer still has to avoid re-fetching 1,497 immutable roll calls.
- Doing retirement first means building the merge against a write path that is
  simultaneously being rewritten.

## Effort

Comparable to the bills fix in code size (~60–90 lines in the producer, plus the
`--full-refresh` hatch and a workflow input), but with more to verify: the member-union
hazard, the stats question, and a test file that does not yet exist. Budget roughly
double the bills change, most of it in tests rather than the merge.

Suggested order: (1) test file asserting the codec and merge invariants; (2) the merge
plus `--full-refresh`; (3) per-session and member-count assertions in the workflow gate;
(4) decide the stats question explicitly rather than by default.
