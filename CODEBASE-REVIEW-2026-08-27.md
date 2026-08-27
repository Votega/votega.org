# Codebase review — data publishing & workflow consistency
**Date:** 2026-08-27
**Scope:** four parallel read-only reviews covering the publishing layer (`scripts/publish_*`, `scripts/lib/sibling_publish.py`, `publish-*.yml`), the generation layer (`scripts/generate_*|fetch_*|enrich_*|build_*`, `scripts/lib/`), workflow orchestration (all 34 workflows), and the consumption layer (top-level `*.html`, `_includes/`, `assets/scripts/`).

No code was changed. Findings were verified against file contents; the publishing review additionally cloned the five sibling repos read-only and checked their live git history.

---

## The one-paragraph version

The repo has good conventions and good shared tooling — `validate_data_update.py`, `only_keys_changed.py`, `validate_workflow_triggers.py`, `lib/http.py`, `lib/ga_match.py`, `data-stamp.js` — and the recurring problem is that **the tooling is applied unevenly**. The same file is delta-guarded on Monday and unguarded on Sunday; the validator that enforces failure-notification coverage is a manual ritual and is currently red; the shared date-stamp module is loaded by pages that then hand-roll the thing it exports. Nearly every finding below is "a solution that already exists in this repo, not applied here" rather than "a thing that needs inventing."

Three findings were reached independently by two or more reviewers. Those are ranked first.

---

## P0 — Silent data loss

These publish bad data over good data and report success. Each is cheap to fix.

### 1. `publish-races-to-ga-races-elections.yml` mirrors unvalidated data off-repo *(flagged by 2 reviewers)*
`publish-races-to-ga-races-elections.yml:31-39` — the step named "Validate races.json" contains no `assert` and no `sys.exit`; it loads the file and prints a count. `races.json valid: 0 races` passes and proceeds. `publish_races.py:171-181` has no guard either. The workflow then mirrors into `Votega/ga-races-elections` with `git add -A`, which **deletes the sibling's content** on a truncated source.

Aggravating factors: this is the only daily-scheduled outbound publisher; `races.json` is 1.1 MB of hand-curated data that no CI job can regenerate; and both *other* consumers of `races.json` (`refresh-general-placeholder.yml:49-63`, `refresh-unopposed-count.yml:41-55`) already carry real assertions. `claude.md:105` states the rule this violates verbatim: *"Validate data integrity (count thresholds + required fields) before committing — never commit based on JSON validity alone."*

**Fix:** `python scripts/validate_data_update.py assets/data/races.json --metric races=len:races --min races=1` — same tool, same shape as eight other workflows.

### 2. `freeze-ga-roster.yml` has no validation on an unrepeatable write
Per `RECURRING-TASKS.md` §3, this is a once-per-biennium snapshot: *"Once the incoming members are seated, that roster is gone from the source and can't be reconstructed."* The workflow has no validation step of any kind. `publish_ga_legislators.py:446-459` (`build_freeze_roster`) has no guard either.

**Fix:** give it the 56-senator / 180-representative assertion that `update-ga-members.yml:54-55` already carries. This is the highest-consequence, lowest-effort fix in the review.

### 3. One failed fetch erases a legislator's entire trade history, and the guard misses it by a rounding boundary
`generate_ga_congress_trades.py:227-231` warns and `continue`s on a failed fetch. `byMember` holds exactly 5 GA members. Dropping one is −20.0%, and `validate_data_update.py:189` tests `change < limit` — **−0.20 is not < −0.20**, so it passes exactly on the boundary. (Verified: the operator is `<`.)

**Fix:** two independent changes. Make the generator `sys.exit(1)` when any expected GA filer fails. Separately, change `validate_data_update.py:189` to `<=` — a boundary-exclusive shrink test is wrong for every small-N metric in the repo, not just this one.

### 4. A failed YAML fetch blanks `committees` for all 537 members of Congress
`generate_current_members_data.py:144-146,158-160` returns `{}` on failure; `:392-394` then unconditionally assigns `committees = lookup.get(id, [])`. Every member gets `[]`. `update-current-members.yml:47-58` validates count, required fields and `enrichmentFailures` — not committees. The wipe commits clean.

The correct pattern is one file away: `generate_ga_members_data.py:96-98` returns `None` on failure and records `metadata.committeesAvailable`.

### 5. `update-ga-votes.yml` commits ~24 MB behind `assert > 0`
`update-ga-votes.yml:44-59` guards `ga-member-votes.json` with only `votes > 0` / `members > 0`, then commits `ga-bills.json` (~9.6 MB) and `ga-party-unity.json` with **no validation at all**. The generator merges incrementally against a 250/day Open States quota, so a partial pull that drops half the roll calls satisfies `votes > 0`.

Note the inconsistency: `update-ga-bills.yml:42-46` runs `validate_data_update.py --scope-key metadata.session` on the *same* `ga-bills.json`. The file is delta-guarded on Sunday and unguarded on Monday.

### 6. `update-ga-bills.yml` validates the artifact it does not commit
`:31-61` validates → `:63-64` enriches (rewriting the file) → `:66-86` commits. The committed bytes were never validated; a broken enrichment corrupts the file *after* the gate. One-step reorder.

### 7. Short-read pagination publishes a truncated roster
`generate_ga_members_data.py:58-60` breaks out of the page loop and returns partial results; `:205-208` guards only `if not raw_members` (empty, not short). Page-1 success + page-2 429 publishes ~50 of 240 members. CI catches this one via the 56/180 assertion, but `claude.md` requires scripts to `sys.exit(1)` standalone. `generate_ga_bills_data.py:153-159` does it correctly by comparing `page` to `total_pages`.

---

## P1 — The guard rails themselves

### 8. `validate_workflow_triggers.py` is unwired and currently failing *(flagged by 2 reviewers, reproduced)*
`RECURRING-TASKS.md:37` and `notify-workflow-failure.yml:15-17` both name this script as the enforcement mechanism for the notifier's hand-typed workflow list. **No workflow invokes it** — confirmed, the only repo references are its own docstring and two prose mentions.

Running it today fails: `refresh-unopposed-count.yml` ("Refresh unopposed-seat count (daily, 07:35 UTC)") is scheduled daily and absent from `notify-workflow-failure.yml:22-45`. Its failures open no issue and are indistinguishable from clean runs — precisely the bug class the script exists to catch, uncaught because the script is a manual ritual.

**Fix:** add the missing notifier entry, and add a two-line `validate.yml` running the script on `push`/`pull_request` with `paths: ['.github/workflows/**']`. Permanently closes the class.

### 9. `RECURRING-TASKS.md`'s cadence table has drifted from the actual crons
Stamped *"Verified against the workflow crons 2026-08-19"* (`:43`), yet missing: `refresh-unopposed-count` (daily 07:35), `build-id-crosswalk` (Sun 09:15), `update-ga-campaign-finance-history` (quarterly — no quarterly row exists at all), plus `stamp-races-updated-at`, `freeze-ga-roster` and `backfill-ga-executive-orders` from the manual-dispatch row.

This doc is the operator's map of what is automated (*"do NOT do these by hand"*, `:13-16`); a workflow missing from it is one someone will hand-edit around. **Fix:** extend `validate_workflow_triggers.py` with a third check — every scheduled workflow must appear in the table. It already parses every cron and name.

### 10. Mode selection by token-absence is a booby trap
`publish_or_dry_run` picks the API path or the `OUT_DIR` dry-run path based on whether a token env var happens to be set. Verified against the workflows: `GA_RACES_TOKEN` (`publish_races.py:25`) and `GA_BALLOT_MEASURES_TOKEN` (`publish_ga_ballot_measures.py:23`) **are never mapped to any secret** — those publishers only ever run in dry-run mode, and the git-path workflow commits the `OUT_DIR` result.

If anyone creates a secret with the matching name and wires it up — the obvious move, since three other publishers work exactly that way — the script silently switches to the API path, writes nothing into `target-repo`, `git diff --cached --quiet` passes, and the workflow reports *"No changes — files are already up to date"* and exits 0, having published through an entirely different code path.

`publish_ga_ballot_measures.py:23` carries a comment acknowledging the dry-run override; `publish_races.py:25` does not. **Fix:** select the mode with an explicit `--out-dir` flag. Also unify secret naming — `GA_FEDERAL_LEGISLATORS`, `GA_LEGISLATORS_TOKEN`, `GA_LEGISLATION_PUSH_TOKEN`, `GA_RACES_PUSH_TOKEN` are three naming schemes, and two of the six `TOKEN_ENV` constants match no real secret.

### 11. No `concurrency` groups on 20 workflows that push to `main`; no `timeout-minutes` anywhere
Only `deploy-pages.yml:30-32` and `stamp-races-updated-at.yml:20-22` declare `concurrency`. The other 20 rely entirely on a hand-rolled 3-attempt rebase loop. Three cron collisions exist, two racing on `main`: `update-scotus-decisions.yml:10` and `update-ga-congress-trades.yml:10` are both `0 10 * * 0`; `refresh-general-placeholder.yml:24` (daily 07:30) collides with `update-ga-bills.yml:11` every Sunday and `update-ga-votes.yml:23` every Monday — and `update-ga-votes` makes three sequential pushes over a long run, maximizing the window.

Separately, `timeout-minutes` appears **zero times in 34 workflows**; everything inherits the 360-minute default. Since `notify-workflow-failure.yml:52` only fires on `conclusion == 'failure'`, a hung scrape (`update-ga-campaign-finance`, `update-ga-executive-orders` with its PDF OCR) is invisible for six hours.

No `publish-*.yml` declares `concurrency` either, and `publish-races-*.yml` has *both* a daily cron and a push trigger, so two of its own runs can overlap on the same target repo. The API path has no defense: `sibling_publish.py:32-46` GETs the blob SHA then PUTs it; a concurrent write between the two returns 409 → unhandled `HTTPError` → the run dies **partway through**, some artifacts published and some not.

---

## P2 — Commit churn (measurable, mechanical)

### 12. The sibling publisher writes one commit per artifact, most of them empty
`sibling_publish.py:29-47` issues one `PUT /contents/{path}` per file, each with its own commit message. GitHub commits even when the blob is unchanged.

Verified in `Votega/ga-executive-orders`: the 2026-08-26 publish produced **17 commits, 12 with an empty diff** — `data/2020.json` through `text/2025.jsonl` all untouched. `git log -- data/2020.json` shows one real edit across two "Publish" commits. This runs daily; the repo accrues ~12 junk commits/day permanently. Same shape in `ga-federal-legislators` (8/publish) and `ga-legislation`.

**Fix:** one Git Data API transaction — create blobs, build one tree from the base commit, create one commit, update the ref — and skip entirely when the new tree SHA equals the base. One commit per publish, zero when nothing changed. Entirely contained in one 69-line file, and it makes findings 11, 14 and 19 substantially easier.

### 13. `ga-bills.json` (9.6 MB) ping-pongs between minified and indented every week
`generate_ga_bills_data.py:536` writes `separators=(',', ':')`; `enrich_bills_with_party_votes.py:125` rewrites the same path with `indent=2`. Confirmed: the committed file is indented at **308,234 lines**. So Sunday commits it as one line and Monday re-expands it to 308k lines — two full 9.6 MB revisions per week, neither reflecting a data change.

This also defeats the guard built for exactly this case: `update-ga-votes.yml:97` runs `only_keys_changed.py ... metadata.partyTallyEnrichedAt`, which can never fire because every byte re-serializes.

### 14. Two publishers stamp `now()` and therefore commit daily by construction
Four publishers deliberately derive the stamp from the source's `generatedAt` and comment that they do so *"so an unchanged run produces a byte-identical pointer."* Two do not: `publish_federal_delegation.py:310` and `publish_ga_executive_orders.py:93` use `datetime.now(timezone.utc)`, rendered into `ROSTER.md` / `SUMMARY.md`. Both run daily, guaranteeing a content commit whether or not Georgia's delegation or EO history changed. (`publish_federal_delegation.py:312` already reads the source stamp into `sourceGeneratedAt` — just promote it.)

### 15. `current-members.json` produces a 538-line no-op diff every day
`generate_current_members_data.py:268,281` stamps `dataUpdatedAt = now()` on **every member**. Commit `499840b` is `538 insertions(+), 538 deletions(-)` on a 1.5 MB file with zero substantive change. The field duplicates `metadata.generatedAt` and Congress.gov's own per-member `updateDate`, which is already carried. `only_keys_changed.py` can't help — it only checks top-level dotted keys.

### 16. `only_keys_changed.py` guards three commits in one workflow and zero elsewhere
Wired only at `update-ga-votes.yml:69,:99,:153`. `update-ga-bills.yml`, `update-search-corpus.yml` and `update-current-members.yml` all have the same shape and no guard.

---

## P3 — Schema and convention drift

### 17. Three different keys for "when was this generated" *(flagged by 2 reviewers, from both sides)*
- `metadata.generatedAt` — `current-members.json`, `ga-members.json`, `ga-bills.json`, `ga-member-votes.json`, `ga-party-unity.json`, `federal-member-votes.json`
- `metadata.updatedAt` — `ga-executive.json`, and all seven `ga-executive-orders-*.json` (**date-only**, losing time of day)
- top-level `updatedAt`, no envelope — `races.json`, `ga-legislative-candidates.json`

Every consumer hardcodes which shape it expects, several with apologetic comments (`race.html:907-908`). `claude.md` requires a `metadata` object with at minimum `generatedAt` and `count` — yet `count` is spelled six different ways across six files (`totalBills`, `totalVotes`, `memberCount`, `totalCandidates`, `totalTrades`, absent), which is precisely why `validate_data_update.py` needs a bespoke `--metric` line per workflow. `sourceUrl` appears in one file; `generatedBy` in none, so nothing on disk records its own producer.

**Fix:** `lib/jsonio.py:envelope(...)` emitting `{generatedAt, generatedBy, count, source, sourceUrl}` uniformly, with dataset-specific totals as *additional* keys. Then `validate_data_update.py` can default to `--metric count=metadata.count` with no per-workflow flags.

### 18. A timestamp written naive and read as UTC
`generate_ga_votes_data.py:513,541` write `datetime.now().isoformat()` (no offset); `:234-239` reads it back and asserts `tzinfo is None → UTC`. Correct by accident on the UTC Actions runner; any local or self-hosted run shifts the `updated_since` window by the offset and **can skip roll calls entirely**. Its sibling `generate_ga_bills_data.py:507` already writes `datetime.now(timezone.utc)`.

Repo-wide: 14 generators write naive `now()`, 10 write `now(timezone.utc)`, and `build_race_results_index.py:414` writes a bare `date.today()` via an inline `__import__('datetime')`. This is the only one where the value is machine-consumed, so fix it first.

### 19. No atomic writes anywhere
All 37 generators use `with open(path, 'w')` + `json.dump`. `grep "os.replace\|tempfile"` across `scripts/` returns one temp *dir* for PDF pages and a test. An interrupt or full disk mid-dump leaves a broken 9.6 MB / 20 MB file where the good one was. Workflows catch it pre-commit; local runs and the three in-place enrichers do not. One `lib/jsonio.py` helper (write to `.tmp`, `os.replace`) fixes all 37 and is the natural home for the indent policy (13), the trailing-newline convention, and `utc_now_iso()` (18).

### 20. `sibling_publish.py` is the one network path with no retry
Raw `urllib.request.urlopen` per artifact, no timeout, no 429/5xx backoff — while `lib/http.py` exists for exactly this and `claude.md:104` states the policy (*"Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx"*). Atomicity is accidental: the pointer files (`latest.json`) happen to be inserted last in the artifact dict, so dict ordering publishes them after their targets. Nothing states or enforces that invariant.

### 21. Sibling repos are GPL-3.0 while `/open-data` promises attribution-only
All five sibling repos carry a GPL v3 `LICENSE` (verified). `open-data.html:83-89` tells reusers only: credit VoteGA and the upstream source, verify upstream terms, no warranty. Copyleft is never mentioned. A journalist reading the page and a developer landing on the repo get materially different legal instructions. No publisher emits `LICENSE` or `README.md` at all — the sibling READMEs are hand-written.

---

## P4 — Public-facing correctness

### 22. Three of seven repo file links on `/open-data` are 404s
- `_data/open_data.yml:41` → `ga-legislators/blob/main/data/votes.json`. No such path; votes live at `sessions/<slug>/votes.json` (`publish_ga_legislators.py:313`).
- `:74-75` → root `ga-bills.json` and `ga-bills-subjects.json` in `ga-legislation`. Both **deliberately deleted** by `publish-ga-bills-to-ga-legislation.yml:65` (`rm -f`), and the sibling's own README documents the move to `sessions/<slug>/`.

`meta.last_reviewed: 2026-08-10` predates the migration. `/open-data` is in the navbar (`_config.yml:49`) and cited three times from `about-the-data.md`. Ballot measures — published to `ga-legislation` by `publish_ga_ballot_measures.py` — are omitted from the catalog entirely.

**Fix:** correct the paths, then make it mechanical: a script that HEADs every `files[].url` in `open_data.yml`, run in the same CI pass as finding 8.

### 23. Data-stamp convention drift on the page `claude.md` cites as its own precedent
- `ga-party-unity.html` — named at `claude.md:166` as *the* precedent — renders source and repo link but **no freshness date at all**, though `ga-party-unity.json` emits `metadata.generatedAt`.
- Six results pages hardcode a front-matter `updated:` date that no script maintains (`ga-general-2026-results.html:7` still reads `2026-08-17`), rendered by `_layouts/election_results.html:109` with different wording than `data-stamp.js` — a third mechanism. The layout already fetches a `races.json` carrying a real `updatedAt`, and `stamp_races_updated_at.py` already automates the data side.
- Four pages load `data-stamp.js` but use only `formatDate`, re-hand-rolling `render()` and its repo link, each behind a ternary that silently degrades to a raw ISO string.
- `ga-bills.html:990` doesn't load the module at all: hardcoded *"May 2026"*, raw `YYYY-MM-DD`, hand-built repo link.
- `find-my-reps.html` and `sample-ballot.html` have no footnote of any kind — and `data-stamp.js:6-7` explicitly names find-my-reps as one of the two journeys it was written to fix.

---

## P5 — Efficiency

### 24. `ga-member.html` downloads 19.4 MB to render one legislator
`:1054-1057` fetches the full 20.4 MB `ga-member-votes.json`, then narrows to `data.memberVotes[member.id]` at `:1060`. Measured: 237 members, **median 95 KB each**; the shared vote index is 942 KB. Every state-legislator profile page does this.

**Fix:** split at generation time into `assets/data/member-votes/<ocd-id>.json` + one shared index. `build_race_results_index.py` → `race-results-index.json` (163 KB, consumed at `race.html:343`) is the in-repo precedent. Largest single win in the codebase.

### 25. `find-my-reps.html` pulls ~1.7 MB to render four rep cards
`:102-103` loads `current-members.json` (1.42 MB) + `ga-members.json` (261 KB) in full, using six fields. `sample-ballot.html:282-292` does the same. A ~50 KB `reps-index.json` serves both. This is a core journey.

### 26. `ga-majority-tracker.html:357` downloads 1.06 MB of `races.json` to compute one integer
Purely to evaluate `Math.max(...cycles)`. The value belongs in `election-status.json` (1.6 KB, already fetched by four pages). The same file also contains two *different* base-path algorithms — `getBasePath()` at `:345` and an ad-hoc regex at `:409` that works only under the current flat permalink.

### 27. Zero conditional requests anywhere
No `ETag` / `If-Modified-Since` / `If-None-Match` in `scripts/`. `generate_scotus_decisions.py:222-231` re-fetches Oyez detail for every decided case weekly, with sleeps — decided cases never change; skipping any case already in the committed JSON needs no HTTP at all. `legislators-current.yaml` (~4 MB) is downloaded by three separate workflows. `generate_fec_data.py:389-408` makes 3 calls + 3× `sleep(1.0)` per candidate across 252 candidates.

---

## P6 — Duplication (largest line count, lowest risk)

Best done *after* the behavioral fixes, so there is one correct implementation to extract.

### 28. Eleven copies of the push-retry loop, in two incompatible flavors
- **`reset --hard` + regenerate** (~35 lines): `publish-ga-ballot-measures-*.yml:82-121`, `publish-ga-bills-*.yml:51-96`, `publish-races-*.yml:48-88` — verbatim, down to an identical comment referencing *"the publish-race incident, 2026-08-19."*
- **`pull --rebase` + `sleep 5`** (~20 lines): `update-current-members.yml`, `update-federal-votes.yml`, `update-ga-members.yml`, `update-ga-votes.yml` (×3), `update-ga-executive-orders.yml`, `backfill-ga-executive-orders.yml`, `stamp-races-updated-at.yml`.

Measured against 2,511 total workflow lines: ~440 lines in the commit-and-push loop alone (22 copies).

**Recommended:** a `.github/actions/commit-and-push/action.yml` composite (~45 lines) taking `paths`, `message`, `ignore-keys`, `branch`. Each call site collapses from ~20 lines to 4. **Net ~440 → ~133 lines (−305, ~12% of the workflow corpus).** More importantly it turns findings 11 and 16 into one-line-each edits rather than 20-file sweeps.

**Two constraints worth knowing before starting:**
1. A *local* composite action requires the repo already checked out, so it **cannot** bundle `actions/checkout`. The checkout + setup-python pair (~125 lines) can only be consolidated by a reusable workflow (`workflow_call`). That larger option fits ~12 workflows exactly and would remove ~580 lines (~23%).
2. `validate_workflow_triggers.py:96-106,118-124` finds `git add` paths and `publish_*.py` calls by walking `jobs[].steps[].run` in `.github/workflows/*.yml` **only**. Moving those steps into a composite or reusable workflow blinds it. **Teach the validator the new shape first**, or the guard from finding 8 goes dark exactly when the workflows become harder to eyeball.

### 29. No shared fetch helper: ~50 `fetch()` sites, 18 byte-identical `getBasePath()` copies
Defined identically in `member.html:472`, `ga-member.html:327`, `race.html:496`, `elections.html:431`, `candidate.html:321`, `ga-majority-tracker.html:345`, `ga-ballot-measures.html:134`, `ga-party-unity.html:232`, `executive-member.html:299`, `justice.html:187`, `supreme-court.html:163`, `ga-executive.html:224`, `ga-congress-trades.html:351`, `find-my-reps.html:111`, `_includes/next-election-strip.html:61`, `_layouts/election_results.html:181`, `assets/scripts/congress.js:17`, `assets/scripts/ga.js:44`.

**No cache-busting exists anywhere** in the repo (zero hits for `?v=`, `Date.now()`, `no-cache`), so a stale CDN copy of a daily-regenerated file is invisible to every page. A shared `data-fetch.js` is the prerequisite for ever having a cache policy at all.

### 30. Fourteen date formatters, nine name normalizers, party helpers under six names
- **Dates:** 14 independent implementations, though `data-stamp.js:40` already exports a correct `formatDate` that handles the local-vs-UTC date-only trap most of them re-solve by hand.
- **Names:** `norm_name` is copy-pasted between `generate_ga_campaign_finance.py:145-158` and `generate_ga_campaign_finance_history.py:168-184`. The history copy adds an apostrophe-strip with a comment claiming O'Steen/Osteen would otherwise diverge — **tested, they produce identical output**, because `[^a-z\s]` already drops apostrophes. The comment documents a divergence that does not exist. (Both copies share a real latent bug: the nickname regex `["\'].*?["\']` treats two surname apostrophes as a quoted pair, so `Sean O'Brien O'Connor` → `sean oconnor`.) The repo has already learned this lesson twice — `lib/ga_match.py` and `lib/ga_voters.py` headers document the drift cost.
- **Party helpers:** `partyClass`, `partyLetter`, `partyIcon`, `partyColor`, `partyAbbrev` (two different implementations of the same name in `congress.js:23` and `ga.js:36`), `partyLabel`, `partyOf` — across 8 files.
- **Escaping:** 13 pages migrated to `VoteGA.escapeHtml`; `ga-party-unity.html:231` and `find-my-reps.html:114` still use a DOM-based `esc()` that does **not** escape `'`, so neither is safe in a single-quoted attribute.

### 31. Eight workflows embed bespoke validation in YAML heredocs
`update-current-members.yml`, `update-ga-members.yml`, `update-fec-data.yml`, `update-ga-campaign-finance.yml`, `update-ga-campaign-finance-history.yml`, `update-search-corpus.yml`, `update-ga-executive-orders.yml`, `update-ga-votes.yml`. Three re-implement "compare against HEAD" by hand (`update-ga-executive-orders.yml:42` shells `git show HEAD:${FILE}`, duplicating `validate_data_update.committed_version`). The dataset-specific checks are worth keeping — but as `scripts/validate_<dataset>.py` modules that can be run and tested locally, not YAML string literals.

### 32. Python helpers copy-pasted across publishers
`compact_json()` byte-identical in two publishers; the `io.StringIO` → `csv.writer` → `.encode()` boilerplate **eight** times; the Markdown preamble hand-repeated in all five; a near-identical nested `table()` helper in two. Dead constant: `SCHEMA_VERSION` is defined in three publishers and used in one — so two published schemas silently carry no version.

---

## Dead code and orphans

- **`scripts/generate_ga_executive_orders.py` — delete.** Line 133 hardcodes `C:\Users\justi\.claude\projects\...\tool-results` and reads three `toolu_*.txt` transcript artifacts, then writes `assets/data/ga-executive-orders-{2023,2024,2025}.json` — the same paths the real workflow-driven `fetch_ga_executive_orders.py` owns. No workflow references it; it survives only because the hardcoded path makes it crash first. It is listed in `claude.md:75` as a current generator, and `claude.md` itself says one-off local scripts are gitignored, not tracked. Likely origin of the `_note`-before-`metadata` key ordering unique to the 2023-2026 EO files.
- **`assets/data/ga-campaign-finance-history.json` (1.08 MB) — orphaned.** Built and committed quarterly by `update-ga-campaign-finance-history.yml:87`; read by no page, no script, no JS. *Two reviewers reached this independently* — the frontend found no consumer, and the workflow review found it is the only quarterly job and missing from the cadence doc. Either wire it into `ga-member.html`/`candidate.html` (a multi-cycle finance history is presumably why it was built) or retire the workflow.
- **`sample-ballot.js:376-391` `resolveBallot()` — no caller.** `sample-ballot.html:307-311` reimplements the same three-file load inline. Two copies of one feature's loading logic is how the two drift.
- **Not orphans, despite having no page consumer:** `ga-legislative-candidates.json` (549 KB) and `curated-ga-bills.json` are legitimate build inputs (`build_legislative_races.py:29`, `generate_curated_ga_bills.py:27`).
- The `not in use/` directory holds only sample posts and images.

---

## Suggested sequencing

1. **P0 guards** (1-7). Hours of work, each independent, each closes a silent-data-loss path. Start with `freeze-ga-roster` (unrepeatable) and `publish-races` (off-repo blast radius).
2. **Wire the validators into CI** (8, 9, 22). Two small workflows; makes the invariants self-enforcing rather than ritual. Fix the `<=` boundary in `validate_data_update.py` here.
3. **`lib/jsonio.py`** (13, 18, 19, and the envelope from 17). One new module, mechanical adoption across 37 call sites, kills the serialization ping-pong and the atomic-write gap together.
4. **Single-commit sibling publish** (12). One file; ends the empty-commit flood and makes 11, 14 and 20 easier.
5. **Frontend shared modules** (23, 29, 30). `html-escape.js`, `data-stamp.js` and `results-contest.js` already prove the migration pattern works and is cheap.
6. **Slim indexes** (24, 25). The only frontend findings needing generator work; together they cut ~21 MB off the two heaviest journeys.
7. **Workflow consolidation** (28). Largest line count, lowest risk — but teach `validate_workflow_triggers.py` the composite-action shape *before* landing it.
