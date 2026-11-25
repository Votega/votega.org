# Project structure map

Moved out of `CLAUDE.md` (verbatim, no edits) so the always-loaded file stays short. `CLAUDE.md` points here.


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
│   ├── data_freshness.yml               # Stale-stamp windows per dataset + the never-flag bucket (see "Stale-stamp rule" below)
│   ├── freshness/<dataset>.json         # {"checkedAt": "YYYY-MM-DD"}, written by the update workflows (scripts/record_data_checked.py)
│   └── ui-text.yml                      # UI text / localization
│
├── assets/
│   ├── data/                            # Generated JSON/CSV data (committed via GitHub Actions)
│   │   ├── current-members.json         # Federal Congress members (daily, from Congress.gov API)
│   │   ├── ga-members.json              # Georgia state legislators (legis.ga.gov SOAP Members
│   │   │                                #   service; canonical since 2026-10 — OS producer retired
│   │   │                                #   to scripts/archive/generate_ga_members_data.py — NOT a working fallback, see below)
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
│   │   ├── freshness.js                 # "older than usual" rule for data stamps; reads window.VOTEGA_FRESHNESS (written by _includes/head.html from data_freshness.yml)
│   │   └── campaign-finance.js          # Shared FEC + PeachFile finance lookup/matching (used by race.html + candidate.html; single source of truth for the JS match logic — mirrors scripts/lib/ga_match.py, the Python side's single source, & tools/ga-finance-overrides-editor.html)
│   ├── css/                             # tokens.css (brand tokens, loaded first), theme stylesheets (beautifuljekyll.css, bootstrap-social.css, etc.)
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
│   │                                     # 2026-10; no API key, no quota). scripts/archive/generate_ga_members_data.py
│   │                                     # is the retired Open States producer, archived for reference
│   ├── generate_ga_votes_soap.py        # legis.ga.gov SOAP (official) → ga-member-votes.json (canonical since 2026-10; OS producer retired to scripts/archive/generate_ga_votes_data.py)
│   │                                     # `--archive <tag>` (2023_24 … 2017_18, lib/ga_sessions.ARCHIVE_SESSIONS) backfills ONE closed biennium to out/archive/ga-votes-<tag>.json (votes + thin roster; never touches live files, refuses their paths). Publish with `publish_ga_legislators.py archive <tag> <file> [--overwrite]` → sessions/<YYYY-YYYY>/ only, no pointer files. Tested by test_publish_ga_legislators_archive.py
│   ├── generate_ga_bills_soap.py (legis.ga.gov SOAP → ga-bills.json; canonical since 2026-10, OS producer retired to scripts/archive/generate_ga_bills_data.py; subjects via ga-bills-subjects-base.json overlay) / enrich_bills_with_party_votes.py / generate_curated_ga_bills.py (curated key votes; reads the committed SOAP artifacts, SOAP-fetches only a session they do not cover — no Open States, no API key, canonical since 2026-10)
│   ├── generate_federal_votes_data.py / generate_fec_data.py / generate_ga_congress_trades.py
│   ├── lib/senate_nominations.py (documentType, nomineeCount and en bloc lists → federal-en-bloc-nominees.json) / backfill_federal_nomination_fields.py (one-time fill of held 119th rows; needs a computer senate.gov answers)
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
│   ├── counterparty-review-editor.html   # Review the local counterparty queue (_data/counterparty_review.yml, read-only) and log approve/reject/edit/split decisions to _data/counterparty_decisions.json; scripts/generate_local_counterparties.py applies the log (see the counterparty bullet in Project-Specific Conventions)
│   ├── local-results-review.html         # Seat-by-seat review of a county-commission election against _data/local_officials.yml. Loads a review JSON (open/drop; no File System Access write) built by scripts/build_local_results_review.py from a saved SoS results pull; keeps decisions in localStorage + export. Writes nothing to the repo
│   └── race-candidate-editor.html        # Curate candidate profiles directly in races.json (federal & other non-regenerated races have no override layer — edited in place). Syncs a candidate's edits across every phase they appear in (e.g. special + runoff); warns off ga-house-*/ga-senate-* (regenerated — use the overrides file); preserves CRLF/2-space/no-trailing-newline for byte-identical diffs
├── .claude/settings.local.json          # Tool permissions (Congress.gov, GitHub, Python)
├── .vscode/settings.json
└── not in use/                          # Archived/unused files
```
