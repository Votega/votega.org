# VoteGA.org Codebase Review — 2026-08-18

Three parallel audits: **data merge/join integrity**, **UX / IA / accessibility**, and **build pipeline & maintainability**.
Read-only review — no files were modified. Every count below was produced by running commands against the live
files at `HEAD = e40f7a3`; unverified hypotheses were dropped rather than reported.

Supersedes nothing. Read alongside [CODEBASE-REVIEW-2026-08-13.md](CODEBASE-REVIEW-2026-08-13.md), whose status is
tracked in [Appendix A](#appendix-a--status-of-the-2026-08-13-review).

---

## Contents

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

## Executive summary

Four things stand out above the rest of the list.

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

---

## Tier 2 — Silent-failure machinery

> **STATUS: all five fixed on 2026-08-18** (uncommitted working tree). Summary:
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

---

### 4.6 — `race.html` hardcodes the cycle in the page title

**Severity: Med** · `race.html:766`

```js
document.title = `${raceTitle} — 2026 Elections`;
```

Two lines later at `:783` the template already renders `${race.cycle} Election Cycle` from the data. Every shared
race link and browser tab will say "2026" through 2028.

**Fix:** `— ${race.cycle} Elections`.

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

---

### 4.9 — `elections-hub.html` hardcodes root-absolute URLs

**Severity: Med** · `elections-hub.html:80,93,106,118`

`href="/elections.html"`, `"/ga-voter-access.html"`, `"/ga-ballot-measures.html"`, `"/results/"` — while
`results.html:115-116` and `ga-voter-access.html:185-187` correctly use `{{ '/elections' | relative_url }}`. The
site's own JS carries a `getBasePath()` handling a `/votega.org-TEST/` prefix (`elections.html:359`, plus 7 other
copies), so a non-root deployment is an expected configuration — under which all four cards on the primary
elections landing page break.

**Fix:** `{{ '/elections.html' | relative_url }}` on all four.

---

### 4.10 — The home page has no entry point for "what's on my ballot"

**Severity: Med** · `index.html:80-105`

Two rep-lookup cards, then straight to `<h2>Latest Updates</h2>`. With a general election on 2026-11-03 there is
no elections card, no next-election date, no deadline. The second of the site's two core journeys is reachable
only via a navbar dropdown.

**Fix:** a third card (or a full-width strip above the two) linking `/elections/`, with the next election date
pulled from `ga-election-calendar.json`.

---

### 4.11 — `/elections/` and `/elections.html` remain two distinct pages

**Severity: Med (IA)**

`elections-hub.html` → `permalink: /elections/`; `elections.html` → `permalink: /elections.html`.
`race.html:790` back-links to `elections.html` (the finder); `results.html:115` and `ga-voter-access.html:185`
link to `/elections` (the hub) while calling it "the current election guide" — the label describes the finder, the
link goes to the hub. Ambiguous to share, and a standing maintenance trap.

**Fix:** rename `elections.html` → `/elections/candidates/` with `redirect_from: /elections.html`.

---

### 4.12 — `elections.html` holds all filter state off-URL

**Severity: Med** · `elections.html:213-215`

`activeTab`, `activePhase`, and `countySelect.value` live in module state only; no `history.pushState`, no
`searchParams` read. A voter cannot share or bookmark "GA House races in Newton County," and browser Back from a
race page lands on the default Executive/Statewide tab with the county cleared. `race.html:795-822` already
solves exactly this correctly — the pattern is in the codebase.

**Fix:** mirror `race.html`'s hash/`popstate` approach, or use `?tab=&phase=&county=`.

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

---

### 4.14 — Candidate profiles never link to the candidate-claim funnel

**Severity: Low**

`/candidates/` ("Claim your candidate profile") is in the navbar under Elections, but `candidate.html` — the page
a candidate or their staffer will actually be sent — contains no link to it (`grep "candidates/" candidate.html`
→ no match), despite carrying the whole `.claim-*` presentation layer at `:219-256`. The one page where the CTA
is guaranteed relevant doesn't have it.

**Fix:** on unclaimed profiles, add "Are you this candidate? Claim this profile →" pointing at `/candidates/`.

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

---

### 5.3 — `apply_overrides.py` only walks `phases[].ballots`, never `phases[].candidates`

**Severity: Low** · `scripts/apply_overrides.py:57`

`races.json` has two general-phase shapes — 261 phases use `ballots`, **91 use a flat `candidates` array**.
`apply()` iterates only the first, so any candidate override targeting a race in the `candidates` shape (all 91
judicial/PSC races) is a silent no-op. `find_candidate()` in `set_general_candidates.py:36-47` correctly handles
both shapes, so the two scripts disagree. Currently zero override keys target those races, so impact is latent.

**Fix:** iterate `list(phase_data.get("ballots", {}).values()) + [phase_data.get("candidates", [])]`.

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

---

### 5.5 — Two federal vote records reference departed members

**Severity: Low** · `assets/data/federal-member-votes.json` ↔ `current-members.json`

`memberVotes` has 17 keys, **2 of which** (`G000596` Greene, `S001157` D. Scott) are absent from
`current-members.json`. All 15 sitting GA members do have vote records, so nothing renders wrong — the entries
are simply unreachable.

**Fix:** a metadata counter, so a *real* drop (a sitting member losing their votes) isn't indistinguishable from
this benign case.

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

---

### 5.12 — Documentation sprawl and broken cross-links

**Severity: Low**

23 `.md` files sit at repo root; only 6 are tracked. `TO-DO.md` is **gitignored** (`.gitignore:33`) yet
`RECURRING-TASKS.md` — which *is* tracked — links to it 4 times (lines 4, 33, 51, 130). On github.com every one of
those links 404s. `.gitignore` also lists `CODEBASE-REVIEW-2026-08-13.md` **twice** (lines 61-62) while the file
is tracked, so the ignore entry is inert.

**Fix:** decide per file — track it (if a tracked doc links to it, it must be tracked) or move it to a
`docs/local/` folder ignored wholesale. Untracked-but-referenced is the worst of both.

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

**1 — Stop the bleeding (this week)**

| # | Item | Why first |
|---|---|---|
| [1.1](#11--build_legislative_racespy-destroys-391-general-election-candidates-on-every-run) | `build_legislative_races.py` merge guard | 391 candidates at risk, one command away, general is ~11 weeks out |
| [2.1](#21--the-push-retry-loop-swallows-total-failure) | `\|\| exit 1` on the push loop | One line × 15 files; until it lands, every fix below can be silently discarded |
| [1.2](#12--fec-districtsurname-match-is-first-hit-wins) | 3 editorial `fecCandidateId` pins | Stops a page showing another person's money today, ahead of the code fix |
| [1.4](#14--ga-general-2026-results-is-live-and-reports-every-candidate-at-0-votes) | Gate the zeroed general-results pages | Only finding that can actively misinform a voter |

**2 — Close the silent-failure loop**

[2.2](#22--no-failure-notification-anywhere) notification step → [2.3](#23--five-workflows-commit-on-validation-that-only-prints)
generic delta validator (which also retires [5.1](#51--update-ga-bills-hardcodes-the-current-sessions-bill-count))
→ [2.4](#24--seven-fetchers-three-incompatible-retry-policies) shared `scripts/lib/http.py`, promoted from the
already-correct `generate_current_members_data.py:41`.

**3 — The GA vote-identity cluster**

[1.5](#15--21-ghost-ocd-person-ids-orphan-38-legislators-from-every-key-vote) is the root cause;
[3.4](#34--party-line-badges-run-on-an-82-complete-roster-and-never-trip-their-own-warning) and
[3.5](#35--curated-ga-bill-votesjson-party-tallies-double-count-a-duplicate-voter-row) are the mis-presentation it
feeds. Fix the fallback trigger, regenerate (`ga-member-votes.json` hasn't been rebuilt since 2026-08-08
regardless), then raise the coverage threshold.

**4 — Remaining wrong joins**

[1.3](#13--normalizename-js-does-not-mirror-normalize_name-python) (unblocks the FEC fallback for ~35% of federal
candidates), [3.1](#31--superior-court-results-one-race-shows-five-other-judges-totals-four-show-none),
[3.2](#32--four-ga-statewide-executives-are-indexed-as-ga-legislator),
[3.3](#33--mergeinto-in-the-trades-generator-merges-trades-but-not-the-counters),
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

[5.2](#52--remove-true-candidate-overrides-are-positional-and-can-delete-the-wrong-person),
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
