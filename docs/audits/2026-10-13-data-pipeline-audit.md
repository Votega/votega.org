# Data Pipeline Audit — 2026-10-13

Four parallel reviews of the votega.org data pipeline: ingest scripts (85),
orchestration workflows (46), captured-vs-rendered data fields, and payload
shape/delivery (~48 MB in `assets/data`, 3,845 tracked files).

Full per-area reports were produced alongside this summary; this document is the
reconciled view. Findings that the four reviews disagreed on are marked
**[reconciled]** with the verified answer.

---

## 0. Read this first: two traps

**Trap 1 — the four most valuable fields in the repo look like dead weight to a
grep.** `ga-bills.json .sponsors[].legisGaGovId`, `.sponsors[].primary`,
`ga-congress-trades.json .trades[].doc_url` / `.comment`, and
`ga-executive-orders-*.json .orders[].archiveUrl` all have zero front-end
references — because they are *opportunities*, not waste. A payload-trimming
pass that keys off "unreferenced" will delete exactly the wrong things.
Section 3 depends on all four surviving section 4.

**Trap 2 — gzip already solves most of the size problem.** GitHub Pages gzips
JSON: `ga-bills.json` is 7.0 MB raw but 811 KB on the wire (8.6x);
`current-members.json` compresses 12.8x. So minification and key-shortening buy
git weight and browser parse time, *not* bandwidth. Only shipping **fewer
records** cuts bandwidth. Prioritise projections and sharding over compaction.

---

## 1. Root cause: lost incrementality

One defect explains the git churn, the CI cost, and the upstream API load.

`scripts/generate_ga_bills_soap.py:416-443` iterates every session and issues one
`GetLegislationDetail` per bill — 5,656 bills weekly, of which **5,480 sit in
sessions that can never change again**. `generate_ga_votes_soap.py:318` does the
same per roll call.

This contradicts the library it is built on. `scripts/lib/ga_sessions.py:5-6,41-43`
states the active session is "the ONLY one fetched live", and the function that
enforced it — `preserved_session_ids()` at `lib/ga_sessions.py:177` — now has
**zero callers**. The retired Open States producer it replaced *did* implement
this (`scripts/archive/generate_ga_bills_data.py:389`, `incremental_since` with a
`FULL_REFRESH=1` escape hatch). Incrementality was dropped in the SOAP cutover.

Consequences, measured:

- Only **660 of 5,656 bills (11.7%)** differ between two consecutive
  `ga-bills.json` revisions, yet a full 6.9 MB blob is committed each run.
- Git blob revisions over a 2-day window: `ga-bills` 20.5 MB, `ga-member-votes`
  11.3 MB, `current-members` 8.6 MB, `races` 5.5 MB — **~25 MB/day**, essentially
  the entire 29.8 MB pack of a 54-commit shallow clone.
- `--delay` defaults to `0` (`generate_ga_bills_soap.py:409`) and the workflow
  passes nothing, so this is 5,656 unthrottled POSTs in a single burst against a
  state government SOAP endpoint.

**Fix:** fetch only `ACTIVE_SESSION`, carry closed sessions forward from the
previous output, restore `preserved_session_ids()`, keep a `FULL_REFRESH=1`
escape hatch, and set a non-zero default delay. Cuts the weekly run ~97% and
removes most of the churn that `only_keys_changed.py` exists to paper over.

---

## 2. Orchestration

### 2.1 The unchanged-output guard is bypassable and half-applied

Every generator stamps a fresh `generatedAt` (e.g.
`generate_current_members_data.py:424`, `generate_ga_news.py:563`,
`generate_ga_bills_soap.py:475`), so a plain `if git diff --cached --quiet` guard
**can never suppress a commit** — the file always differs. Only
`only_keys_changed.py` can, and it is wired into 9 of ~24 committing workflows.

Unguarded, worst first: `update-ga-bills.yml:75` (6.8 MB, 52×/yr ≈ 350 MB/yr),
`update-current-members.yml:72` (1.4 MB daily ≈ 510 MB/yr),
`update-ga-executive-orders.yml:75` (0.3 MB, 2×/day ≈ 220 MB/yr),
`build-id-crosswalk.yml:55`, `update-ga-members.yml:91`, plus six smaller.
Roughly **1.2 GB/yr** of meaningless history. `generate_ga_bills_soap.py:24`
documents the guard as present in its workflow; it is not.

**Fix:** add the `elif only_keys_changed.py` branch to each, then enforce it as a
third invariant in `scripts/validate_workflow_triggers.py` (which already
enforces two). Note this is mitigation — section 1 is the cure.

### 2.2 The five `publish-*` workflows cannot fire

Each is `on: push` with a `paths:` filter on a **bot-written** file, and
`GITHUB_TOKEN` commits do not raise `push` events. The repo already knows:
`update-current-members.yml:92-96` records that `publish-federal-delegation` "had
run 4 times in two months — all of them manual". So `publish_federal_delegation.py`,
`publish_ga_bills.py` and `publish_ga_executive_orders.py` each exist as a
never-firing workflow *plus* two inline copies.

Same root cause as the deploy latency documented at `deploy-pages.yml:61-78`
(hence its two daily crons and 0–11 h publish lag). Moving the writers to a PAT
or GitHub App token makes the whole graph event-driven and collapses the dead
workflows, the latency, and the news-cadence mismatch at once. The author's
stated objection — a hand-maintained `workflow_run` name list — is already
solved by `validate_workflow_triggers.py`.

### 2.3 Cadence

- `update-ga-news.yml:10` runs 8×/day; the site deploys 2×/day. **Six of eight
  runs can never reach a visitor** — ~2,900 runs/yr for 2 useful refreshes.
- Session-only GA sources (bills, votes, curated bills, legis-sessions) run
  year-round, ~8 months of guaranteed no-ops.
- `update-vp-tie-votes.yml:10` weekly on data that changes a few times per
  Congress; `update-current-members.yml:9` daily on a roster that moves a few
  times a year.
- **14 of 26 schedules sit on minute `:00`**, the most delay-prone minute, on a
  latency-sensitive chain. Exact collisions at `0 10 * * 0` (scotus +
  congress-trades) and `0 7 * * *` (ga-members + publish-races).

### 2.4 Ordering inversions

`update-ga-bills.yml:68` enriches bills from `ga-member-votes.json` on Sun 07:30,
but votes refresh Mon 07:30 — the join is **always a cycle stale**, and is redone
the next morning anyway at `update-ga-votes.yml:119`. Delete the duplicate.
`build-id-crosswalk.yml:13` (Sun 09:15) has the same inversion. No commit loops
exist — the token behaviour in 2.2 prevents them.

### 2.5 Reliability gaps

- `timeout-minutes` on **2 of 46** workflows. A hung SOAP or OCR fetch burns the
  full 6 h job limit.
- `concurrency` on 4 of 46; the other 25 writers hand-roll `git pull --rebase`
  retry loops to survive races that one shared `data-push` group would remove.
- Retries wrap `git push` only — never the flaky upstream HTTP fetch.
- 7 workflows have no `permissions:` block.
- Every action floats on a mutable major tag (`checkout@v4` ×40); no
  `dependabot.yml`.
- `python-version: '3.x'` in 31 of 36 setups; no `requirements.txt`, so **no pip
  caching anywhere**; no `Gemfile.lock`.
- `notify-workflow-failure.yml:19-52` name-matches 31 strings, **18 of which
  embed their own schedule** — so retuning any cadence renames the workflow and
  silently unmonitors it. Its invariant covers only `has_schedule`, leaving
  `indexnow` / `stamp-races` / `apply-overrides` unmonitored despite writing to
  `main`; `writes_to_main` already exists at `validate_workflow_triggers.py:147`.

### 2.6 Nothing runs the tests

Five `test_*.py` files — including `test_ga_vote_rules.py`,
`test_fec_name_parity.py`, `test_ga_voter_resolution.py` — have **zero references
in any workflow**; grep for pytest/unittest across `.github/workflows/` returns
nothing. They guard precisely the vote-counting and money-attribution logic that
everything else depends on. Adding a `tests.yml` is the cheapest high-value fix
in this audit.

Relatedly, `validate_data_update.py` is used by 10 of ~29 committing workflows;
the rest carry inline heredoc validators with hand-pinned absolute floors — the
exact anti-pattern its own docstring (`:12-19`) was written to replace.

**[update 2026-10-17]** Both halves of this finding are now largely addressed,
and the recommendation above has been overtaken.

*Tests.* `run-script-tests.yml` runs every `scripts/test_*.py` (21 files,
including the three named above) and `test-js.yml` runs every
`tests/js/*.test.js` (5 files). No separate `tests.yml` was needed.

*Validators.* Adoption is now 15 of 29 committing workflows, and the newer ones
are purpose-built per dataset (`validate_ga_members.py`, `validate_ga_bills.py`,
`validate_curated_ga_bills.py`, `validate_ga_votes.py`,
`validate_current_members.py`, `validate_fec_data.py`) rather than all routed
through `validate_data_update.py`. Four workflows still carry hand-pinned
absolute floors:

  - `update-ga-campaign-finance` — `by_seat < 150`, `legislative < 400`. The
    live one: early in a cycle, before candidates file, the legislative count
    legitimately falls below 400 and the run is discarded.
  - `update-ga-executive-orders` — `len(orders) < prev_n`, a comparison against
    the last commit. Encodes a real invariant (the merge is additive, so a drop
    is loss) but blocks permanently on a legitimately withdrawn order.
  - `update-search-corpus` — `count >= 200`.
  - `update-ga-campaign-finance-history` — `len(filers) < 1200` (an archive that
    only grows; low risk).

*The target has moved.* This finding recommends migrating to
`validate_data_update.py`, which still hard-fails and so discards the run's data
— the regenerated file dies with the runner, and the site keeps serving stale
data. `update-local-government.yml` (2026-10-14, one day after this audit) and
`update-fec-data.yml` instead split checks in two: conditions the file's own
contents contradict fail the run, while differences from the previous run are
reported and the data commits anyway. See `scripts/validate_fec_data.py`'s
module docstring for why the two cannot be collapsed — a candidate's money
disappearing is indistinguishable, by shape alone, from the fetch bug that
would cause it.

---

## 3. Data captured but never shown

Ranked by value per unit of work.

### 3.1 `legisGaGovId` on bill sponsors — best ratio in the repo

`ga-bills.json .bills[].sponsors[].legisGaGovId` (e.g. `4983` for Michelle Au) is
an exact-match join key to `ga-members.json .members[].legisGaGovId`. Present on
all 1,960 sponsor rows sampled; **zero front-end occurrences**.
`ga-bills.html:528/743/825` renders sponsor names as escaped plain text and
discards the id — and `sponsors[].primary`, which distinguishes lead author from
co-signer.

Unlocks, in increasing order of effort: clickable sponsor names; a **"Bills
sponsored by this member"** block on `_includes/entity/ga-legislator.html`, which
today shows votes but no sponsorship at all while the *federal* member page
already has a sponsored-bills tab (a straight parity gap); and a co-sponsorship
network across all 5,656 bills.

### 3.2 `ga-campaign-finance-history.json` — 1.1 MB, loaded by nothing

1,545 committee-cycle records of GA state fundraising spanning **2014–2028**,
with prebuilt `byCycleYear` / `byOffice` / `bySeat` indexes and a
`metadata.joinNote` that spells out the join. Meanwhile legislator and candidate
pages show a single 2026 cycle, because the live PeachFile feed starts
2026-01-01. This is a war-chest-over-time sparkline already sitting on disk,
one `campaign-finance.js` change from being visible. **[reconciled]** — the
payload review flagged this file as never-fetched dead weight; it is an
opportunity, not waste.

### 3.3 `assets/data/eo-text/` — 17 MB, 3,475 OCR'd executive orders

**[reconciled]**: verified at 17 MB / 3,475 `.txt` files, all tracked (the
payload review undercounted at 5.4 MB / 2,020). Deliberately excluded from the
build at `_config.yml:364` with a comment explaining it is a build-time input
only.

That exclusion is correct for the *files*, but it means a full-text corpus of
every Kemp executive order since 2020 is unreachable. Two features are latent in
it: full-text EO search, and a **gubernatorial appointments tracker** — the text
names appointees, counties, boards and term-expiry dates. Either would need a
derived index (an inverted index or an extracted-appointments JSON), not the raw
text shipped to browsers.

### 3.4 Primary sources discarded at the last step

- `ga-congress-trades.json .trades[].doc_url` — the House Clerk PTR PDF for every
  one of 593 trades, never rendered. Its sibling `comment` turns a
  "$1,001–$15,000 of GE" band into *"sale of 33 shares of GE @ $328.035"* and
  exposes asset classes the ticker hides (crypto, T-bills).
- `ga-executive-orders-*.json .orders[].archiveUrl` — a Wayback permalink
  captured at fetch time for every order. `gov.georgia.gov` rotates document
  URLs and the page currently has no fallback, so links rot with a fix already
  in hand.

### 3.5 Also substantial

- `scotus-decisions.json` carries `question` + `conclusion` — a ready-made
  "Question presented / What the Court held" pair, far better than the one-line
  `description` currently shown — plus `opinions[]` on 87 of 114 cases with
  per-justice authorship. The justice page shows how each justice *voted* but not
  that Kagan wrote the majority.
- `current-members.json .members[].cosponsoredLegislation.count` is present on
  every member while `sponsoredLegislation.count` is rendered. The standard
  "writes bills vs. signs others'" ratio is one stat card away.
- `id-crosswalk.json` (978 KB) is published as a public download and read by
  **zero pages**, despite carrying `candidacies[]` run history, per-identifier
  `provenance`, and free `govtrackId` / `openSecretsId` outbound links.
- Local agendas compute `topicExcerpts`, `matchedTerms` and `itemCount`
  **per meeting**, but `local-subjects.js` reads only the file-level summary — so
  a resident must open a PDF to learn the 13 Oct DeKalb agenda has 126 items,
  3 of them data-center items.
- `ga-legislative-candidates.json` (549 KB, unfetched) carries
  `Date_Qualified__c` and `Declaration__c`, which `races.json` currently
  approximates with hand-set `withdrawn` / `disqualified` booleans.

### 3.6 Consistency risks, not features

- `ga-party-unity.json` is read by exactly one page, while
  `_includes/entity/ga-legislator.html:1072-1094` **recomputes the same metrics
  client-side**. Two implementations of one statistic that can silently drift.
- `presidingOfficer` is absent from the legislator page, which makes the Speaker
  and Lt. Governor read as chronic absentees.

---

## 4. Payload and delivery

Subject to Trap 2 — these are ranked by *gzipped* wire cost and request count,
not raw bytes.

### 4.1 Ship fewer records

| Change | Today | After | Win |
|---|---|---|---|
| `ga-bills.html` list projection | 6.99 MB / 811 KB gz, one request | 1.63 MB / 234 KB gz + detail on demand | −71% gz per visit |
| GA-only `current-members.json` | 1.47 MB, 539 members / 56 states | 124 KB / 19 KB gz, GA's 16 | ×7 call sites |
| `races.json` index/detail split | 1.15 MB; `phases` is 762 KB of the 826 KB body | titles-only index | ×12 call sites |
| Chamber-split `ga-votes-index.json` | 1.14 MB (the member page's whole cost) | 641 / 498 KB | member shard is already only 13 KB |

`current-members.json` is the clearest case: **every** consumer filters
`state === 'Georgia'` in the browser (`congress.js:181`,
`find-my-reps.html:183`). The site ships 523 irrelevant members to use 16.

Per-page totals today: federal legislator 3.44 MB / 7 requests; GA legislator
3.03 MB / 6; sample ballot 2.88 MB / 5.

### 4.2 `ga-member-votes.json` (4.0 MB) is byte-redundant — but do not delete it

**[reconciled].** The payload review called it 100% redundant and recommended
dropping it; that is half right. The redundancy is real: `voteIds` is
byte-identical to `ga-votes-index.json`'s, `votes` differs only by the index
additionally carrying `partyTally` (one key, all 2,418 records), and
`memberVotes` is the same data as the 246 files in `ga-votes/` (3.13 MB). 8.3 MB
committed for 4.3 MB of information, and it is the #2 source of git churn at
11.3 MB of blob revisions in two days.

But `_config.yml:366-372` documents it as a retained **build-time input** with
named consumers — `enrich_bills_with_party_votes.py`, `generate_party_unity.py`,
`publish_ga_legislators.py`, the slice builder — and it is already excluded from
`_site`, so it costs visitors nothing. The orchestration review independently
confirmed `update-ga-bills.yml:68` reads it.

So the work is **repointing those four consumers** at `ga-votes-index.json` plus
the shards, then retiring the file — not deleting it and breaking the pipeline.

### 4.3 Structural compaction (git weight and parse time, not bandwidth)

- The `ga-votes/` shards encode the vote-index position as a quoted dict key per
  cell: 300,165 cells / 3.13 MB = **10.4 bytes per cell for 4 distinct values**.
  A positional string per member re-encodes all 246 shards in 0.59 MB (−2.54 MB).
- `ga-bills.json` stores 32,962 sponsor entries for **245 distinct people** =
  2.05 MB; an id table is ~0.3 MB. Note this is the same structure as 3.1 — the
  id table *preserves* `legisGaGovId`, so the two changes agree.
- Derivable URLs cost ~1.0 MB: `billUrl` from `legislationId`, `id` as
  `"gga-bill/" + legislationId`, EO `archiveUrl` embedding its own `url`.
- 2.69 MB of the 27.8 MB of top-level JSON is pure indentation;
  `id-crosswalk.json` serialises 6,792 null/empty fields (118 KB, 12%);
  `ga-votes-index.json` key names are 349 KB of 1.17 MB (30%).
- Microsecond-precision `generatedAt` forces a new blob every run — confirmed on
  a no-op 263 KB recommit of `ga-members.json`. Second or date precision would
  let the section 2.1 guard work.
- `passageVotes` (804 KB) shadows the vote index but carries no `voteId` (zero
  key intersection), so neither file can shrink until one is added.

Checked and **cleared** — do not "fix" these: campaign-finance current vs.
history have zero id overlap; `bySeat` / `byOffice` views store id lists, not
copies; and `local-X-meetings.json` is **not** removable once the enriched file
exists (enriched drops `agendaUrl` / `minutesUrl` / `videoUrl` and carries fewer
meetings — overlap is only 87 KB, though merging would save 35 requests).

### 4.4 Housekeeping

- **`.gitignore:26-27` lists `current-members.json` and `ga-members.json` while
  both are tracked and committed.** Verified. Stale and actively misleading to
  anyone reasoning about what the pipeline writes.
- Two unoptimised 4.5 MB JPEGs in `assets/img/flock_devices/`.
- ~12 MB (34%) of `assets/data` is never fetched by a browser. Per 3.2/3.3/3.5
  most of that is opportunity or deliberate build input, not garbage — but it
  should be *labelled*, since three reviews reached three different conclusions
  about the same files.
- Genuine dead weight, ~160 KB + change: per-member `api.congress.gov` URLs and
  duplicate timestamps in `current-members.json`; constants
  (`currentMember: true`, `contactInfo.city: "Washington"` × 539); scraper
  bookkeeping (`sha256` / `bytes` / `fetchedAt` across ~2.2 MB of EO JSON,
  `docType` / `sourceType` / `fips` on topic mentions);
  `metadata.gaMembers` duplicating `Object.keys(byMember)`.

### 4.5 Caching

No data fetch is versioned and there is no manifest. JS gets `?v={{ site.time }}`
— invalidating on every build — while the multi-MB JSON gets nothing. GitHub
Pages serves `max-age=600` with an ETag, so a page view can trigger up to six
JSON revalidations. A `manifest.json` of content hashes plus `?v=<hash>` would
make the data immutable-cacheable and is a precondition for the sharding in 4.1
paying off on repeat visits.

---

## 5. Suggested order of work

**Tier 1 — small, high leverage, low risk**

1. `tests.yml` to run the five orphaned test files (2.6). Do this first: it
    guards the logic every later change touches.
2. Fix `.gitignore:26-27` (4.4).
3. Add `only_keys_changed.py` to the unguarded workflows and enforce it in
    `validate_workflow_triggers.py` (2.1).
4. Drop `generatedAt` to second precision so that guard can fire (4.3).
5. Render `doc_url` / `comment` on trades and `archiveUrl` on EOs (3.4) —
    visible value, a few lines each.
6. Retune `update-ga-news` to the deploy cadence; jitter the 14 `:00` crons;
    delete the duplicated enrichment at `update-ga-bills.yml:68` (2.3, 2.4).

**Tier 2 — the real wins**

7. Restore incremental SOAP fetch and the delay default (section 1).
8. `legisGaGovId` join: clickable sponsors, then sponsored-bills on the GA
    legislator page (3.1).
9. GA-only `current-members.json` across its 7 call sites (4.1).
10. `ga-bills.html` index + on-demand detail (4.1).
11. `timeout-minutes` and a shared `concurrency` group across all writers (2.5).

**Tier 3 — larger, decide deliberately**

12. Move data writers to a PAT/App token; make the graph event-driven; retire
     the five dead `publish-*` workflows (2.2).
13. Repoint the four build-time consumers off `ga-member-votes.json`, then
     retire it (4.2).
14. Campaign-finance history sparkline (3.2).
15. Content-hash manifest and versioned data URLs (4.5).
16. Derived index over `eo-text/` — full-text EO search and/or an appointments
     tracker (3.3).
17. Single-source party-unity: delete the client-side recomputation (3.6).

**Do not do:** delete anything named in Trap 1 or in the "cleared" list in 4.3.
