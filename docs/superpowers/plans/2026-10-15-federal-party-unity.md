# Federal Party-Unity Scorecard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish party-unity and participation figures for each member of Georgia's congressional delegation and show them on the member's profile page.

**Architecture:** A build-time generator reads the committed roll-call record and the roster, scores each member with a shared library that the existing GA generator also calls, and writes a small per-member artifact. The entity page fetches that artifact and renders it; it computes nothing.

**Tech Stack:** Python 3 standard library only (no third-party imports in `scripts/test_*.py` — `run-script-tests.yml` installs no pip packages). Client side: vanilla JS inside a Jekyll include.

**Spec:** `docs/superpowers/specs/2026-10-15-federal-party-unity-design.md`

## Global Constraints

- Write all output through `scripts/lib/atomic_io.write_json_atomic` — never bare `open()` + `json.dump`.
- Optional fields are `None`/`null`, never `""` or `0`.
- Resolve every client-side data URL through `getBasePath()`, never bare-relative.
- `escHtml()` every interpolated value in the include.
- Tests are standalone scripts (`python scripts/test_x.py`), using the repo's `check(name, got, want)` + `failures` convention, exiting 1 on failure. No pytest, no network, no repo writes.
- `assets/data/ga-party-unity.json` must be byte-identical before and after Task 1.
- Rank 1 is the top of the metric. Ties take the same rank; the next rank skips (standard competition ranking).
- The panel shows a rank only when `cohortSize >= RANK_MIN_COHORT` (5); below that it shows a peer comparison.

## Review Focus

These are real conditions in the committed data, verified 2026-10-15. Each line's test is assigned to the task that owns the code.

- **A roll call with no `partyTally` at all** — `H2025_0002`, the Speaker election, whose "votes" are candidate names. Must be skipped as not-a-party-line-vote, not crash and not counted. (Task 1)
- **A tied caucus** — 3 roll calls. "The party's position" is undefined, so the vote is excluded from the unity denominator. (Task 1)
- **Both caucuses voting the same way** — 275 roll calls. Bipartisan, excluded; counting them would inflate every member's unity. (Task 1)
- **A member with votes but no roster entry** — `S001157`, `G000596`, departed mid-Congress. No party, so unscoreable: excluded and counted in metadata, never scored as 0%. (Task 2)
- **A member absent from the artifact, or the artifact missing entirely** — the Voting History panel must render exactly as it does today, with no scorecard block and no zeros. (Task 4)

---

### Task 1: Shared party-unity rule

**Files:**
- Create: `scripts/lib/party_unity.py`
- Modify: `scripts/generate_party_unity.py` (replace the inline rule in `member_scores`, lines ~146-186)
- Test: `scripts/test_party_unity_rule.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `OTHER_PARTY: dict[str, str]` — `{"Democratic": "Republican", "Republican": "Democratic"}`
  - `party_line_direction(tally: dict | None, party: str, other_party: str) -> str | None` — returns the member's own-caucus majority direction (`"Yea"`/`"Nay"`) when the roll call is a party-line vote, else `None`.
  - `score_unity(votes_by_rollcall: dict[str, str], tallies: dict[str, dict], party: str) -> tuple[int, int]` — returns `(party_line_votes, voted_with_party)`.
  - `score_participation(votes_by_rollcall: dict[str, str]) -> tuple[int, int, int]` — returns `(total, cast, missed)`.

`votes_by_rollcall` maps a roll-call key to that member's vote string. `tallies` maps the same keys to `{party: {"yea": int, "nay": int}}`; extra keys such as `"other"` are ignored.

- [ ] **Step 1: Write the failing test** in `scripts/test_party_unity_rule.py`, covering each clause of the rule and both scorers:

```python
D, R = "Democratic", "Republican"
PL = {D: {"yea": 0, "nay": 10}, R: {"yea": 9, "nay": 1}}   # party-line, R majority Yea

check("party-line gives own-caucus direction", party_line_direction(PL, R, D), "Yea")
check("same roll call from the other side", party_line_direction(PL, D, R), "Nay")
check("no tally is not a party-line vote", party_line_direction(None, R, D), None)
check("empty tally is not a party-line vote", party_line_direction({}, R, D), None)
check("tied own caucus excluded",
      party_line_direction({D: {"yea": 5, "nay": 5}, R: {"yea": 9, "nay": 1}}, D, R), None)
check("tied other caucus excluded",
      party_line_direction({D: {"yea": 5, "nay": 5}, R: {"yea": 9, "nay": 1}}, R, D), None)
check("both caucuses agree excluded",
      party_line_direction({D: {"yea": 8, "nay": 1}, R: {"yea": 9, "nay": 1}}, R, D), None)
check("lone own-party voter excluded",
      party_line_direction({D: {"yea": 1, "nay": 0}, R: {"yea": 9, "nay": 1}}, D, R), None)
check("silent other caucus excluded",
      party_line_direction({D: {"yea": 0, "nay": 0}, R: {"yea": 9, "nay": 1}}, R, D), None)

VOTES = {"a": "Yea", "b": "Nay", "c": "Not Voting", "d": "Yea"}
TALLIES = {"a": PL, "b": PL, "c": PL, "d": {D: {"yea": 8, "nay": 1}, R: {"yea": 9, "nay": 1}}}
check("unity counts only party-line votes the member cast", score_unity(VOTES, TALLIES, R), (2, 1))
check("an absence is not a defection", score_unity({"c": "Not Voting"}, TALLIES, R), (0, 0))
check("participation counts Yea and Nay only", score_participation(VOTES), (4, 3, 1))
check("participation of an empty record", score_participation({}), (0, 0, 0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_party_unity_rule.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.party_unity'`

- [ ] **Step 3: Implement the four names above in `scripts/lib/party_unity.py`**

Port the rule verbatim from `generate_party_unity.py:146-186`; do not re-derive it. The four exclusion clauses, in order: no tally; fewer than two own-party Yea/Nay voters or a tied own caucus; a silent or tied other caucus; both majorities in the same direction.

- [ ] **Step 4: Run test to verify it passes**

Run: `python scripts/test_party_unity_rule.py`
Expected: PASS, no failures reported.

- [ ] **Step 5: Capture the GA baseline before touching the GA generator**

Run: `cp assets/data/ga-party-unity.json /tmp/ga-party-unity.before.json`

- [ ] **Step 6: Replace the inline rule in `generate_party_unity.py`**

In `member_scores`, delete the party-unity loop body and call `score_unity(seen, party_vote_index, party)`; replace the participation counting with `score_participation(seen)`. Keep every GA-specific concern where it is — `rollcall_key` dedup, `vote_chamber` filtering, `VOTING_CHAMBERS`, `DEPARTED_STATUSES`, the presiding-officer heuristic, and the shape of the returned `scores` dict including `independenceRate`.

- [ ] **Step 7: Prove the GA artifact is unchanged**

Run: `python scripts/generate_party_unity.py && python -c "import json;a=json.load(open('/tmp/ga-party-unity.before.json'));b=json.load(open('assets/data/ga-party-unity.json'));a['metadata'].pop('generatedAt');b['metadata'].pop('generatedAt');print('IDENTICAL' if a==b else 'DIVERGED')"`
Expected: `IDENTICAL`. Anything else means the extraction changed a published number — revert it rather than accepting the new figures.

- [ ] **Step 8: Run the full suite and commit**

Run: `for t in scripts/test_*.py; do python "$t" >/dev/null || echo "FAIL $t"; done`
Expected: no output.

```bash
git add scripts/lib/party_unity.py scripts/test_party_unity_rule.py scripts/generate_party_unity.py assets/data/ga-party-unity.json
git commit -m "Extract the party-line rule into lib/party_unity.py"
```

---

### Task 2: Federal scorecard generator

**Files:**
- Create: `scripts/generate_federal_party_unity.py`
- Test: `scripts/test_federal_party_unity.py`

**Interfaces:**
- Consumes: `party_line_direction`, `score_unity`, `score_participation`, `OTHER_PARTY` from Task 1.
- Produces:
  - `RANK_MIN_COHORT = 5`
  - `build_scorecard(votes_data: dict, members_data: dict) -> dict` — the complete output document, so the test can call it without touching disk.
  - Artifact `assets/data/federal-party-unity.json`, shape per the spec's "Data shape" section.

CLI: `python scripts/generate_federal_party_unity.py [votes.json] [members.json] [out.json]`, defaulting to `assets/data/federal-member-votes.json`, `assets/data/current-members.json`, `assets/data/federal-party-unity.json`. Written with `write_json_atomic(..., indent=2)`.

A member's chamber is `terms.item[-1].chamber`; only `state == "Georgia"` members are scored. Own-chamber filtering compares that against each vote's `chamber` field (`"House"`/`"Senate"`).

- [ ] **Step 1: Write the failing test** in `scripts/test_federal_party_unity.py`, using a hand-built fixture of 1 senator plus 6 representatives
(`OLD00001`, `NEW00001`, `NOPL0001`, `TIED0001`, `TIED0002`, `LAST0001`) and one
departed member with votes but no roster entry (`GHOST001`):

```python
check("a mid-Congress arrival is scored against their own window",
      doc["members"]["NEW00001"]["totalRollCalls"], 2)
check("the full-term member is scored against all of them",
      doc["members"]["OLD00001"]["totalRollCalls"], 5)
check("unity is null, never zero, with no party-line votes",
      (doc["members"]["NOPL0001"]["partyUnity"], doc["members"]["NOPL0001"]["partyLineVotes"]), (None, 0))
check("a member with votes but no roster entry is excluded",
      "GHOST001" in doc["members"], False)
check("...and is counted in metadata",
      doc["metadata"]["withVotesButNotInRoster"], 1)
check("rank 1 is the most loyal", doc["members"]["OLD00001"]["unityRank"], 1)
check("ties share a rank and the next rank skips",
      [doc["members"][b]["unityRank"] for b in ("TIED0001", "TIED0002", "LAST0001")], [1, 1, 3])
check("cohort is the chamber delegation", doc["members"]["OLD00001"]["cohortSize"], 6)
check("the delegation block carries the chamber median",
      doc["delegation"]["House"]["medianUnity"], expected_median)
check("the senate cohort is reported even when below the rank threshold",
      doc["delegation"]["Senate"]["cohortSize"], 1)
check("a roll call with no party tally is skipped, not counted",
      doc["members"]["OLD00001"]["partyLineVotes"], 3)
check("participation excludes the other chamber's roll calls",
      doc["members"]["OLD00001"]["cast"] <= doc["members"]["OLD00001"]["totalRollCalls"], True)
```

Build the fixture so those numbers hold: 5 House roll calls of which 3 are party-line, one is bipartisan and one has `partyTally: None`; plus Senate roll calls the House members must not be scored against.

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_federal_party_unity.py`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `build_scorecard` and the CLI in `scripts/generate_federal_party_unity.py`**

Per member: collect their own-chamber votes into `{voteId: vote}`, call the Task 1 scorers against each vote's `partyTally`, then compute `unityRank`/`participationRank` within the chamber cohort and the chamber medians. `independenceRate` is `1 - partyUnity`, and is `None` whenever `partyUnity` is. Rates are rounded to 4 decimal places, matching the GA generator.

- [ ] **Step 4: Run test to verify it passes**

Run: `python scripts/test_federal_party_unity.py`
Expected: PASS.

- [ ] **Step 5: Generate the real artifact and sanity-check it against the figures in the spec**

Run: `python scripts/generate_federal_party_unity.py && python -c "import json;d=json.load(open('assets/data/federal-party-unity.json'));m=d['members'];print(d['metadata']['count'], d['metadata']['withVotesButNotInRoster']);print('C001103', m['C001103']['partyUnity'], m['C001103']['partyLineVotes']);print('O000174', m['O000174']['partyUnity'], m['O000174']['partyLineVotes']);print('B001328', m['B001328']['totalRollCalls'])"`
Expected: `16 2`; Carter `0.9889 449`; Ossoff `0.96 795`; Blair `29`. A different Carter or Ossoff figure means the scorer disagrees with the spec's measured values — stop and reconcile before continuing.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_federal_party_unity.py scripts/test_federal_party_unity.py assets/data/federal-party-unity.json
git commit -m "Score party unity and participation for the GA federal delegation"
```

---

### Task 3: Validator and workflow wiring

**Files:**
- Create: `scripts/validate_federal_party_unity.py`
- Modify: `.github/workflows/update-federal-votes.yml` (add a generate step and a validate step after "Build the shared vote index and per-member slices"; add the artifact to the `git add`, `git restore` and `git checkout` path lists)

**Interfaces:**
- Consumes: the artifact from Task 2.
- Produces: CLI `python scripts/validate_federal_party_unity.py <scorecard.json> <votes.json>`, exit 0 on success and 1 on any violation, printing each violation.

- [ ] **Step 1: Write the failing test** — extend `scripts/test_federal_party_unity.py` with cases that call the validator's `problems(scorecard, votes) -> list[str]`:

```python
check("a clean document has no problems", problems(good_doc, votes), [])
check("a rate above 1 is caught", len(problems(rate_over_one_doc, votes)), 1)
check("votedWithParty above partyLineVotes is caught", len(problems(aligned_too_high_doc, votes)), 1)
check("more roll calls than the chamber held is caught", len(problems(impossible_total_doc, votes)), 1)
check("a sitting roster member missing from the scorecard is caught", len(problems(missing_member_doc, votes)), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_federal_party_unity.py`
Expected: FAIL — `problems` not defined.

- [ ] **Step 3: Implement `problems()` and a `main()` in `scripts/validate_federal_party_unity.py`**

Checks: every rate within 0..1; `votedWithParty <= partyLineVotes`; `cast <= totalRollCalls`; no member scored against more roll calls than their chamber actually held in the votes file; every sitting Georgia roster member present in `members`.

- [ ] **Step 4: Run test and the validator against the real artifact**

Run: `python scripts/test_federal_party_unity.py && python scripts/validate_federal_party_unity.py assets/data/federal-party-unity.json assets/data/federal-member-votes.json`
Expected: PASS, then `All federal party-unity checks passed.`

- [ ] **Step 5: Wire both into the workflow, then confirm the watchlist is still intact**

Run: `python scripts/validate_workflow_triggers.py`
Expected: the 48-workflow summary line, exit 0. (The workflow's `name:` does not change, so `notify-workflow-failure.yml` needs no edit.)

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_federal_party_unity.py scripts/test_federal_party_unity.py .github/workflows/update-federal-votes.yml
git commit -m "Validate the federal scorecard and build it in the weekly run"
```

---

### Task 4: Scorecard panel

**Files:**
- Modify: `_includes/entity/federal-legislator.html` (add the fetch helper beside `getFederalVoteIndex`; render in the `container.innerHTML` template at ~line 1531, between the scope paragraph and `${chartHtml}`)

**Interfaces:**
- Consumes: `assets/data/federal-party-unity.json` from Task 2.
- Produces: nothing other tasks use.

- [ ] **Step 1: Add `getFederalScorecard()`**

A cached-promise fetch of `getBasePath() + 'assets/data/federal-party-unity.json'`, mirroring `getFederalVoteIndex()`: resolves to the parsed document, or `null` on a non-ok response or a parse failure. A `null` result must never surface as a zero.

- [ ] **Step 2: Add `scorecardHtml(entry, delegation)` returning `''` when `entry` is falsy**

Renders participation always, and unity only when `entry.partyUnity !== null` — otherwise a short line saying a unity score needs party-line votes and this member has none. Shows `unityRank`/`participationRank` only when `entry.cohortSize >= RANK_MIN_COHORT`,
a JS constant declared beside the function mirroring `RANK_MIN_COHORT = 5` in the
generator; below that, renders the other delegation member's figure as a peer comparison. Ends with a provenance line built from this file's own `metadata.generatedAt` via the existing `fmtDate`, not the page's Congress.gov stamp.

- [ ] **Step 3: Render it in the Voting History template**

Await the scorecard alongside the existing index and slice fetches, and insert `${scorecardHtml(...)}` between the scope paragraph and `${chartHtml}`.

- [ ] **Step 4: Verify in the browser on clean entity URLs**

Run: `mcp__Claude_Browser__preview_start` with the `jekyll` config, then visit `/us-congress/earl-carter-ga-1/#votingHistory` and `/us-congress/jon-ossoff-senate/#votingHistory`.
Expected: Carter shows a rank out of 14; Ossoff shows a peer comparison against Warnock, no rank; no console errors; and `/us-congress/everton-blair-ga-13/` shows participation against 29 roll calls rather than reading as a near-total absence.

- [ ] **Step 5: Confirm the panel degrades**

Run: temporarily rename the artifact (`mv assets/data/federal-party-unity.json /tmp/`), reload the page, then restore it.
Expected: the Voting History panel renders exactly as before with no scorecard block and no zeros; restore afterwards.

- [ ] **Step 6: Commit**

```bash
git add _includes/entity/federal-legislator.html
git commit -m "Show the party-unity scorecard on the federal legislator page"
```
