# VoteGA.org Codebase Review — 2026-08-18

Three parallel audits: **data merge/join integrity**, **UX / IA / accessibility**, and **build pipeline & maintainability**.
Read-only review — no files were modified. Every count below was produced by running commands against the live
files at `HEAD = e40f7a3`; unverified hypotheses were dropped rather than reported.

Supersedes nothing. Read alongside [CODEBASE-REVIEW-2026-08-13.md](CODEBASE-REVIEW-2026-08-13.md), whose status is
tracked in [Appendix A](#appendix-a--status-of-the-2026-08-13-review).

---

## Contents

- [Remediation progress](#remediation-progress)
- [Executive summary](#executive-summary)
- [Tier 1 — Wrong data reaching users, or one command away](#tier-1--wrong-data-reaching-users-or-one-command-away)
- [Tier 2 — Silent-failure machinery](#tier-2--silent-failure-machinery)
- [Tier 3 — Wrong joins, narrower blast radius](#tier-3--wrong-joins-narrower-blast-radius)
- [Tier 4 — UX, IA, and accessibility](#tier-4--ux-ia-and-accessibility)
- [Tier 5 — Hygiene, docs, and latent traps](#tier-5--hygiene-docs-and-latent-traps)
- [Appendix A — Status of the 2026-08-13 review](#appendix-a--status-of-the-2026-08-13-review)
- [Appendix B — Verified clean](#appendix-b--verified-clean)
- [Suggested sequencing](#suggested-sequencing)

---

## Remediation progress

| Tier | Findings | Fixed | Remaining |
|---|---|---|---|
| Tier 1 — wrong data reaching users | 5 | **all five** | — |
| Tier 2 — silent-failure machinery | 5 | **all five** | — |
| Tier 3 — wrong joins | 6 | **3.1, 3.2, 3.3, 3.4, 3.5, 3.6** | — |
| Tier 4 — UX / IA / a11y | 15 | **all fifteen** | — |
| Tier 5 — hygiene, docs, traps | 12 | **5.1 – 5.9, 5.11, 5.12** | 5.10 |

- **2026-08-18, `4573e63` "Workflow Hardening"** — all of Tier 2, plus 5.1.
- **2026-08-18, `11af8df` "Tier 1 - Data Fixes"** — findings 1.1, 1.2, 1.3, plus the
  `remove: true` half of 5.2 (a prerequisite for 1.1 — see below).
- **2026-08-18, `a34b7ac` "General Election Results Page"** — finding 1.4, as a
  reusable `preview` status.
- **2026-08-18, working tree** — finding 1.5 (shared `lib/ga_voters.py`), which also
  fixes 3.5. **Tier 1 is complete.**

Each fixed finding keeps its original text and gains a **FIXED** note recording what
changed, what was verified, and — where the original diagnosis was wrong — what the
cause actually was.

---

## Executive summary

Four things stand out above the rest of the list. **All four are now fixed.**

1. **`build_legislative_races.py` is an armed trap.** Running it today destroys 391 general-election candidate
   entries across all 236 GA legislative races. It already fired once on 2026-08-17. The only guard is a prose
   warning, and the script is step 2 of the documented workflow. The general election is ~11 weeks out. → [1.1](#11--build_legislative_racespy-destroys-391-general-election-candidates-on-every-run)

2. **A candidate's page displays another person's campaign money.** The FEC district+surname matcher takes the
   first hit with no ambiguity check, and the name-based fallback that would correct it is dead for ~35% of
   federal candidates because the JS and Python normalizers don't actually mirror each other. → [1.2](#12--fec-districtsurname-match-is-first-hit-wins), [1.3](#13--normalizename-js-does-not-mirror-normalize_name-python)

3. **The workflows can report green after throwing the data away.** A `set -e` bug in a push-retry loop copied
   into 15 workflows means three failed pushes exit 0. No workflow anywhere has a failure notification. Every
   data fix below can be silently discarded at the last step until this is fixed. → [2.1](#21--the-push-retry-loop-swallows-total-failure), [2.2](#22--no-failure-notification-anywhere)

4. **A zeroed "Unofficial Results" page for the November general is live and linked.** It reports every candidate
   at 0 votes under an "Unofficial Results" header, and the election calendar renders a "View Results →" button
   pointing at it. → [1.4](#14--ga-general-2026-results-is-live-and-reports-every-candidate-at-0-votes)

The structural read: **every generator and every workflow is a copy-paste fork of its siblings.** Five separate
`fetch_*` implementations with three incompatible retry policies, five distinct `norm_name` variants, a
`target_cycle()` duplicated with a comment admitting it's hand-synced, and 15 identical copies of the same broken
push loop. Most Tier 2 findings are one fact wearing six costumes.

---

## Tier 1 — Wrong data reaching users, or one command away

> **STATUS: all five Tier 1 findings fixed on 2026-08-18.**
>
> | # | Fix |
> |---|---|
> | 1.1 | `build_legislative_races.py` merges instead of replacing, and refuses to write when the post-primary candidate count would drop. A full rebuild is now content-idempotent against `races.json`. **Required fixing the `remove: true` half of [5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person) as a prerequisite** — see the note on that finding. |
> | 1.2 | `findFecId` collects every district+surname hit and narrows on full name → filing activity → shared committee, reporting `ambiguous` rather than guessing. All three misresolved candidates now resolve correctly; **0 ambiguous across 136 federal entries**, so the editorial pins the finding recommended proved unnecessary. |
> | 1.5 | Voter identity resolution extracted to `scripts/lib/ga_voters.py`; the name fallback now fires on an *unresolvable* id, not merely a missing one. Code fixed and tested; **the data corrects itself on the next scheduled run** — offline repair was shown to be indeterminate (0 of 21 ghosts uniquely identifiable). Also fixes [3.5](#35--curated-ga-bill-votesjson-party-tallies-double-count-a-duplicate-voter-row). |
> | 1.4 | Both general-results pages are staged behind a new `status: preview` + `noindex`/`sitemap: false`/`search: false`, removing them from the sitemap and site search until election night. **Two of the finding's claims did not hold** — the zeroed cards and the calendar link — see the note on that finding. |
> | 1.3 | Both normalizers reduce to `first last` and strip honorifics. New `scripts/test_fec_name_parity.py` runs the real JS (via node) against the real Python over 329 names. **The finding's stated cause was wrong** — see the note on that finding. |

### 1.1 — `build_legislative_races.py` destroys 391 general-election candidates on every run

**Severity: High** · `scripts/build_legislative_races.py:244-251`

```python
existing = [r for r in dest.get("races", []) if not r["id"].startswith("ga-house-") and not r["id"].startswith("ga-senate-")]
dest["races"] = existing + new_races
dest["updatedAt"] = src.get("updatedAt", "")
```

`build_races()` always emits `phases.general = {"electionDate": "2026-11-03", "candidates": []}` and
`activePhase: "primary"`. General-election ballots live **only** in `races.json` (written there by
`set_general_candidates.py`), so a rebuild discards them.

**Measured against the current `races.json`:**

| Effect | Count |
|---|---|
| General-election candidate entries destroyed | **391** |
| Races with populated `general.ballots` today | 236 / 236 |
| `activePhase` reset `general` → `primary` | 236 / 236 |
| `ballots` shape reverted to empty `candidates` array | 236 |
| `updatedAt` rolled back | `2026-08-18T11:57:14Z` → `2026-05-06T02:28:42Z` |
| `_note` fields surviving (re-applied via `_raceOverrides`) | 26 |

TO-DO.md:20-23 confirms this already fired on 2026-08-17 and was restored from git. The script remains step 2 of
the documented workflow at TO-DO.md:295.

**Fix:** merge instead of replace — preserve `activePhase`, any non-empty `phases.general`, `phases.runoff`, and
`primaryResult` from the existing race object; overwrite only `phases.primary.ballots`. Stamp `updatedAt = now()`
rather than copying `src["updatedAt"]`. Add a refuse-to-run guard when any target race has `activePhase != "primary"`.

#### ✅ FIXED — 2026-08-18

`merge_race()` rebuilds `phases.primary.ballots` from source and carries forward `activePhase`, any populated
`general`/`runoff` phase, and every race-level key the builder does not own (`BUILDER_OWNED` names the ones it
does). `updatedAt` now stamps `now()`. Races keep their original index in the array, so the diff stays readable.

The guard is a count rather than an `activePhase` check: the run sums post-primary candidates before and after and
refuses to write if the number falls. An `activePhase != "primary"` block as originally proposed would have
refused *every* run, since all 236 races are currently `general`. `--allow-loss` overrides; `--force-reset
--allow-loss` reproduces the old wholesale-replace behaviour deliberately.

**A prerequisite the finding missed.** Fixing the merge was not sufficient to make the script safe to run. The
first clean run reintroduced every duplicate candidate that had been removed — `ga-house-149` went 3 → 5
candidates, `ga-house-14` grew a second Bella Bautista — because the builder never honoured `remove: true`
(finding [5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person)). This was
invisible in `races.json`, which already had them stripped, which is also why 5.2 recorded those 14 override keys
as "orphaned": they are orphaned *against `races.json`* but load-bearing *against the source export*. The builder
now applies `remove`, with 5.2's name check.

**Verified:**

| Check | Result |
|---|---|
| Default run vs. HEAD | **0** races differ — a full rebuild is content-idempotent |
| General-election candidates | 391 → **391** |
| `activePhase` reset to primary | **0** of 236 |
| Duplicate candidate names after rebuild | **0** |
| Non-legislative races touched | **0** |
| `--force-reset` without `--allow-loss` | reports `391 → 0`, **exits 1, writes nothing** |
| Stale positional `remove` (simulated re-order) | **exits 1, deletes nobody**, names the mismatch |

---

### 1.2 — FEC district+surname match is first-hit-wins

**Severity: High** · `assets/scripts/campaign-finance.js:119`

```js
const match = fecData.byDistrict[distKey].find(cid => fecData.candidates?.[cid]?.lastName === last);
```

`.find()` returns the first array element and never checks for a second hit — unlike the GA/PeachFile path
(`findGaFilers`, line 197) which deliberately returns `ambiguous` rather than guessing.

**Simulating `findFecId()` over all federal `races.json` candidates** (excluding those with an `fecCandidateId`
pin or a resolving bioguide) yields 3 ambiguous cases, all resolving wrongly:

| Race | Candidate | JS picks | Actually is | What the page shows |
|---|---|---|---|---|
| `ga-11-2026` | **Tricia R. Pridemore** | `H4GA11087` — her 2014 candidacy, no totals | `H6GA11207` — **$618,361.76 raised** | all `—`, for a $618K campaign |
| `ga-14-2026` | **Timothy Beau Brown** | `H6GA14177` = **"BROWN, JAMES M MR"** | `H6GA14185` ($13,050.01) | $9,879.55 raised / $1,492.03 CoH / "Retired- State Farm" — **another person's money**, plus an FEC link to the wrong committee |
| `ga-08-2026` | Justin M. Lucas | `H6GA08153` | `H6GA08146` (same committee) | cosmetic only |

`byNormalizedName` already holds the correct answer for Pridemore (`tricia pridemore → H6GA11207`), but step 2
fires before step 3 and short-circuits it.

**Fix:** collect all district+surname hits; if `length > 1`, fall through to `byNormalizedName`; if still
ambiguous, return `status: 'ambiguous'` rather than guessing — mirroring the GA branch's own stated rule. Ship
editorial `fecCandidateId` pins for these three immediately.

#### ✅ FIXED — 2026-08-18

`findFecMatch()` (new; `findFecId()` remains as a thin wrapper so `candidate.html`'s direct call still works)
collects **every** district+surname hit, then narrows through `narrowFecMatches()`:

1. **exact normalized full name** — separates two different people sharing a surname and district
   (`BROWN, JAMES M` vs `BROWN, TIMOTHY BEAU`);
2. **filing activity** — a record with `totalRaised`/`coverageEndDate` beats one with neither, which is what
   distinguishes a live 2026 campaign from the same person's dormant 2014 candidacy;
3. **shared `committeeId`** — one committee across the remaining ids means duplicate FEC records for a single
   filer, so either is correct.

Anything still unresolved returns `status: 'ambiguous'`. Step 3 is now collision-aware too, backed by an index the
JS builds from `fecData.candidates` rather than reading `byNormalizedName` — that index stores one id per key and
therefore **cannot represent the 14 real collisions** in the current data, which is why falling through to it (as
the fix above proposed) would not have been safe on its own.

**Verified** — in-browser against the live module, and by a 23-assertion node suite:

| Race | Candidate | Was | Now |
|---|---|---|---|
| `ga-11-2026` | Tricia R. Pridemore | all `—` | **$618,361.76** (`H6GA11207`) |
| `ga-14-2026` | Timothy Beau Brown | $9,879.55 / $1,492.03 — *James Brown's* | **$13,050.01 / $6,212.27** (`H6GA14185`) |
| `ga-08-2026` | Justin M. Lucas | arbitrary of two | resolves via shared committee |

Brown's candidate page now lists Advocate Health and International Paper as top donor employers instead of
"Retired- State Farm". Sweep over all **136** federal candidate entries: 129 `ok`, 7 `none`, **0 `ambiguous`** —
so the editorial `fecCandidateId` pins this finding recommended turned out to be unnecessary.

`candidate.html` now distinguishes "Multiple FEC filings match this name" from "No FEC filing found", matching
how `race.html:391` already worded the ambiguous case. `member.html:590` carried its own copy of the same
`.find()` bug — unreachable today (all 15 GA members resolve by bioguide) but now delegating to the shared
`narrowFecMatches()`.

**Not changed:** `ga-member.html:470` reads `byNormalizedName` via its own `financeNormalizeName()`, but against
the GA/PeachFile dataset whose matcher [Appendix B](#appendix-b--verified-clean) verified clean. Worth folding
into the shared rule if the state side is ever consolidated.

---

### 1.3 — `normalizeName()` (JS) does not mirror `normalize_name()` (Python)

**Severity: High** · `assets/scripts/campaign-finance.js:69-83` vs `scripts/generate_fec_data.py:186-202`

The JS carries a comment claiming it mirrors the Python. It doesn't, in two ways:

1. **Middle names.** Python builds `"first last"` from `"LAST, FIRST MIDDLE"`. JS only reformats when the input
   *contains a comma* — and `races.json` names are `"First Middle Last"` with no comma, so every middle token survives.
2. **Single-char initials.** Python skips them (`tokens = [t for t in first.split() if len(t) > 1]`); JS takes
   `split(/\s+/)[0]` unconditionally.

**Evidence:** of 125 federal candidate entries in `races.json`, **44 distinct names** normalize (JS-side) to a
3+ token key that does not exist in `byNormalizedName`:

- `"Tricia R. Pridemore"` → `tricia r pridemore` (index has `tricia pridemore`)
- `"Timothy Beau Brown"` → `timothy beau brown`
- `"Justin M. Lucas"`, `"Joyce Marie Griggs"`, `"Dr. Krista Penn"` (JS also doesn't strip honorifics; Python's
  suffix regex doesn't either)

Step 3 is therefore dead for **~35% of federal candidates** — which is precisely why the bad step-2 guesses in
[1.2](#12--fec-districtsurname-match-is-first-hit-wins) are never corrected.

**Fix:** in JS, drop middle tokens and single-char initials the way Python does (build `first + last` from the
token list regardless of comma), and add `dr|mr|mrs|ms` to the JS suffix regex to match the GA branch's
`GA_SUFFIX_RE`. Add a fixture asserting the two implementations agree on all 252 `ga-fec-data.json` names.

#### ✅ FIXED — 2026-08-18 · original diagnosis corrected

**Divergence #1 above is wrong.** Both implementations reformatted **only** the comma form — the Python has no
`else` branch either, so it also retained middle tokens for a no-comma name. Measured across the 252 FEC names,
the two functions disagreed on exactly **2**, both from divergence #2 (single-char initials): `OSSOFF, T.
JONATHAN` → `jonathan ossoff` in Python vs `t ossoff` in JS, and one Monteleone variant. That divergence is real
but was latent, since the JS is only ever fed no-comma display names.

**The actual defect** is a shape mismatch, not a drift: `byNormalizedName` is built from FEC's `LAST, FIRST
MIDDLE` strings and so contains **228 two-token keys** (plus 2 three-token), while lookups pass `races.json`
display names like `Tricia R. Pridemore`, which reduce to three-token keys. A three-token key cannot match a
two-token entry, so **57 of 91** distinct federal names missed — 44 of them specifically because a middle name or
initial survived. The finding's *conclusion* (a dead fallback for most of the field) was right; its stated cause
was not.

Both sides now reduce to `first last` — dropping middle tokens and bare initials in the no-comma path as well as
the comma path — and both strip `dr|mr|mrs|ms`. That recovers **32** previously unmatchable names.

**A hazard the fix had to avoid:** reducing to `first last` creates **14 collisions** inside the FEC data,
including `tricia pridemore` (the 2014 and 2026 filings) and `justin lucas`. A naive first-wins index built on the
new keys would have reintroduced [1.2](#12--fec-districtsurname-match-is-first-hit-wins) at step 3. This is why
the JS builds a collision-aware `key → [ids]` index and routes it through `narrowFecMatches()`.

**Verified:** `scripts/test_fec_name_parity.py` runs the **real** JS `normalizeName()` through node — not a Python
re-implementation of it — against the **real** `normalize_name()`, over every FEC name, every federal candidate
name in `races.json`, and pinned edge cases (quoted nicknames, `III`, hyphenated and single-word names): **329
names, 0 disagreements**, 326 reducing to a two-token key. Negative-tested by reintroducing the exact drift, which
produces 42 failures — so the fixture fails when it should.

Note this changes the `byNormalizedName` keys `generate_fec_data.py` emits on the next regeneration. Nothing
depends on that: the JS now builds its own index, and the committed `ga-fec-data.json` still works with the new
code as-is.

---

### 1.4 — `/ga-general-2026-results/` is live and reports every candidate at 0 votes

**Severity: High** · `ga-general-2026-results.html:1-21` · `_layouts/election_results.html:112,116`

Front matter sets `status: unofficial`, so the layout renders **"Election Date: November 3, 2026 · Unofficial
Results"** above the fold, with every race card showing 0 votes and 0.0% bars. The explanatory `notice` renders
*below* `{{ content }}`, after the reader has already seen "Unofficial Results."

Compounding:

- The page is **not** in `_data/election_archive.yml`, so `/results/` doesn't list it and `/results/latest/`
  won't point at it —
- but it **is** indexed in `searchcorpus.json`, and it **is** linked from `assets/data/ga-election-calendar.json:68`
  (`resultsUrl`), which `ga-voter-access.html:273` renders as a **"View Results →"** button.
- Meanwhile `results.html` describes the same election as `status: upcoming`, pointing at `/elections`.

A voter following the calendar CTA lands on an apparently-official zeroed results page; a voter on `/results/` is
told the election hasn't happened. The same setup exists for `ga-general-2026-runoff-results.html`, for a runoff
that may never occur.

**Fix:** add `status: upcoming` handling to the layout (suppress the "Unofficial Results" label and the zeroed
cards, render the notice first), or gate both pages behind `published: false` / `sitemap: false` + `noindex`
until polls close, and drop `resultsUrl` from the calendar until then.

#### ✅ FIXED — 2026-08-18 · two claims corrected, and the page's purpose clarified

**Context the review lacked:** both pages exist deliberately, staged so the foundation is ready as the general
approaches. The goal was therefore to make them undiscoverable and honest until election night, *not* to remove
them.

**Correction 1 — the zeroed cards do not exist.** The layout already handles this: `getStatus()` returns
`no-results` when `totalVotes` is falsy, so every race renders **"Awaiting Results" / "No results reported" / "—"**.
Verified on the rendered page: **532** `no-results` badges, and **0** occurrences of `0 votes` or `0.0%` anywhere
in the DOM. The claim of "0 votes and 0.0% bars" was read from the front matter's own `notice` text rather than
from the page.

**Correction 2 — the calendar CTA does not link here.** `ga-voter-access.html:267` gates the CTA on
`isUpcoming` (`parseLocalDate(e.date) >= today`, line 345): an upcoming election renders `racesUrl`
("View races & candidates"), and only a past one renders `resultsUrl`. The finding quoted lines 273-274 without
the branch above them. The `resultsUrl` in `ga-election-calendar.json` is correct and deliberate — it activates
by itself once the date passes.

**What was actually wrong** — two real discovery paths, both confirmed against the built `_site`:

| Path | Before | After |
|---|---|---|
| `sitemap.xml` | both pages listed | removed (48 URLs, was 50) |
| On-site search corpus | both indexed | removed (49 entries, was 51) |
| `<meta name="robots">` | absent | `noindex, follow` |
| Header label | "Unofficial Results" | "Ballot preview — results post after polls close" |

**Implementation** — a reusable `preview` status rather than a one-off patch:

- `_layouts/election_results.html` gains `status: preview`, which replaces the "Unofficial Results" label and
  renders an informational blue notice (`.pr-notice-preview`) instead of the amber "unofficial" warning — nothing
  is provisional when nothing has been counted. The front-matter contract documents it.
- `_includes/head.html` honours a `noindex` front-matter flag (none existed before).
- `assets/data/searchcorpus.json` skips pages with `search: false`.
- Both pages carry `status: preview` + `noindex` / `sitemap: false` / `search: false`, above a comment stating
  the go-live step: **set `status: unofficial` and delete the three flags.** Nothing else changes.
- The `notice` on the general page was reworded — it claimed "All candidates currently show 0 votes", which is
  not what the page renders.

**Regression-checked:** the four live results pages are untouched (no robots meta, labels unchanged), the
certified primary page still reads "Official Certified Results" with `.pr-notice-certified`, only 2 pages
site-wide carry a robots meta, and the Jekyll build logs and browser console are clean.

**One timing edge, left as-is:** `isUpcoming` uses `>=`, so on election day itself (Nov 3) the calendar still
shows "View races & candidates"; the results CTA appears Nov 4. If you want the link live on election night, the
comparison needs to become "strictly after the close of polls" rather than a date compare — a deliberate change,
not a bug fix, so it is flagged rather than made.

---

### 1.5 — 21 ghost OCD person IDs orphan 38 legislators from every key vote

**Severity: High** · `scripts/generate_curated_ga_bills.py:131-137` · surfaces on `ga-member.html` key-votes tab

`build_vote_record()` keys `memberVotes` on `voter.id` with no validation against `ga-members.json`.

**Evidence:** 226 distinct voter IDs across the 9 curated bills; **21 are not in `ga-members.json`** (e.g.
`ocd-person/06eaa836-9c03-4dc0-800d-e08f57333d19`). None appear in `ga-member-votes.json` either. Consequence:
**38 of 232 active legislators have zero curated votes** — Jan / Emanuel / Todd / Sheila / Nissa Jones;
Lynn / Michael / Tyler / Vance Smith; Derrick / Edna / Kim / Mack Jackson; Al / Mary Frances / Rick Williams;
Chas / Park Cannon; Joe / Lisa Campbell; Jaha / Jutt Howard; Jason / Jordan Ridley; Darlene / Rhonda Taylor;
Ben / Sam Watson; and 8 more.

**Every one of the 38 shares a surname with another sitting member.**

This is a *different root cause* than the 8/13 review's finding 1.2. There, `voter.id` was assumed absent; here
`voter.id` is **present but points at a deprecated/duplicate Open States person record**. The name-fallback added
at `generate_ga_votes_data.py:437-446` only fires `if not voter_id`, so **it will never fix these members** even
after regeneration.

**Fix:** after resolving `voter_id`, if it is not in `ga-members.json`, fall back to `(chamber, normalized
voter.name)` — move the fallback trigger from "id missing" to "id unresolvable". Emit a `ghostVoterIds` count in
metadata so it can't regress silently. Add ghost→canonical aliases to `ga-members-overrides.json`.

#### ✅ FIXED IN CODE — 2026-08-18 · data pending the next scheduled run

Every number in the finding checks out: **226** distinct voter ids, **21** ghosts, **38** orphaned legislators.
Two small refinements — the raw orphan count is 42, of which 4 are `executive`-chamber members (Governor, Lt.
Governor, AG, SoS) who never cast roll-call votes, giving 38 actual legislators; and of those 38, **35** share a
surname rather than all of them (Sheila Nelson, Sylvia Wayfer and Venola Mason have unique surnames and are
missing for some other reason).

**The committed data cannot be repaired offline, and should not be.** `memberVotes` stores only
`{ocd-person-id: vote}` — no names — so nothing in the file identifies who a ghost was. I tested whether roll-call
signatures could identify them (which members are absent from exactly the roll calls a ghost appears in):
**0 of 21** are uniquely determined; each has 17–48 candidates. Any offline repair would be guesswork, and
guessing here publishes a false claim about how a named legislator voted. The fix is therefore in the generator,
and the data corrects itself on the next run.

**Implementation** — extracted `scripts/lib/ga_voters.py`, since this was another copy-paste fork:
`generate_ga_votes_data.py` had the name index, chamber inference and legacy-id map; `generate_curated_ga_bills.py`
had none of them and keyed `memberVotes` on the raw `voter.id`.

- `resolve_voter()` returns `(member_id, how)` with `how ∈ id | alias | name | ghost | unresolved`. The fallback
  now fires when the id is **unresolvable**, not merely missing — the actual defect.
- Ambiguity is never guessed: a `(chamber, name)` pair matching two members maps to `None`, and the fallback is
  chamber-scoped, so a House "Jones" can never absorb a Senate "Jones".
- `LEGACY_PERSON_ID_MAP` moved to the shared module. **The stranded Jon Burns id is one of the 21 ghosts** — the
  votes generator had an alias for it; the curated generator had no such concept.
- Both generators now emit `ghostVoterIds`, `unresolvedVoterRows` and `nameFallbackResolved`; the curated file
  also records `sittingLegislators` / `legislatorsWithVotes`, so coverage is a delta-checkable metric rather than
  something a reader has to notice.
- `update-curated-ga-bills.yml` gained its first validation step: the delta validator plus an assertion that no
  roll call's `partyTally` exceeds its own roster.

**This also fixes [3.5](#35--curated-ga-bill-votesjson-party-tallies-double-count-a-duplicate-voter-row), necessarily.**
The tally is now derived from the de-duplicated `memberVotes` instead of counted per row. That was not optional:
resolving a ghost onto a member already present would have double-counted them, so per-row counting became wrong
in a second way. The new workflow assertion detects **7** over-tallied Senate roll calls in the current data and
will read 0 after regeneration.

**Verified:**

| Check | Result |
|---|---|
| `scripts/test_ga_voter_resolution.py` | **27/27** — ghost recovery, chamber scoping, ambiguity refusal, alias folding, `"Last, First"` and title forms, empty-index fallback |
| End-to-end against the real generator with a mocked Open States response | 3 real House members named Jones, given ghost ids, **all recovered by name**; an unrecoverable ghost correctly dropped; `partyTally` 7 = roster 7 |
| Workflow validation on a simulated post-fix file | passes, and reports coverage `230/232` |
| `--sanitize` offline path, all generators, all 27 workflow YAMLs | unchanged and green |

#### 🔁 ROOT CAUSE CORRECTED — 2026-08-19, after running the pipeline

The first regeneration fixed [3.5](#35--curated-ga-bill-votesjson-party-tallies-double-count-a-duplicate-voter-row)
(0 over-tallied roll calls, from 7) but left coverage at **194/232** — the name fallback recovered 3 of 299 rows.
A diagnostic run (`scripts/inspect_ga_voter_resolution.py`) against the live API shows the finding's diagnosis was
wrong in both halves.

**The 21 ghost ids are former legislators, not deprecated ids for sitting members.** They appear in exactly two
roll calls — SB 233 and SB 189, which `curated-ga-bills.json` deliberately pins to `session: 2023_24` (school
vouchers, election-law overhaul). **Every 2025-26 roll call has `ghost=0`.** Looking the ids up via `/people`
returns `current_role: null` for each: David Knight, Gloria Frazier, Gregg Kennard, James Beverly, Jodi Lott,
Lauren Daniel, Penny Houston, Roger Bruce, Teri Anulewicz, Mike Dugan… all people who served in 2023-24 and have
since left. Their votes *cannot* be attributed to sitting members, and dropping them is correct. **The ghosts
orphan nobody.**

**What actually orphans the 38 is the `unresolved` population, and the cause is the data format.** Georgia roll
calls identify voters by **bare surname** — `voter_name` is `'JONES'`, `'WATSON'`, `'ANULEWICZ'`; the diagnostic
reports **120/120** failed rows as a single token — and Open States omits `voter.id` *precisely when that surname
is shared*. So the rows needing help are exactly the ones a name lookup can never settle, and the existing
fallback (which compares against full names) could never match even an unambiguous surname.

The arithmetic is exact:

| Chamber | Sitting | Members sharing a surname | `unresolved` per roll call in the log |
|---|---|---|---|
| House | 178 | **26** | **26** |
| Senate | 54 | **6** | 5–6 |

**Fix: elimination against the roster.** A roll call lists every seat (a House vote has 180 rows), so the
unresolved rows must be the members not otherwise accounted for. `assign_remaining_by_surname()` assigns them, but
only when both conditions hold: the number of rows carrying a surname equals the number of still-unassigned
sitting members with that surname, **and** every one of those rows recorded the same option — in which case the
pairing is irrelevant because they all voted alike. A split vote within a surname group is refused outright, since
the data cannot say who voted which way.

**Verified:** 42 unit tests, including the adversarial cases — a split Jones group attributes **nobody**, a count
imbalance refuses, a Senate member never fills a House row, and former members are never invented into the
roster. End-to-end on a synthetic full 178-row House roll call built from the real member list: all 26
shared-surname members resolved, **0 misattributed**, tally equal to roster.

#### ✅ CONFIRMED IN DATA — 2026-08-19

The regenerated `curated-ga-bill-votes.json` reports **coverage 194 -> 224 of 232 (+15.5%)**, with **141** rows
recovered by surname elimination. The remaining 8 are all explained, and none is a defect:

| Members | Why they have no key votes |
|---|---|
| Lee Anderson (R), Tonya Anderson (D) | The only shared-surname pair that splits its vote. Elimination refuses rather than guess who voted which way — working as designed. Watson (2 R) and Jones (2 D) vote alike and resolved in all 9 bills. |
| Venola Mason | Seated 2026-04-18, after the last curated roll call (2026-03-31). |
| Sheila Nelson | Seated 2026-03-15; only 2 of 17 roll calls postdate that. |
| Bo Hatchett, Lanny Thomas, Max Burns, Sylvia Wayfer | Absent from every curated roll call. Ordinary absence, not a resolution failure. |

Resolving the Andersons would need district-level data, which Georgia roll calls do not carry. Closing that gap
means an editorial override, not a code change.

#### ⚠️ THE SAME DEFECT IS LARGER IN `ga-member-votes.json`

Cross-checking the curated result against `ga-member-votes.json` exposed the real scope. That file — which powers
the voting-history tab on every legislator page — records **no votes at all for 39 of 232 sitting legislators**,
and **92% of them share a surname**: Jan/Nissa/Sheila/Todd Jones, all four Smiths, four Jacksons, both Watsons,
both Cannons, both Campbells, both Ridleys, three Howards. Ben Watson and Emanuel Jones are absent there while
resolving cleanly in the curated file, which is what gave it away.

`generate_ga_votes_data.py` now runs the same two-pass resolution. **But it is incremental by default**: a normal
run only re-fetches bills changed since the last one, so the 39 members' back history stays missing. Backfilling
needs a full rebuild, so `update-ga-votes.yml` gained a `full_refresh` dispatch input. That costs more than one
day of the 250-request Open States quota — partial progress is merged and resumes on the next run, so it may take
two passes on days when nothing else uses the key.

---

## Tier 2 — Silent-failure machinery

> **STATUS: all five fixed on 2026-08-18**, committed as `4573e63` "Workflow Hardening". Summary:
>
> | # | Fix |
> |---|---|
> | 2.1 | `pushed` flag + `exit 1` after the loop, in all 15 occurrences across 14 workflows. Verified: 3 failed attempts now exit 1; success still exits 0. |
> | 2.2 | New `.github/workflows/notify-workflow-failure.yml` — one `workflow_run` listener covering all 21 data workflows, opening/commenting a deduplicated issue. Every listed name cross-checked against the real workflow names. |
> | 2.3 | New `scripts/validate_data_update.py` (relative delta + optional floors + `--scope-key`), wired into the five print-only workflows. Verified against real data and against simulated truncation, emptiness, and rollover. |
> | 2.4 | New `scripts/lib/http.py`, promoted from the compliant `generate_current_members_data.py` implementation; **12** fetchers migrated (5 more than the review counted). 15 unit tests cover the policy. |
> | 2.5 | `update-curated-ga-bills` moved off the daily schedule to Tue/Thu, leaving at most two Open States jobs per day. |
>
> Two findings were corrected while fixing: the review's table of seven fetchers
> missed five more, including `generate_ga_members_data.py` — the *daily* Open
> States job, which retried 5xx only and so gave up immediately on a quota 429.
> And `update-ga-congress-trades.yml`'s validator read
> `metadata.tickersWithTrades`, a key that does not exist, so it had been
> printing `0` on every run.

### 2.1 — The push-retry loop swallows total failure

**Severity: High** · **15 workflows**, e.g. `.github/workflows/update-current-members.yml:78`,
`update-ga-members.yml:97`, `update-ga-votes.yml:60,78`, `update-ga-bills.yml:67`, `update-fec-data.yml:79`,
`update-federal-votes.yml:63`, `update-curated-ga-bills.yml:40`, `update-ga-campaign-finance.yml:85`,
`update-ga-congress-trades.yml:56`, `update-ga-executive-orders.yml:41`, `update-presidential-laws.yml:57`,
`update-scotus-decisions.yml:53`, `update-search-corpus.yml:59`, `update-vp-tie-votes.yml:53`

```bash
set -e
for attempt in 1 2 3; do
  git pull --rebase origin main && git push && break
  echo "Push attempt $attempt failed, retrying..."
  sleep 5
done
```

Verified empirically:

```
$ bash -c 'set -e; for a in 1 2 3; do false && true && break; echo "attempt $a failed"; done; echo rc=$?'
attempt 1 failed / attempt 2 failed / attempt 3 failed / rc=0
```

`set -e` does not fire inside an `&&` list, and the loop's last command (`sleep`/`echo`) exits 0. After three
failed rebases — the exact case this loop exists for, a concurrent workflow pushing to `main` — the step and the
job **succeed** while the freshly generated data is silently discarded.

**This defeats every validation improvement upstream of it.** Cheapest fix on the whole list.

**Fix:** `|| { echo "push failed after 3 attempts"; exit 1; }` after the loop, or a `pushed=1` flag with
`[ "$pushed" = 1 ] || exit 1`.

---

### 2.2 — No failure notification anywhere

**Severity: High** · all of `.github/workflows/`

```
$ grep -ln "failure()\|always()" .github/workflows/*.yml
(no matches)
```

Zero of 26 workflows have an `if: failure()` step, issue-filing action, or notification. Combined with
[2.1](#21--the-push-retry-loop-swallows-total-failure), a broken generator is invisible: the site keeps serving
last-good JSON and the Actions tab is the only signal. RECURRING-TASKS.md §0 documents the detection method as
"if one looks stale, check the Actions tab" — i.e. a human noticing.

**Corroborating but not conclusive:** `ga-member-votes.json` was last committed 2026-08-13, but `update-ga-votes`
runs Mondays 07:30 UTC and Monday 2026-08-17 has passed. That is *consistent with* a legitimate no-op run (closed
session), so it is not proof of failure — but nothing in the system distinguishes the two cases.

**Fix:** one reusable `if: failure()` step per workflow that opens/updates a dedup'd GitHub issue, or a single
scheduled staleness watchdog asserting each `metadata.generatedAt` is within its cadence — the watchdog catches
both hard failures *and* silent no-ops.

---

### 2.3 — Five workflows commit on validation that only prints

**Severity: High** · `update-ga-congress-trades.yml:31-41`, `update-scotus-decisions.yml:38-47`,
`update-vp-tie-votes.yml:38-47`, `update-presidential-laws.yml:38-49`, `update-federal-votes.yml:38-50`

CLAUDE.md: *"never commit based on JSON validity alone."* These steps load the JSON, `print()` a count, and exit 0
regardless:

```python
print(f'Validated: {tickers} tickers with trades, {trades} total trades, ...')
# ← no assert, no sys.exit
```

Two go further and explicitly downgrade the empty case to a warning:

```python
if count == 0:
    print('Warning: no laws found — Congress.gov API may be unavailable')
```

Given [2.4](#24--seven-fetchers-three-incompatible-retry-policies), a single transient 503 produces a truncated or
empty file that passes validation and gets committed. `update-fec-data.yml`, `update-ga-members.yml`,
`update-ga-bills.yml`, and both campaign-finance workflows show exactly the right pattern (count floors,
`metadata.count == len()`, structural checks, `sys.exit(1)`) — these five just never got the treatment.

**Fix:** count floors plus a generic "did this file shrink >20% vs. the committed version" delta check. The delta
check is dataset-agnostic and covers all five at once — and also retires
[5.1](#51--update-ga-bills-hardcodes-the-current-sessions-bill-count).

---

### 2.4 — Seven fetchers, three incompatible retry policies

**Severity: High** · CLAUDE.md: *"Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx."*

| Script:line | Retries 429? | Retries 5xx? | Note |
|---|---|---|---|
| `generate_current_members_data.py:41` | yes | yes | **compliant reference impl** |
| `generate_ga_bills_data.py:112` | yes | yes | compliant |
| `generate_ga_campaign_finance.py:81` | yes | yes | compliant |
| `generate_curated_ga_bills.py:42` | **no** | yes | `if e.code >= 500 and attempt < retries` |
| `generate_fec_data.py:71-80` | yes | **no** | non-429 `HTTPError` returns `None` immediately |
| `generate_ga_congress_trades.py:44` | **none** | **none** | single attempt, `return None` |
| `generate_federal_votes_data.py:70,85` | **none** | **none** | single attempt, `return None` |

The `generate_curated_ga_bills.py` gap is sharpest: it runs **daily against Open States**, whose
quota-exhaustion response is exactly HTTP 429 — the one status it refuses to retry. Its own comment at line 253
(`time.sleep(7)  # Open States rate limit is 10 req/min`) shows rate limiting was anticipated in one place and
missed in the other.

Every one of these returns `None` on failure and lets the caller continue with a partial dataset.

**Fix:** extract one `scripts/lib/http.py` with a single `fetch_json(url, headers, retries)` implementing the
documented policy; have all seven import it. A correct version already exists at
`generate_current_members_data.py:41` — this is promotion, not new design.

---

### 2.5 — Open States quota stacks three jobs into one Sunday-morning window

**Severity: Med** · `update-ga-members.yml:9`, `update-ga-bills.yml:11`, `update-curated-ga-bills.yml:9`,
`update-ga-votes.yml:12`

Verified consumers of `OPENSTATES_API_KEY`: `update-ga-members` (daily 07:00), `update-ga-bills` (Sun 07:30),
`update-curated-ga-bills` (daily 08:00), `update-ga-votes` (Mon 07:30), plus three dispatch-only `inspect-*` jobs.

On Sundays, three quota-consuming jobs fire inside 60 minutes against a shared 250 req/day budget, with no
coordination, no shared counter, and no guard checking whether an earlier job drained the key. Nothing reads a
remaining-quota signal. Failure mode: 429 → `None` → partial data → (for curated bills) a job that doesn't retry
429 at all.

RECURRING-TASKS §3 documents the worst case: a session changeover forces `generate_ga_bills_data.py` into a
~100+ page full pull that must be scheduled on a day nothing else uses the key — i.e. the quota conflict is
currently managed by human calendar discipline.

**Fix:** spread the crons across days (members daily; bills Sun; curated Tue/Thu; votes Mon), and have each Open
States generator write `metadata.requestsUsed` so a shared preflight can bail early with a clear message rather
than half-fetching.

---

## Tier 3 — Wrong joins, narrower blast radius

> **STATUS: 3.5 fixed on 2026-08-18** as a necessary part of
> [1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) — the tally is now
> derived from the de-duplicated roster. **All six fixed 2026-08-19.**

### 3.1 — Superior Court results: one race shows five other judges' totals; four show none

**Severity: Med** · `scripts/build_race_results_index.py:187-226` (`find_contests` candidate-name-overlap fallback)

Re-running the builder: 347/353 races matched, 6 unmatched.

- `_data/election_results/ga-primary-results.json` lumps **all five** Gwinnett Superior Court seats under one
  office label, `"Superior Court - Gwinnett Judicial Circuit"`. The name-overlap fallback attached that entire
  5-contest group to **`superior-court-gwinnett-hutchinson-2026`** — whose candidates are BT Gutter Parker /
  Ramona Toole / Regina Jeanette Matthews. That race page now renders Tracie H. Cason's 130,118 votes, Angela
  Duncan's 130,666, Tim Hamil's 128,268, and Tracey Mason's 129,755 as if they were its own. Meanwhile
  `superior-court-gwinnett-cason-2026`, `-duncan-2026`, `-hamil-2026`, and `-mason-2026` show **no results at all**.
- DeKalb: results label the seats `"(A. Jackson)"` / `"(L. Jackson)"`; `races.json` carries `Asha F. Jackson` /
  `LaTisha Dear Jackson`. Neither matches, so both Jackson races show nothing — while the sibling
  `superior-court-dekalb-johnson-2026` matches fine.

**Fix:** when a matched contest group contains more contests than the race has candidates, select the single
contest whose candidate set actually overlaps rather than attaching the group; require the winning overlap to
exceed the runner-up by a margin instead of accepting `best_score` ties; report near-misses rather than silently
emitting the mis-join.

#### ✅ FIXED — 2026-08-19

`race-results-index.json` regenerated: **347 → 353 of 353 races matched, 0 lost.** Exactly one previously-matched
race changed, and that is the mis-join itself.

| Race | Before | After |
|---|---|---|
| `superior-court-gwinnett-hutchinson-2026` | 7 candidates across 5 seats, incl. Cason's 130,118 | its own contest only: Matthews 74,667 / Parker 38,695 / Toole 20,906 |
| `-cason` / `-duncan` / `-hamil` / `-mason` | no results | 130,118 / 130,666 / 128,268 / 129,755 |
| `-dekalb-jackson-asha` / `-latisha` | no results | 143,551 / 143,736 |

Four changes:

1. **`narrow_group()`** drops contests in a group sharing no candidate with the race, so Gwinnett's five-seat
   group competes on the one seat that matches.
2. **The name fallback scores narrowed groups and requires a unique winner.** A tie is reported, not resolved by
   sort order — `(surname, initial)` is not unique within a section (courts holds a Robert Lane and a Roger Lane).
3. **The `best_score >= 2` bar now also accepts a match covering the race's whole ballot.** An uncontested
   judicial seat has one name to match on, so requiring two guaranteed those races could never match — which is
   why all four uncontested Gwinnett seats showed nothing.
4. **A surname-only tier** for `Richard Timothy Hamil` (races.json) vs `Tim Hamil` (state results), where even the
   first initial drifts. Restricted to a single-candidate race whose surname appears in exactly one contest in the
   expected section, and where that contest is itself uncontested.

Near-misses are now printed. Two are currently rejected, both correctly: `ga-14-2026` matching 1 of 10 candidates
against District 13, and `ga-house-41-2026` matching a bare surname into a contested District 117 race.

**One design correction during the work.** Narrowing was first applied to exact-office matches too, which silently
dropped legitimate results from 22 races — `ga-house-12-2026` lost its Republican primary entirely because
races.json carries `James E Lumsden` while the state reports `Eddie Lumsden`. An exact office label identifies the
seat, so its group is authoritative regardless of name drift; narrowing is now confined to the name fallback,
where group membership is genuinely in doubt. The before/after diff is what caught it.

**Verified in the browser:** the Hutchinson page's "Earlier This Cycle" tab renders only its own three candidates
and mentions none of the other four judges; Cason's renders 130,118 unopposed. No console errors.

---

### 3.2 — Four GA statewide executives are indexed as "GA Legislator"

**Severity: Med** · `scripts/generate_search_corpus.py:80-110` (missing chamber filter at :93)

`ga-members.json` contains **a fifth chamber value not in the CLAUDE.md schema: `"executive"`** (4 members).
`build_ga_legislators()` filters on `status` and OCD-id shape but never on chamber.

`search-entities.json` contains, verbatim:

```json
{"title":"Brian Kemp","desc":"Governor, Republican","category":"GA Legislator","url":"ga-member.html?id=ocd-person%2F600e5c48-..."}
```

plus Burt Jones (`Lt_Governor` — the raw enum leaking into the UI), Chris Carr, and Brad Raffensperger. All four
are *also* correctly indexed as `GA Executive → ga-executive.html`, so search shows the Governor twice, once
under the wrong category pointing at a legislator detail page. `metadata.categories["GA Legislator"] = 237` vs
232 actual sitting legislators. The `add()` dedupe key is `(title, url)`, so differing URLs never collapse.

`ga.js:111` and `ga-majority-tracker.html:448,501` filter by exact chamber string, so only the search index leaks.

**Fix:** `if chamber not in ("Senate", "House of Representatives"): continue` at :93. Add `"executive"` to the
documented chamber enum in CLAUDE.md.

#### ✅ FIXED — 2026-08-19

`build_ga_legislators()` now skips any member whose chamber is not in `VOTING_CHAMBERS`, imported from
`scripts/lib/ga_voters.py` so "is a legislator" has one definition rather than a fourth copy.

`search-entities.json` regenerated: **1,381 → 1,377 records, GA Legislator 237 → 233.** The diff is exactly the
four executives removed and nothing added. All four remain findable under `GA Executive` (and as `Candidate`
where they are on a 2026 ballot), and `Lt_Governor` no longer appears anywhere in the index.

**The count discrepancy had a second, benign half.** 233 is not 232: Sharon Henderson (House 113) carries
`status: "Suspended"`, and `ga.js:136-139` and `ga-majority-tracker.html:353` both keep suspended members and
badge them, because they still hold the seat. Indexing her is correct, and the generator's claim to use "the same
filter as ga.js" holds. Only the executives were wrong.

**Verified in the browser:** searching "kemp" now returns RaShaun Kemp — a genuinely different sitting senator —
as the only `GA Legislator`, with Brian Kemp appearing solely as `GA Executive`. Burt Jones returns Candidate +
GA Executive; Chris Carr returns GA Executive only. Jan Jones and the suspended Sharon Henderson are still
indexed as legislators. No console errors.

CLAUDE.md's `ga-members.json` schema now documents `"executive"` as a fifth chamber value, with a warning that
anything meaning "member of the General Assembly" must filter on chamber, plus the `status` semantics that
distinguish a historical record (`Resigned`/`Removed`/`Deceased`) from a seated-but-suspended member.

---

### 3.3 — `_mergeInto` in the trades generator merges trades but not the counters

**Severity: Med** · `scripts/generate_ga_congress_trades.py:197-208`

The merge extends `trades` and recomputes `tradeCount = len(trades)`, but never sums `purchases`, `sales`,
`lateFilings`, or `estVolume` from the merged filer.

**Michael A. Collins** (the one member with an active `_mergeInto`, `house_michaela_collins_jr → house_michaela_collins`):

| Field | Published | Actual (counted from `trades[]`) |
|---|---|---|
| `tradeCount` | 42 | 42 ✓ |
| `purchases` | **18** | 34 |
| `sales` | **5** | 8 |
| `estVolume` | **$306,511.50** | covers ~23 of 42 trades |

`ga-congress-trades.html:482-508` renders `estVolume` and `tradeCount` on the member card, so his card shows 42
trades beside a volume figure omitting 19 of them. The other four members reconcile.

**Two latent bugs in the same file:**

- **`:194`** — `total_trades -= by_member.get(member_name, {}).get('tradeCount', 0)` runs **after**
  `del by_member[member_name]` on `:193`, so the subtraction is always 0 and `metadata.totalTrades` would
  over-report on any exclusion. Not yet visible: both `_exclude` targets (Graves, Greene) are absent from the
  source, so `561` is currently correct.
- **`:26-40`** — `load_bioguide_by_last_name()` builds a **surname-only** `lastName → bioguideId` map with
  last-write-wins. This is the exact bug `generate_fec_data.py:227-234` documents having fixed ("two
  Representatives named Scott… stamped one bioguide onto every Scott"). Safe today only because GA-13 is vacant;
  it returns the moment the delegation seats a second Scott / Collins / Williams. `:156` also derives the surname
  as `name.split()[-1]`, yielding `"jr"` for any `"… Collins Jr"` filer.

**Fix:** recompute all counters from the merged `trades[]` after merging; move the `total_trades` subtraction
before the `del`; key the bioguide map on `(state, district, lastName)` as the FEC generator does.

#### ✅ FIXED — 2026-08-19 · one sub-claim corrected, one hazard found in the fix

`derive_counters()` computes `tradeCount`, `purchases`, `sales`, `lateFilings` and `estVolume` from the trade list
at build time and again after any merge, so every number on a card describes the trades published beside it.
Michael Collins: **purchases 18 → 34, sales 5 → 8, estVolume $306,511.50 → $458,521.00**; his card now reads
"42 trades · 2 late · $0.5M".

Deriving is verified, not assumed: against the four unmerged members, `purchases`, `lateFilings` and `estVolume`
reproduce the upstream figures **exactly**. `sales` does not — upstream reports 8 for Earl Carter against 14 sale
transactions, 48 for Austin Scott against 54, 130 for Richard Allen against 131. That field was unreliable
upstream and is now computed here; `report_counter_drift()` logs each divergence on every run rather than hiding it.

**Sub-claim corrected — the `total_trades` bug is dead code, not an over-count.** The subtraction does run after
the `del`, but `total_trades` is *recomputed* from `by_member` immediately after the override loop
(`total_trades = sum(len(m['trades']) ...)`), so the stale line never reached the output. `metadata.totalTrades`
was already correct. The line is removed and the recompute documented in its place.

**The bioguide fix went the opposite way from the recommendation, and the data is why.** Keying on district
looked stronger, so I built it that way first — and it linked Collins' trades to **Austin Scott's** profile. The
upstream filer index is wrong about office: it lists Richard McCormick (GA-07) as **"NY-01"** and Michael Collins
(GA-10) as **"GA-08"**, which is Scott's seat. Surname is now primary, with every match retained so an ambiguous
surname is *detected*; district is consulted only to break a tie among same-surname members. A wrong `office` can
now only fail to disambiguate, never mis-resolve. `filer_surname()` also strips generational suffixes — the old
`name.split()[-1]` returned `"jr"` for the very filer being merged, `Michael A. Collins Jr`.

**Verified:** `scripts/test_ga_congress_trades.py`, 52 assertions — every published member self-consistent with
its own trades, every bioguide link resolving to the matching surname, and explicit cases for the wrong-office
strings above. Regenerated live: all five links unchanged and correct, `metadata.totalTrades` equal to the summed
trade lists. In the browser, all five profile links point at the right member and there are no console errors.
(McCormick's larger swing — 87 → 113 trades — is fresh upstream data from the same run, not this change.)

---

### 3.4 — Party-line badges run on an 82%-complete roster and never trip their own warning

**Severity: Med** · `scripts/enrich_bills_with_party_votes.py:94-105` · `ga-bills.html:476`

Coverage across all 2,223 enriched votes:

| min | p10 | median | mean | **max** |
|---|---|---|---|---|
| 0.7857 | 0.7857 | 0.8214 | 0.8212 | **0.8500** |

2,223 / 2,223 fall below 0.9; 515 below 0.8; **0 below the `COVERAGE_WARN_THRESHOLD = 0.5`**. The red "too
incomplete for a party-line call" branch (`ga-bills.html:512`) is therefore **unreachable**, and every bill instead
gets the gray hedge — displayed beside official totals it contradicts by ~18%.

Contributing: `ga-members.json` has 3 members with `party: null`, whose votes are dropped from every tally by
`enrich_bills_with_party_votes.py:80`.

**Fix:** raise the threshold to ~0.9 (or suppress the ⚡ badge whenever coverage < 0.95) — which, given the
measured distribution, effectively means "suppress until [1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) is fixed and the data regenerated."

#### ✅ FIXED — 2026-08-19 · a threshold was the wrong instrument

**Coverage can never reach 100%, so no threshold is safe.** Votes cast by members who have since left the
legislature sit in the roll call but carry no party in `ga-members.json`, so they can never be tallied. Measured
ceiling after the 1.5 regeneration: **max 0.9889, median 0.9107, and 0 of 2,145 votes at 1.0.** A 0.95 cutoff
would suppress **80.7%** of votes and a 0.90 cutoff 36.2% — deleting the feature rather than qualifying it, which
is precisely what the existing code comment warned about when it chose 0.5.

**What matters is whether the missing votes could change the answer.** `computePartyLineInfo()` calls a vote
party-line when the two parties' *majorities* went opposite ways, so a party's direction only flips if the
unaccounted votes outnumber its margin. `partyLineIsSound()` now tests exactly that: the tag is shown only when
both `|yea − nay|` margins strictly exceed the unaccounted count.

Measured over the real data — **390** votes whose parties split opposite ways:

| Rule | Tag kept | Tag withheld |
|---|---|---|
| Old (`coverage < 0.5`) | 390 | 0 |
| Flat 0.95 threshold | ~74 | ~316 |
| **Margin-aware** | **366** | **24** |

The 24 withheld are the genuinely uncertain ones, and the page now says why instead of showing a bare percentage:
`Dem 4-5 · Rep 25-0 (yea-nay by party; 89% of the official tally — 6 unmatched votes, too close to call
party-line)` — a Democratic margin of 1 against 6 unattributed votes. `Dem 22-0 · Rep 13-16` is withheld on a
Republican margin of 3 against 5. Both previously carried a confident ⚡.

`enrich_bills_with_party_votes.py` now emits `partyTallyTallied` and `partyTallyOfficial` alongside the ratio,
since reconstructing the gap from a rounded coverage loses the precision the comparison depends on. The old
threshold survives at **0.75** for its stated purpose only — catching a roster that is actually broken by a future
matching regression. It fires on 0 votes today.

**One sub-claim corrected:** the 3 members with `party: null` are all `status: "Vacant"` placeholder entries with
synthetic non-OCD ids. Vacant seats cast no votes, so they never appear in a roster and contribute nothing to the
shortfall.

**Verified:** 10 assertions running the page's own extracted functions over the real `ga-bills.json`, including
the boundary cases (margin equal to unmatched → withheld; margin one greater → shown) and the fallback for older
records lacking exact counts. In the browser, 10 tags shown and 3 withheld with the explanatory wording on the
first screen; no console errors.

#### 🐞 A DEFECT FOUND WHILE VERIFYING — full refresh replaced instead of merging

The 2026-08-19 `FULL_REFRESH=1` run left `ga-member-votes.json` at **2,145 roll calls, down from 2,223**. That is
not quota truncation being carried forward honestly — it is data loss, and the advice to "re-run full_refresh
until it completes" was wrong on both counts:

- **A full refresh cannot complete.** `incremental_since()`'s own docstring says so: the session is ~274 pages
  against a 250/day quota shared with every other Open States job. Every run ends early by design.
- **It did not merge.** `was_incremental = bool(since and prior_votes)`, and `FULL_REFRESH` sets `since = None`,
  so `merge_votes()` was skipped entirely. One day's quota therefore *replaced* the accumulated baseline with
  whatever it reached — discarding 78 roll calls and leaving 78 `passageVotes` in `ga-bills.json` carrying
  tallies from the previous enrichment.

Repeating the run would not have recovered them; it would have re-fetched the same leading pages and truncated
again. Adding the `full_refresh` input to the workflow put that one click away.

**Fixed:** the merge now runs whenever a baseline exists **for the same session**, full refresh included, so a
partial full refresh is additive — old roll calls are re-processed under current resolution logic and anything the
run did not reach is retained. A session changeover still bypasses the merge, which is the one case where the
prior file genuinely must not be carried forward.

**Recovered:** the pre-refresh file was still in git at `10e5ae5~1`. Merging the current data over it — using the
generator's own `merge_votes` + `sanitize_member_votes`, offline — restores **2,223 roll calls while keeping the
improved 235-member resolution**. Re-running the enrichment then produced **2,223 enriched votes with 0 stale
records**, up from 2,145 enriched + 78 stale.

The 1.5 gain is intact throughout: `surnameResolved: 22,722`, `ghostVoterIds: 0`, legislators with no voting
history **39 → 8** (the same 8 identified in 1.5: the split-voting Andersons, two members seated after the votes,
and four absentees).

**Still worth doing, but not urgent:** `paginationComplete` remains false, which is the normal steady state for
this dataset and is reported honestly in metadata. Ordinary weekly incremental runs keep it fresh; a full refresh
is only worth running after a *resolution-logic* change, and now that it merges, running one is safe.

---

### 3.5 — `curated-ga-bill-votes.json` party tallies double-count a duplicate voter row

**Severity: Med** · `scripts/generate_curated_ga_bills.py:136-141`

`member_votes[voter_id] = option` is a dict (so a repeated voter dedupes), but `party_tally[party][bucket] += 1`
executes once **per row** in the same loop. A duplicated voter row inflates the tally without inflating the roster.

**Every one of the 9 Senate roll calls has `sum(partyTally) = len(memberVotes with a party) + 1`:**

| Bill | Chamber | Roster | partyTally sum | Roster w/ party |
|---|---|---|---|---|
| SB 443 | senate | 48 | **49** | 48 |
| SB 116 | senate | 48 | **49** | 48 |
| HB 1009 | senate | 47 | **48** | 47 |
| HB 68 / HB 111 / HB 112 | senate | 50 | **51** | 50 |
| SB 233 / SB 189 | senate | 50 / 50 | 47 / 47 | 46 / 46 |

The House rows also show the [1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) loss:
SB 233 house roster 151 → tally 134 (17 ghost/no-party voters); SB 189 house 152 → 135.

**Fix:** build the tally from `member_votes` after the loop, not inside it.

#### ✅ FIXED — 2026-08-18 (with [1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote))

`build_vote_record()` now derives `partyTally` from the de-duplicated `member_votes` mapping after the
loop. This came along with 1.5 out of necessity rather than convenience: once a ghost id can resolve onto
a member who is already in the roster, per-row counting is wrong in a second, worse way.

`update-curated-ga-bills.yml` now asserts no roll call's tally exceeds its own roster. Run against the
current data that assertion flags **7** Senate roll calls (SB 443, SB 116, HB 1009, HB 1193, HB 68,
HB 111, HB 112), each exactly one over — the signature of the duplicated voter row. It reads 0 once the
file is regenerated. Unit-covered by `scripts/test_ga_voter_resolution.py` (duplicate row collapses;
tally equals roster, not row count).

---

### 3.6 — `generate_ga_members_data.py` emits empty strings where the schema says `null`

**Severity: Med** · `scripts/generate_ga_members_data.py:146,190`

```python
email   = next((o.get('email', '') for o in offices if o.get('email')), '') or raw.get('email', '') or ''   # L146
'imageUrl': raw.get('image') or '',                                                                          # L190
```

Measured in the committed output:

```
assets/data/ga-members.json      {'imageUrl': 7, 'email': 2}
assets/data/current-members.json {}
assets/data/races.json           {}
```

Violates CLAUDE.md's rule stated three separate times (*"Use `None` for missing optional fields — never empty
strings"*, and again under Enforcement), and contradicts CLAUDE.md's own `ga-members.json` schema. It is the only
generator that does this. Downstream JS testing `if (m.imageUrl)` still works, but `=== null` checks and any
JSON-schema validation would not.

**Fix:** replace the trailing `or ''` with `or None` at both lines.

#### ✅ FIXED — 2026-08-19

Fixed, and widened slightly: the same defect sits on **five** optional fields, not two. `phone`, `address` and
`officialWebsiteUrl` were written the same way — they just happen to be populated for all 250 current members, so
the audit that counted committed values couldn't see them. Leaving them would have made this recur the first time
a member arrived without a phone number.

`scripts/generate_ga_members_data.py` now emits `None` for all five:

```python
phone   = next((o.get('voice')   for o in offices if o.get('voice')),   None)
address = next((o.get('address') for o in offices if o.get('address')), None)
email   = next((o.get('email')   for o in offices if o.get('email')), None) or raw.get('email') or None
website = None                                    # link-fallback initialiser
'imageUrl': raw.get('image') or None,
```

The `next(...)` calls already guarded on truthiness (`if o.get('voice')`), so an office carrying a blank string is
skipped rather than selected — verified against a synthetic record whose first office has `voice`/`address`/`email`
all `''`: phone correctly falls through to the second office, address and email come back `None`.

**Committed data normalised to match.** The generator needs an API key, so rather than leave the file disagreeing
with the code until the next scheduled run, the 9 affected values were converted in place. The diff is exactly
9 lines, all `""` → `null`. The next workflow run is now a no-op on these fields instead of an unexplained diff.

**Verified no consumer breaks.** Every reader of these five fields tests truthiness, which treats `''` and `null`
identically:

| Consumer | Pattern |
|---|---|
| `ga-member.html:551,606-610` | `member.imageUrl ? … : ''` — all five fields |
| `scripts/build_legislative_races.py:259,300,445` | `if member.get("imageUrl")` |
| `scripts/build_candidate_claim_links.py:126` | `cand.get("email") or ""` |
| `.github/workflows/update-ga-members.yml:57` | checks `field in m`, not the value |

`scripts/inspect_openstates_fields.py:61` also reads `email`, but from the raw API response, not from our JSON.

Post-fix scan of `ga-members.json`: **no empty-string value on any field, on any of the 250 members.**

---

## Tier 4 — UX, IA, and accessibility

### 4.1 — Wide data tables have no overflow container

**Severity: High on mobile**

Only four wrappers exist site-wide (`ga-congress-trades.html:109`, `race.html:261`,
`ga-majority-tracker.html:113,185`). Unwrapped:

- `member.html:878` `.vote-table` — Date / Bill / Motion / Vote, bill titles untruncated
- `ga-member.html:1105` `.vote-table` — same four columns
- `member.html:652` and `candidate.html:592` `.employers-table`
- `ga-executive-orders.html:130` `.order-table` (mitigated — `:122` hides column 2 under the breakpoint)

At 375px the vote tables force the **whole page body** to scroll horizontally, dragging the nav and every other
element sideways. These sit on the two most-visited detail pages on the site.

**Fix:** `<div class="table-wrap">` with `overflow-x:auto` around each, matching `race.html:261`.

#### 🔁 SYMPTOM REAL, CAUSE WRONG — FIXED 2026-08-19

The sideways-scrolling page is real, but **the tables are not causing it, and they are not unwrapped.** Both halves
of the diagnosis were wrong, and the proposed fix would have changed nothing.

**The tables already have an overflow container.** The theme sets it globally, on the bare element:

```css
/* assets/css/beautifuljekyll.css:835-838 */
table { padding: 0; overflow-x: auto; display: block; }
```

`display:block` + `overflow-x:auto` is the standard way to make a table its own scroll container, and none of the
four page-level rules (`.vote-table`, `.employers-table`, `.order-table`) override `display` or `overflow`. Measured
in the browser at 375 px, with the tab panels opened so the tables actually lay out:

| Table | clientW | scrollW | Behaviour |
|---|---|---|---|
| `ga-member.html` `.vote-table` (1,219 rows) | 311 | 314 | scrolls internally ✅ |
| `member.html` `.vote-table` (70 rows) | 311 | 311 | fits ✅ |
| `member.html` `.employers-table` | 311 | 311 | fits ✅ |
| `ga-executive-orders.html` `.order-table` (221 rows) | 345 | 382 | scrolls internally ✅ |

`ga-executive-orders.html` and `candidate.html` never overflowed the body at all (`documentElement.scrollWidth`
== `clientWidth` == 375 on both, before any change).

**`member.html` did not overflow either** — contradicting "these sit on the two most-visited detail pages". Only
`ga-member.html` did: body `scrollWidth` **454** against a 375 viewport.

**The actual cause.** `#pageLayout` sets `align-items: flex-start`, and the mobile media query only flipped the
direction:

```css
#pageLayout { display: flex; gap: 1.5rem; align-items: flex-start; }
@media (max-width: 700px) { #pageLayout { flex-direction: column; } }   /* align-items still flex-start */
```

In a **column** flex container, `align-items: flex-start` sizes children to their *content* width instead of
stretching them to the container. So `#memberDetails` sized to its **min-content** — the widest unbreakable token
in it. That token is the official-website link, which renders the raw URL as its own link text:

```
https://www.legis.ga.gov/members/senate/754     → 439 px, unbreakable
```

Isolated in the live page: forcing that one link to wrap dropped `#memberDetails` from **439 px → 348 px**, and
setting `align-items: stretch` alone dropped `documentElement.scrollWidth` from **454 → 375**. Both confirm the
flex/URL pair, not the tables.

Why `member.html` escaped: federal website URLs are short (`https://mccormick.house.gov`, 27 chars) and fit. The
same latent bug is in that file verbatim — it just has no long enough URL to trip it yet.

**The fix**, applied to `ga-member.html` and `member.html`:

```css
.url-text { overflow-wrap: anywhere; }              /* the raw-URL link, new class */
#memberDetails { … overflow-wrap: break-word; }     /* last-resort guard for any long token */
@media (max-width: 700px) {
  #pageLayout { flex-direction: column; align-items: stretch; }
}
```

`align-items: stretch` is the structural half — it clamps the stacked column to the viewport, so *any* future wide
child scrolls or wraps inside instead of widening the page. The wrap rules are the content half.

**Verified after the change**, at 375 px with the voting-history tab open:

| | `ga-member.html` | `member.html` |
|---|---|---|
| body overflows | **no** (375 == 375) | no |
| `#memberDetails` | 345 px (was 439) | 345 px |
| URL link | wraps to 2 lines | 1 line, unchanged |
| `.vote-table` | 311 / 314, scrolls internally | 311 / 311, fits |

**Desktop regression check at 1280 px:** `flex-direction: row`, `align-items: flex-start` still in force, sidebar
still top-aligned rather than stretched to the full column height, URL on one line, no overflow. The media query
scopes the change to ≤700 px, so nothing above the breakpoint moved.

Side benefit: `#stateSidebar` now stretches to the full 345 px on mobile instead of shrink-fitting to 207 px.

**No `table-wrap` divs were added** — they would have been redundant with the theme rule.

---

### 4.2 — House hemicycle seats are keyboard-unreachable and party is color-only

**Severity: High (a11y)** · `ga-majority-tracker.html:520-545`

Each seat is an SVG `<circle>` created via `svgEl()` with `fill: COLOR[party]` (`:340`) and a `click` listener —
no `tabindex`, no `role`, no key handler. The member name and the **"View 2026 race →" link live inside a hover
tooltip** (`:536`), so that link is unreachable by keyboard *or* touch. Party is conveyed purely as red/blue fill
on a 9px circle. Fails WCAG 1.4.1 (use of color) and 2.1.1 (keyboard). The `aria-label` on the `<svg>` at `:259`
describes the chart but exposes none of the 180 seats.

**Fix:** render each seat as an `<a>` wrapping the circle (the Senate side already does something equivalent),
give the circle a `<title>` child naming the member *and party word*, add a shape or hatch difference between D
and R, and move the race link out of the tooltip.

#### ✅ FIXED — 2026-08-19 · both chambers, both failure modes

Applied as prescribed for the House hemicycle, and the same fixes carried to the Senate grid, which had the
identical color-only problem (the finding only named the hemicycle).

**Keyboard + the trapped link (WCAG 2.1.1).** Each of the 180 hemicycle seats is now an SVG `<a>` with a `<title>`
child — focusable, and named `District 1, Mike Cameron, Republican` rather than exposing nothing. The
`View 2026 race →` link that lived *inside the hover tooltip* (unreachable by keyboard or touch) is gone: a
filled seat links to the member page, which already carries a "View … race" banner for seats up this cycle, and a
vacancy links straight to the race. Verified in-browser: **180 seat links, tooltip HTML contains no `<a>`**, focus
grows the seat the same way hover does (`focusin`/`focusout` added alongside the mouse handlers).

**Color-only (WCAG 1.4.1).** Party is now carried by **shape, not just fill**: Democrats are circles, Republicans
squares, vacancies hollow. Measured on the live chart: **81 circles + 99 rects = 180**, one hollow vacancy, and the
counts reconcile (80 D + 99 R + 1 V). The Senate grid gets a party glyph (`D`/`R`/`—`) in the seat corner plus a
real `aria-label`, so it no longer leans on its background color or a bare surname. The legend marks mirror the seat
shapes (`.dot-square`, `.dot-hollow`).

The chamber-switch bar was the tenth tab UI on the site; it is wired through the shared enhancer from 4.7.

---

### 4.3 — `justice.html` contains zero heading elements

**Severity: High (a11y)** · verified: `grep -c "<h[1-6]" justice.html` → **0**

The layout is `default`, which never includes `header.html`, so nothing auto-renders a title. The justice's name
is a styled `<div>` inside the JS at `:380`. A screen-reader user gets a page with no structure at all — no
`<h1>`, no landmarks. This is the only page on the site in this state, and it was flagged on 8/13.

Also at `:404`: `content.innerHTML = \`<p style="color:#c00;">${err.message}</p>\`` — raw error text injected
unescaped as the only failure state.

**Fix:** wrap the profile name in `<h1>`, section titles in `<h2>`; replace `err.message` with a user-facing
string plus a "← Supreme Court" link.

#### ✅ FIXED — 2026-08-19 · and an unescaped-injection sink closed with it

Done as prescribed, plus the security half the "Also at :404" note pointed at turned out to be two sinks, not one.

**Headings.** The justice name is now an `<h1>`; each tab panel opens with an `sr-only` `<h2>` (Voting Record /
Biography) so the structure exists for a screen reader without visually duplicating the tab labels. `grep -c "<h[1-6]"
justice.html` went **0 → 5**; in-browser the outline reads H1 → two H2s, exactly one H1.

**The error path was an XSS sink, in two places.** `content.innerHTML = \`<p>${err.message}</p>\`` was the one the
finding named, but the not-found branch was worse: `Justice not found: <code>${id}</code>` reflected the **raw URL
`id` parameter** unescaped. A single shared `showError()` now renders a fixed heading, a static message, a
`role="alert"`, and a "← Back to the Supreme Court" link — no interpolation of `err.message` or `id`. Verified by
loading `?id=<img src=x onerror=alert(1)>`: **0 `<img>` elements injected**, message is the static string. The page
had no `escHtml` helper at all; added one and applied it to every interpolated profile field (name, title,
appointed-by, law school, home state, image alt) while there.

The Voting Record / Biography tab bar is wired through the shared enhancer from 4.7.

---

### 4.4 — No footer navigation; three orphan pages with zero inbound links

**Severity: High (IA)** · `_includes/footer.html`

The footer still renders only social icons + copyright. With 14 navbar destinations against ~35 pages, everything
else depends on a single inbound link — and these have none:

| Page | Status |
|---|---|
| `local-officials.html` | Zero inbound links anywhere. No `sitemap: false`, no `noindex` — so `jekyll-sitemap` publishes it and site search indexes it. Its own comment (`:8-13`) says it's unfinished. |
| `results-latest.html` (`/results/latest/`) | Zero inbound links. Has `sitemap: false`, so it is invisible to crawlers *and* users — the maintenance-free election-night pointer is unreachable. |
| `ga-general-2026-*-results.html` | Not in `election_archive.yml` — see [1.4](#14--ga-general-2026-results-is-live-and-reports-every-candidate-at-0-votes). |

**Fix:** three-column footer sitemap (Representatives / Elections / Government / About). Point the elections-hub
"Election Results" CTA (`elections-hub.html:118`) at `/results/latest/` with `/results/` secondary. Add
`sitemap: false` + `<meta name="robots" content="noindex">` to `local-officials.html` until it launches.

#### ✅ FIXED — 2026-08-19 · two of the three sub-fixes, per owner direction

**Footer sitemap — built.** New `_includes/footer-sitemap.html`, rendered above the social icons in
`_includes/footer.html`, so every page now links to every primary destination. Four columns
(Representatives / Elections / Government / About), **21 links**, wrapped in `<nav aria-label="Site map">` with an
`<h2>` per column. All internal links go through `relative_url` (finding 4.9). Styled with the theme's existing
footer colour tokens; **4 columns ≥768px, 2 on mobile**, no horizontal overflow.

Verified in-browser: all 21 links resolve **200** (fetched each), grid collapses 4→2 at the mobile breakpoint, and
the include renders on ordinary pages *and* on the results pages via the shared layout.

**The `results-latest` orphan — fixed, by a different route than proposed.** The finding suggested repointing the
elections-hub "Election Results" CTA at `/results/latest/`. Instead the footer now carries a **"Latest Results"**
link (→ `/results/latest/`) on *every* page, which reaches the pointer from everywhere rather than from one card,
and leaves the hub CTA pointing at `/results/` (the full index) where "browse all results" is the better landing.
Confirmed `/results/latest/` still redirects to the newest archived election — today
`/ga-special-2026-results/` — and that its `sitemap: false` is intact (absent from the built `sitemap.xml`), so it
stays crawler-invisible while being user-reachable.

**`local-officials.html` — left exactly as-is, per owner.** The page is unlisted on purpose while its candidate
data is built out. Per direction, no `noindex` / `sitemap: false` was added and it is **not** linked from the
footer — so the "publishes it to the sitemap / indexes it" observation stands by choice, not oversight. When it
launches, add its footer link (and drop any interim `noindex` if one is later chosen).

**`ga-general-2026-*-results` — already handled under [1.4](#14--ga-general-2026-results-is-live-and-reports-every-candidate-at-0-votes)**
(preview status + `noindex`), so untouched here.

---

### 4.5 — `elections.html` shows a false "Open Seat" badge

**Severity: Med** · `elections.html:441` vs `:336`

```js
${race._note ? `<span class="phase-badge phase-open-seat">Open Seat</span>` : ''}
```

The badge fires on `race._note` being merely truthy; the filter checkbox at `:336` uses the correct test,
`race._note.toLowerCase().startsWith('open seat')`. In `races.json` today exactly one race has a
non-open-seat note — *"Clay Fuller (R) won the April 2026 special election and is the incumbent"* — so that race
is labeled **Open Seat** in the list while being excluded by the "Show open seats only" filter. Contradictory,
and factually wrong about an incumbent.

**Fix:** use `isOpenSeat(race)` at `:441`.

#### ✅ FIXED — 2026-08-19 · and the same bug found on `race.html`

Confirmed exactly as described, and the audit missed the worse instance: **`race.html:694` has the identical loose
test**, and it renders a full banner rather than a small badge. Before the fix, `race.html?id=ga-14-2026` read:

> **Open Seat** — Clay Fuller (R) won the April 2026 special election and is the incumbent running for a full term.

A single sentence contradicting its own label, on the race's own detail page.

Reproduced in the browser before the fix, U.S. House tab under the General phase: **5 rows badged "Open Seat", but
"show open seats only" returned 4** — District 14 carried the badge and was dropped by the filter.

**Both fixed, plus the data that was being thrown away.** `elections.html:441` now calls the existing
`isOpenSeat(race)`. `race.html` gets the same prefix test — but rather than simply suppressing a non-open-seat note
(which would have silently discarded a true and useful fact about the race), it renders it as a neutral aside:

```js
const rawNote    = race._note || '';
const isOpenSeat = rawNote.toLowerCase().startsWith('open seat');
const noteText   = rawNote.replace(/^open seat\s*[—–-]+\s*/i, '');
const openSeatHtml = !noteText ? ''
  : isOpenSeat
    ? `<div class="open-seat-banner"><span class="open-seat-label">Open Seat</span><span>${noteText}</span></div>`
    : `<div class="race-note">${noteText}</div>`;
```

`.race-note` is a new neutral grey variant of the existing orange `.open-seat-banner`, with no label.

**Verified after the fix:**

| Check | Result |
|---|---|
| `race.html?id=ga-14-2026` | no open-seat banner; note shown as a neutral aside ✅ |
| `race.html?id=ga-01-2026` (a real open seat) | orange banner intact, "Open seat — " prefix still stripped ✅ |
| badge count vs filter count, all 6 office tabs | agree on every tab (5/5, 0/0, 4/4, 7/7, 19/19, 6/6) ✅ |
| every row surviving the filter | badged ✅ |

Badge total reconciles exactly against the data: **41 badged under the General phase + 1 (`ga-13-special-2026`)
under the Runoff phase = 42**, matching the 42 `_note` values that begin "open seat" out of 43 total.

---

### 4.6 — `race.html` hardcodes the cycle in the page title

**Severity: Med** · `race.html:766`

```js
document.title = `${raceTitle} — 2026 Elections`;
```

Two lines later at `:783` the template already renders `${race.cycle} Election Cycle` from the data. Every shared
race link and browser tab will say "2026" through 2028.

**Fix:** `— ${race.cycle} Elections`.

#### ✅ FIXED — 2026-08-19 · plus one more hardcoded cycle in the same file

Confirmed and applied verbatim. Then swept the file for the same class of defect and found a second one the audit
missed — `race.html:464`, in the campaign-finance disclaimer:

```js
${race.level === 'federal' ? '' : ' or filed before the 2026 PeachFile records begin'}
```

Same failure mode, and `race.cycle` was already in scope at that line. This one also contradicted the module it
describes: `assets/scripts/campaign-finance.js:373,383` already derives its cycle label from
`data.metadata.cycle` rather than hardcoding. Both now read from the data.

`race.html` no longer contains a hardcoded cycle anywhere — the only remaining `2026` strings in it are inside the
comments added by [4.5](#45--electionshtml-shows-a-false-open-seat-badge).

**Not changed, and why:** `elections.html:8` `<h1 id="pageTitle">2026 Georgia Elections</h1>` is only the pre-JS
placeholder — `:303` overwrites it with `fillTemplate(meta.title, iso)` from the data on load. The Jekyll front
matter `title:` / `share-description:` at `:3,5` genuinely are hardcoded, but those are page metadata rather than
render logic and belong with the other per-cycle items in `RECURRING-TASKS.md`.

Because every race in `races.json` is cycle 2026 today, this fix is invisible in the current output by design —
verified instead by reading `race.cycle` (int `2026`) through to the rendered title on `ga-14-2026` and
`ga-01-2026`, and by confirming no literal cycle remains in the file.

---

### 4.7 — Zero ARIA on every tab implementation on the site

**Severity: Med (a11y)**

```
$ grep -rn 'role="tab"\|aria-selected\|aria-controls' *.html _layouts/*.html
(nothing)
```

Six independent tab UIs — `ga-state-reps.html:127`, `elections.html:169`, `federal-reps.html`, `ga-bills.html`,
`race.html:769`, `_layouts/election_results.html:126` — are real `<button>`s (so focusable), but a screen reader
announces six unlabeled buttons and never says which is selected or what it controls.

**Fix:** `role="tablist"` on the bar; `role="tab" aria-selected aria-controls` on the buttons; `role="tabpanel"
aria-labelledby` on the panels. Best done once in a shared component.

#### ✅ FIXED — 2026-08-19 · shared enhancer, and it was ten bars, not six

Done as the "shared component" the fix suggested — `assets/scripts/a11y-tabs.js`. The count was higher than the six
listed: `justice.html` (missed — see 4.3) and `ga-majority-tracker.html`'s chamber switch (missed — see 4.2) bring it
to **ten**, and two of the six (`member.html`, `race.html`) build their bars *at runtime* from data, so a static
`role="tab"` in the source would not have covered them.

**Why an enhancer, not hand-edited attributes.** The ten bars use five different class conventions
(`tab-btn`/`active`, `bills-tab`/`active`, `tab-btn`/`tab-active`, `race-tab-btn`/`active`, `chamber-tab`/`active`)
and five different activation handlers. The enhancer **observes** each page's own active class via a
`MutationObserver` and mirrors it into `aria-selected` + a roving `tabindex`, so every page keeps its existing
switch code untouched and the ARIA stays correct no matter how the class gets toggled. A small markup contract on
the bar (`data-tabs`, `aria-label`, and a panel-locator attribute) drives the wiring; runtime-built bars call
`window.a11yTabs.scan(container)` after they render.

Delivered behaviour, verified in-browser on every bar:

- `role="tablist"` + `aria-label` on the bar; `role="tab"` + `aria-selected` + `aria-controls` on each button;
  `role="tabpanel"` + `aria-labelledby` on each panel (a shared output region relabels to follow the selection).
- **`aria-selected` tracks a real switch** — confirmed it flips on both a mouse click and an ArrowRight, on
  `ga-bills` (shared panel), `member`/`race` (runtime-built, per-tab panels), `ga-member` (non-standard
  `tab-active` class, exercised through the `data-tab-active` override), and the results layout.
- **Full keyboard model**: roving tabindex (one tab stop for the whole bar), Arrow/Home/End move focus *and*
  activate, delegating the switch back to the page via `.click()`.

Loads once per page (`defer`), initialises on all 15 built pages (9 source pages + the 6 results pages via the
shared layout).

---

### 4.8 — Unlabeled form controls on the bill tracker and all six results pages

**Severity: Med (a11y)**

- `ga-bills.html:336` `#billSearch`, `:337` `#billSubject`, `:340` `#billSort` — three controls, placeholder-only
- `_layouts/election_results.html:139` `#searchBox` — placeholder-only, inherited by all six results pages

Done correctly elsewhere: `ga-congress-trades.html:238-255`, `federal-reps.html:105`, `elections.html:172`,
`ga-state-reps.html:134`.

Related: async-populated error regions still lack `role="alert"` on `member.html`, `ga-member.html`,
`federal-reps.html`, and `justice.html`. Only `elections.html:584` and `ga-congress-trades.html:231` have it.

**Fix:** visually-hidden `<label for>` on each; add `role="alert"` to the `.msg` containers.

#### ✅ FIXED — 2026-08-19

Both parts applied. Bootstrap already ships the `.sr-only` utility (confirmed it computes to the standard
1×1px clip), so the labels reuse it rather than adding a new class.

**Labels.** `sr-only` `<label for>` on `ga-bills.html`'s `#billSearch` / `#billSubject` / `#billSort`, and on the
`#searchBox` in `_layouts/election_results.html` — the latter inherited by all six results pages from one edit.
Verified each `<label>`'s `for` resolves to its control and the label is visually hidden.

**Live regions.** `role="alert"` added to the async-populated `.msg#status` on `member.html`, `ga-member.html`,
`federal-reps.html`, and `elections.html`, to `#billsError` on the bill tracker, and — as part of 4.3 — to the
`justice.html` error paragraph. So a load failure or "no results" that appears after the page settles is now
announced instead of landing silently.

---

### 4.9 — `elections-hub.html` hardcodes root-absolute URLs

**Severity: Med** · `elections-hub.html:80,93,106,118`

`href="/elections.html"`, `"/ga-voter-access.html"`, `"/ga-ballot-measures.html"`, `"/results/"` — while
`results.html:115-116` and `ga-voter-access.html:185-187` correctly use `{{ '/elections' | relative_url }}`. The
site's own JS carries a `getBasePath()` handling a `/votega.org-TEST/` prefix (`elections.html:359`, plus 7 other
copies), so a non-root deployment is an expected configuration — under which all four cards on the primary
elections landing page break.

**Fix:** `{{ '/elections.html' | relative_url }}` on all four.

#### ✅ FIXED — 2026-08-19 · the defect is 5× wider than the four links reported

Confirmed exactly, including the cited contrast (`results.html:115-116` and `ga-voter-access.html:185-187` do use
`relative_url`, and the site already uses it in 44 places). But `elections-hub.html` is not the only offender —
sweeping the whole source tree found **16 root-absolute references across 12 files**, and building under a
non-root baseurl exposed **21 more** that no source-level `href="/…"` grep can see.

**Round 1 — literal `href="/…"` / `src="/…"` in source (16):**

| File | Refs |
|---|---|
| `elections-hub.html` | 4 (the reported ones) |
| `index.html` | 2 — **both home-page rep cards**, the site's primary journey |
| `find-my-reps.html` | 2 |
| `open-data.html` | 2 |
| `candidates.html`, `_layouts/election_results.html`, `flock-covington.md` | 1 each |
| `_posts/` (3 files) | 3, incl. one `<img src>` |

`index.html` matters more than the reported page: those two cards are the entry point to the whole
representative-lookup flow.

**Round 2 — found only by building with a baseurl (21).** These are invisible to a source grep because the path
never appears next to an `href` in a page file:

| Source | Refs | Why the grep missed it |
|---|---|---|
| `about-the-data.md` | 9 | kramdown `[text](/path)` syntax, not an `href` attribute |
| `_data/election_archive` → `results.html:99,104` | 7 | path lives in a data file, emitted as `{{ event.url }}` |
| `_data/open_data.yml` → `_includes/open-data-card.html:36` | 8 | `docs:` / `files[].url:` emitted raw |
| front matter `related.url` → `_layouts/election_results.html` | 2 | path lives in page front matter |
| `_data/local_officials.yml` → `local-officials.html:93` | 2 | `related_pages[].url` emitted raw |
| `_posts/2026-06-17-…md` | 1 | kramdown link syntax |

Fixes at each render site rather than in the data, and the file loop keeps its existing external-URL branch:

```liquid
{% assign f_href = f.url %}{% unless f.url contains "http" %}{% assign f_href = f.url | relative_url %}{% endunless %}
```

**Verified two ways.**

*Does it work?* A full `jekyll build --baseurl "/votega.org-TEST"` — the exact prefix `getBasePath()` sniffs for —
then a regex sweep of every built page for `href`/`src` starting `/` but **not** `/votega.org-TEST/`:

```
UNPREFIXED INTERNAL REFS REMAINING: 0        (was 21 after round 1, and 37 before any fix)
```

*Does it change production?* `baseurl` is unset in `_config.yml`, so `relative_url` should be an identity today.
Confirmed by building the repo at `HEAD` in a detached git worktree and diffing against a post-fix root build:

```
rendered HTML pages compared: 51
HTML pages differing between HEAD and post-fix root builds: 0
```

**Byte-identical output on all 51 pages.** The change is pure latent-defect removal — zero production risk, and
the whole class is now closed rather than the four links that happened to be greppable.

---

### 4.10 — The home page has no entry point for "what's on my ballot"

**Severity: Med** · `index.html:80-105`

Two rep-lookup cards, then straight to `<h2>Latest Updates</h2>`. With a general election on 2026-11-03 there is
no elections card, no next-election date, no deadline. The second of the site's two core journeys is reachable
only via a navbar dropdown.

**Fix:** a third card (or a full-width strip above the two) linking `/elections/`, with the next election date
pulled from `ga-election-calendar.json`.

#### ✅ FIXED — 2026-08-19

Built as the strip option, in `_includes/next-election-strip.html`, placed above the two rep cards. It reads
`ga-election-calendar.json` at runtime and shows the next election's name, full date, a countdown, and the two
deadlines a voter actually needs — with a primary **"See what's on my ballot →"** to `/elections/` and a secondary
link to the voter-access page.

Verified live on the home page:

```
Next Election
Special Election Runoff — U.S. House District 13
Tuesday, August 25, 2026 · 6 days away
Register by  Jul 27, 2026     Early voting  Begins Aug 18, 2026
```

**Cycle-agnostic by construction.** The next election is picked as the earliest calendar entry on or after today,
so this never needs hand-editing as the cycle advances. The strip starts `hidden` and only unhides once it has a
real upcoming election — if the calendar runs out, or the fetch fails, the page silently returns to its previous
layout rather than showing a stale or empty box. Dates parse as *local* dates, matching `ga-voter-access.html`.

---

### 4.11 — `/elections/` and `/elections.html` remain two distinct pages

**Severity: Med (IA)**

`elections-hub.html` → `permalink: /elections/`; `elections.html` → `permalink: /elections.html`.
`race.html:790` back-links to `elections.html` (the finder); `results.html:115` and `ga-voter-access.html:185`
link to `/elections` (the hub) while calling it "the current election guide" — the label describes the finder, the
link goes to the hub. Ambiguous to share, and a standing maintenance trap.

**Fix:** rename `elections.html` → `/elections/candidates/` with `redirect_from: /elections.html`.

#### ✅ FIXED — 2026-08-19 · and a path-depth regression the rename exposed

Renamed as prescribed: the finder is now `permalink: /elections/candidates/` with `redirect_from: /elections.html`
(the plugin is already in use). The hub stays at `/elections/`, so the two pages now form a clean hierarchy
instead of the `/elections/` vs `/elections.html` collision. Verified in-browser: old `/elections.html` meta-refreshes
to `/elections/candidates/`, the hub still resolves at `/elections/`, and the finder loads at its new home.

**A slug caveat, left as the finding specified.** `/elections/candidates/` sits right beside the existing
`/candidates/` (the claim-your-profile portal), which reads as slightly ambiguous. I kept the finding's slug — the
page is branded "Candidate Finder" and the `/elections/` parent disambiguates it — but if you'd prefer
`/elections/races/`, it's a one-line permalink change plus the inbound links below.

**Every inbound link repointed**, not just the finder's own URL:

- **The mislabelled links the finding named.** `ga-ballot-measures.html`, `ga-voter-access.html`, and
  `results.html` all say "see who's on your ballot" / "what's on the ballot" but linked to the *hub*. Repointed to
  the finder, so the label and destination now agree. (`404.html`'s generic "Elections" → hub is correct and left.)
- **The JS-built links** on `race.html` (back-link + 3 error states) and `candidate.html` (6 error states), plus
  the Liquid links on `candidates.html`, `elections-hub.html`'s Candidate Finder card, and the new footer sitemap.

**A regression the rename introduced, caught and fixed.** Moving the page from the root to a two-segment path
broke two **document-relative** asset references that had silently assumed root depth:

```
<script src="assets/scripts/ga-districts.js">   → 404 at /elections/candidates/assets/scripts/…
const RACES_URL = 'assets/data/races.json'      → 404, so the finder rendered zero races
```

Caught in-browser: `countyOptionCount: 1`, `racesRendered: 0`, and a `…/elections/candidates/assets/scripts/ga-districts.js
404` in the network log. Fixed the script tag to `{{ '/…' | relative_url }}` and `RACES_URL` to
`getBasePath() + 'assets/data/races.json'` (the page's own base-path helper, already baseurl-aware). Re-verified:
**160 counties load, 180 GA House general races render**, filters restore from the URL.

**Baseurl-safe.** The 9 error-fallback links I first wrote as root-absolute `/elections/candidates/` (JS string
literals, so no `relative_url`) would have missed the prefix under a non-root deployment. Rewrote them
document-relative (`elections/candidates/`), matching the original code's style. A full
`--baseurl "/votega.org-TEST"` build then reported **0 unprefixed internal refs** across the whole site.

---

### 4.12 — `elections.html` holds all filter state off-URL

**Severity: Med** · `elections.html:213-215`

`activeTab`, `activePhase`, and `countySelect.value` live in module state only; no `history.pushState`, no
`searchParams` read. A voter cannot share or bookmark "GA House races in Newton County," and browser Back from a
race page lands on the default Executive/Statewide tab with the county cleared. `race.html:795-822` already
solves exactly this correctly — the pattern is in the codebase.

**Fix:** mirror `race.html`'s hash/`popstate` approach, or use `?tab=&phase=&county=`.

#### ✅ ALREADY FIXED (pre-review) — completed 2026-08-19

**Stale finding.** This was resolved in commit `c70181c "Deep Links"`, before this review run — `git log -S` on
both `syncURL` and `applyURLParams` points there. `elections.html` already:

- writes `?tab=&phase=&county=` via `history.replaceState` on every tab/phase/county change (deliberately
  `replaceState`, not `pushState`, so filter clicks don't each add a Back stop), and
- reads them back in `applyURLParams()` after the data-driven defaults are computed.

Verified in-browser: `?tab=ga-house&county=Newton` restores that exact filtered view, and changing the county
rewrites the URL. Browser Back from a race page returns to the filtered view rather than the default tab.

**One real gap closed.** The `openSeatOnly` checkbox was the only filter still left off the URL. Added it to both
`syncURL()` (`?open=1`) and `applyURLParams()`, so "open seats only" is now shareable too — confirmed
`?tab=ga-house&county=Newton&open=1` restores all three. Everything now round-trips through the finder's new
`/elections/candidates/` URL.

---

### 4.13 — "Last updated" provenance is missing from the highest-traffic pages

**Severity: Med**

Shown on 7 pages (`executive-member.html:444`, `ga-ballot-measures.html:247`, `ga-bills.html:909`,
`ga-congress-trades.html:435`, `ga-executive-orders.html:277`, `ga-executive.html:321`, `ga-voter-access.html:350`).
**Absent** from `member.html`, `ga-member.html`, `race.html`, `candidate.html`, `ga-state-reps.html`,
`federal-reps.html`, `elections.html`, and every results page — i.e. every page in both core journeys. For a
civic-data site where staleness is the primary failure mode, that is the wrong half.

Where it *is* shown, three formats coexist: raw string (`Data last updated: 2026-07-15`), formatted
(`August 17, 2026`), and raw-plus-term-cycle.

**Fix:** one shared `formatDate()` plus a standard footer stamp component; add it to the eight pages missing it.

#### ✅ FIXED — 2026-08-19 · one correction to the inventory

Built as prescribed: `assets/scripts/data-stamp.js` exposes a shared `formatDate()` plus
`dataStamp.render(el, {updated, source, extra})`, with one `.data-stamp` style.

**Correction — the results pages were not missing it.** `_layouts/election_results.html:110` already renders
`Last updated: {{ page.updated }}`, and 2 of the 6 results pages set that front matter. The real gap was the other
**4** (`ga-special-2026-*`, `ga-general-2026-*`), which had no `updated:` key so the layout printed nothing. Added
it to all four, dated from the last commit touching each page's own results data file — an honest answer rather
than an invented one. So the count was **7 pages, not 8**.

**Stamps added to all 7 genuinely-missing pages**, each verified rendering live:

| Page | Renders |
|---|---|
| `federal-reps.html`, `member.html` | `Data last updated: August 19, 2026 · Source: Congress.gov API` |
| `ga-state-reps.html`, `ga-member.html` | `… August 19, 2026 · Source: Open States API` |
| `elections.html`, `race.html`, `candidate.html` | `… August 18, 2026 · Source: VoteGA curated race data` |

The two lookup pages are stamped from inside the shared `congress.js` / `ga.js`, so the logic lives once per data
source rather than once per page.

**A schema difference worth recording.** The member files carry provenance as `metadata.generatedAt`, but
`races.json` keeps it as a **top-level `updatedAt`** with no `metadata` object at all. The three race-data pages
read that different key; the helper's `render()` returns false and leaves the element empty when there is no date,
so a page never prints a dangling "Data last updated:" with nothing after it.

**Three formats unified to one.** The raw-ISO stamps on `ga-ballot-measures.html` and `ga-voter-access.html`
(`2026-07-15`) and the raw-plus-term-cycle on `ga-executive.html` now run through the shared formatter, as does
`ga-executive-orders.html`. Verified: ballot measures now reads `July 15, 2026`, executive reads
`May 3, 2026 · Source: georgia.gov · Term cycle: 2023–2027`, executive orders reads `Data as of: August 19, 2026`.
Date-only strings are parsed as *local* dates, so a stamp does not read as the previous day west of UTC.

---

### 4.14 — Candidate profiles never link to the candidate-claim funnel

**Severity: Low**

`/candidates/` ("Claim your candidate profile") is in the navbar under Elections, but `candidate.html` — the page
a candidate or their staffer will actually be sent — contains no link to it (`grep "candidates/" candidate.html`
→ no match), despite carrying the whole `.claim-*` presentation layer at `:219-256`. The one page where the CTA
is guaranteed relevant doesn't have it.

**Fix:** on unclaimed profiles, add "Are you this candidate? Claim this profile →" pointing at `/candidates/`.

#### 🔁 MOSTLY ALREADY BUILT — gap closed 2026-08-19

**Stale finding.** The CTA exists and has since commit `436e1a7 "Candidate Claims"`.
`candidate.html:391` renders `CandidateClaims.claimCtaHtml(...)` on exactly the right condition — unclaimed, not
withdrawn, not disqualified, and has a claim key — using the `.claim-*` presentation layer the finding noticed.
Confirmed live on an unclaimed profile: the "Are you …, or part of this campaign?" block renders with a
**Claim this profile →** button.

The finding's `grep "candidates/" candidate.html → no match` was reading a real absence but drawing the wrong
conclusion: the CTA links **straight to the prefilled Tally form**, not to `/candidates/`. For conversion that is
better than bouncing a candidate through an explainer first.

**The one real gap, closed.** A candidate who wants to know what the programme *is* before handing over their
details had no route to `/candidates/` from this page. Added a secondary **"How it works"** link beside the
primary button in `candidate-claims.js`, so the funnel keeps its direct path and gains an informational one.
Uses the same `basePath()` helper as the rest of the site, so it survives a non-root deployment (finding 4.9).
Verified rendering at `/candidates/` with the primary CTA unchanged.

---

### 4.15 — Smaller UI items (grouped)

**Severity: Low**

- `404.html:8-9` — two sibling `<h1>`s; `:12` `alt="Not found"` on a decorative joke image (should be `alt=""`).
- Heading-level skips: `ga-member.html` has `<h1>` + six `<h3>` and no `<h2>`; same in `member.html` (1× h1,
  7× h3), `race.html`, `candidate.html` (8× h3 + an h4), `ga-majority-tracker.html`.
- `elections.html:433-438` — `titleText` and `summary` (candidate names from `races.json`) interpolated into
  `innerHTML` with no `escHtml`, though `escHtml` is defined elsewhere in the codebase six times over.
- `race.html:644,657` — `c.votes.toLocaleString()` / `total.toLocaleString()` with no null guard; a prior-results
  row missing `votes` throws and blanks the entire "Earlier This Cycle" panel.
- `justice.html:180` calls `https://api.oyez.org/people/` live from the browser on every profile view — a
  third-party runtime dependency on an otherwise fully static site. The fallback at `:296` is correct, but the
  page hangs on "Loading biography…" for the full timeout when Oyez is slow.
- Card CSS duplicated byte-for-byte across `index.html:11-77`, `find-my-reps.html:14-80`, and
  `elections-hub.html:11-77` — **three** copies now, up from two at the last review.

#### ✅ FIXED — 2026-08-19 · all six

**Two were genuine bugs, and both are now proven fixed rather than assumed:**

- **`race.html` prior-results crash.** `c.votes.toLocaleString()` had no guard, and `pct` divided by an undefined
  `votes`. Now `const votes = Number(c.votes) || 0`. Demonstrated the exact failure in the live page: the old
  expression **throws `TypeError`** on a row with no `votes` (blanking the whole "Earlier This Cycle" panel), the
  new one returns `"0"`. (`total` was already guarded by `contest.totalVotes || 0`, so only the per-candidate
  value was at risk.) Panel re-verified rendering with real figures — 9,441 / 7,680 / 1,778.
- **`elections.html` unescaped candidate names.** Confirmed: the page had **no `escHtml` at all**, and both
  `titleText` and the candidate names in `candidateSummary()` reached `innerHTML` raw. Added the helper and applied
  it to both. Verified the escape renders `<img src=x onerror=alert(1)>` as literal text with **0 `<img>` elements
  created**; 180 races still render normally.

**`404.html`** — the second sibling `<h1>` is now a `<p class="h1-sub">`, and the decorative joke image takes
`alt=""` so a screen reader skips it instead of announcing "Not found" twice. The sub-line is styled to the same
36px/800 weight, so the two-line gag looks **pixel-identical** to before — confirmed h1 and sub both compute to
`36px` / `800`.

**Heading-level skips** — fixed on all five pages, and this was the one with real regression risk: the theme sets
`h2` at 1.875rem against `h3` at 1.5rem, so a naive tag swap would have enlarged every section heading. Each
scoped rule (`.finance-section h3`, `#stateSidebar h3`, `.tracker-card h3`, …) was moved to `h2` with the
font-size pinned. Baseline sizes were captured *before* the change and compared after:

| Page | Before | After |
|---|---|---|
| `ga-member.html` | 16 / 24 / 24 / 15.2 px | **identical** |
| `member.html` | — | 16 / 24 / 24 / 24 / 15.2 px, 0 skips |
| `ga-majority-tracker.html` | — | 13.6 px preserved, 0 skips |
| `race.html`, `candidate.html` | — | 16 px + 14.08 px, 0 skips |

The two `<h4>` "Top Donors by Employer" headings became `<h3>` so they nest correctly under the promoted `<h2>`.
Every page now reports **zero `h(n) -> h(n+2)` skips** when walked programmatically.

**`justice.html` Oyez dependency** — kept (the data genuinely lives there and the fallback was already correct),
but the wait is now bounded: an `AbortController` with an 8s timeout, cleared in a `finally`. A slow Oyez now
degrades to the "Could not load biography · View on Oyez →" fallback in seconds instead of leaving
"Loading biography…" on screen for the browser's default timeout.

**Card CSS triplication** — extracted to `assets/css/cards.css`, linked from all three pages via the theme's
existing `page.css` front-matter hook. **202 duplicated lines removed** (68 + 67 + 67). Selectors are *grouped*
(`.reps-grid, .elections-grid`) rather than renamed, so no page markup changed; the home page's different margins
are preserved by a `.reps-grid-home` modifier.

> **A trap worth recording:** `_config.yml`'s `defaults` gives every non-post file `layout: page`, so a stylesheet
> with *empty* front matter gets wrapped in the site's full HTML layout and served as a web page — the browser
> then silently drops every rule. Caught it when the grid rendered as one column: the CSS request returned
> `<!DOCTYPE html>`. `beautifuljekyll.css` already uses `layout: null` for exactly this reason; `cards.css` now
> does too. Re-verified all three pages render `543px 543px` / `353px 353px` two-column grids with card styling intact.

---

## Tier 5 — Hygiene, docs, and latent traps

### 5.1 — `update-ga-bills` hardcodes the current session's bill count

**Severity: Med** · `.github/workflows/update-ga-bills.yml` (validate step)

```python
assert len(bills) >= 5000, f'Expected 5000+ bills for the 2025-26 session, got {len(bills)}'
```

A newly opened 2027–28 session has tens of bills, not 5,000. Once `GA_SESSION` is bumped
(`scripts/generate_ga_bills_data.py:33`), this assert fails on every weekly run for roughly the first year of the
biennium — and per [2.2](#22--no-failure-notification-anywhere) nobody is notified, so `ga-bills.json` quietly
stops updating. RECURRING-TASKS §3's changeover checklist lists the two script constants but **not** this assert.

**Fix:** relative floor — `assert len(bills) >= 0.9 * previous_committed_count` with a small absolute floor for a
genuinely new session. This is the same delta check proposed in [2.3](#23--five-workflows-commit-on-validation-that-only-prints).

#### ✅ FIXED — 2026-08-18 (`4573e63`)

The `>= 5000` assert is gone, replaced by `scripts/validate_data_update.py` with `--scope-key metadata.session`:
the floor is now relative to the previously committed count, and a session rollover resets the baseline instead of
failing every run for a year. The workflow's structural checks (`metadata.totalBills == len(bills)`,
`paginationComplete`, required fields) were kept as-is.

---

### 5.2 — `remove: true` candidate overrides are positional and can delete the wrong person

**Severity: Med** · `assets/data/ga-race-candidate-overrides.json` (14 keys) · `scripts/apply_overrides.py:68-71`
· ids minted at `scripts/build_legislative_races.py:41`

`make_candidate_id()` is `f"ga-{chamber}-{district}-2026-{party}-{idx+1}"` — a **row index into the source CSV**.
Fourteen overrides use that positional id to delete duplicate rows (`ga-house-15-2026-d-3`,
`ga-house-149-2026-d-4`, …). If the source export re-orders or drops a row, `d-3` becomes a different candidate
and `apply_overrides.py` deletes them with no name check.

**Evidence:** all 14 `remove: true` keys are currently **orphaned** (0 matching candidates in `races.json`) — the
deletions already took effect, so these entries now sit as live loaded triggers with no target.
`apply_overrides.py` prints nothing when a key doesn't match, so a re-mint reusing `ga-house-15-2026-d-3` would
delete the new occupant silently. Note also that `build_legislative_races.py:172-174` does `c.update(patch)` and
appends unconditionally — it does **not** honor `remove`, so the two scripts disagree about what the flag means.

**Fix:** require a `_name` match before removing; warn on unmatched keys; dedupe inside
`build_legislative_races.py` (the "durable fix, not yet done" at TO-DO.md:45) so these 14 entries can be deleted.

#### 🟡 PARTIALLY FIXED — 2026-08-18 · and one premise corrected

Fixed as a prerequisite for [1.1](#11--build_legislative_racespy-destroys-391-general-election-candidates-on-every-run):
`build_legislative_races.py` now honours `remove: true`, resolving the disagreement between the two scripts about
what the flag means. Before deleting, it compares the candidate's name against `_name` (taking the text before the
` (` annotation, so `"Brian Lamar Prince (duplicate of d-1)"` targets `Brian Lamar Prince`). A mismatch aborts the
run, names the conflict, and **deletes nobody** — verified by simulating a re-ordered source. Unmatched keys are
reported as a note rather than passing silently.

**"All 14 keys are currently orphaned" was misleading.** They are orphaned against `races.json`, where the
deletions already took effect — but all 14 match live rows in the *source export*, and a rebuild applies every
one of them. They are load-bearing, not vestigial: deleting them would have silently reintroduced 14 duplicate
candidates on the next run. The evidence that they were dead was an artefact of measuring against the wrong file.

#### ✅ NOW COMPLETE — 2026-08-19

The two open pieces are done, and the "retire the 14 entries" idea is confirmed wrong:

- **`apply_overrides.py` now has the same name guard.** Its removal path — which ran with *no* name check — now
  compares `_name` before deleting and, on a mismatch, keeps the candidate, records it, and `sys.exit(1)`s rather
  than deleting the wrong person. Verified on a synthetic re-ordered ballot: the matching-name target is removed,
  the mismatched one is kept and reported.
- **Unmatched keys are surfaced, split by kind.** A `remove` key that matches nothing here is expected (the source
  dedupe already ran upstream) and prints as a quiet note; a *patch* key that matches nothing is a real defect and
  prints to stderr — which is exactly how [5.4](#54--a-financebio-override-keyed-on-an-ocd-id-can-never-fire)'s
  mis-keyed override would now announce itself.
- **The 14 `remove` entries stay.** Ran the builder against a redirected output and it reported **"Applied 14 of 14
  'remove' override(s)"** — the source export still contains all 14 duplicate rows, so the keys are load-bearing.
  Deleting them (the finding's suggested endpoint) would reintroduce 14 duplicate candidates on the next build.

---

### 5.3 — `apply_overrides.py` only walks `phases[].ballots`, never `phases[].candidates`

**Severity: Low** · `scripts/apply_overrides.py:57`

`races.json` has two general-phase shapes — 261 phases use `ballots`, **91 use a flat `candidates` array**.
`apply()` iterates only the first, so any candidate override targeting a race in the `candidates` shape (all 91
judicial/PSC races) is a silent no-op. `find_candidate()` in `set_general_candidates.py:36-47` correctly handles
both shapes, so the two scripts disagree. Currently zero override keys target those races, so impact is latent.

**Fix:** iterate `list(phase_data.get("ballots", {}).values()) + [phase_data.get("candidates", [])]`.

#### ✅ FIXED — 2026-08-19

`apply_overrides.py` now walks both shapes via a `phase_candidate_lists()` helper (ballots' value-lists **plus** the
flat `candidates` array). Re-measured against the current file: **533 ballots-shape phases and 184 candidates-shape**
— the flat shape was a quarter of all phases, every judicial/PSC race among them, silently unreachable. Verified with
a synthetic candidates-shape race: the patch now applies where it previously no-op'd. Still zero override keys target
those races today, so no committed data changed — this closes the latent gap before it bites.

---

### 5.4 — A finance/bio override keyed on an OCD id can never fire

**Severity: Low** · `assets/data/ga-race-candidate-overrides.json`, key
`ocd-person/cf955c60-cbda-4414-9266-3d8dca3553fe`

The key is Tim Fleming's OCD *person* id, but override lookup in both `build_legislative_races.py:172` and
`apply_overrides.py:65` keys on `c["id"]` — a *candidate* id. The live record is
`challenger-timothy-fleming-sos-2026` in `ga-secretary-of-state-2026`.

The override's `bio`, `imageUrl`, and `website` were clearly hand-copied into `races.json` (present across all
three phases), but its `existingMemberId` / `existingMemberSource: "state"` fields are **absent** from the live
record — so Fleming's candidate page carries no link to his GA House District 114 legislative record, and
`campaign-finance.js:243` (`candidate.id || candidate.existingMemberId`) can't reach the state-member fallback.

Note that `||` also means `existingMemberId` is unreachable for *any* GA state candidate, since
`build_legislative_races.py` always mints an `id`.

**Fix:** re-key the override to `challenger-timothy-fleming-sos-2026`; add the warn-on-unmatched-key pass from
[5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person).

#### ✅ FIXED — 2026-08-19 · one sub-claim corrected

Re-keyed the override from the OCD id to `challenger-timothy-fleming-sos-2026`, and aligned its stray `name` field to
the file's own `_name` convention so the re-key adds the missing member link **without** also renaming him
("Timothy Kyle Fleming" is preserved). Ran the hardened `apply_overrides.py`: the diff is exactly
`existingMemberId` + `existingMemberSource` added across his three phases (plus a canonical trailing slash on the
website) — no unmatched-patch warning now that the key resolves.

**Verified in the browser**, not just the data: Fleming's candidate page now renders **"View legislative record →"**
→ `ga-member.html?id=ocd-person/cf955c60…#votingHistory`, and that id resolves to his real sitting record —
*Tim Fleming, House of Representatives District 114*.

**One claim corrected.** The finding blamed `campaign-finance.js`'s `candidate.id || candidate.existingMemberId`
for the broken link. That `||` is in the *finance-override* lookup (correctly keyed by candidate id) and is not the
cause. The actual consumer is `candidate.html:352-357`, which builds the legislative-record link straight from
`existingMemberId` / `existingMemberSource`; supplying those fields is the whole fix, and no JS change was needed.

---

### 5.5 — Two federal vote records reference departed members

**Severity: Low** · `assets/data/federal-member-votes.json` ↔ `current-members.json`

`memberVotes` has 17 keys, **2 of which** (`G000596` Greene, `S001157` D. Scott) are absent from
`current-members.json`. All 15 sitting GA members do have vote records, so nothing renders wrong — the entries
are simply unreachable.

**Fix:** a metadata counter, so a *real* drop (a sitting member losing their votes) isn't indistinguishable from
this benign case.

#### ✅ FIXED IN CODE — 2026-08-19 · data updates on the next scheduled run

`generate_federal_votes_data.py` never actually loaded the `MEMBERS_FILE` it declared. It now reads the sitting GA
delegation from `current-members.json` and writes four reconciling fields into `metadata`: `memberCount`,
`sittingDelegation`, `sittingMembersWithVotes`, `staleVoteRecords` — plus a stderr warning and a
`sittingMembersMissingVotes` list if a *sitting* member ever has no votes (the real-drop case the benign stale
records currently mask). It fails safe: if the members file can't be read, the counters are skipped rather than
emitted wrong.

Validated offline against the committed data (the generator itself needs `CONGRESS_API_KEY`): **15 sitting, 17
records, 2 stale (`G000596`, `S001157`), 0 real drops** — matching the finding exactly. The committed
`federal-member-votes.json` gains the metadata on the next `update-federal-votes` run (weekly, Sunday 09:00).

---

### 5.6 — Repo bloat: 105 MB of dead blobs in history

**Severity: Med** · `.git` = 57 MB packed

Largest blobs ever committed:

```
52,779,557  assets/data/GA_2025_26_bills.json   ← file no longer tracked
52,656,467  assets/data/GA_2025_26_bills.json
17,172,522  assets/data/ga-member-votes.json
16,807,928  assets/data/ga-member-votes.json     (… 10+ more ~16 MB revisions)
```

Two 52 MB revisions of a deleted file are permanently in history. `ga-member-votes.json` (currently 15 MB, the
largest tracked file) has **22 commits** and grows by a near-full copy each time `update-ga-votes` runs.

**Fix:** low-risk half — make `update-ga-votes` skip the commit when only `metadata.generatedAt` changed, which
stops the growth. Higher-effort half — a `git filter-repo` pass dropping the two dead `GA_2025_26_bills.json`
blobs; that rewrites history and needs a deliberate decision.

#### ✅ LOW-RISK HALF DONE — 2026-08-19 · history rewrite awaiting your go-ahead

**The growth is stopped.** New `scripts/only_keys_changed.py` compares a staged JSON file against `HEAD` with the
named keys blanked, and exits 0 only when *nothing but those keys* moved. `update-ga-votes` now calls it before
committing: if only `metadata.generatedAt` changed on `ga-member-votes.json`, it reverts the file and skips the
commit instead of adding a near-full ~15 MB revision.

Applied to **both** large per-run files, not just the one named — `ga-bills.json` (~9 MB) carries the same
per-run `partyTallyEnrichedAt` stamp and had the identical problem. The helper fails safe: a new file, unreadable
file, non-JSON, or any real content change all exit 1 (commit). Verified both directions on a real data file —
timestamp-only bump → skip, a changed member name → commit — and confirmed the workflow YAML still parses.

Net effect: on a week when no vote or tally actually changed, `update-ga-votes` now commits **nothing** rather than
~24 MB across the two files.

**Higher-effort half — NOT done, needs your decision.** Dropping the two dead 52 MB `GA_2025_26_bills.json` blobs
(and optionally squashing the ~22 historical `ga-member-votes.json` revisions) requires `git filter-repo`, which
**rewrites every commit hash and force-pushes**. That breaks existing clones and forks and would need the
`publish-*-to-<sibling-repo>` syncs re-based. That is an outward-facing, hard-to-reverse operation, so I have not
run it. When you want it, the dead-blob pass is:

```bash
git filter-repo --path "assets/data/GA_2025_26_bills.json" --invert-paths
git push --force-with-lease origin main   # then re-sync the sibling repos
```

This reclaims ~105 MB from history; the low-risk fix above ensures it does not simply re-accumulate.

---

### 5.7 — Nine stray CSVs tracked in `assets/data/`

**Severity: Med** · verified with `git ls-files`

```
assets/data/Total Votes - 2026.05.19_11pm.csv    212 KB
assets/data/Total Votes - 2026.05.20_12pm.csv    212 KB
assets/data/Total Votes - 2026.05.23_8am.csv     212 KB
assets/data/Total Votes Results - OFFICIAL.csv   212 KB
assets/data/ga-primary-runoff-results.csv
assets/data/ga-special-2026-results.csv / -official.csv / -runoff-results.csv
assets/data/ga.csv                               224 KB
```

The first three are superseded snapshots of the same primary export. The `- OFFICIAL` file is the one
RECURRING-TASKS §1 says to use (*"Do not update a results CSV from an unofficial export once certified numbers
exist — replace it wholesale"*). Keeping unofficial drafts adjacent to the certified file, with spaces in the
filenames and no naming convention, is precisely the setup for grabbing the wrong one. They are also served
publicly from `assets/`.

**Fix:** move source CSVs to `_sources/election_results/` (outside the published tree), keep only the certified
file per election, and adopt the `ga-<election>-results-official.csv` convention the newer files already use.

#### ✅ FIXED — 2026-08-19 · plus a 10th CSV the audit missed

Confirmed the setup was exactly the wrong-file trap described, and found the ambiguity live: the two special-election
CSVs (`ga-special-2026-results.csv` and `…-official.csv`) **differ** in row order and name quoting, and
`build_results_json.py`'s own docstring pointed at the *non-official* one. Building from each produced
**byte-identical** JSON, so there was no data bug — but it is precisely the "which file is real?" hazard the finding
warns about.

**Zero source CSVs remain in the published tree.** All results-source CSVs now live in
`_sources/election_results/`, which Jekyll excludes from `_site` (underscore-prefixed dirs are not copied) — verified
the built site contains **no `_sources/` and no tracked CSV under `assets/data/`**.

| Was (`assets/data/`) | Now |
|---|---|
| `Total Votes - 2026.05.19_11pm.csv`, `…05.20…`, `…05.23…` | **deleted** — unofficial primary snapshots, superseded by the certified export |
| `ga-special-2026-results.csv` | **deleted** — builds identically to the `-official` file |
| `Total Votes Results - OFFICIAL.csv` | `_sources/election_results/ga-primary-results-official.csv` (renamed — drops the space hazard) |
| `ga-primary-runoff-results.csv` | `_sources/election_results/` (name kept — already clean) |
| `ga-special-2026-results-official.csv`, `…-runoff-results.csv` | `_sources/election_results/` |
| `ga.csv` (**10th** — a stale Open States member dump, in the list but not the fix; referenced by nothing) | `_sources/openstates/ga-members-export.csv` |

**Every reference repointed** — the three consuming scripts (`build_results_json.py` docstring,
`update_general_from_primary.py`, `update_general_from_runoff.py`), the legacy `generate_html.py` default path, and
the workflow docs that describe the per-cycle "drop the CSV" step (`TO-DO.md`, `General Election Transition Plan.md`).
`update_general_from_primary.py` had pointed at the *unofficial* `05.23_8am` snapshot; it now reads the certified
export, matching RECURRING-TASKS §1's "replace wholesale once certified numbers exist."

**Reproducibility proven, not assumed.** Rebuilt all four results JSONs from the moved CSVs and diffed against the
committed `_data/election_results/*.json`: **byte-identical on all four.** A `README.md` in the new directory records
the convention and the CSV → JSON → served mapping.

> **One workflow change to note:** the per-cycle "drop the SoS export" target moved from `assets/data/` to
> `_sources/election_results/`. The docs are updated to say so. Left the already-clean runoff filenames as-is rather
> than force an `-official` suffix on them (that would ripple through more docs for little gain) — say the word if you
> want full standardization.

---

### 5.8 — RECURRING-TASKS.md §2's hardcoded-year table is 3-of-7 wrong

**Severity: Med** · `RECURRING-TASKS.md:73-79`

| Claim in §2 | Reality |
|---|---|
| `generate_fec_data.py` L37 `CYCLE = 2026` | **Stale.** L38 is `FALLBACK_CYCLE`; L44-58 `target_cycle()` derives from `races.json`. Already cycle-agnostic. |
| `candidate.html` L433, L446 `election_year=2026` | **Stale.** `grep -rn "election_year" *.html` → 0 matches. Moved to `campaign-finance.js:30`, which reads `metadata.cycle`. |
| `member.html` L608 `election_year=2026` | **Stale.** Same — 0 matches. |
| `_config.yml` L30 nav label `2026 Election Cycle:` | **Stale.** `grep -n 2026 _config.yml` → 0 matches. |
| `set_general_candidates.py` L74 cycle filter | **True**, now at L75. |
| `generate_ga_bills_data.py` L33-34 `GA_SESSION` | **True**, exact. |
| `generate_ga_votes_data.py` L41-42 `GA_SESSION` | **True but misnumbered** — it's at L48. |

This matters more than ordinary doc rot: the table is the operational checklist someone follows under time
pressure at a cycle rollover. Three entries send them hunting for code that no longer exists, eroding trust in the
four that are real. The good news buried here: **the cycle-agnostic refactor succeeded** — the doc just never
recorded it.

**Also stale in §0:** `update-ga-votes` is listed as "Weekly (Sun) 08:00"; the cron is `30 7 * * 1` —
**Monday 07:30**. And "Manual dispatch only … the `publish-*` repo syncs" understates it: `publish-ga-bills`,
`publish-ga-ballot-measures`, and `publish-federal-delegation` all also fire on `push:`.

#### ✅ FIXED — 2026-08-19 · re-verified, and §0 was wronger than the finding said

Re-checked all seven §2 rows and both §0 claims against the current tree (line numbers had drifted again from this
session's edits — e.g. `generate_ga_votes_data.py`'s `GA_SESSION` is now L53, not the finding's L48). The finding's
core verdict held: `generate_fec_data.py` (cycle now via `target_cycle()`), the `election_year=2026` links in
`candidate.html` / `member.html` (0 matches — moved to `campaign-finance.js`, reads `metadata.cycle`), and the
`_config.yml` nav label (0 matches) are all stale. Those four rows are **removed** from the §2 checklist and their
now-agnostic status recorded in the "Already cycle-agnostic" list, so no one re-adds them.

**§0 had a third error the finding didn't catch.** `update-curated-ga-bills` was listed under **Daily**, but its
cron is `0 8 * * 2,4` — **Tuesday & Thursday only**. Fixed alongside the two the finding did flag:

- `update-ga-votes` moved from the (wrong) "Weekly (Sun) 08:00" to its real **Monday 07:30** slot.
- The `publish-*` line was worse than stated: **all five** fire on `push` (four are push+dispatch only; the fifth,
  `publish-races`, is scheduled + push + dispatch), so "manual dispatch only" was flatly wrong. Rewrote that row to
  say they fire on a push that changes the data file each mirrors.

Every cron in the table was verified against the workflow files, not transcribed — the table now carries a
"Verified 2026-08-19" stamp so the next reader knows when it was last trued up.

---

### 5.9 — Genuinely hardcoded 2026 that §2 does *not* list

**Severity: Med** · `scripts/build_legislative_races.py:43,46,206,210,214`

```python
return f"ga-{chamber_slug}-{district}-2026-{party_slug}-{idx+1}"   # L43
return f"ga-{chamber_slug}-{district}-2026"                        # L46
"cycle": 2026,                                                     # L206
"electionDate": "2026-05-19",  # L210    "electionDate": "2026-11-03",  # L214
```

Race IDs, cycle, and both election dates are literals in the generator that rebuilds all 236 GA legislative races.
Same in `scripts/build_general_placeholder.py:168,200`. Neither file is in the §2 changeover table, so a 2028
rollover would regenerate 2026-branded IDs. This compounds the positional-ID fragility in
[5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person).

#### ✅ FIXED — 2026-08-19 · hoisted to constants, not left as scattered literals

Confirmed all five sites in `build_legislative_races.py` plus the two in `build_general_placeholder.py`, and found a
third file in the same class: `set_general_candidates.py` had a bare `== 2026` cycle filter **and** a `2026-11-03`
fallback date.

Each is now a **labeled constant at the top of its file**, matching the `GA_SESSION` pattern the GA data generators
already use — a cycle rollover is a one-line-per-file edit instead of a hunt through embedded f-strings:

```python
# build_legislative_races.py
CYCLE        = 2026
PRIMARY_DATE = "2026-05-19"
GENERAL_DATE = "2026-11-03"
```

Race IDs (`ga-{chamber}-{district}-{CYCLE}`), the `cycle` field, and both phase dates now derive from these.

**Proven value-preserving.** I did not run the generators (they overwrite `races.json` and the placeholder, and
`build_legislative_races` carries the loss-guard from [1.1](#11--build_legislative_racespy-destroys-391-general-election-candidates-on-every-run)).
Instead, imported the refactored module and asserted the ID/date builders emit the exact old strings:
`make_race_id('house', 15)` → `ga-house-15-2026`, `make_candidate_id('senate', 7, 'd', 2)` → `ga-senate-7-2026-d-3`.
Since `CYCLE == 2026`, the output is identical by construction. A grep confirms **no bare `2026` literal survives**
in any of the three generators outside the constant block and comments.

The full picture — including [5.10](#510--session-identifiers-hardcoded-in-the-two-ga-generators)'s `GA_SESSION` —
is now consolidated into the [5.8](#58--recurring-tasksmd-2s-hardcoded-year-table-is-3-of-7-wrong) rollover
checklist, which is the doc someone actually opens at changeover.

---

### 5.10 — Session identifiers hardcoded in the two GA generators

**Severity: Low** · `scripts/generate_ga_votes_data.py:48-49`, `scripts/generate_ga_bills_data.py:33-34` —
`GA_SESSION = "2025_26"`

Both scripts *do* detect a baseline-session mismatch (`:302`, `:409`) and `sys.exit(1)` on an empty result
(`:505-508`), so the failure is loud rather than silent — genuinely the safest of the hardcodes. Contrast the
finance path, which now derives the cycle from data. Flagged only because RECURRING-TASKS tracks it as manual
per-session work and the 2027 session bump is the next one due.

---

### 5.11 — CLAUDE.md's inventory counts are drifting

**Severity: Low** · `CLAUDE.md:18,68,81`

| CLAUDE.md says | Actual (`git ls-files`) |
|---|---|
| "21 GitHub Actions workflows" | **26** |
| "~26 tracked scripts" | **34** |
| "~26 top-level HTML pages" | **35** |

CLAUDE.md hedges appropriately ("not an exhaustive file list"), so this is cosmetic — but ~30% undercounts across
all three suggest the header line dates to 2026-07 and the tree below it hasn't been walked since. Undocumented
workflows include `update-ga-campaign-finance-history`, `update-search-corpus`, `inspect-ga-sessions`, and the four
`publish-*` syncs.

#### ✅ FIXED — 2026-08-19 · re-counted after this session's additions

The gap had widened — this session added workflows (`notify-workflow-failure`, `inspect-ga-voter-resolution`) and
scripts (`only_keys_changed.py`, `inspect_ga_voter_resolution.py`, `validate_data_update.py`, and the new
`scripts/lib/` package). Re-counted from `git ls-files`:

| CLAUDE.md now says | Verified |
|---|---|
| 28 GitHub Actions workflows | `git ls-files '.github/workflows/*.yml'` → 28 |
| ~43 tracked scripts (incl. `scripts/lib/`) | 40 at `scripts/*.py` + 3 in `scripts/lib/` |
| ~35 top-level HTML pages | 35 |

Updated all three sites (the header line, the `scripts/` tree comment, and the `.github/workflows/` comment) and
added a "counts drift — `git ls-files` is the source of truth" note so the next reader treats them as indicative,
not authoritative.

---

### 5.12 — Documentation sprawl and broken cross-links

**Severity: Low**

23 `.md` files sit at repo root; only 6 are tracked. `TO-DO.md` is **gitignored** (`.gitignore:33`) yet
`RECURRING-TASKS.md` — which *is* tracked — links to it 4 times (lines 4, 33, 51, 130). On github.com every one of
those links 404s. `.gitignore` also lists `CODEBASE-REVIEW-2026-08-13.md` **twice** (lines 61-62) while the file
is tracked, so the ignore entry is inert.

**Fix:** decide per file — track it (if a tracked doc links to it, it must be tracked) or move it to a
`docs/local/` folder ignored wholesale. Untracked-but-referenced is the worst of both.

#### ✅ FIXED — 2026-08-19 · resolved by the repo's own evident intent

Both facts confirmed (line numbers had drifted: the `TO-DO.md` links are at RECURRING-TASKS lines 4/35/54/124, and
the duplicate ignore entries at `.gitignore` 60-61). Reading the full `.gitignore` settled the "track vs ignore"
question the finding left open: there is a deliberate cluster of **maintainer-local** planning docs —
`TO-DO.md`, the `*-design.md` files, `General Election Transition Plan.md` — all gitignored, while the review
deliverables (`CODEBASE-REVIEW-2026-08-13.md`, and this file) are tracked. So `TO-DO.md` is private *by intent*, and
promoting it to public to satisfy the links would be the wrong resolution — it would expose a working doc the owner
chose to keep local.

**So the fix runs the other way** — stop the public tracked doc from hard-linking a private one:

- The four `[TO-DO.md](TO-DO.md)` links in `RECURRING-TASKS.md` are now plain `` `TO-DO.md` `` references, with a
  one-time note at first mention that it's a maintainer-local doc not in the published repo. No more github.com
  404s; local maintainers still know where to look. Swept every other tracked `.md` for links to gitignored files —
  **none remain**.
- The two inert, duplicated `CODEBASE-REVIEW-2026-08-13.md` lines were removed from `.gitignore` (the file is
  tracked, so the entries did nothing — and its sibling `-08-18.md` is tracked with no ignore entry, confirming the
  intent). Verified afterward: `08-13.md` is still tracked and no longer carries a dead ignore rule.

---

## Appendix A — Status of the 2026-08-13 review

### Data findings

| Prior finding | Status | Evidence |
|---|---|---|
| 1.1 Bill links point at a SOAP WSDL endpoint | Marked done in the prior doc | — |
| 1.2 GA vote rosters incomplete, 39 members with zero votes | **Still open in data** — code fix written, never regenerated | `ga-member-votes.json` metadata still shows `paginationComplete:false, duplicateVotesDropped:1693, crossChamberDropped:4184` with **no** `unresolvedVoterRows`/`nameFallbackResolved` keys that `generate_ga_votes_data.py:552` now emits. File stamped 2026-08-08. **43** active legislators (up from 39) have zero vote records. |
| 1.3 Party tallies on a partial roster | **Partially fixed** — `partyTallyCoverage` now emitted and rendered, but the threshold makes the warning unreachable | See [3.4](#34--party-line-badges-run-on-an-82-complete-roster-and-never-trip-their-own-warning) |
| 1.4 / App. A "Ghost OCD IDs fixed" | **Fixed for `ga-member-votes.json`, NOT for `curated-ga-bill-votes.json`** | 0/204 ghosts in the former ✓; **21 of 226** voter IDs in the latter are absent from `ga-members.json`. See [1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) |
| 1.5 Resigned legislators in search index | **Fixed** | `generate_search_corpus.py:89` filters Resigned/Removed/Deceased. A new defect was introduced instead — see [3.2](#32--four-ga-statewide-executives-are-indexed-as-ga-legislator) |
| 2.2 Hardcoded finance cycle | **Fixed** | `campaign-finance.js:27-35` derives from `metadata.cycle`; `generate_fec_data.py:44` from `races.json` |
| 2.3 `races.json.updatedAt` stale | **Fixed for most writers, still regressed by one** | `updatedAt = 2026-08-18T11:57:14Z` ✓, but `build_legislative_races.py:251` would set it back. See [1.1](#11--build_legislative_racespy-destroys-391-general-election-candidates-on-every-run) |
| App. A "`campaign-finance.js` and `report_ga_finance_matches.py` genuinely mirror each other" | **True for the GA/PeachFile half; FALSE for the FEC half** | See [1.3](#13--normalizename-js-does-not-mirror-normalize_name-python) |
| App. A "52 override keys match the 52 embedded" | **Still true** | 52/52, zero orphans |

### UI findings

**Fixed and verified:** 3.1 (nested HTML doc), 3.2 (`my-representatives.html` is now a 4-line `redirect_to`),
3.3 (home page rep cards), 3.4 (`federal-reps.html:105` county filter), 3.6 (`document.title` set at
`member.html:917` / `ga-member.html:550`; real `<h1>`s), 3.9 (404 has links + search), 3.12 / 3.14 / 3.15
(back-links, deep-link messages), 3.16 for `race.html` (hash + `popstate` at `:795-822`), 3.17–3.28 (cross-links,
error copy), and party letters now render at `ga.js:142`.

**Still open:** 3.5 (`local-officials` orphan), 3.7 (footer nav), 3.8 (`results-latest` orphan), 3.11
(`/elections` vs `/elections.html`), 3.13 (address lookup), 3.29–3.33 (CSS duplication, date formats, table
overflow), 3.36–3.41 (headings, labels, keyboard, color-only, alerts, alt text).

---

## Appendix B — Verified clean

Checked and found correct — no action needed. Recorded so these aren't re-flagged.

**Joins and overrides**

- 0 orphaned keys in `ga-members-overrides.json` (236/236 resolve)
- 0 orphaned race-level keys in `ga-race-candidate-overrides.json` (27/27)
- 0 orphaned keys in `ga-campaign-finance-overrides.json` (52/52)
- 0 duplicate candidate ids and 0 ids reused across races in `races.json` (1,148 entries, 692 distinct ids)
- All 451 `memberId` / `existingMemberId` references in `races.json` resolve to a real `bioguideId` or `ocd-person` id
- 0 duplicate active districts in `ga-members.json`
- All 4 ballot-measure enabling bills join to `ga-bills.json`
- GA/PeachFile matcher: 614 candidates → 555 auto / 52 override / **0 ambiguous** / 0 same-seat surname conflicts
- 2 federal vote records reference departed members, but all 15 sitting GA members have records — see [5.5](#55--two-federal-vote-records-reference-departed-members)

**Repo hygiene — the suspicion did not hold**

`debug_legiscan_rollcall.py`, `chrome_fetch.py`, `recon_sos.py`, `nodriver_test.py`, `watch_downloads.py`,
`token_extract.py`, `aura_context.json`, `watcher.log`, `watcher_err.log`, all `scripts/*.png`, and `scripts/*.csv`
are present on disk but **not tracked**:

```
$ git ls-files scripts/ | wc -l
34          # all legitimate generators/builders/validators
$ git ls-files | git check-ignore --stdin
(no output — nothing tracked is ignored)
```

`.gitignore:5-27` covers them explicitly and correctly. `_site/` is likewise untracked.

**Secret scan clean.** No leaked credentials in tracked content or in the history of `scripts/*.py`:

```
$ git ls-files -z | xargs -0 grep -lIE "(api[_-]?key|token|secret|bearer)['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}"
(no matches)
$ git log --all -p -- 'scripts/*.py' | grep -iE "^\+.*API_KEY\s*=\s*['\"][A-Za-z0-9]{20,}"
(no matches)
```

All seven Open States consumers read `os.environ.get('OPENSTATES_API_KEY')` and check it before use.
`token_extract.py` / `aura_context.json` / `session_id.py` are local scraper experiments, never committed.
**No alarm warranted.**

**Two workflows have no validation step, but both are adequately guarded in-script**

```
NO VALIDATION: update-curated-ga-bills.yml
NO VALIDATION: update-ga-executive-orders.yml
```

`generate_curated_ga_bills.py` actually has the **best** failure handling in the repo — per-bill fallback to the
previously published record, `sys.exit(1)` if any bill has no fallback, and `sys.exit(1)` again if more than half
came from cache ("treating this as an API outage rather than publishing a mostly-stale file").
`fetch_ga_executive_orders.py` is merge-only with a title-length sanity gate and returns early when nothing is
new, so it cannot truncate.

---

## Suggested sequencing

**~~1 — Stop the bleeding~~ · complete, 2026-08-18**

| # | Item | Outcome |
|---|---|---|
| ~~1.1~~ | `build_legislative_races.py` merge guard | ✅ Rebuild is content-idempotent; loss guard refuses to write |
| ~~2.1~~ | `\|\| exit 1` on the push loop | ✅ 15 occurrences across 14 workflows |
| ~~1.2~~ | FEC first-hit-wins | ✅ Fixed in code; the 3 editorial pins proved unnecessary (0 ambiguous) |
| ~~1.4~~ | Gate the staged general-results pages | ✅ Out of the sitemap and site search; header no longer claims "Unofficial Results". The zeroed-cards and calendar-link claims proved incorrect |

**~~2 — Close the silent-failure loop~~ · done 2026-08-18 (`4573e63`)**

All of [2.2](#22--no-failure-notification-anywhere), [2.3](#23--five-workflows-commit-on-validation-that-only-prints)
(which also retired [5.1](#51--update-ga-bills-hardcodes-the-current-sessions-bill-count)),
[2.4](#24--seven-fetchers-three-incompatible-retry-policies) and
[2.5](#25--open-states-quota-stacks-three-jobs-into-one-sunday-morning-window). Note 2.4 migrated **12** fetchers,
not the 7 the finding counted.

**~~3 — The GA vote-identity cluster~~ · code done 2026-08-18**

[1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) is the root cause;
[3.4](#34--party-line-badges-run-on-an-82-complete-roster-and-never-trip-their-own-warning) and
[3.5](#35--curated-ga-bill-votesjson-party-tallies-double-count-a-duplicate-voter-row) are the mis-presentation it
feeds. Fix the fallback trigger, regenerate (`ga-member-votes.json` hasn't been rebuilt since 2026-08-08
regardless), then raise the coverage threshold.

**4 — Remaining wrong joins**

~~1.3~~ ✅ done (the FEC name fallback is live; 32 previously unmatchable names now resolve),
[3.1](#31--superior-court-results-one-race-shows-five-other-judges-totals-four-show-none),
[3.2](#32--four-ga-statewide-executives-are-indexed-as-ga-legislator),
[3.3](#33--_mergeinto-in-the-trades-generator-merges-trades-but-not-the-counters),
[3.6](#36--generate_ga_members_datapy-emits-empty-strings-where-the-schema-says-null).

**5 — UI: the contained edits**

[4.1](#41--wide-data-tables-have-no-overflow-container) table wrappers,
[4.2](#42--house-hemicycle-seats-are-keyboard-unreachable-and-party-is-color-only) hemicycle,
[4.3](#43--justicehtml-contains-zero-heading-elements) justice headings,
[4.5](#45--electionshtml-shows-a-false-open-seat-badge) / [4.6](#46--racehtml-hardcodes-the-cycle-in-the-page-title)
(one-liners), [4.9](#49--elections-hubhtml-hardcodes-root-absolute-urls).

**6 — IA and shared components**

[4.4](#44--no-footer-navigation-three-orphan-pages-with-zero-inbound-links) footer sitemap (retires three orphans
at once), [4.10](#410--the-home-page-has-no-entry-point-for-whats-on-my-ballot),
[4.11](#411--elections-and-electionshtml-remain-two-distinct-pages), then the shared-component pass —
[4.7](#47--zero-aria-on-every-tab-implementation-on-the-site) tab ARIA,
[4.8](#48--unlabeled-form-controls-on-the-bill-tracker-and-all-six-results-pages) labels,
[4.13](#413--last-updated-provenance-is-missing-from-the-highest-traffic-pages) date/provenance helper — all
against one new CSS/JS file, which also retires the triplicated card CSS.

**7 — Override plumbing and hygiene**

[5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person) (🟡 the `remove`
handling and name check are done; the durable dedupe remains),
[5.3](#53--apply_overridespy-only-walks-phasesballots-never-phasescandidates),
[5.4](#54--a-financebio-override-keyed-on-an-ocd-id-can-never-fire) — each removes a class of silent no-op — then
[5.6](#56--repo-bloat-105-mb-of-dead-blobs-in-history) / [5.7](#57--nine-stray-csvs-tracked-in-assetsdata) /
[5.8](#58--recurring-tasksmd-2s-hardcoded-year-table-is-3-of-7-wrong) doc corrections.

---

## The single highest-leverage change

**Extract `scripts/lib/` — starting with the HTTP fetcher — and add one `if: failure()` step to every workflow.**

Findings [2.1](#21--the-push-retry-loop-swallows-total-failure),
[2.2](#22--no-failure-notification-anywhere), [2.3](#23--five-workflows-commit-on-validation-that-only-prints),
[2.4](#24--seven-fetchers-three-incompatible-retry-policies),
[5.1](#51--update-ga-bills-hardcodes-the-current-sessions-bill-count), and
[3.6](#36--generate_ga_members_datapy-emits-empty-strings-where-the-schema-says-null) are not six independent
bugs. They are six instances of one structural fact: **every generator and every workflow is a copy-paste fork of
its siblings, so a fix applied to one never reaches the other twenty.**

The evidence is direct — five separate `fetch_*` implementations with three incompatible retry policies;
`target_cycle()` duplicated verbatim across two files with a comment admitting it ("*Mirrors
generate_ga_campaign_finance.py's target_cycle()… kept in sync*" — by hand); five distinct
`norm_name`/`normalize_name` functions, one pair of which
([1.3](#13--normalizename-js-does-not-mirror-normalize_name-python)) has already silently diverged and is
breaking a user-facing feature; and 15 identical copies of a push loop that all share the same `set -e` bug.

The retry fetcher is the right first target because it is the *narrowest* shared surface with the *widest* blast
radius: it is where quota exhaustion, truncation, and silent `None`-propagation all originate, and a correct
version already exists in the repo. Ship it alongside a generic `validate_delta.py` and the notification step.

The alternative — fixing each finding in place — is roughly the same total effort and leaves the twenty-first
generator free to reintroduce all of them.
