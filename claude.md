# Agent Instructions for votega.org Project

## Scope
These instructions apply only to the votega.org project (a static GitHub Pages Jekyll site). They do not affect other projects or general coding tasks.

## Project Overview
VoteGA.org is a static GitHub Pages Jekyll site for Georgia voter information. It displays federal and state legislators, election info, and civic topics.

**Tech Stack:** Jekyll (Beautiful Jekyll theme) · Congress.gov API · GitHub Actions · Python · JavaScript

**Data Flow:**
```
Congress.gov API → GitHub Actions → Python script → assets/data/*.json → JS lookup → HTML pages
```

## Project Structure

This map shows categories and representative examples, not an exhaustive file list — run `ls` / `Glob` for the current full set. As of 2026-08, the repo has ~35 top-level HTML pages, ~43 tracked scripts (incl. `scripts/lib/`), and 28 GitHub Actions workflows. (Counts drift — `git ls-files` is the source of truth.)

```
votega.org/
├── _config.yml                          # Jekyll + Beautiful Jekyll theme config
├── CLAUDE.md                            # This file
├── README.md / CHANGELOG.md / LICENSE
├── Gemfile / Gemfile.lock               # Ruby dependencies
│
├── 📄 Pages (HTML/Markdown, ~26 top-level)
│   ├── index.html, about.md, 404.html, tags.html, about-the-data.md
│   ├── Federal: my-representatives.html, member.html, federal-reps.html, find-my-reps.html
│   ├── GA Legislature: ga-state-reps.html, ga-member.html,
│   │   ga-bills.html, ga-majority-tracker.html, ga-congress-trades.html
│   ├── Elections/Races: elections-hub.html (/elections nav hub), elections.html (candidate finder),
│   │   race.html (incl. Campaign Finance comparison tab), candidate.html, ga-ballot-measures.html,
│   │   ga-primary-results.html, ga-primary-runoff-results.html, ga-voter-access.html
│   ├── Executive/Judicial: executive-branch.html, executive-member.html, ga-executive.html,
│   │   ga-executive-orders.html, justice.html, supreme-court.html
│   └── Topics: flock-safety.md, flock-covington.md
│
├── _layouts/                            # Jekyll page templates (base, default, home, page, post, minimal)
├── _includes/                           # Reusable components (header, footer, nav, analytics, comments, search)
├── _posts/                              # Blog posts (YYYY-MM-DD-title.md)
├── _data/
│   └── ui-text.yml                      # UI text / localization
│
├── assets/
│   ├── data/                            # Generated JSON/CSV data (committed via GitHub Actions)
│   │   ├── current-members.json         # Federal Congress members (daily, from Congress.gov API)
│   │   ├── ga-members.json              # Georgia state legislators (from Open States API)
│   │   ├── ga-members-overrides.json    # Manual patches/injections applied after Open States fetch
│   │   ├── ga-member-votes.json         # GA passage votes keyed by OCD person ID
│   │   ├── ga-bills.json                # GA bills/resolutions (Open States), enriched with party vote tallies
│   │   ├── curated-ga-bill-votes.json / curated-federal-bills.json  # Editorial "key votes" picks
│   │   ├── races.json / ga-election-calendar.json / ga-ballot-measures.json (+ ga-ballot-measures.schema.json; lifecycle potential→certified→passed/failed, published to Votega/ga-legislation)
│   │   ├── ga-executive-orders-*.json / ga-executive.json / executive.json
│   │   ├── scotus-decisions.json / supreme-court.json / presidential-laws.json / vp-tie-votes.json
│   │   ├── ga-congress-trades.json      # Stock trade disclosures for GA federal delegation
│   │   ├── election-status.json         # Certified/unofficial/upcoming per election (Jekyll-rendered from the results pages' front matter; the live overlay race.html applies to race-results-index.json)
│   │   ├── searchcorpus.json            # Site search index (Jekyll-rendered: posts + static pages)
│   │   └── search-entities.json         # Site search index (entities: members, races, candidates, etc. — built by generate_search_corpus.py)
│   ├── scripts/                         # Client-side JS (loaded by HTML pages) + a few standalone Python utilities
│   │   ├── congress.js                  # Federal lookup: reads current-members.json, filters by state/chamber
│   │   ├── ga.js                        # GA lookup: county→district mapping, reads ga-members.json
│   │   └── campaign-finance.js          # Shared FEC + PeachFile finance lookup/matching (used by race.html + candidate.html; single source of truth for the JS match logic — mirrors scripts/lib/ga_match.py, the Python side's single source, & tools/ga-finance-overrides-editor.html)
│   ├── css/                             # Theme stylesheets (beautifuljekyll.css, bootstrap-social.css, etc.)
│   ├── js/                              # Theme JS (beautifuljekyll.js, staticman.js)
│   ├── img/                             # Images (logo.png, avatar-icon.png, bgimage.png, etc.)
│   └── docs/                            # PDFs (flock_safety_covington_pd_contract.pdf)
│
├── scripts/                             # Build-time data generation (run by GitHub Actions), ~43 tracked
│   ├── generate_current_members_data.py # Congress.gov API → assets/data/current-members.json
│   ├── generate_ga_members_data.py      # Open States API → assets/data/ga-members.json
│   ├── generate_ga_votes_data.py        # Open States API → assets/data/ga-member-votes.json
│   ├── generate_ga_bills_data.py / enrich_bills_with_party_votes.py / generate_curated_ga_bills.py
│   ├── generate_federal_votes_data.py / generate_fec_data.py / generate_ga_congress_trades.py
│   ├── generate_ga_executive_orders.py / generate_scotus_decisions.py / generate_presidential_laws.py / generate_vp_tie_votes.py
│   ├── build_legislative_races.py / build_results_json.py (CSV → _data/election_results/*.json, shared by all results pages)
│   ├── generate_search_corpus.py (entity JSONs → assets/data/search-entities.json for site search)
│   ├── apply_overrides.py / validate_ga_overrides.py / import_legiscan_csv.py / fix_general_fallbacks.py
│   ├── inspect_ga_bill_votes.py / inspect_openstates_fields.py  # diagnostics, each backed by its own workflow
│   └── (one-off/local-machine scripts — e.g. debug_*.py, watch_downloads.py — are gitignored, not tracked)
│
├── .github/workflows/                   # 28 workflows: deploy, per-dataset daily/scheduled updates
│   │                                     # (update-*.yml), and publish-*-to-<sibling-repo>.yml syncs
│   ├── deploy-pages.yml
│   ├── update-current-members.yml       # Daily: runs generate_current_members_data.py, commits JSON
│   ├── update-ga-members.yml            # Daily: runs generate_ga_members_data.py, commits JSON
│   └── sync-generated-data-on-pr.yml
│
├── tools/                                # Standalone editing HTML utilities (not part of the Jekyll site; open locally in a Chromium browser, use the File System Access API to read/write a data file in place)
│   ├── ga-overrides-editor.html          # Two override-file modes: Members (ga-members-overrides.json) + Race candidates (ga-race-candidate-overrides.json, GA state legislative → applied by apply_overrides.py). Its old "Federal challengers" mode is retired — direct races.json editing moved to race-candidate-editor.html
│   ├── ga-member-overrides-editor.html   # Simpler per-field member overrides editor (loads ga-members.json for context)
│   ├── ga-finance-overrides-editor.html  # Resolve ambiguous/no-filing PeachFile finance matches → candidate finance overrides
│   └── race-candidate-editor.html        # Curate candidate profiles directly in races.json (federal & other non-regenerated races have no override layer — edited in place). Syncs a candidate's edits across every phase they appear in (e.g. special + runoff); warns off ga-house-*/ga-senate-* (regenerated — use the overrides file); preserves CRLF/2-space/no-trailing-newline for byte-identical diffs
├── .claude/settings.local.json          # Tool permissions (Congress.gov, GitHub, Python)
├── .vscode/settings.json
└── not in use/                          # Archived/unused files
```

## Core Principles
- **API Key Security First**: Never expose API keys in client-side code. Use build-time generation (GitHub Actions) to fetch data and serve static JSON. If live API calls are needed, implement a proxy.
- **Static Site Best Practices**: Prefer prebuilt data over dynamic fetches to avoid CORS issues and key exposure.
- **Congress.gov API Handling**: Fields are `partyName` (direct), `terms.item[0].chamber` for chamber. Always filter client-side for state/chamber — the API doesn't support direct chamber queries. Note API limitations in UI (e.g., no contact info).
- **Error Handling**: Clear, actionable error messages for users ("Data file missing—run the workflow"). Log errors to console for debugging. Python scripts should `sys.exit(1)` on fatal errors so workflows catch failures.
- **Environment Awareness**: Detect GitHub Pages paths and adjust redirects accordingly.
- **GitHub Actions**: Use secrets for sensitive data. Schedule workflows for daily updates. Validate data integrity (count thresholds + required fields) before committing — never commit based on JSON validity alone.

## Coding Patterns
- **JavaScript**: `async/await` for fetches. `fetch()` over XMLHttpRequest. Constants at top (e.g., `DATA_URL`).
- **Resolve every data/asset URL through `getBasePath()`, never bare-relative.** A `fetch('assets/data/…')` is resolved against the *current page*, so it only works at the site root (legacy `/race.html`, `/candidate.html`). On the clean entity URLs (`/races/<slug>/`, `/ga-legislators/<slug>/`, `/us-congress/<slug>/`, `/candidates/<slug>/`) a bare-relative path resolves *under the entity directory* and 404s silently — the fetch returns not-ok, the loader yields `null`, and the UI shows a false "data unavailable". This is easy to miss because it passes on the root page you're probably testing. Applies especially to **shared JS modules** (`campaign-finance.js` and friends) that run on both root and entity pages — the module must build its own base-path prefix, not assume the page did it. Mirror the `getBasePath()` helper the entity includes already use (returns `/`, or `/votega.org-TEST/` on the test path). Verify any finance/data change on a clean `/races/<slug>/` URL, not just `/race.html?id=…`.
- **HTML**: Semantic elements. Fallback links (e.g., back to search page). Inline scripts for simplicity.
- **Python**: `urllib` for requests (no third-party HTTP libs except where already present). Paginate with `while True` loops. Output clean JSON with a `metadata` object containing at minimum `generatedAt` (ISO timestamp) and `count`. Use `None` for missing optional fields — never empty strings.
- **Python retries**: Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx — these are non-retryable client errors.
- **Workflows**: `ubuntu-latest` runners. Validate output data before committing (count thresholds, required-field spot checks, metadata.count == len(members)).

## Data Schemas

### `current-members.json`
Top-level: `{ metadata: { generatedAt, source, count, apiVersion }, members: [...] }`
Each member: `bioguideId`, `name`, `partyName`, `state`, `district`, `terms.item[]` (chamber via `item[0].chamber`), `depiction.imageUrl`, `leadership[]`, `committees[]`, `contactInfo`, `officialWebsiteUrl`, `birthYear`, `firstName`, `lastName`.
Enriched from `unitedstates/congress-legislators` (public-domain crosswalk, merged in `generate_current_members_data.py`; absent when that member isn't in the crosswalk yet, e.g. a just-seated member): `birthday` (full ISO date), `gender`, `externalLinks[]` (`{label, url}` for Wikipedia/Ballotpedia/OpenSecrets/GovTrack), `socialLinks[]` (`{label, url}` for X/Facebook/Instagram/YouTube). The same repo also backs the deterministic FEC-ID crosswalk in `generate_fec_data.py`.
For GA delegation only: `recentSponsored[]`.

### `ga-members.json`
Top-level: `{ metadata: { generatedAt, source, jurisdiction, count, committeesAvailable }, members: [...] }`
Each member: `id` (OCD `ocd-person/<uuid>`), `name`, `firstName`, `lastName`, `party` (null if unknown), `chamber` (`"Senate"` | `"House of Representatives"` | `"executive"` — see below), `district` (int or null), `title`, `imageUrl`, `phone`, `address`, `email`, `officialWebsiteUrl`, `birthDate`, `birthYear`, `termStart` (ISO date or null), `termStartYear`, `committees[]`, `legisGaGovId` (int or null — needed to join with vote data), `status` (null = active; `"Vacant"` | `"Suspended"` | `"Resigned"` | `"Removed"` | `"Deceased"` if set via overrides), `statusDate`, `statusNote`.
Optional override-only fields: `leadershipRole`, `statusNote`.

**⚠ Not every member is a legislator.** Four statewide executives (Governor, Lt. Governor, Attorney General, Secretary of State) sit in this file under `chamber: "executive"`, with a raw-enum `title` (`"Lt_Governor"`). Anything that means "a member of the General Assembly" must filter on chamber — use `VOTING_CHAMBERS` from `scripts/lib/ga_voters.py` server-side, or an exact chamber-string check client-side (as `ga.js` and `ga-majority-tracker.html` do). Omitting that filter put the Governor in site search as a "GA Legislator" (see CODEBASE-REVIEW-2026-08-18.md 3.2). Executives are surfaced from `ga-executive.json`, not this file.

**`status`** is `null` for a sitting member. `"Resigned"`/`"Removed"`/`"Deceased"` are historical records to filter out; `"Suspended"` members still hold the seat and should stay listed (badged), and `"Vacant"` entries are injected placeholders with synthetic non-OCD ids.

### `ga-members-overrides.json`
Manual patches applied after Open States fetch. Keys are OCD person IDs (`ocd-person/...`) or member full names. Use `_inject` array for entirely new entries (vacant seats). Departure fields: `status`, `statusDate`, `statusNote`. Fields prefixed `_` are stripped before merging.

### `ga-member-votes.json`
Top-level: `{ metadata: { schemaVersion: 2, generatedAt, session, sessionName, source, totalVotes, totalBillsSeen, paginationComplete }, voteIds: [<voteId>, ...], votes: { <voteId>: {...} }, memberVotes: { <ocdPersonId>: { <indexString>: <code> } } }`
Members are joined by OCD person ID — the same `id` field as in `ga-members.json`.

**⚠ Compact schema (v2).** At ~270k rows the old `memberVotes: {pid: [{voteId, vote}]}` form repeated the keys and a 45-char uuid on every entry, making the file ~19 MB — the site's largest blob and top client-fetched file. v2 shrinks it to ~3.6 MB (81%): `voteIds` is an ordered index of vote ids; `memberVotes` values are `{indexString: code}` maps, where the index resolves via `voteIds[i]` and `code` is `Y`/`N`/`O` (full map `Y`/`N`/`NV`/`P`/`A`/`E`/`O` for the Open States options `Yea`/`Nay`/`Not Voting`/`Present`/`Absent`/`Excused`/`Other`; GA data currently only uses Yea/Nay/Other). `votes` is **unchanged** (still keyed by voteId).

**Never hand-decode this.** `scripts/lib/votes_schema.py` is the one codec: `member_votes_map(data)` returns the legacy `{pid: [{voteId, vote}]}` shape from **either** schema (readers use it — `generate_party_unity.py`, `enrich_bills_with_party_votes.py`, `publish_ga_legislators.py`), and `encode_member_votes(mv, list(votes.keys()))` writes v2 (writers use it — `generate_ga_votes_data.py`, `import_legiscan_csv.py`). `_includes/entity/ga-legislator.html` decodes inline (the only client that fetches this file). The **sibling-repo publish keeps the legacy shape** (the publisher expands via the codec), so `Votega/ga-legislators` `votes.json`/`votes.schema.json` are unaffected. `federal-member-votes.json` (0.14 MB) stays legacy and does **not** use this codec. Index order tracks the append-only `votes` dict so quiet incremental runs stay byte-identical (finding 5.6).

### `id-crosswalk.json` + `id-crosswalk-ledger.json`
Top-level: `{ metadata: { schemaVersion, schemaStability, generatedAt, count, scope, sources[], provenanceMethods, coverage }, people: [...] }`
Each person: `vgId` (**may be null**), `name{full,first,last}`, `role{...}` (null for candidate-only records), `ids{...}`, `candidacies[]`, `provenance{...}`.
`ids` carries `ocdPersonId`, `legisGaGovId`, `bioguideId`, `govtrackId`, `openSecretsId`, and the **lists** `fecCandidateIds`, `peachfileFilerEntityIds`, `votegaCandidateIds`.

Built by `scripts/build_id_crosswalk.py` from the roster, finance and races files; it calls no API of its own. Validate with `scripts/validate_id_crosswalk.py`.

`id-crosswalk-overrides.json` holds hand-reviewed decisions, keyed by **OCD person ID, bioguide ID, `peachfile:<id>` or `fec:<id>`** — *not* the races.json candidate ID that `ga-campaign-finance-overrides.json` uses. Pin a filing with `peachfileFilerEntityId`, record a verified non-filer with `peachfileNoFiling`, or merge two ledger keys onto one person with `sameAs`. Every entry needs a `_note` recording how it was confirmed.

**⚠ Never key identity on a races.json candidate ID.** They are positional — `make_candidate_id()` ends them with a row index into the SoS export, so a re-ordered export makes `ga-house-15-2026-d-3` a different person (CODEBASE-REVIEW-2026-08-18.md 5.2). Candidates are keyed on their campaign filing (`peachfile:` / `fec:`) instead; a candidate with no filing gets `vgId: null` rather than an invented ID. The validator fails the build if a positional ID reaches the ledger.

**⚠ `vgId`s are append-only.** `id-crosswalk-ledger.json` is the assignment record; never renumber or remove an entry, or a published `vgId` silently comes to mean a different person. The validator compares against HEAD and fails on any renumbering.

**⚠ A null filing list is not "no filing".** Check `provenance`: `confirmed-none` means a human verified there is none; `no-match` and `ambiguous` mean the join didn't resolve, which is not the same claim.

## GA Overrides System
`assets/data/ga-members-overrides.json` is the mechanism for correcting Open States data and injecting entries (e.g., vacant seats) that Open States doesn't track. When editing:
- Prefer OCD ID keys over name keys for precision.
- Only include fields that need changing — all other fields are preserved from the API.
- Use `_inject` for net-new entries; they must include all required schema fields.
- After changes, re-run `generate_ga_members_data.py` locally or trigger the workflow to regenerate `ga-members.json`.

## Project-Specific Conventions
- **Never commit secrets** — only generated JSON files go back to the repo via workflows.
- **OCD IDs**: GA members use `ocd-person/<uuid>` format. Injected entries (vacant seats) use synthetic IDs like `ga-senate-7-vacant` — these won't match OCD format and won't join to vote records.
- **`legisGaGovId`**: Numeric ID used by legis.ga.gov to construct `officialWebsiteUrl`. Not used for vote joins — those use the OCD person `id`. Members without it get no official website link. New members from Open States may lack it — add via overrides file.
- **UX**: Show loading states, handle empty/null data gracefully, explain API limitations in UI.
- **The open-data catalog is checked, not trusted** — `_data/open_data.yml` drives `/open-data` (a navbar page) but points at artifacts in the sibling repos, so a publisher that moves a file silently turns catalog entries into 404s. That happened: the `sessions/` migration broke three of seven repo links. `scripts/validate_open_data_links.py` resolves every `files[].url` (GitHub blob → `raw.githubusercontent.com`; site-relative → the working tree) and runs in CI weekly and on change. Weekly matters — the breaking change lands in a *different* repo, so a PR-only trigger cannot catch it. When a publisher's output paths change, update the catalog in the same commit.

- **Reuse terms are emitted, never hand-copied** — VoteGA data is published under **CC BY 4.0**. `scripts/lib/sibling_publish.py` injects `LICENSE` (canonical SPDX legalcode, so GitHub detects it) and `NOTICE.md` (the attribution string) into every publish automatically; no publisher needs to opt in and none can omit them. The upstream name comes from `REPO_SOURCES`, keyed by **target repo, not publisher** — two publishers write to `ga-legislation`, and per-publisher sources would rewrite `NOTICE.md` against each other on every run. Adding a new sibling repo means adding it to `REPO_SOURCES`; publishing to an unregistered repo raises rather than emitting an uncredited notice. Do not add a per-dataset license field to `open_data.yml` — the license is stated once on the page and once in the publisher.

- **Each rendered dataset carries its own dated provenance** — a page that mixes data from more than one source must not let a single "last updated" stamp stand in for all of them. Stamp each block from *its own* `metadata.generatedAt` (or the file's own top-level timestamp, e.g. `races.json` uses `updatedAt`, not `metadata`), not from whichever file the page happened to load first. Precedent: a race entity page's bottom stamp reflects `races.json` (the candidate roster), but the Campaign Finance panel's figures come from `ga-fec-data.json` / `ga-campaign-finance.json`, so that panel prints its own line ("Finance data from the FEC, updated …") from the finance data's `generatedAt`. Borrowing the roster stamp for the money figures both understated freshness and named the wrong source. Degrade gracefully: omit the dated line when the timestamp is absent rather than printing a bare or wrong date.
- **Link the published dataset, not the internal asset** — whenever a page renders data we also spin off into a sibling repo (a `publish_*.py` → `Votega/<repo>`), that page's data/source footnote MUST link to the published repo, not the raw `assets/data/*.json` path it happens to fetch. The internal asset is a build artifact (often destructively replaced at a session/cycle rollover); the sibling repo is the stable, archived, multi-format (JSON/CSV/schema) open-data home. Prefer the repo's stablest location for the data on screen (e.g. the matching `sessions/<biennium>/` dir), built from metadata so it self-updates, with a fallback to the repo root. Match how `about-the-data.md` already cites that repo. Precedents: `ga-party-unity.html` → `Votega/ga-legislators`, `ga-executive-orders.html` → `Votega/ga-executive-orders`. Known sibling datasets whose source pages should follow this: ga-federal-legislators, ga-legislators, ga-legislation (bills + ballot measures), ga-executive-orders, ga-races-elections.

## Enforcement
- Check for API key exposure before suggesting any code changes.
- If proposing live API calls, suggest static/build-time alternatives first.
- For new features, verify against Congress.gov API docs and test with sample data.
- When modifying `normalize_member()` in `generate_ga_members_data.py`, ensure all schema fields are present in the output — missing fields cause silent JS failures downstream.
- Do not use empty strings for optional fields — use `None`/`null`.

## Scaling & GitHub limits (REVISIT — findings 2026-09)

Baseline at time of writing (Phase 1 entity pages live, before Phase 2 candidates):
built `_site` ≈ **111 MB**, ~4,200 files, 613 generated entity pages, ~7 s Jekyll build.

Where the caps are and how close we are:
- **Published site size — 1 GB hard.** At ~111 MB (~11%). Phase 2 adds ~707 candidate
  pages (~70 KB each ≈ +50 MB) → ~160 MB. Would take ~9× current content to approach 1 GB.
  Not a concern.
- **Build time / Actions minutes.** Deploy is via GitHub Actions (`actions/jekyll-build-pages`
  + `deploy-pages`), so the legacy "10 builds/hour" Pages soft limit does **not** apply. Public
  repo ⇒ unlimited Actions minutes. Build is seconds. Not a concern.
- **Single file — 100 MB.** Largest is `assets/data/ga-bills.json` ≈ 6 MB (`ga-member-votes.json`
  was ~20 MB before the v2 compact schema took it to ~3.6 MB — see its schema note above). Fine.

First ceilings we would actually hit (in order):
1. **Bandwidth — 100 GB/month soft.** Not from HTML (tiny) but from the big client-fetched
   JSON: `ga-member-votes.json` (~3.6 MB since the v2 compact schema, down from ~20 MB) +
   `ga-bills.json` (~6 MB, minified). The v2 compaction cut the worst offender ~5×; further
   mitigation if needed = slice/paginate these blobs (also the outstanding Core Web Vitals item).
   GitHub warns before throttling.
2. **Git history bloat.** The `update-*` workflows commit these JSON files, but git delta-
   compresses them in the packfile, so the reality is far milder than a naive
   "full-file-per-commit" projection: measured, the two big files' entire history was only
   ~10 MB on disk and `.git` packs to ~56 MB. The v2 compaction (and the `ga-bills.json` minify)
   shrink each future commit further. If history ever does approach a few GB, options are **Git
   LFS** or **generate-at-deploy** for the big blobs — but at current sizes neither is justified
   (a history rewrite would recover single-digit MB at high risk).

Bottom line: safe through Phase 2. The compaction bought a large margin on both bandwidth and
history; revisit only before a big traffic spike or if `.git` actually trends toward GitHub's ~5 GB warning.
