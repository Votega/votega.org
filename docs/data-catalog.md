# Data catalog

Where each dataset in `assets/data/` comes from, what builds it, when it refreshes, and who reads it. One row per dataset (a directory of per-member slices counts as one row). Field-level detail lives in the per-source docs linked in each section; this file is the map, not the dictionary.

Scope: the six main families. Not covered here: local government (`local-*`, `school-*`, `georgia-commons-meetings.json`; see `docs/conventions-local-government.md`), news, search corpus, and other site-support files.

**Keeping it current.** Add a row when you add a dataset, and change the row when you change its source, producer, or schedule. Schedules are the `cron:` lines in `.github/workflows/<workflow>.yml` (UTC); "hand" means a maintainer edits the file and no script writes it.

Column key:
- **Source**: the upstream system.
- **Built by**: the script under `scripts/` that writes the file.
- **Refresh**: the workflow and its schedule.
- **Read by**: pages, includes, JS and MCP tools.
- **Published to**: the sibling `Votega/*` repo it reaches, if any. See `docs/conventions-publishing.md`.

## 1. GA bills

Field detail: `docs/ga-soap-data-dictionary.md` (SOAP fields and derived fields), `docs/data-schemas.md` § GA bill sponsors.

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `ga-bills.json` | legis.ga.gov SOAP (Legislation, Votes, Committees, Session) | `generate_ga_bills_soap.py` | `update-ga-bills`: daily Jan–Apr, Sundays May–Dec | `ga-bills.html`, `ga-legislator.html`, `ga-bills-resolve.js`, MCP `search_bills` / `get_bill` | ga-legislation (`publish_ga_bills.py`) |
| `ga-bills-subjects.json`, `ga-bills-subjects-base.json` | Open States subject tags (base) plus local AI tagging | `ai_enrich_ga_bills.py` (maintainer's PC); merged by `generate_ga_bills_soap.py` | on demand | `ga-bills.json` subjects | ga-legislation |
| `ga-bill-summaries.json`, `ga-bill-ai.json` | Local AI (Ollama draft, Claude refine) over bill text | `ai_enrich_ga_bills.py` | on demand | `ga-bills.html`, `tools/ai-summary-review.html` | — |
| `ga-governor-statements.json` | The Governor's yearly "Veto Messages and Signing Statements" PDF (gov.georgia.gov) | `import_governor_statements.py` | yearly, by hand after the signing deadline (`docs/conventions-ga-legislature.md`) | merged into `ga-bills.json` as `governorStatements` | ga-legislation (via `ga-bills.json`) |
| `ga-legis-sessions.json` | legis.ga.gov SOAP `Session/GetSessions` | `generate_legis_sessions.py` | `update-legis-sessions`: Sundays | bills and votes producers | — |
| `curated-ga-bills.json` | hand (maintainer's key-bill list) | hand | — | `generate_curated_ga_bills.py` | — |
| `curated-ga-bill-votes.json` | legis.ga.gov, for the curated list | `generate_curated_ga_bills.py` | `update-curated-ga-bills`: Tue/Thu | `ga-legislator.html` | — |
| `ga-sponsorship-index.json` + `ga-sponsorship/` | derived from `ga-bills.json` | `build_sponsorship_slices.py` | `update-ga-bills` | `ga-legislator.html` | — |
| `ga-bienniums/<tag>/` | frozen copies of the bills, votes and roster at biennium end | `freeze_ga_bills.py`, `freeze_ga_biennium.py`, `freeze_ga_party_unity.py` | once per biennium (`archive-ga-session`) | `ga-bills.html`, `ga-legislator.html`, MCP | ga-legislation, ga-legislators |
| `ga-ballot-measures.json` | Georgia Secretary of State (ballot questions) | hand, checked by `validate_ballot_measures.py` | `validate-ballot-measures` | `ga-ballot-measures.html`, `sample-ballot.html`, results pages | ga-legislation (`publish_ga_ballot_measures.py`) |

## 2. GA legislators and votes

Field detail: `docs/data-schemas.md` (§ `ga-members.json`, `ga-member-votes.json`, seats, holds, crosswalks), `docs/ga-soap-data-dictionary.md` (Members, Votes).

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `ga-members.json` | legis.ga.gov SOAP Members, plus `ga-members-overrides.json` and `ga-openstates-crosswalk.json` | `generate_ga_members_soap.py` | `update-ga-members`: daily | legislator pages, races, MCP `find_my_representatives` / `get_legislator` | ga-legislators (`publish_ga_legislators.py`) |
| `ga-members-overrides.json` | hand (corrections the SOAP lacks) | hand, checked by `validate_ga_members.py` | `validate-ga-overrides` | `generate_ga_members_soap.py` | — |
| `ga-openstates-crosswalk.json` | openstates/people (OCD and Ballotpedia ids) | `generate_openstates_crosswalk.py` | `update-ga-openstates-crosswalk`: monthly, 5th | `generate_ga_members_soap.py` | — |
| `ga-legislator-ledger.json` | append-only vgId ledger | `generate_ga_members_soap.py`, `freeze_ga_biennium.py` | `update-ga-members` | legislator pages | ga-legislators |
| `ga-departure-labels.json` | hand (approved labels, rollover decision D6) | hand | — | `ga-legislator.html`, `departure-label.js` | — |
| `ga-member-votes.json` + `ga-votes-index.json` + `ga-votes/` | legis.ga.gov SOAP Votes | `generate_ga_votes_soap.py`; slices by `build_member_votes_slices.py` | `update-ga-votes`: Mondays; also `update-ga-bills` | `ga-legislator.html`, `ga-majority-tracker.html`, MCP `get_legislator_votes` | ga-legislators |
| `ga-party-unity.json` | derived from GA votes (`lib/party_unity.py`) | `generate_party_unity.py` | `update-ga-votes` | `ga-party-unity.html`, `ga-legislator.html`, MCP | ga-legislators |
| `seats.json` | reapportionment office plans plus 2020 Census blocks | `build_seat_registry.py` | on demand | `ga-majority-tracker.html`, `ga-executive.html` | — |
| `seat-holds.json` | committed rosters, specials and overrides | `build_seat_holds.py` | on demand | seat history | — |
| `ga-legislative-specials.json` | hand (special elections) | hand | — | `build_seat_holds.py` | — |
| `ga-zip-districts.json` | HUD-USPS ZIP crosswalks, Census, 2023 district plans | `generate_ga_zip_districts.py` | `update-ga-zip-districts`: monthly, 6th | find-my-reps, sample ballot, MCP | ga-district-information |
| `id-crosswalk.json` + `id-crosswalk-ledger.json` | every id we hold (legis.ga.gov, bioguide, FEC, Ethics Commission, Open States) | `build_id_crosswalk.py` | `build-id-crosswalk`: Sundays | most producers, `about-the-data.md` | — |

## 3. Federal (Congress, President, Supreme Court)

Field detail: `docs/data-schemas.md` (§ `current-members.json`, federal sponsorship, federal votes, presidential orders, agency actions).

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `current-members.json` | Congress.gov API | `generate_current_members_data.py` | `update-current-members`: daily | federal legislator, race and candidate pages, `congress.js` | ga-federal-legislators |
| `federal-sponsorship-index.json` + `federal-sponsorship/` | Congress.gov API | `generate_current_members_data.py` | `update-current-members` | `federal-legislator.html` | ga-federal-legislators |
| `federal-member-votes.json` + `federal-votes-index.json` + `federal-votes/` + `federal-votes-keyvotes.json` | Clerk of the House, Senate vote XML | `generate_federal_votes_data.py`; slices by `build_federal_votes_slices.py` | `update-federal-votes`: Sundays | `federal-legislator.html`, MCP votes tools | ga-federal-legislators (`publish_federal_delegation.py`) |
| `federal-en-bloc-nominees.json` | Senate en bloc nomination votes | `generate_federal_votes_data.py` | `update-federal-votes` | `votega-nominations.js` | ga-federal-legislators |
| `curated-federal-bills.json` | hand (key federal votes) | hand | — | `build_federal_votes_slices.py` | — |
| `federal-party-unity.json` | derived from federal votes (`lib/party_unity.py`) | `generate_federal_party_unity.py` | `update-federal-votes` | `federal-legislator.html`, MCP | ga-federal-legislators |
| `federal-congresses/` | frozen copies at each Congress's end | `freeze_federal_congress.py`, `freeze_congress_committees.py` | once per Congress (`freeze-federal-delegation`) | `federal-legislator.html` | ga-federal-legislators |
| `federal-departure-labels.json` | hand (rollover decision D12) | hand | — | `federal-legislator.html` | — |
| `ga-congress-trades.json` | kadoa-org/congress-trading-monitor (House and Senate disclosures) | `generate_ga_congress_trades.py` | `update-ga-congress-trades`: Sundays | `ga-congress-trades.html`, `federal-legislator.html` | — |
| `presidential-executive-orders.json` | Federal Register API (plus whitehouse.gov for recent orders) | `generate_presidential_executive_orders.py` | `update-presidential-executive-orders`: twice daily | `federal-executive.html` | — |
| `presidential-laws.json` | Congress.gov `/law` API | `generate_presidential_laws.py` | `update-presidential-laws`: Sundays | `federal-executive.html`, `federal-legislator.html` | — |
| `agency-actions-index.json` + `agency-actions/` | Federal Register API (final and proposed rules) | `generate_agency_actions.py` | `update-agency-actions`: daily | `federal-executive.html` | — |
| `vp-tie-votes.json` | Senate vote XML | `generate_vp_tie_votes.py` | `update-vp-tie-votes`: Sundays | `federal-executive.html` | — |
| `scotus-decisions.json` | Oyez API | `generate_scotus_decisions.py` | `update-scotus-decisions`: Sundays | `supreme-court.html`, justice pages | — |
| `supreme-court.json` | hand (the justices) | hand | — | `supreme-court.html`, justice pages | — |
| `executive.json` | Jekyll re-emit of `_data/executive.json` (hand) | Jekyll build | every build | `executive-branch.html`, `ga-executive.html` | — |

## 4. Campaign finance

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `ga-campaign-finance.json` | Georgia Ethics Commission PeachFile API (2026 onward), plus `ga-campaign-finance-overrides.json` | `generate_ga_campaign_finance.py` | `update-ga-campaign-finance`: Sundays | `ga-legislator.html`, `race.html`, `campaign-finance.js` | — |
| `ga-campaign-finance-donors.json` | PeachFile API (donor summaries; sidecar) | `generate_ga_donor_summaries.py` | `update-ga-campaign-finance` | `campaign-finance.js` | — |
| `ga-campaign-finance-history.json` | Ethics Commission legacy records search (pre-2026) | `generate_ga_campaign_finance_history.py` | `update-ga-campaign-finance-history`: quarterly | — (history panel) | — |
| `ga-campaign-finance-overrides.json` | hand (filer-to-candidate matches) | hand, via `tools/ga-finance-overrides-editor.html` | — | `generate_ga_campaign_finance.py`, `build_id_crosswalk.py` | — |
| `ga-fec-data.json` | FEC API (needs `FEC_API_KEY`) | `generate_fec_data.py` | `update-fec-data`: Sundays | `federal-legislator.html`, `race.html`, `campaign-finance.js` | — |

## 5. Executive orders (Georgia)

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `ga-executive-orders-<year>.json` (2020–) | gov.georgia.gov executive-action pages | `fetch_ga_executive_orders.py` (current year); `generate_ga_executive_orders.py` (CSV backfill) | `update-ga-executive-orders`: twice daily | `ga-executive.html` | ga-executive-orders (`publish_ga_executive_orders.py`) |
| `eo-text/` | the order PDFs' text | `enrich_ga_executive_orders.py` | `update-ga-executive-orders` | `generate_ga_news.py` | ga-executive-orders |
| `ga-eo-issuers.json` | hand (who may issue orders) | hand, checked by `validate_ga_executive_orders.py` | — | validator | — |
| `ga-executive.json`, `ga-executive-seats.json` | hand (georgia.gov officeholders) | hand | — | `ga-executive.html`, `build_seat_holds.py` | — |

## 6. Elections

Conventions and runbooks: `docs/conventions-elections.md`.

| File | Source | Built by | Refresh | Read by | Published to |
|---|---|---|---|---|---|
| `races.json` | Georgia Secretary of State qualifying lists, plus `ga-race-candidate-overrides.json` | `build_legislative_races.py` (legislative primaries), `apply_overrides.py` | `apply-race-candidate-overrides` | race, candidate and legislator pages, MCP `search_races` | ga-races-elections (`publish_races.py`) |
| `ga-legislative-candidates.json` | Secretary of State candidate CSVs | `build_legislative_races.py` input | on demand | `build_legislative_races.py` | — |
| `ga-race-candidate-overrides.json` | hand | hand | — | `apply_overrides.py`, `build_legislative_races.py` | — |
| `race-results-index.json` | Secretary of State results (via `build_results_json.py`) | `build_race_results_index.py` | `publish-results` | `race.html` | ga-races-elections (`publish_results.py`) |
| `election-status.json` | hand | hand | — | `race.html`, `build_race_results_index.py` | — |
| `ga-election-calendar.json` | hand, from the Secretary of State election calendar | hand | — | next-election strip, `sample-ballot.html`, `ga-voter-access.html` | — |
| `ga-governor-2026-county.json` | Secretary of State county results | hand | — | `county-map.html`, `ga-general-2026-results.html` | — |
| `candidate-claims.json` | candidate submissions (Tally form), verified | hand | — | `candidate-claims.js` | — |
| early-vote data | Secretary of State absentee files plus ACS (Georgia Civic Data) | `generate_ga_early_vote.py` | `publish-early-vote-to-ga-races-elections` | early-vote pages | ga-races-elections (`publish_early_vote.py`) |
