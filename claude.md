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
│   │   ├── ga-members.json              # Georgia state legislators (legis.ga.gov SOAP Members
│   │   │                                #   service; canonical since 2026-10 — OS producer retired
│   │   │                                #   to generate_ga_members_data.py, still runnable)
│   │   ├── ga-openstates-crosswalk.json # legisGaGovId → ocdPersonId/ballotpediaId sidecar (monthly, from the CC0
│   │   │                                #   openstates/people repo); merged into the roster as nullable slots
│   │   ├── ga-members-overrides.json    # Editorial patches/injections applied after the fetch —
│   │   │                                #   the ONLY place departures/vacancies live
│   │   ├── ga-member-votes.json         # GA passage votes keyed by OCD person ID
│   │   ├── ga-bills.json                # GA bills/resolutions (Open States), enriched with party vote tallies
│   │   ├── curated-ga-bill-votes.json / curated-federal-bills.json  # Editorial "key votes" picks
│   │   ├── races.json / ga-election-calendar.json / ga-ballot-measures.json (+ ga-ballot-measures.schema.json; lifecycle potential→certified→passed/failed, published to Votega/ga-legislation)
│   │   ├── ga-executive-orders-*.json / ga-executive.json / executive.json
│   │   ├── scotus-decisions.json / supreme-court.json / presidential-laws.json / vp-tie-votes.json
│   │   ├── ga-congress-trades.json      # Stock trade disclosures for GA federal delegation
│   │   ├── election-status.json         # Certified/unofficial/upcoming per election (Jekyll-rendered from the results pages' front matter; the live overlay race.html applies to race-results-index.json)
│   │   ├── federal-sponsorship-index.json / federal-sponsorship/<bioguideId>.json
│   │   │                                # GA federal delegation's complete sponsored +
│   │   │                                # cosponsored record for the current Congress
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
│   │                                     # + federal-sponsorship-index.json & federal-sponsorship/
│   │                                     # (GA delegation's complete sponsored + cosponsored
│   │                                     # record, via lib/federal_sponsorship.py)
│   ├── generate_ga_members_soap.py      # legis.ga.gov SOAP → ga-members.json (canonical since
│   │                                     # 2026-10; no API key, no quota). generate_ga_members_data.py
│   │                                     # is the retired Open States producer, kept for rollback
│   ├── generate_ga_votes_soap.py        # legis.ga.gov SOAP (official) → ga-member-votes.json (canonical since 2026-10; OS producer retired to scripts/archive/generate_ga_votes_data.py)
│   ├── generate_ga_bills_soap.py (legis.ga.gov SOAP → ga-bills.json; canonical since 2026-10, OS producer retired to scripts/archive/generate_ga_bills_data.py; subjects via ga-bills-subjects-base.json overlay) / enrich_bills_with_party_votes.py / generate_curated_ga_bills.py (curated key votes; reads the committed SOAP artifacts, SOAP-fetches only a session they do not cover — no Open States, no API key, canonical since 2026-10)
│   ├── generate_federal_votes_data.py / generate_fec_data.py / generate_ga_congress_trades.py
│   ├── generate_ga_executive_orders.py / generate_scotus_decisions.py / generate_presidential_laws.py / generate_vp_tie_votes.py
│   ├── build_legislative_races.py / build_results_json.py (CSV → _data/election_results/*.json, shared by all results pages)
│   ├── generate_search_corpus.py (entity JSONs → assets/data/search-entities.json for site search)
│   ├── apply_overrides.py / validate_ga_overrides.py / import_legiscan_csv.py / fix_general_fallbacks.py
│   ├── generate_legis_sessions.py       # Session/GetSessions → ga-legis-sessions.json (every
│   │                                     # session back to 2001; legis_session_id() reads it,
│   │                                     # so session ids are never hand-maintained or probed)
│   ├── lib/congress_session.py          # which Congress is sitting, derived from the date
│   │                                     # (never a literal; $CONGRESS overrides for a backfill).
│   │                                     # All four federal generators read it
│   ├── lib/federal_sponsorship.py       # paginated Congress.gov sponsored/cosponsored fetch
│   │                                     # (injected fetcher, so it is testable with no API key)
│   │                                     # + the index/slice writer
│   ├── lib/ga_roster.py                 # roster field shaping + the editorial overrides layer
│   │                                     # (apply_member_overrides — departures/vacancies)
│   ├── lib/ga_soap.py                   # shared legis.ga.gov SOAP client (no auth, no quota):
│   │                                     # GetVotes listings (incl. the authoritative chamber +
│   │                                     # rollNumber), GetVote detail keyed on legisGaGovId
│   ├── inspect_ga_bill_votes.py / inspect_openstates_fields.py  # diagnostics, each backed by its own workflow
│   └── (one-off/local-machine scripts — e.g. debug_*.py, watch_downloads.py — are gitignored, not tracked)
│
├── .github/workflows/                   # 28 workflows: deploy, per-dataset daily/scheduled updates
│   │                                     # (update-*.yml), and publish-*-to-<sibling-repo>.yml syncs
│   ├── deploy-pages.yml
│   ├── update-current-members.yml       # Daily: runs generate_current_members_data.py, commits JSON
│   ├── update-ga-members.yml            # Daily: runs generate_ga_members_soap.py, commits JSON
│   └── sync-generated-data-on-pr.yml
│
├── tools/                                # Standalone editing HTML utilities (not part of the Jekyll site; open locally in a Chromium browser, use the File System Access API to read/write a data file in place)
│   ├── ga-overrides-editor.html          # Two override-file modes: Members (ga-members-overrides.json) + Race candidates (ga-race-candidate-overrides.json, GA state legislative → applied by apply_overrides.py, which CI runs on push via apply-race-candidate-overrides.yml; `--check` guards PRs). Its old "Federal challengers" mode is retired — direct races.json editing moved to race-candidate-editor.html
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
- **Congress.gov API Handling**: Fields are `partyName` (direct), `terms.item[-1].chamber` (the most recent term; terms run oldest → newest) for chamber. Always filter client-side for state/chamber — the API doesn't support direct chamber queries. Note API limitations in UI (e.g., no contact info).
- **Error Handling**: Clear, actionable error messages for users ("Data file missing—run the workflow"). Log errors to console for debugging. Python scripts should `sys.exit(1)` on fatal errors so workflows catch failures.
- **Environment Awareness**: Detect GitHub Pages paths and adjust redirects accordingly.
- **GitHub Actions**: Use secrets for sensitive data. Schedule workflows for daily updates. Validate data integrity (count thresholds + required fields) before committing — never commit based on JSON validity alone.

## Coding Patterns
- **First-party JS/CSS is cache-busted; keep the `?v=` suffix on every new script tag.** Every `{{ '/assets/scripts/*.js' | relative_url }}` reference carries `?v={{ site.time | date: '%s' }}`, so a new build's HTML always requests a URL the browser/edge cache doesn't hold — HTML and its JS can never be mismatched. This exists because `votega-core.js` is edge- and browser-cached for 4h (`max-age=14400`): shipping HTML that called a new global (`VotegaPortraits`) added by an as-yet-uncached `votega-core.js` `ReferenceError`'d and blank-screened every entity page, and a Cloudflare purge can't reach a returning visitor's already-cached JS. When you add a first-party `<script>`/stylesheet tag, append the same `?v={{ site.time | date: '%s' }}` (see `_includes/head.html`); theme/vendored assets (`/assets/js/*`, beautifuljekyll/bootstrap-social/staticman css) are intentionally left unversioned. Belt-and-suspenders: still guard bare references to any newly-added `votega-core.js` global with `window.X ? …`.
- **JavaScript**: `async/await` for fetches. `fetch()` over XMLHttpRequest. Constants at top (e.g., `DATA_URL`).
- **Resolve every data/asset URL through `getBasePath()`, never bare-relative.** A `fetch('assets/data/…')` is resolved against the *current page*, so it only works at the site root (legacy `/race.html`, `/candidate.html`). On the clean entity URLs (`/races/<slug>/`, `/ga-legislators/<slug>/`, `/us-congress/<slug>/`, `/candidates/<slug>/`) a bare-relative path resolves *under the entity directory* and 404s silently — the fetch returns not-ok, the loader yields `null`, and the UI shows a false "data unavailable". This is easy to miss because it passes on the root page you're probably testing. Applies especially to **shared JS modules** (`campaign-finance.js` and friends) that run on both root and entity pages — the module must build its own base-path prefix, not assume the page did it. Mirror the `getBasePath()` helper the entity includes already use (the site is served at the domain root, so it returns `/`; see `assets/scripts/votega-core.js`). Verify any finance/data change on a clean `/races/<slug>/` URL, not just `/race.html?id=…`.
- **HTML**: Semantic elements. Fallback links (e.g., back to search page). Inline scripts for simplicity.
- **Python**: `urllib` for requests (no third-party HTTP libs except where already present). Paginate with `while True` loops. Output clean JSON with a `metadata` object containing at minimum `generatedAt` (ISO timestamp) and `count`. Use `None` for missing optional fields — never empty strings.
- **Python retries**: Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx — these are non-retryable client errors.
- **Workflows**: `ubuntu-latest` runners. Validate output data before committing (count thresholds, required-field spot checks, metadata.count == len(members)).

## Data Schemas

### `current-members.json`
Top-level: `{ metadata: { generatedAt, source, count, apiVersion }, members: [...] }`
Each member: `bioguideId`, `name`, `partyName`, `state`, `district`, `terms.item[]` (chamber via the last item: `item[-1].chamber` — terms run oldest → newest, so `item[0]` is a House-to-Senate member's first chamber), `depiction.imageUrl`, `leadership[]`, `committees[]`, `contactInfo`, `officialWebsiteUrl`, `birthYear`, `firstName`, `lastName`.
Enriched from `unitedstates/congress-legislators` (public-domain crosswalk, merged in `generate_current_members_data.py`; absent when that member isn't in the crosswalk yet, e.g. a just-seated member): `birthday` (full ISO date), `gender`, `externalLinks[]` (`{label, url}` for Wikipedia/Ballotpedia/OpenSecrets/GovTrack), `socialLinks[]` (`{label, url}` for X/Facebook/Instagram/YouTube). The same repo also backs the deterministic FEC-ID crosswalk in `generate_fec_data.py`.
For GA delegation only: `recentSponsored[]` (the 20 most recently introduced bills this member sponsored this Congress — a convenience slice, republished to the sibling repo) and `sponsorship` (`{congress, sponsored, cosponsored}`, or `null` if that run's fetch failed).

**⚠ The COMPLETE sponsorship record is not in this file.** It lives in `federal-sponsorship-index.json` + `federal-sponsorship/<bioguideId>.json` (below). current-members.json is fetched by `federal-reps.html`, `find-my-reps.html`, `my-representatives.html` and every `/us-congress/<slug>/` page, so the delegation's ~27k sponsorship rows inline there would be paid for by every visitor to read one member's panel. `sponsorship` is the two integers the entity page needs *before* any slice fetch, to decide whether the Sponsored Legislation tab appears at all.

### `federal-sponsorship-index.json` + `federal-sponsorship/<bioguideId>.json`
Written by `scripts/lib/federal_sponsorship.py`, called from `generate_current_members_data.py` in the same run as the roster (so the roster's inline counts and the slices can never disagree on the deployed site). Scope is the **16-member Georgia delegation**, the only scope the site renders.

Index: `{ metadata: { generatedAt, source, congress, scope, memberCount, totalSponsored, totalCosponsored }, members: { <bioguideId>: [nPrimary, nCosponsored] } }`.
Slice: `{ bioguideId, congress, actions[], policyAreas[], primary[], cosponsored[] }`, where each row is positional — `[type, number, title, introducedDate, actionDate, actionIdx, policyIdx]`, the last two indexing the slice's own intern tables. `billUrl` is omitted and rebuilt client-side from congress+type+number. Mirrors `build_sponsorship_slices.py`; `_includes/entity/federal-legislator.html` carries the matching `R_*` constants and `BILL_TYPE_SLUG` — keep the two in step.

**⚠ Never read these endpoints as a single page.** `/member/{bioguide}/sponsored-legislation` has no `congress=` filter and is **not** ordered newest-Congress-first, so the old `?limit=20`-then-filter call both truncated the record and sampled it arbitrarily: off the same 20-row page, Sen. Warnock surfaced 3 bills and Sen. Ossoff 14. `fetch_member_legislation()` walks every page (limit=250, `pagination.next` with an offset fallback) and filters afterwards.

**⚠ A failed page discards the whole member's list.** `fetch_member_legislation()` returns `None` rather than a short list, the member is then left out of the slice writer, and their inline `sponsorship` is `null` — because once written, a truncated list is indistinguishable from a real one and would publish as fact that a member sponsored less than they did. The entity page reads a `null` summary as "no tab", never as "sponsored nothing".

**⚠ A missing slice means different things depending on the inline counts.** Counts present and zero = the genuine empty record; counts absent = a roster written before the slices existed (the window between a deploy and the next daily run), which is NOT "sponsored nothing"; counts non-zero = a real failure. The panel says which.

Request cost of a full delegation refresh: ~131 pages (18 sponsored + 113 cosponsored, set by the delegation's career totals — these endpoints page the whole career), against Congress.gov's documented 5,000 requests/hour. `scripts/test_federal_sponsorship.py` pins the pagination and slice invariants with a fake API and no network.

### `federal-member-votes.json` + `federal-votes-index.json` + `federal-votes-keyvotes.json` + `federal-votes/<bioguideId>.json`
Written by `generate_federal_votes_data.py`, then split by `build_federal_votes_slices.py`. Scope is every recorded roll call of the current Congress, joined to the 16-member Georgia delegation.

Monolith: `{ metadata: { generatedAt, congress, sessionName, source, scope, totalVotes, houseVotes, senateVotes, billLessVotes, memberCount, updateMode, rollCallsFetchedThisRun, sittingDelegation, sittingMembersWithVotes, staleVoteRecords }, votes: { <voteId>: {...} }, memberVotes: { <bioguideId>: [{voteId, vote}] } }`. Each vote: `bill`, `billUrl`, `billType`, `billNumber`, `title`, `motionText`, `date`, `yea`, `nay`, `chamber`, `session`, `rollNumber`, `result`, `partyTally`. Vote ids are `H<year>_<nnnn>` (House) and `S<congress>_<session>_<nnnnn>` (Senate).

**The universe is the chambers' own indexes, NOT enacted laws.** This script used to drive off Congress.gov `/v3/law/{congress}`, walking each enacted law's `/actions` for the roll-call URLs they referenced — so the frame was "roll calls attached to bills that became law" and could not, by construction, see a failed bill, an amendment, a nomination or any procedural vote. Measured 2026-10-14 that was **216 of 1,591 real roll calls (13.6%)**, giving a House member a party-line denominator of 42. Now: the Senate's per-session index `vote_menu_<congress>_<session>.xml` lists every vote number (two fetches enumerate the chamber), and the House's `clerk.house.gov/evs/<year>/roll<nnn>.xml` is walked per calendar year. Needs **no Congress.gov API key at all** — the key is off this job's critical path. Congress.gov's beta `/house-vote` family does not help: House-only and also legislation-associated.

**⚠ A missing House roll is an HTTP 200, not a 404.** A nonexistent number returns `<xml>Error sanitizing file "roll700.xml". Please try again.</xml>` with status 200, so a walk-until-404 loop never terminates and ingests that error body as a vote. `looks_like_house_vote()` decides on CONTENT, reading several KB (the XML declaration alone is 38 bytes, the error body 65) before looking for the `rollcall-vote` element; the walk stops only after `MISS_STREAK` *consecutive* absences, because one gap is not the end of the year.

**⚠ `bill` and `billUrl` are null on a large, normal share of the record.** A quorum call, a motion to adjourn and a Senate nomination are associated with no measure — about a third of the corpus. Never `""` (CLAUDE.md's optional-field rule); every consumer must render a bill-less row, and the enacted-law connector must simply yield nothing for one rather than joining on an empty key.

**⚠ Never read the result as pass/fail with a single keyword.** The chambers write "Passed", "Agreed to", "Adopted", "Nomination Confirmed", "Amendment Rejected", "Cloture Motion Agreed to". The old House branch tested only for `"pass"`, so every "Agreed to" roll call published as a FAILURE — H.Res. 1014 of 2026 (427-0, Agreed to) rendered as "Failed". The enacted-law frame hid it because resolution and amendment votes almost never reached it. `pass_fail()` is the one implementation; unrecognized wording is reported at the end of a run rather than silently bucketed.

**Incremental by default.** A full build is ~1,591 fetches (~20 min at `XML_DELAY`); a normal run reuses every roll call already in the committed file and fetches only the missing ones, so the weekly workflow costs a few dozen requests and its commit is empty on a quiet week. Enumeration order is deterministic, so a no-op run is byte-identical apart from the run-scoped metadata (which `only_keys_changed.py` is given alongside `generatedAt`). `--full-refresh` re-fetches everything.

Index: `{ metadata (+sliceFormat), voteIds[], motions[], rows[] }`, `rows[i]` positional for `voteIds[i]` — `[chamber, date, billType, billNumber, title, motionIdx, result, yea, nay, tally]`, where `chamber` is `H`/`S`, `result` is `P`/`F`, `motionIdx` indexes the `motions` intern table and `tally` is six flat ints `[dYea, dNay, dOther, rYea, rNay, rOther]`. `bill` and `billUrl` are **omitted and rebuilt client-side** from type+number. Slice: `{ bioguideId, compact: { <indexString>: <code> } }`, codes from `lib/votes_schema.py`. `_includes/entity/federal-legislator.html` carries the matching `FV_*` constants, `FED_BILL_LABEL` and `FED_VOTE_CODE` — `scripts/test_federal_votes_slices.py` fails the build if any of the four drift.

**The monolith deliberately stays on the LEGACY vote schema while the SLICES use the codec.** `publish_federal_delegation.py` passes the monolith straight through to `Votega/ga-federal-legislators`, so its shape is a published contract, and the party-unity generator that will read it is server-side where size is free. Compaction only has to happen on the wire, which is what the index and slices are: the page fetches a small key-votes sidecar + one ~7 KB slice instead of a ~1.2 MB blob (which it previously fetched *twice*, once for Key Votes and once for Voting History).

**⚠ The full index is NOT what a page load fetches — the key-votes sidecar is.** `federal-votes-keyvotes.json` holds only the roll calls `curated-federal-bills.json` names (15 of 1,591), in the same positional row format with its own interned motion table, so `hydrateVoteIndex()` decodes it unchanged. It exists because Key Votes is the DEFAULT tab: reading those 15 votes out of the full index cost every visitor 291 KB raw / 55 KB gzip, against 3.1 KB / 1.3 KB for the sidecar. The full index is now fetched lazily by `activateTab()`, only when Voting History is opened — which is also why `currentMember` must be set BEFORE `initTabs()`, or a `#votingHistory` deep link fires `activateTab` with a null member and the panel never loads.

**⚠ The sidecar's `indices` are positions in the FULL `voteIds` list, and must stay so.** A member's slice is keyed on that position, so the sidecar has to carry it to resolve how this member voted on a curated roll call without the full list; carrying the whole `voteIds` array instead was measured at 5.4 KB gzip against 1.4 KB for `indices`. An off-by-one there is valid JSON of the right length that shows one roll call's record under another's heading — so `scripts/test_federal_votes_slices.py` pins the alignment and `scripts/validate_federal_votes.py` re-checks it on the committed artifacts (pass the sidecar and the curated file as its 4th and 5th arguments).

### `presidential-executive-orders.json`
Written by `scripts/generate_presidential_executive_orders.py` (twice daily, `update-presidential-executive-orders.yml`), read by `loadExecOrders()` in `_includes/entity/federal-executive.html` — the browser no longer calls the Federal Register for this. Top-level: `{ metadata: { generatedAt, termStart, count, federalRegisterCount, provisionalCount, whitehouseFeed, expiredProvisional[], duplicateRegisterRecords[], matchedByNumber[], numberConflicts[] }, orders: [...] }`. Each order mirrors the Federal Register field names (`document_number`, `executive_order_number`, `title`, `signing_date`, `abstract`, `html_url`) plus `whitehouse_url` and `provisional`.

**⚠ Two sources, reconciled at build time, never in the browser.** The Register publishes an order 3–5 days after signing; whitehouse.gov's Presidential Actions RSS has it the day it is signed. An order only whitehouse.gov has is `provisional: true` with `executive_order_number`/`document_number` null (the page prints `EO #: PENDING` and links whitehouse.gov). When the Register publishes it the record is replaced by the Register's, which **keeps `whitehouse_url`** as provenance. Fewer Register orders than the White House has announced is the normal lag, never a validation failure.

**⚠ The join is the normalized title** (lowercase, alphanumerics only), within 7 days of signing, plus an EO-number cross-check where whitehouse.gov has one: once an order is numbered its page gains an attached `uploads/.../eo-NNNNN.pdf` (≈9 of 11 items; read as `claimed_number`, **never parse numbers out of the body text — those cite other orders**). A claimed number outranks the title: it rescues a reworded title (`matchedByNumber`) and vetoes a title match to a different order (`numberConflicts`). A provisional entry unmatched after 14 days is dropped into `expiredProvisional` — that means matching broke, so the validator reports it.

**⚠ `pubDate` is not the signing date** (an order signed after ~8pm ET posts after midnight UTC). The signature block (`THE WHITE HOUSE, October 16, 2026.`) is authoritative; `pubDate` converted to US Eastern is the fallback. The feed's `content:encoded` opens with site-nav markup — only `<p class="wp-block-paragraph">` text is the order, and the `By the authority vested in me…` / `Section 1. Purpose.` lead-in is stripped before taking an abstract. Titles can contain U+FFFD where an apostrophe was.

**⚠ The Register republishes corrected orders under an `R1-` document number** (EO 14388 appears twice); `dedupe_register()` keeps the original. Failure policy: the Register is required (exit 1, file untouched); a whitehouse.gov outage carries the previous file's provisional entries forward. `validate_presidential_executive_orders.py` is tier 1 (self-contradiction, gates) / tier 2 (changes, reports); tests in `scripts/test_presidential_executive_orders.py`. The department-rules tab on the same page was migrated the same way (see `agency-actions-index.json`).

### `agency-actions-index.json` + `agency-actions/<slug>.json`
Written by `scripts/generate_agency_actions.py` (daily, `update-agency-actions.yml`), read by `loadAgencyActions()` in `_includes/entity/federal-executive.html` for a Cabinet member's department. Index: `{ metadata, departments: { <department name as in executive.json>: { agencyId, slug, file, count } } }`. Slice: `{ metadata: { generatedAt, department, agencyId, slug, termStart, count }, documents: [{ document_number, title, type ("Rule" | "Proposed Rule"), publication_date, html_url, abstract }] }` — every final and proposed rule since the term began. `lib/federal_register.py` is the shared paged fetch (also used by the executive-orders generator).

**⚠ The department → Federal Register id map lives in the generator, nowhere else** (the page resolves through the index). It verifies every id against `agencies.json` on each run and exits 1 on a mismatch, because a wrong id would silently publish another agency's rules. The Office of the Director of National Intelligence has no Register entry and is absent on purpose.

**⚠ Always date-filter this query.** The page used to ask for a department's whole history and printed "Showing 20 of 10000" — 10,000 is the API's cap on `count`, not a number of rules. Term-scoped USDA is 224.

**⚠ A publication date can be in the future.** The Register lists documents on public inspection under their scheduled date (a Saturday run sees Monday's), so the validator tolerates up to 7 days ahead and the page says "Scheduled to publish". A strict "not in the future" check failed real data on its first run.

Sizing, measured 2026-10-17 (why it is sliced): 5,509 rules across 16 departments, ~1 MB gzipped if combined; slices 8–114 KB gzipped, Transportation 371 KB (2,191 rules, 1,046 of them FAA airworthiness directives). Abstracts are ~80% of the bytes and are kept in full. If Transportation's weight becomes a problem, truncate abstracts or lazy-load the tab before adding more machinery. `generatedAt` is preserved when a department's rules are unchanged, so a quiet day commits nothing. Tests: `scripts/test_agency_actions.py`.

### `ga-members.json`
Produced by `generate_ga_members_soap.py` from legis.ga.gov's **Members** service (canonical since 2026-10; no API key, no quota).

Top-level: `{ metadata: { generatedAt, source, jurisdiction, session, legisSessionId, count, committeesAvailable, carriedForward, withoutOcdId, preservedNotInMembersService, overridesApplied, overridesInjected }, members: [...], review: {...} }`
Each member: `id` (see below), `name`, `firstName`, `lastName`, `party` (null if unknown), `chamber` (`"Senate"` | `"House of Representatives"` | `"executive"` — see below), `district` (int or null), `title` (derived from `chamber`), `imageUrl`, `phone`, `address`, `email`, `officialWebsiteUrl`, `birthDate`, `birthYear`, `termStart` (ISO date or null), `termStartYear`, `committees[]`, `legisGaGovId` (int or null), `status` (null = active; `"Vacant"` | `"Suspended"` | `"Resigned"` | `"Removed"` | `"Deceased"` if set via overrides), `statusDate`, `statusNote`.
From the SOAP service: `leadershipRole` (normalized by `lib/ga_leadership.py`), `committeeRoles[]` (`{name, role}`), `occupation`, `residence`, `pressUrl`, `birthdayMonthDay`, `dateVacated`, `termStartSession`.

**⚠ `id` is an OPAQUE HANDLE — `legisGaGovId` is the primary key.** `id` is "the stable string this member was first assigned, which never changes and which nothing may parse or interpret." It is the join key into `ga-member-votes.json`'s `memberVotes` and the legacy key in `id-crosswalk-ledger.json`, and that is ALL it means. **It is heterogeneous:** 247 values are OCD-shaped (`ocd-person/<uuid>`, carried over from the Open States era), a member Open States had not catalogued is `legis-<legisGaGovId>`, and an `_inject`ed placeholder is synthetic (`ga-senate-7-vacant`). Never test `id.startswith("ocd-person/")` to ask "does this person have an OCD id" — read `ocdPersonId`. An `id` is assigned once and never changes (the producer refuses to write if any `legisGaGovId → id` pair moves, because re-keying breaks the member's vote join and their append-only `vgId`); do not migrate the existing values. `legisGaGovId` is official, collision-proof, direct from the source and back to 2001 — the one identifier that makes this data joinable, and published by nobody else.

**Identity slots (additive, nullable): `ocdPersonId`, `ballotpediaId`, with `idProvenance` beside them.** Cross-references that are stable, 1:1 and properties of the person, and that land WHENEVER they arrive without re-keying anything. They are never load-bearing for identity. `ocdPersonId` is an OCD person id **or null — never the roster `id`** (the validator rejects anything else). Provenance reuses the id-crosswalk vocabulary (`method` / `source` / `confidence`) so a null is never a bare claim: `confidence: "no-match"` = we looked and the source has no record; `"ambiguous"` (+`candidates`) = more than one fit, none picked; `method: "unresolved"` = no lookup has run yet; `"out-of-scope"` = no `legisGaGovId` (executives, vacancies). Written by `lib/ga_identity.py::apply_identity_slots` from the sidecar `ga-openstates-crosswalk.json` (below), called by the roster producer so it stays the one writer of this file. A pre-existing OCD-shaped `id` is *carried* into `ocdPersonId` (copied, never derived) until the resolver answers. **There is deliberately no `wikidataId` slot:** no source we read carries one, so it shipped on all 251 members and was never populated; it was dropped (2026-10-19) rather than published as a permanently empty column — re-add it with the first source that has it. A human can resolve an `ambiguous` slot with a `pinSlots` override (see `id-crosswalk-overrides.json` below), applied by `lib/ga_identity.py` in the roster producer and again by the crosswalk builder. **FEC and PeachFile ids are deliberately NOT roster fields:** they are lists, cycle-dependent and produced by matching, and `id-crosswalk.json` already models them with provenance — the roster links to it by `legisGaGovId`.

**⚠ Four fields the service cannot supply, preserved from the committed file.** `birthDate`/`birthYear` (it has a birthday with no year, so it cannot yield an age), `termStart` (it has the earliest session served, not a date), and `name`/`firstName`/`lastName` — it returns the FORMAL name where the site publishes the common one (`Timothy Bearden` vs `Tim Bearden`). 18 members differ; applying the formal name would move their entity URL, since `build_entity_pages.py` slugs on the name. Divergences are reported in `review.nameDiffersFromLegis`, never applied — a real rename is an editorial decision with a redirect attached. `email` falls back to the committed value for the 2 members the service has none for.

**⚠ The producer proposes; a human disposes.** It never writes `status` — see the overrides file. `review` carries the queues it declined to act on: `vacatedWithoutStatusOverride`, `vacatedDateDiffersFromOurs`, `nameDiffersFromLegis`, `lapsedLeadershipTitles`, `leadershipNeedsReview`, `carriedForward`, `notInCommittedRoster`, `preservedNotInMembersService`. Check it after a roster change rather than trusting a clean run.

**⚠ Not every member is a legislator.** Four statewide executives (Governor, Lt. Governor, Attorney General, Secretary of State) sit in this file under `chamber: "executive"`, with a raw-enum `title` (`"Lt_Governor"`). Anything that means "a member of the General Assembly" must filter on chamber — use `VOTING_CHAMBERS` from `scripts/lib/ga_voters.py` server-side, or an exact chamber-string check client-side (as `ga.js` and `ga-majority-tracker.html` do). Omitting that filter put the Governor in site search as a "GA Legislator" (see CODEBASE-REVIEW-2026-08-18.md 3.2). Executives are surfaced from `ga-executive.json`, not this file.

**`status`** is `null` for a sitting member. `"Resigned"`/`"Removed"`/`"Deceased"` are historical records to filter out; `"Suspended"` members still hold the seat and should stay listed (badged), and `"Vacant"` entries are injected placeholders with synthetic non-OCD ids.

### `ga-members-overrides.json`
The editorial layer, applied by `apply_member_overrides` in `scripts/lib/ga_roster.py` — **the single implementation; any roster producer must call it.** Keys are OCD person IDs (`ocd-person/...`) or member full names. Use the `_inject` array for entirely new entries. Departure fields: `status`, `statusDate`, `statusNote`. Fields prefixed `_` are stripped before merging.

**⚠ This is the only thing that knows a member has left.** No roster source has the concept — legis.ga.gov records who holds a seat, not who vacated one. Skip this step and 11 Resigned + 1 Suspended members read as sitting, and `ga-majority-tracker.html` paints their seats as filled.

**⚠ An `_inject` entry for a member the source now returns is MERGED, not skipped.** The source's facts win, but the editorial `status`/`statusDate`/`statusNote` are layered on top, because they exist nowhere else. This is not a detail: Open States dropped departed members, so their `Resigned` lived only inside `_inject`, while legis.ga.gov returns all 247 who served the biennium — a plain skip silently promoted all 11 back to sitting. An explicit patch entry still outranks the merge.

**⚠ Overrides are biennium-scoped by `_session`.** A departure describes a seat of ONE General Assembly, so every entry carrying `status`/`statusDate`/`statusNote` (an `_inject` entry or an id/name patch) has `"_session": "2025_26"` (the roster's regular-session tag). `apply_member_overrides(..., session=tag)` skips entries tagged for another biennium, and `validate_ga_members.py` tier 1 demands only the in-scope `_inject` entries in the output — so stale entries go inert at a rollover instead of hard-blocking it. Untagged entries apply everywhere, and the rollover run refuses while a departure is untagged.

**⚠ A biennium rollover is never the daily run's job.** `generate_ga_members_soap.py` compares the session it would build to `metadata.session`/`legisSessionId` in the committed file; on a mismatch it exits 1 and says so (otherwise the preserve-verbatim rule would republish the whole outgoing class as sitting and trip tier 1 every morning). `--new-biennium` (the `update-ga-members` dispatch input) performs it: requires the outgoing roster published by `freeze-ga-roster`, drops non-returning members, keeps the non-voting-chamber records (Lt. Governor), stamps `metadata.rollover`, adds the `incomingCohort`/`departingCohort`/`newMemberNameReview` queues to `review`, and derives a first-termer's `termStart` as the convening date. A different biennium with no stamp fails tier 1. Procedure and the 2027-01-11 deadline: RECURRING-TASKS.md §3.

### `ga-member-votes.json`
Top-level: `{ metadata: { schemaVersion: 2, generatedAt, session, sessionName, source, totalVotes, totalBillsSeen, paginationComplete }, voteIds: [<voteId>, ...], votes: { <voteId>: {...} }, memberVotes: { <roster id>: { <indexString>: <code> } } }`
Members are joined by the roster's opaque `id` — the same field as in `ga-members.json` (OCD-shaped for most, `legis-<n>` for a member Open States has not catalogued; never interpret it).

Each `votes[<voteId>]`: `bill`, `billUrl`, `title`, `session`, `motionText`, `chamber`, `rollNumber`, `time`, `excused`, `notVoting`, `date`, `yea`, `nay`, `vacant` (omitted when 0), `result`. `chamber`, `rollNumber`, `time`, `excused` and `notVoting` come straight off the SOAP `GetVotes` listing (`generate_ga_votes_soap.py`), which the producer already fetches per chamber — so they cost no extra requests and are authoritative rather than inferred.

**⚠ Never infer the chamber from `motionText`.** The motion names *whose work is being accepted*, so the chamber casting the vote is the other one: "Agree to Senate Substitute" is a **House** vote. Three copies of the naive reading got it backwards — measured against the official record it was 0-for-270 (136 wrong, and being case-sensitive it left the 134 upper-case Senate motions unclassified), which silently dropped 136 roll calls from every House member's own-chamber participation and party-alignment figures. Read `chamber`; fall back only to `chamber_from_motion()` in `scripts/lib/ga_voters.py`, the one implementation (mirrored by `voteChamber()` in `_includes/entity/ga-legislator.html` and `vote_chamber()` in `generate_party_unity.py` — keep all three in step).

**⚠ `rollNumber` cannot be derived; it has to be stored.** It is the chamber's own roll-call number, and it counts EVERY roll call the chamber held while this file keeps only passage votes (312 dropped in 2025-26), so the sequence is gapped here and dense at the source. `voteId` is **not** a substitute: it tracks record creation and goes backwards 137 times within a day in the House. It matters because a chamber can hold two passage roll calls on one bill on one day (89 such groups in 2025-26, 5 of them with one passing and one failing), and `rollNumber` is what identifies the operative final vote. Open States republished this same field as `"House Vote #752"`; where the two differ (7 of 1,898) OS points at the procedural roll call that preceded the passage vote and the SOAP `Number` is right.

**⚠ Compact schema (v2).** At ~270k rows the old `memberVotes: {pid: [{voteId, vote}]}` form repeated the keys and a 45-char uuid on every entry, making the file ~19 MB — the site's largest blob and top client-fetched file. v2 shrinks it to ~3.6 MB (81%): `voteIds` is an ordered index of vote ids; `memberVotes` values are `{indexString: code}` maps, where the index resolves via `voteIds[i]` and `code` is `Y`/`N`/`O` (full map `Y`/`N`/`NV`/`P`/`A`/`E`/`O` for the Open States options `Yea`/`Nay`/`Not Voting`/`Present`/`Absent`/`Excused`/`Other`; GA data currently only uses Yea/Nay/Other). `votes` is **unchanged** (still keyed by voteId).

**Never hand-decode this.** `scripts/lib/votes_schema.py` is the one codec: `member_votes_map(data)` returns the legacy `{pid: [{voteId, vote}]}` shape from **either** schema (readers use it — `generate_party_unity.py`, `enrich_bills_with_party_votes.py`, `publish_ga_legislators.py`), and `encode_member_votes(mv, list(votes.keys()))` writes v2 (writers use it — `generate_ga_votes_soap.py` (canonical; `generate_ga_votes_from_legis.py` and the archived `generate_ga_votes_data.py` also write it), `import_legiscan_csv.py`). `_includes/entity/ga-legislator.html` decodes inline (the only client that fetches this file). The **sibling-repo publish keeps the legacy shape** (the publisher expands via the codec), so `Votega/ga-legislators` `votes.json`/`votes.schema.json` are unaffected. `federal-member-votes.json` stays legacy and does **not** use this codec — but its per-member *slices* (`federal-votes/<bioguideId>.json`) do; see its own schema section above for why the split falls that way. Index order tracks the append-only `votes` dict so quiet incremental runs stay byte-identical (finding 5.6).

### `ga-zip-districts.json`
Written by `scripts/generate_ga_zip_districts.py` (monthly, `update-ga-zip-districts.yml`; HUD only publishes quarterly, so most runs change nothing and commit nothing). Top-level: `{ metadata: { generatedAt, source, hudRelease, statePlans, censusVintage, count, withDistricts, poBox, other, kinds, meaning }, zips: { <zip>: { city, kind, counties[], stateSenate[], stateHouse[], usHouse[] } } }`. Each list is `[{district|fips(+name), share}]`, **largest share first**, shares summing to ~1.

**⚠ It means "districts TOUCHING the ZIP", never "your district".** A ZIP can span several and only a street address identifies the voter's. **Every district with any residents is listed — nothing is cut off at a threshold**, because a voter on the edge of a ZIP lives in a small sliver and hiding it hands them the wrong ballot. `share` is published so a consumer can *mark* a small one, never so a consumer (or this generator) can drop it.

**⚠ State shares are estimated, not looked up.** HUD gives the share of a ZIP's *residential addresses* per census tract (`type=1`); `scripts/data/ga-tract-districts.json` gives each tract's 2020 population by 2023 state Senate / House / congressional district. Their product, summed over the ZIP's tracts, is the ZIP's share (empty tracts are left out and the rest renormalised, so an all-empty block cannot add a district nobody lives in). Congressional districts use the **same tract method**, not HUD's own ZIP -> district crosswalk (`type=5`): ours reconciles exactly to the official plan files, while HUD's disagreed about the largest district for 21 of 914 ZIPs (cause not established). Counties come straight from HUD (`type=2`), which has no state-legislative crosswalk. The county route (ZIP -> county -> `ga-districts.js`) was measured and never narrows anything — it is a copy of the county table (178 metro ZIPs listed a median 22 House districts, the same as the county dropdown) — so do not reintroduce it.

**⚠ The tract table is hand-built on redistricting, not by the monthly job.** `build_ga_tract_district_table.py` joins the reapportionment office's block-equivalency files to the Census PL 94-171 block populations (`gageo2020.pl` alone carries `POP100`) and **refuses to write unless the roll-up reproduces the plans' packet district totals and county reports exactly** (it does, to the person, for all 56 Senate / 180 House districts and the 14 congressional districts, the latter against the sums of its county report since that plan has no packet in our files). `build_usps_ga_zips.py` builds `usps-ga-zips.json` the same way from USPS's Zip Locale Detail, which lists post-office facilities, not delivery areas — it is used only to know which ZIPs are real Georgia delivery ZIPs and which are PO-box-only (`kind: "po-box"`, which carry no districts). A ZIP HUD reports but USPS's Georgia list lacks is `kind: "other"` (campus/government/military ZIPs) and is treated like `standard`. Re-run both only when Georgia redraws its maps or the Census vintage changes.

**Token:** `HUD_USER_TOKEN` (a read-only HUD USER API token; it has no scopes). It is a repository secret read only by the workflow; never client-side. `validate_ga_zip_districts.py` is tier 1 (shares sum to 1, ranked, valid district numbers, PO-box ZIPs carry none, coverage floor) / tier 2 (ZIPs added/removed, largest district changed: reported, never gates); tests in `scripts/test_ga_zip_districts.py`.

### `ga-openstates-crosswalk.json`
Written by `scripts/generate_openstates_crosswalk.py` (monthly, `update-ga-openstates-crosswalk.yml`), read by the roster producer. `{ metadata: { generatedAt, source, upstreamCommit, count, resolved, license, primaryKey, slotsNotResolvedHere }, people: { <legisGaGovId>: { ocdPersonId, ballotpediaId, provenance } }, review: {...} }`. Reads GA person files from the `openstates/people` GitHub repo — **CC0 1.0** (LICENSE, GitHub's licence metadata and the README's public-domain dedication all agree), so it is compatible with our CC BY-SA 4.0 publication. No key, no quota; the repo leads the v3 API by days. It must never call the v3 API or use `OPENSTATES_API_KEY`.

**⚠ Matching facts verified against the live repo (2026-10-19), contrary to the design brief:** the person files carry NO `other_identifiers` entry for `legisGaGovId` and NO Wikidata id (hence no `wikidataId` slot). The join is the member's own `legis.ga.gov/members/(senate|house)/<n>` profile link in `links`/`sources` (exact, but a link rather than a declared id — recorded in the provenance note); Ballotpedia is the page title from a `sources` URL. `wikidataId` is therefore never populated here (provenance `unresolved`) until a source that carries it is wired in. **⚠ One `legisGaGovId` can be claimed by two files** (Derrick Jackson, 4891: a current file and a retired duplicate): the sole `legislature/` claimant wins, otherwise the member is `ambiguous` and gets no value. Two Ballotpedia links on one file (7 members) is `ambiguous` too. Two members resolving to one value are both demoted. A previously resolved slot coming back null, or a short read, exits 1 without writing. PyYAML is imported lazily (the workflow installs it; the tests inject parsed docs and need nothing).

### `id-crosswalk.json` + `id-crosswalk-ledger.json`
Top-level: `{ metadata: { schemaVersion, schemaStability, generatedAt, count, scope, sources[], provenanceMethods, coverage }, people: [...] }`
Each person: `vgId` (**may be null**), `name{full,first,last}`, `role{...}` (null for candidate-only records), `ids{...}`, `candidacies[]`, `provenance{...}`.
`ids` carries `rosterId` (the opaque roster handle — the join key into `ga-members.json` and `ga-member-votes.json`; never interpret it), `ocdPersonId` (**OCD-shaped or null, never a roster handle**), `ballotpediaId`, `legisGaGovId` (the primary key for state legislators), `bioguideId`, `govtrackId`, `openSecretsId`, and the **lists** `fecCandidateIds`, `peachfileFilerEntityIds`, `votegaCandidateIds`. State-legislator slots carry the roster's `idProvenance`; `provenance.legisGaGovId` is `legis.ga.gov`, not Open States. `unresolved` is a provenance method meaning "no lookup has run" — a null there is not a claim that none exists. Additive since schema version 2: `rosterId`, `ballotpediaId` (a `wikidataId` briefly shipped alongside them, always null, and was removed).

Built by `scripts/build_id_crosswalk.py` from the roster, finance and races files; it calls no API of its own. Validate with `scripts/validate_id_crosswalk.py`.

`id-crosswalk-overrides.json` holds hand-reviewed decisions, keyed by **roster `id` (OCD-shaped for most), bioguide ID, `peachfile:<id>` or `fec:<id>`** — *not* the races.json candidate ID that `ga-campaign-finance-overrides.json` uses. Pin a filing with `peachfileFilerEntityId`, record a verified non-filer with `peachfileNoFiling`, merge two ledger keys onto one person with `sameAs`, or resolve an `ambiguous` identity slot with `"pinSlots": {"ballotpediaId": "<slug>"}` (pinnable: `ocdPersonId`, which must stay OCD-shaped, and `ballotpediaId`; a bare id, never a URL; keyed by roster id / `ocdPersonId` for state members or bioguide id for federal). Every entry needs a `_note` recording how it was confirmed — a pin without one is refused.

**⚠ A pin resolves an ambiguity; it never moves a vgId.** Slots are not ledger keys, so pinning changes the published slot and its provenance (`method: "reviewed"`, `chosenFrom` = the candidates the resolver offered) and nothing else. It is applied by `lib/ga_identity.py` (`pin_patch` / `apply_slot_pins`, the single implementation) in both the roster producer and `build_id_crosswalk.py`, so it lands on the next crosswalk build without waiting for the roster. `validate_id_crosswalk.py` fails the build if a pin is malformed, matches nobody, or did not land.

**⚠ The tier-2 ambiguity report is grouped by KIND of ambiguity** (the provenance key: Ballotpedia page, Open States person id, PeachFile / FEC filing), prints the competing candidates inline, and names the remedy that exists for that kind — slot ambiguities go to `pinSlots`, filing ambiguities to the filing overrides. It never gates the commit.

**⚠ Never key identity on a races.json candidate ID.** They are positional — `make_candidate_id()` ends them with a row index into the SoS export, so a re-ordered export makes `ga-house-15-2026-d-3` a different person (CODEBASE-REVIEW-2026-08-18.md 5.2). Candidates are keyed on their campaign filing (`peachfile:` / `fec:`) instead; a candidate with no filing gets `vgId: null` rather than an invented ID. The validator fails the build if a positional ID reaches the ledger.

**⚠ `vgId`s are append-only.** `id-crosswalk-ledger.json` is the assignment record; never renumber or remove an entry, or a published `vgId` silently comes to mean a different person. The validator compares against HEAD and fails on any renumbering.

**Ledger keys (the published contract).** Resolved in this order by `lib/ga_identity.py::ledger_keys` — the single implementation, used by the builder and audited by the validator: (1) **`legis:<legisGaGovId>`** for state legislators (the primary key; a brand-new member is minted under it); (2) the **legacy roster `id`** (`ocd-person/...`, `legis-<n>`, or a synthetic placeholder id) that existing entries were keyed on — the first key already in the ledger wins, nothing is aliased or rewritten; (3) a **bioguide id** for the federal delegation; (4) **`peachfile:<filerEntityId>`** / **`fec:<candidateId>`** for candidates. **An identifier SLOT is never a key**: keying on a late-arriving `ocdPersonId` would mint a second `vgId` for the same person, permanently (`scripts/test_ga_identity.py` reproduces exactly that with a slot-keyed builder and asserts it is caught; the validator also fails on any person reachable by two ledger keys with different `vgId`s).

**⚠ A null filing list is not "no filing".** Check `provenance`: `confirmed-none` means a human verified there is none; `no-match` and `ambiguous` mean the join didn't resolve, which is not the same claim.

## GA Overrides System
`assets/data/ga-members-overrides.json` is the mechanism for correcting Open States data and injecting entries (e.g., vacant seats) that Open States doesn't track. When editing:
- Prefer OCD ID keys over name keys for precision.
- Only include fields that need changing — all other fields are preserved from the API.
- Use `_inject` for net-new entries; they must include all required schema fields.
- After changes, re-run `generate_ga_members_data.py` locally or trigger the workflow to regenerate `ga-members.json`.

## Project-Specific Conventions
- **Portrait cache is government-sources-only, and idempotent** — `scripts/fetch_candidate_images.py` downloads portraits, resizes them to ≤400px JPEG under `assets/img/candidates/`, and writes the URL→local-path manifest `assets/data/candidate-image-cache.json`; the render layer swaps via `VotegaPortraits` in `votega-core.js` (wired into the race/candidate/ga-legislator/federal-legislator entity includes). Two invariants must hold. (1) **Only add government hosts to `ALLOWED_HOSTS`** (currently `congress.gov`, `legis.ga.gov`). Re-hosting a campaign/Ballotpedia/social photo is a reproduction of a copyrighted work — attribution is not a license — so those stay hot-linked (the render layer only lazy-loads them). (2) **Never make the fetcher re-download cached files.** Images are binary and do not delta-compress, so skip-if-exists (stable hash filenames) is what keeps the weekly `update-candidate-images.yml` commit empty on a quiet week and stops `.git` from bloating; a blind re-fetch every run would add ~10 MB/run of undeletable history. The `legis.ga.gov` originals are ~3–15 MB each (the real cause of slow race pages), shrunk to ~15 KB. Renaming that workflow means updating `notify-workflow-failure.yml` in the same commit (see the renaming convention above).
- **Never commit secrets** — only generated JSON files go back to the repo via workflows.
- **Member ids**: the roster `id` is an opaque handle, not an OCD id (see the `ga-members.json` schema section). Most are `ocd-person/<uuid>`, a member Open States has not catalogued is `legis-<legisGaGovId>`, and injected entries (vacant seats) use synthetic IDs like `ga-senate-7-vacant` — these won't join to vote records. For "does this person have an OCD id", read `ocdPersonId`.
- **`legisGaGovId`**: Numeric ID used by legis.ga.gov to construct `officialWebsiteUrl`. Not used for vote joins — those use the OCD person `id`. Members without it get no official website link. New members from Open States may lack it — add via overrides file.
- **UX**: Show loading states, handle empty/null data gracefully, explain API limitations in UI.
- **The open-data catalog is checked, not trusted** — `_data/open_data.yml` drives `/open-data` (a navbar page) but points at artifacts in the sibling repos, so a publisher that moves a file silently turns catalog entries into 404s. That happened: the `sessions/` migration broke three of seven repo links. `scripts/validate_open_data_links.py` resolves every `files[].url` (GitHub blob → `raw.githubusercontent.com`; site-relative → the working tree) and runs in CI weekly and on change. Weekly matters — the breaking change lands in a *different* repo, so a PR-only trigger cannot catch it. When a publisher's output paths change, update the catalog in the same commit.

- **Reuse terms are emitted, never hand-copied** — VoteGA data is published under **CC BY-SA 4.0** (site code is PolyForm Noncommercial 1.0.0; see `LICENSE`/`NOTICE.md`). `scripts/lib/sibling_publish.py` injects `LICENSE` (canonical SPDX legalcode, so GitHub detects it) and `NOTICE.md` (the attribution string) into every publish automatically; no publisher needs to opt in and none can omit them. The upstream name comes from `REPO_SOURCES`, keyed by **target repo, not publisher** — two publishers write to `ga-legislation`, and per-publisher sources would rewrite `NOTICE.md` against each other on every run. Adding a new sibling repo means adding it to `REPO_SOURCES`; publishing to an unregistered repo raises rather than emitting an uncredited notice. Do not add a per-dataset license field to `open_data.yml` — the license is stated once on the page and once in the publisher.

- **Published files name their own session** — `Votega/ga-legislators` (`scripts/publish_ga_legislators.py`) overwrites `data/all.json`, `data/members.csv` and `ROSTER.md` IN PLACE at a biennium rollover; only the deliberate `freeze-roster` run preserves the outgoing roster under `sessions/<slug>/`. So a downloaded copy must say which General Assembly it describes: `members.csv` ends with a constant `session` column (from `ga-members.json` `metadata.session`; the publisher exits 1 if it is missing), `members.schema.json` describes `metadata.session` / `legisSessionId` / `generatedAt` and points at `sessions/` for history, and the live `ROSTER.md` heading names the session. The same rule is applied to the session-partitioned files: `votes.csv` ends with `session` and `scorecard.csv` (biennium grain) with `biennium`. New CSV columns are APPENDED, never inserted, so positional consumers keep working; schemas gain `properties` but no new `required`. Pinned by `scripts/test_publish_ga_legislators_session.py`. A new publisher whose output is overwritten per cycle should carry its scope the same way.

- **Every publish is gated before the PUT** — `publish_or_dry_run` in `scripts/lib/sibling_publish.py` runs `_assert_artifacts_sane` on the way out (before both the live publish AND the dry-run, so local/CI runs fail identically): it refuses to push an empty artifact set, any empty-byte artifact, or any `*.json` that does not parse. This is the choke point every publisher calls, so the guard cannot be forgotten by a new one; it exists because publishers `json.load` local disk and PUT with a standing write-PAT and nothing else re-checks the bytes (PIPELINE-AUDIT.md #1), and it reinforces the atomic-write fix (#2). For a dataset record floor, pass `validate=min_items("<primary artifact>", "<collection>")` — a corpus-independent non-empty check that catches a well-formed-but-empty dataset (valid JSON, so the sanity guard passes) before it wipes a public repo. Use it only for FLAT, always-populated datasets (races, ballot-measures, federal delegation, the members roster, the local-gov registry); do NOT add it to the session-partitioned publishers (`publish_ga_bills`, `publish_ga_legislators` votes/scorecard/freeze-roster), which emit empty sessions by design and would false-positive — the universal sanity guard still covers them.

- **The in-place `races.json` writers guard before they overwrite** — `races.json` is the core of the elections section and ~7 scripts read-and-overwrite it in place. Each takes a `copy.deepcopy` snapshot right after `json.load` and, immediately before `write_json_atomic`, runs the matching check(s) from `scripts/lib/races_guard.py`, aborting with `RacesGuardError` (no write — atomic, so disk is untouched) on a violation. The invariants are writer-specific: `assert_phase_transitions` (only `primary→general` / `runoff→general`, right count, non-empty resulting ballot) for `update_general_from_primary`/`_runoff`; `assert_active_phases_unchanged` for `fix_general_fallbacks`; `assert_active_phases_unchanged` + `assert_membership_preserved` (candidate id-set/count/`type` unchanged per phase) for `sync_candidate_profiles`; `assert_only_race_changed` for `set_general_candidates`; `assert_equal_except(..., "updatedAt")` for `stamp_races_updated_at`; `apply_overrides` keeps its own positional-id guard. All build on `assert_race_set_preserved` (no race added/dropped, no top-level key lost) — the check that catches the headline #3 risk of a bug silently shrinking the roster. The snapshot is the baseline, NOT git HEAD (these run manually against uncommitted trees). When adding a new `races.json` mutator, wire the appropriate guard the same way. (PIPELINE-AUDIT.md #3.)

- **Each rendered dataset carries its own dated provenance** — a page that mixes data from more than one source must not let a single "last updated" stamp stand in for all of them. Stamp each block from *its own* `metadata.generatedAt` (or the file's own top-level timestamp, e.g. `races.json` uses `updatedAt`, not `metadata`), not from whichever file the page happened to load first. Precedent: a race entity page's bottom stamp reflects `races.json` (the candidate roster), but the Campaign Finance panel's figures come from `ga-fec-data.json` / `ga-campaign-finance.json`, so that panel prints its own line ("Finance data from the FEC, updated …") from the finance data's `generatedAt`. Borrowing the roster stamp for the money figures both understated freshness and named the wrong source. Degrade gracefully: omit the dated line when the timestamp is absent rather than printing a bare or wrong date.
- **Link the published dataset, not the internal asset** — whenever a page renders data we also spin off into a sibling repo (a `publish_*.py` → `Votega/<repo>`), that page's data/source footnote MUST link to the published repo, not the raw `assets/data/*.json` path it happens to fetch. The internal asset is a build artifact (often destructively replaced at a session/cycle rollover); the sibling repo is the stable, archived, multi-format (JSON/CSV/schema) open-data home. Prefer the repo's stablest location for the data on screen (e.g. the matching `sessions/<biennium>/` dir), built from metadata so it self-updates, with a fallback to the repo root. Match how `about-the-data.md` already cites that repo. Precedents: `ga-party-unity.html` → `Votega/ga-legislators`, `ga-executive-orders.html` → `Votega/ga-executive-orders`. Known sibling datasets whose source pages should follow this: ga-federal-legislators, ga-legislators, ga-legislation (bills + ballot measures), ga-executive-orders, ga-races-elections.
- **Renaming a workflow means updating the failure-notifier in the same commit** — `notify-workflow-failure.yml` watches other workflows via `workflow_run`, which matches on the workflow's exact `name:` string. Change a workflow's `name:` (even trivially, e.g. `(daily, 08:15 UTC)` → `(twice daily)`) and its notifier entry silently watches nothing — the workflow then runs unattended, so a failure opens no issue and looks identical to a clean run. `scripts/validate_workflow_triggers.py` catches this (it fails CI when a scheduled workflow is unwatched or a notifier name matches no workflow), but it's a two-file change: edit the workflow's `name:` **and** the matching line in `notify-workflow-failure.yml`'s `workflows:` list together. Run the validator locally before pushing.

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
