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

This map shows categories and representative examples, not an exhaustive file list — run `ls` / `Glob` for the current full set. As of 2026-07, the repo has ~26 top-level HTML pages, ~26 tracked scripts, and 21 GitHub Actions workflows.

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
│   ├── Elections/Races: elections.html, race.html, candidate.html, ga-ballot-measures.html,
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
│   │   ├── races.json / ga-election-calendar.json / ga-ballot-measures.json
│   │   ├── ga-executive-orders-*.json / ga-executive.json / executive.json
│   │   ├── scotus-decisions.json / supreme-court.json / presidential-laws.json / vp-tie-votes.json
│   │   ├── ga-congress-trades.json      # Stock trade disclosures for GA federal delegation
│   │   └── searchcorpus.json            # Site search index
│   ├── scripts/                         # Client-side JS (loaded by HTML pages) + a few standalone Python utilities
│   │   ├── congress.js                  # Federal lookup: reads current-members.json, filters by state/chamber
│   │   └── ga.js                        # GA lookup: county→district mapping, reads ga-members.json
│   ├── css/                             # Theme stylesheets (beautifuljekyll.css, bootstrap-social.css, etc.)
│   ├── js/                              # Theme JS (beautifuljekyll.js, staticman.js)
│   ├── img/                             # Images (logo.png, avatar-icon.png, bgimage.png, etc.)
│   └── docs/                            # PDFs (flock_safety_covington_pd_contract.pdf)
│
├── scripts/                             # Build-time data generation (run by GitHub Actions), ~26 tracked
│   ├── generate_current_members_data.py # Congress.gov API → assets/data/current-members.json
│   ├── generate_ga_members_data.py      # Open States API → assets/data/ga-members.json
│   ├── generate_ga_votes_data.py        # Open States API → assets/data/ga-member-votes.json
│   ├── generate_ga_bills_data.py / enrich_bills_with_party_votes.py / generate_curated_ga_bills.py
│   ├── generate_federal_votes_data.py / generate_fec_data.py / generate_ga_congress_trades.py
│   ├── generate_ga_executive_orders.py / generate_scotus_decisions.py / generate_presidential_laws.py / generate_vp_tie_votes.py
│   ├── build_legislative_races.py / build_results_json.py (CSV → _data/election_results/*.json, shared by all results pages)
│   ├── apply_overrides.py / validate_ga_overrides.py / import_legiscan_csv.py / fix_general_fallbacks.py
│   ├── inspect_ga_bill_votes.py / inspect_openstates_fields.py  # diagnostics, each backed by its own workflow
│   └── (one-off/local-machine scripts — e.g. debug_*.py, watch_downloads.py — are gitignored, not tracked)
│
├── .github/workflows/                   # 21 workflows: deploy, per-dataset daily/scheduled updates
│   │                                     # (update-*.yml), and publish-*-to-<sibling-repo>.yml syncs
│   ├── deploy-pages.yml
│   ├── update-current-members.yml       # Daily: runs generate_current_members_data.py, commits JSON
│   ├── update-ga-members.yml            # Daily: runs generate_ga_members_data.py, commits JSON
│   └── sync-generated-data-on-pr.yml
│
├── tools/                                # Standalone override-editing HTML utilities (not part of the Jekyll site)
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
- **HTML**: Semantic elements. Fallback links (e.g., back to search page). Inline scripts for simplicity.
- **Python**: `urllib` for requests (no third-party HTTP libs except where already present). Paginate with `while True` loops. Output clean JSON with a `metadata` object containing at minimum `generatedAt` (ISO timestamp) and `count`. Use `None` for missing optional fields — never empty strings.
- **Python retries**: Retry on HTTP 429 and 5xx only. Return `None` immediately on 4xx — these are non-retryable client errors.
- **Workflows**: `ubuntu-latest` runners. Validate output data before committing (count thresholds, required-field spot checks, metadata.count == len(members)).

## Data Schemas

### `current-members.json`
Top-level: `{ metadata: { generatedAt, source, count, apiVersion }, members: [...] }`
Each member: `bioguideId`, `name`, `partyName`, `state`, `district`, `terms.item[]` (chamber via `item[0].chamber`), `depiction.imageUrl`, `leadership[]`, `committees[]`, `contactInfo`, `officialWebsiteUrl`, `birthYear`, `firstName`, `lastName`.
For GA delegation only: `recentSponsored[]`.

### `ga-members.json`
Top-level: `{ metadata: { generatedAt, source, jurisdiction, count, committeesAvailable }, members: [...] }`
Each member: `id` (OCD `ocd-person/<uuid>`), `name`, `firstName`, `lastName`, `party` (null if unknown), `chamber` (`"Senate"` or `"House of Representatives"`), `district` (int or null), `title`, `imageUrl`, `phone`, `address`, `email`, `officialWebsiteUrl`, `birthDate`, `birthYear`, `termStart` (ISO date or null), `termStartYear`, `committees[]`, `legisGaGovId` (int or null — needed to join with vote data), `status` (null = active; `"Vacant"` | `"Suspended"` | `"Resigned"` | `"Removed"` | `"Deceased"` if set via overrides), `statusDate`, `statusNote`.
Optional override-only fields: `leadershipRole`, `statusNote`.

### `ga-members-overrides.json`
Manual patches applied after Open States fetch. Keys are OCD person IDs (`ocd-person/...`) or member full names. Use `_inject` array for entirely new entries (vacant seats). Departure fields: `status`, `statusDate`, `statusNote`. Fields prefixed `_` are stripped before merging.

### `ga-member-votes.json`
Top-level: `{ metadata: { generatedAt, session, sessionName, source, totalVotes, totalBillsSeen, paginationComplete }, votes: { <voteId>: {...} }, memberVotes: { <ocdPersonId>: [{voteId, vote}] } }`
Vote values: `"Yea"`, `"Nay"`, `"Not Voting"`, `"Present"`, `"Absent"`, `"Excused"`, `"Other"`.
Members are joined by OCD person ID — the same `id` field as in `ga-members.json`.

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

## Enforcement
- Check for API key exposure before suggesting any code changes.
- If proposing live API calls, suggest static/build-time alternatives first.
- For new features, verify against Congress.gov API docs and test with sample data.
- When modifying `normalize_member()` in `generate_ga_members_data.py`, ensure all schema fields are present in the output — missing fields cause silent JS failures downstream.
- Do not use empty strings for optional fields — use `None`/`null`.
