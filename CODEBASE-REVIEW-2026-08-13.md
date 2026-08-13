# VoteGA.org Codebase Review — 2026-08-13

Three-part audit: **data accuracy**, **captured-but-unsurfaced data**, and **UI flow / IA / accessibility**.
All findings were verified against the actual data and source files. Read-only review — no files were modified.

Two findings were **disproven during cross-check** and are excluded from the body; see [Appendix B](#appendix-b--claims-checked-and-rejected).

---

## Contents

- [Tier 1 — Data is wrong or misleading in the UI right now](#tier-1--data-is-wrong-or-misleading-in-the-ui-right-now)
- [Tier 2 — Will break on a date](#tier-2--will-break-on-a-date)
- [Tier 3 — UI flow, IA, and accessibility](#tier-3--ui-flow-ia-and-accessibility)
- [Tier 4 — Captured but unsurfaced](#tier-4--captured-but-unsurfaced)
- [Appendix A — Verified clean](#appendix-a--verified-clean)
- [Appendix B — Claims checked and rejected](#appendix-b--claims-checked-and-rejected)
- [Appendix C — Status of prior review docs](#appendix-c--status-of-prior-review-docs)
- [Suggested sequencing](#suggested-sequencing)

---

## Tier 1 — Data is wrong or misleading in the UI right now

### 1.1 Every bill link in every legislator's voting history points at a SOAP WSDL endpoint
#### [X - 8/13/26] 

**Where:** `scripts/generate_ga_votes_data.py:341-345` → rendered at `ga-member.html:1035`

The source picker is:

```python
next(s['url'] for s in sources if 'legis.ga.gov' in s['url'])
```

`http://webservices.legis.ga.gov/GGAServices/Members/Service.svc?wsdl` contains that substring and wins the match.

**Evidence:** **2,223 of 2,223** entries in `ga-member-votes.json` have a `billUrl` ending in `Service.svc?wsdl`. By contrast, `ga-bills.json` has 5,480/5,480 correct `https://www.legis.ga.gov/legislation/<id>` URLs — the two files disagree about the same bills.

**Fix:** match `'www.legis.ga.gov/legislation/'` (or exclude `webservices.`) instead of the bare domain. Regenerate `ga-member-votes.json`.

**Effort:** S (one line + regeneration)

---

### 1.2 GA per-legislator vote rosters are ~15% incomplete; 39 sitting legislators have zero votes
#### [X - 8/13/26] 

**Where:** `scripts/generate_ga_votes_data.py:378-381` — `if not voter_id: continue`, silently, with no counter.

**Evidence:**

| Measure | Value |
|---|---|
| Sum of reported yes/no across all roll calls | 227,613 |
| Accounted for in per-member rosters | 192,575 (84.6%) |
| Roll calls with a deficit | 2,223 of 2,223 (min 6, median 10, max 26) |
| Active legislators with no vote record at all | 39 |
| …of those, sharing a surname with another member | **36 of 39** |
| Surname collisions among members who *do* have votes | 6 of 193 |

Colliding surnames include Jones (×5), Smith (×5), Jackson (×4), Williams (×3). Open States is failing to resolve `voter.id` for ambiguous surnames, and the script drops those rows without counting them.

**Fix:**
1. Count and report unresolved-voter rows in `metadata` so the gap is visible in the data file.
2. Fall back to matching `voter.name` against `ga-members.json` when `voter.id` is absent.

**Effort:** M

---

### 1.3 Party tallies and the ⚡ party-line badge are computed on that 85% roster and shown beside official totals
#### [X - 8/13/26]

**Where:** `scripts/enrich_bills_with_party_votes.py:80-92` → `ga-bills.html:486-493`; `computePartyLineInfo()` at `ga-bills.html:449-465`

**Evidence:** HB 1000 renders `✓ 172 yes / 0 no` with `Dem 61-0 · Rep 85-0` underneath — 146 of 172 votes accounted for. The party-line ⚡ tag and its `dPct`/`rPct` percentages run on the same partial data.

There *is* a caveat string ("may not include every recorded vote"), which is why this is not rated higher — but the systematic ~15% gap is not disclosed in magnitude, and the numbers sit directly beside the official totals they contradict.

**Compounding factor:** `ga-member-votes.json` metadata carries `paginationComplete: false`, with `duplicateVotesDropped: 1693` and `crossChamberDropped: 4184` over `totalBillsSeen: 4540` (vs. 5,480 bills in `ga-bills.json`). 294 of 2,517 `passageVotes` have no `partyTally` at all. Meanwhile `ga-member.html:854-951` presents participation-rate percentages as if the denominator were whole.

**Fix:** resolve 1.2. Until then, have the enricher emit a per-vote `coverage` ratio so the UI can suppress the party-line tag below a threshold.

**Effort:** S for the coverage ratio; depends on 1.2 for the real fix.

---

 ### 1.4 `TO-DO.md`'s "ghost OCD IDs" entry is stale in a user-facing direction
 #### [X - 8/13/26] 

`TO-DO.md` states the party breakdown is "currently hidden." **It is not hidden** — `ga-bills.html:481-506` ships it behind a gray parenthetical hedge. Known-incomplete numbers are being published while the tracking doc says they aren't.

The 11 ghost OCD IDs themselves **are fixed**: 0 of 204 vote-member IDs are now missing from `ga-members.json`.

**Fix:** update `TO-DO.md` to reflect what actually ships, and decide deliberately whether the hedge is sufficient (see 1.3).

**Effort:** S

---

### 1.5 Ten resigned legislators are indexed as sitting members in site search
#### [X - 8/13/26] 

**Where:** `scripts/generate_search_corpus.py:82-105` — no `status` filter in `build_ga_legislators()`.

**Evidence:** `search-entities.json` contains Freddie Powell Sims (indexed as "Senator, District 12, Democratic"), Nabilah Islam Parkes, Dexter Sharper, Jason Esteves, John Kennedy, Brandon Beach, Lynn Heffner, Karen Bennett, Mandi Ballinger, and Marcus Wiedower — all carrying `status: "Resigned"` in `ga-members.json`, none marked as such in the index.

Every other consumer filters these correctly: `ga.js:174`, `ga-majority-tracker.html:322`, `ga-member.html:365`.

**Fix:** skip `Resigned`/`Removed`/`Deceased` in `build_ga_legislators()`, or append the status to `desc`.

**Effort:** S

---

### 1.6 GA-13 has no federal representative record, and no page explains why
#### [X - 8/13/26] 

**Evidence:** `current-members.json` (generated 2026-08-12) contains 15 Georgia members covering districts 1–12 and 14. **District 13 is absent** — Rep. David Scott died; the special election was 2026-07-28 with a runoff 2026-08-25.

`congress.js:100` logs "No members matched" to the console and the UI shows nothing. A GA-13 constituent using find-my-reps gets an empty result rather than an explanation.

**Fix:** add a vacancy notice keyed off the missing district, linking to `/ga-special-2026-runoff-results/`.

**Effort:** S

---

## Tier 2 — Will break on a date

### 2.1 `ga-executive-orders.html` will silently hide all 2027 executive orders on Jan 1
#### [X - 8/13/26]

**Where:** `ga-executive-orders.html:147-152` (the `DATA_FILES` map) and `:177` (`let activeYear = 2026`)

The workflow writes `ga-executive-orders-$(date +%Y).json` (`update-ga-executive-orders.yml:32`), so a 2027 file will be generated and committed — but it has no entry in `DATA_FILES` and no year button. Confirmed hardcoded, not derived.

**Fix:** derive the year list from `new Date().getFullYear()` down to 2023 and default `activeYear` to the current year.

**Effort:** S

---

### 2.2 Hardcoded election cycle in the shared finance code and its consumers
#### [X - 8/13/26]

| File | Line | Hardcoded value |
|---|---|---|
| `assets/scripts/campaign-finance.js` | 21 | `election_year=2026` |
| `assets/scripts/campaign-finance.js` | 180 | `cycleLabel: '2025–2026 cycle'` |
| `candidate.html` | 461, 474, 480-481 | duplicated cycle logic |
| `member.html` | 609, 615-616 | duplicated cycle logic |
| `scripts/generate_fec_data.py` | 37 | `CYCLE = 2026` |
| `ga-majority-tracker.html` | 280 | literal `-2026` appended to every race URL |

**Contrast:** `scripts/generate_ga_campaign_finance.py:48` does this correctly — derives the cycle from `races.json`, with `FALLBACK_CYCLE` only as a fallback.

**Fix:** derive from `ga-fec-data.json` → `metadata.cycle` (already present, `= 2026`) the way the GA generator does.

**Effort:** M — the duplication across four files is most of the work.

---

### 2.3 `races.json.updatedAt` is three months stale relative to file content
#### [X - 8/13/26] 

`assets/data/races.json` carries `updatedAt: "2026-05-11T00:00:00Z"`, but `git log` shows the file was last written **2026-08-09**. The general-election ballots *were* resolved post-primary (0 of 441 party-ballots has more than one candidate, vs. 140 contested primary ballots) — the data is current, the timestamp is not.

**Fix:** have `update_general_from_primary.py` / `set_general_candidates.py` stamp `updatedAt` on write.

**Effort:** S

---

### 2.4 `primaryResult` is empty on all 352 races, so a UI branch is dead

`race.html:556-561` gates on `race.phases.primary?.primaryResult`. All 352 races have `primaryResult: ""` despite the primary (2026-05-19) and runoff (2026-06-16) being complete, with certified results sitting in `_data/election_results/ga-primary-results.json`.

**Fix:** populate it from the results JSON, or remove the dead branch.

**Effort:** M to populate, S to remove.

---

### 2.5 `update-ga-votes` did not produce a commit this week

`ga-member-votes.json` is stamped `generatedAt: 2026-08-08` (a Saturday), while `update-ga-votes.yml` runs `30 7 * * 1` (Mondays). Monday 2026-08-10 produced no update.

`generate_ga_votes_data.py:441-447` calls `sys.exit(1)` on a partially-applied incremental run — the expected symptom of the Open States 250/day quota being exhausted.

**Fix:** check the workflow run log; consider staggering `update-ga-bills` and `update-ga-votes` onto different days so they don't share the daily quota.

**Effort:** S

---

## Tier 3 — UI flow, IA, and accessibility

### Top priorities

#### 3.1 `federal-reps.html` and `my-representatives.html` embed a nested full HTML document
#### [X - 8/13/26]

**Where:** `federal-reps.html:28-48`, `my-representatives.html:35-48`

Both pages contain a complete `<!DOCTYPE html><html><head><style>…<body>` document *inside* the Jekyll page. The inline rule:

```css
body { font-family: system-ui; margin: 2rem; max-width: 680px; }
```

applies to the **real** `<body>`. The site's primary federal-lookup page therefore renders in a different font, at a different width, with different margins than every other page. `select, button { width: 100% }` leaks the same way.

**Fix:** delete the nested document; keep only the `<form>` and scope the CSS.

**Effort:** S — largely a deletion. Highest visible-defect-per-line-changed item in this review.

---

#### 3.2 `member.html` sends users to a deprecated page in three places
#### [X - 8/13/26]

`member.html:303`, `:360`, and `:990` all link to `my-representatives.html`, which is now a stub whose entire content is a "This page has moved" banner. Every federal member profile's "Search for another member" link is a bounce.

**Fix:** repoint all three to `/federal-reps`. Then replace `my-representatives.html`'s body with `redirect_to: /federal-reps` — the `jekyll-redirect-from` plugin is already loaded (`_config.yml:351`). It currently duplicates `federal-reps.html` verbatim and competes with it for the same search queries.

**Effort:** S

---

#### 3.3 The home page has no presence for the site's core journey
#### [X - 8/13/26] 

`index.html` is 8 lines of front matter with `layout: home`, which renders nothing but the paginated blog feed (`_layouts/home.html`). A Georgia voter arriving at votega.org sees ten blog posts and must find "Find My Reps" in the navbar.

**Fix:** put the two `find-my-reps` cards (or a chamber + county picker) directly in `index.html` above the post feed. The card CSS already exists at `find-my-reps.html:20-80`.

**Effort:** S–M

---

#### 3.4 Federal lookup has no county filter; state lookup does
#### [X - 8/13/26] 

`ga-state-reps.html:134` offers "Filter by county." `federal-reps.html` offers only Chamber → a dropdown of 14 names, forcing the user to already know their congressional district.

`assets/scripts/ga-districts.js:331` already defines `COUNTY_US_HOUSE_DISTRICTS`, and `congress.js` already loads that file (only to enumerate vacant seats).

**Fix:** add the same county filter. The data is already loaded in the browser.

**Effort:** S

---

#### 3.5 `local-officials.html` is a published orphan

The page documents its own intent at `local-officials.html:8-13` ("Intentionally NOT in the navbar yet") — but it has no `sitemap: false`, so `jekyll-sitemap` publishes it, and Jekyll's page corpus feeds it into site search (`_includes/search.html`). Users can land on an unfinished roster from Google or the search box with no way back to context.

**Fix:** add `sitemap: false` plus `<meta name="robots" content="noindex">` until launch, **or** wire it into `find-my-reps.html` as a third card.

**Effort:** S

---

#### 3.6 Member detail pages have generic `<h1>`s and never set `document.title`
#### [X - 8/13/26]

`member.html:7` = "Legislative Member Details"; `ga-member.html:8` = "Georgia Legislator Details". The actual person is an `<h2>`. Neither calls `document.title = …`.

Contrast the pages that do it correctly: `race.html:619`, `candidate.html:311`, `justice.html:328`, `executive-member.html:281`.

Every shared federal or state legislator link previews and reads identically — bad for sharing, search, and screen readers.

**Effort:** S

---

### Navigation and information architecture

#### Actual site graph

```
/ (home)  ──> blog posts only
nav ──> /find-my-reps ──> /federal-reps ──> member.html?bioguideId=
        │                └> /ga-state-reps ──> ga-member.html?id=
        │                                       ├> race.html?id=
        │                                       └> candidate.html?id=
        ├─> /elections/ (hub) ──> elections.html ──> race.html ──> candidate.html
        │                    ├─> ga-voter-access.html    [dead end]
        │                    ├─> ga-ballot-measures.html [dead end]
        │                    └─> /results/ ──> ga-primary-results, ga-primary-runoff-results,
        │                                      ga-special-2026-results, -runoff-results
        ├─> ga-congress-trades.html  [dead end]
        ├─> executive-branch.html ──> executive-member.html
        ├─> supreme-court.html ──> justice.html
        ├─> ga-executive.html ──> candidate.html (reelection only)
        ├─> ga-bills.html            [dead end]
        ├─> ga-majority-tracker.html ──> race.html
        ├─> ga-executive-orders.html [dead end]
        ├─> flock-safety, flock-covington
        └─> about, about-the-data, open-data ──> /about-the-data

ORPHANS: local-officials.html, results-latest.html, 404.html (dead end),
         tags.html (posts only), my-representatives.html (reachable only
         *backwards* from member.html)
```

The nav (`_config.yml:26-46`) exposes 14 destinations across 1 hub + 2 direct links + 4 dropdowns. Everything else is second- or third-level.

#### 3.7 No footer navigation — the cheapest IA win available

`_includes/footer.html` renders only email/RSS icons and a copyright line. With ~30 pages and 14 in the navbar, a three-column footer sitemap (Representatives / Elections / Government / About) would surface `/results/`, `/ga-ballot-measures`, `/ga-voter-access`, `justice.html`, and `local-officials` — none of which are in the navbar.

**Effort:** S

#### 3.8 `results-latest.html` is built but never linked

`/results/latest/` (`results-latest.html:4`) is a maintenance-free pointer to the newest non-upcoming election, and nothing links to it. `elections-hub.html:118` points at `/results/` (the full archive). On election night, `/results/latest/` is the useful link.

**Fix:** make the elections-hub "Election Results" card CTA `/results/latest/`, keep the archive as a secondary link inside the card.

#### 3.9 `404.html` is a total dead end
#### [X - 8/13/26] 

`404.html:8-13` is an `<h1>`, a joke, and an image — no link home, no search prompt, no nav. On a site with several `?param=`-driven detail pages that 404 on a mistyped ID, this is the highest-traffic failure surface.

**Fix:** add "Find my representatives / Elections / Search" links.

#### 3.10 Nav grouping mixes taxonomies

"Federal Government" contains *Congressional Stock Trades* (a legislator-behavior dataset) while "Find My Reps" contains the legislators themselves. "State of Georgia" contains a bill tracker, a majority tracker, executive offices, and executive orders with no sub-grouping. *Flock Safety* — a single-topic section unrelated to the other five menus — occupies a whole top-level slot.

**Suggested regroup:** `Find My Reps` / `Elections` / `Legislation` (bills, majority tracker, key votes) / `Government` (federal exec, SCOTUS, GA exec, EOs, stock trades) / `About` (+ Flock under About or the footer).

#### 3.11 `elections-hub.html` and `elections.html` are one character apart in URL

`/elections/` and `/elections.html` are two different pages. `race.html:644` back-links to `elections.html`; `results.html:114` links to `/elections`. Maintenance trap and an ambiguous URL to share.

**Fix:** rename `elections.html` to `/candidates` or `/elections/candidates`.

---

### Entry-point flow

Core journey: *"I'm a Georgia voter — who represents me and how do they vote?"*

| Path | Steps |
|---|---|
| **State** | `/` → nav *Find My Reps* (1) → *GA State Representatives* card (2) → chamber tab (3) → county dropdown, 159 options (4) → member row (5) |
| **Federal** | `/` → nav *Find My Reps* (1) → *Federal Representatives* card (2) → Chamber `<select>` (3) → Member `<select>` (4) → **Submit** (5) |

#### 3.12 Two different interaction models for the same task

State: tabs + county filter + clickable rows, live-filtering, no submit. Federal: two dependent dropdowns + an explicit Submit. Users who do one and then the other have to relearn. **The state pattern is better; port it.**

#### 3.13 Address-based lookup remains unimplemented

Both lookups punt to the SoS My Voter Page (`federal-reps.html:24`, `ga-state-reps.html:15`, `elections.html:454`). The address-based lookup recommended in `01-Recommendations for votega.md` item 8 (Census Geocoder — free, keyless, CORS-friendly) would eliminate this friction across `find-my-reps`, `ga-state-reps`, `federal-reps`, and `elections.html` at once.

#### 3.14 Deep-link behavior is uneven

| Page | Param | Missing param | Bad param |
|---|---|---|---|
| `member.html` | `?bioguideId=` | "No member selected" + link ✓ (to dead page) | "Error loading details" — **misleading**, it's a not-found |
| `ga-member.html` | `?id=`, `&county=`, `#hash` ✓ | "No member selected" ✓ | throws → "Error loading details" ✗ |
| `race.html` | `?id=` | "No race specified" ✓ | "Race not found" ✓ |
| `candidate.html` | `?id=` / `?raceId=&memberId=&memberSource=` | "No candidate specified" ✓ | "Candidate not found" ✓ |
| `justice.html` | `?id=` | "No justice ID specified" ✓ | "Justice not found: `id`" ✓ |
| `executive-member.html` | `?id=` | throws → generic "Could not load" ✗ | same ✗ |
| `ga-congress-trades.html` | `?member=` ✓ | prompt shown ✓ | silently empty table ✗ |
| `elections.html` | **none** ✗ | — | — |
| `ga-bills.html` | **none** ✗ | — | — |

**Fixes:**
- `member.html:326`, `:354-360` and `ga-member.html:349`, `:375-381` — distinguish "not found in data" from a fetch failure, the way `race.html` does.
- `executive-member.html:278` — give the not-found case its own message with a link back.
- `elections.html` — put `activeTab`, `activePhase`, and `countySelect.value` in the query string (`:466-486` already holds all three in module state) so a voter can share "GA House races in Newton County."
- `ga-bills.html` — add `?bill=HB111` and a per-card anchor. **There is currently no way to link to a specific bill at all.**

#### 3.15 Back-navigation is inconsistent
#### [X - 8/13/26] 

`candidate.html:332` and `race.html:644` have styled `.back-link` blocks; `justice.html:172` has a top-of-page link; `executive-member.html:381` has a bottom paragraph link; `member.html` and `ga-member.html` have **neither** — only an inline "Search for another member" buried after the contact block (`member.html:990`), and nothing at all on `ga-member.html`.

#### 3.16 Tab state is lost on browser Back
#### [X - 8/13/26] 

`member.html:996-1004`, `ga-member.html`, `race.html:626`, and `_layouts/election_results.html:212` all use in-page tabs with no hash/history sync. Open Voting History → click a bill → hit Back → land on Key Votes.

---

### Cross-linking gaps

Ranked by cost to the user.

**3.17 — bill ↔ sponsor (missing both directions).** `ga-bills.html:560-562` renders `bill.sponsors.map(s => s.name).join(' · ')` inside `escHtml` — dead text. `ga-member.html`'s curated-bill cards link out to `openstatesUrl`/`fullTextUrl` (external), never to the site's own bill tracker. **The two flagship datasets — 5,480 bills and 236 legislators — do not touch each other in the UI.**
Fix: match `sponsors[].name` against `ga-members.json` at build time (add an `ocdId` field per sponsor in the bills generator), render as links, and add a per-bill anchor so `ga-member.html` can link back in. See also 4.2.

**3.18 — trades → member.** `ga-congress-trades.html:463-511` renders name, party badge, photo, district, and trade count — everything needed for a profile link — and links nowhere. `member.html:991` links *into* trades; nothing links back out. The page has no outbound site links at all.

**3.19 — majority tracker → member.** `ga-majority-tracker.html:432` and `:492` route every seat click to `race.html?…`. A user clicking "Newton, D-113" in a seating chart almost certainly wants the legislator, not their 2026 race. Link seats to `ga-member.html?id=…`; put the race link in the tooltip or a secondary line.

**3.20 — ballot measure → enabling bill.** `ga-ballot-measures.html:166-167` links enabling legislation to an external `leg.url`. That bill is in `ga-bills.json`. Link internally.

**3.21 — election results → candidate/race.** `_layouts/election_results.html:renderContest()` renders `cd.name` as bare text on every results page. `_data/election_archive.yml` already joins to `races.json` on cycle+phase per its own header comment, so candidate names could link to `candidate.html?id=`. A voter reading results has no path to the candidate's finance or bio.

**3.22 — voter access & ballot measures are dead ends.** `ga-voter-access.html` links only to `mvp.sos.ga.gov` (`:144`, `:154`); `ga-ballot-measures.html` links only to external bill text. Both should carry elections-hub sibling links the way `results.html:113-116` does.

**3.23 — `member.html` has no candidate-profile link.** `ga-member.html:557` builds `candidate.html?id=…` for state members running for another office; `member.html:945-976` only ever links to `race.html`. Federal members running for re-election should get the same "View candidate profile →".

---

### Loading / empty / error states

This is the **strongest area of the site** — nearly every fetch has all three states. Exceptions:

**3.24** — `ga-congress-trades.html:348-352`: failure message is workflow jargon — *"Could not load trade data. Run the update-ga-congress-trades workflow to generate it."* — an instruction only the maintainer can act on. `init()` also returns early, leaving the filter bar, table headers, and member-card container rendered and empty.

**3.25** — `elections.html:504-506`: the error renders into a `.msg` div *above* `#racesOutput`, which is left blank. With `.msg { color:#c00 }` and no `role="alert"`, a failure looks like an empty page with small red text far above the fold. Render the error inside `#racesOutput`.

**3.26** — `ga-congress-trades.html` has no empty state distinct from error. Filtering to a ticker with no matches produces an empty `<tbody>` with no message. (Contrast `ga-bills.html:311` `.bills-empty`, which is done well.)

**3.27** — Cascading fetches fail silently with developer-facing copy. `race.html:690-696` — if the members fetch fails, `members` stays `[]` and every incumbent card renders *"Member data not found. Check that memberId matches the data file."* (`race.html:412`). `ga-member.html:341` — if `racesRes` fails, election banners silently vanish with no note.

**3.28** — Debug logging ships to production. `assets/scripts/congress.js` logs on every filtered-out member (`:70`, `:76`, `:88`) — roughly 500 console lines per lookup. `member.html:281` has a `DEBUG` flag; `congress.js` has none.

---

### Consistency

**3.29 — Global CSS leaking out of page scope.** Beyond 3.1: `elections.html:12-13` has bare `label { display:block; margin-top:1.2rem }` and `select { width:100% }`, applying to every label and select on the page — including the county filter, which then has to re-specify at `:105`.

**3.30 — Card CSS is copy-pasted, not shared.** `find-my-reps.html:20-80` (`.rep-card*`) and `elections-hub.html:11-71` (`.election-card*`) are byte-for-byte identical rule sets with a different class prefix — 60 duplicated lines. Same for `.tab-bar`/`.tab-btn`, defined independently in `ga-state-reps.html:83-97`, `elections.html`, `_layouts/election_results.html:70-76`, and `ga-bills.html`.
**Fix:** one `assets/css/votega-components.css` added via `site-css` in `_config.yml:188`.

**3.31 — Party color/label conventions differ per page.**

| Page | Dem | Rep | Mechanism |
|---|---|---|---|
| `_layouts/election_results.html:63` | `#2471a3` | `#c0392b` | CSS vars + text badge ✓ |
| `ga-state-reps.html:172-173` | `#1d4ed8` | `#b91c1c` | `.party-d`/`.party-r`, color only |
| `local-officials.html:53-54` | `#1a56a8` | `#b91c1c` | pill with label ✓ |
| `ga-bills.html:485-486` | `#2563eb` | `#dc2626` | inline color + "Dem"/"Rep" ✓ |
| `race.html`, `candidate.html` | `.party-D`/`.party-R` | | badge with label ✓ |
| `ga-congress-trades.html:466-468` | `badge-d` "D" | `badge-r` "R" | single letter |
| `ga-majority-tracker.html` | `COLOR[party]` | | **fill color only, no label** ✗ |

Four different blues, three reds, and one page conveying party purely by color (see 3.35).

**3.32 — Date formats.** `ga-bills.html:498` and `:515` render raw ISO strings (`2025-03-04`) — the only page that does. Among formatted pages there are three variants: `{month:'long'}` (`race.html:388`, `elections.html:332`), `{month:'short'}` (`justice.html:191`, `member.html:749`), and `{weekday:'long', month:'long'}` (`ga-voter-access.html:182`). Pick two and share a helper.

**3.33 — Tables that will overflow on narrow screens.** Only `ga-congress-trades.html:101`, `race.html:206`, and `ga-majority-tracker.html:113` wrap tables in `overflow-x:auto`. Unwrapped and at risk:
- `member.html:620` `.employers-table`, `member.html:846` `.vote-table`
- `candidate.html:485` `.employers-table`
- `ga-member.html:1062` `.vote-table`
- `ga-executive-orders.html:130` `.order-table` (4 columns including a long title column)

**3.34 — `escHtml` is used on only 6 of 12 data-rendering pages.**
Defined in: `candidate.html`, `ga-ballot-measures.html`, `ga-bills.html`, `ga-member.html`, `ga-voter-access.html`, `member.html`.
**Absent from:** `race.html`, `ga-congress-trades.html`, `executive-branch.html`, `executive-member.html`, `justice.html`, `supreme-court.html`, `ga-executive.html` — all of which interpolate names, bios, and third-party asset descriptions straight into `innerHTML`.

`ga-congress-trades.html` is the sharpest case: asset descriptions come from congressional disclosure filings, the least-sanitized upstream on the site.

Also note six duplicate copies of `escHtml` and eight of `getBasePath()` — candidates for the shared-JS file.

**3.35 — Filter UI patterns.** Three coexisting idioms: pill buttons (`ga-bills.html:355-364`, `_layouts/election_results.html:198-202`), `<select>` dropdowns (`ga-state-reps.html:134`, `elections.html:172`), and clickable cards (`ga-congress-trades.html`). Search boxes exist on `ga-bills.html:336` and `_layouts/election_results.html:204` but not on `ga-state-reps.html` or `elections.html`, where a name search would be the fastest path.

---

### Accessibility

**3.36 — Heading order.**
- **`justice.html` contains zero heading elements** — the justice's name is a styled `<div>`. A screen-reader user has no page structure at all.
- `member.html:7` / `ga-member.html:8` — generic `<h1>`, person at `<h2>` (see 3.6).
- `ga-member.html:276` — `<h3 id="sidebarTitle">Nearby Districts</h3>` appears in source *before* the `<h2>` that JS injects into `#memberDetails`, giving DOM order h1 → h3 → h2.
- `_layouts/default.html` never includes `header.html`, so unlike `page.html` the title is never auto-rendered — every `layout: default` page must hand-write its own `<h1>`, and `justice.html` doesn't.

**3.37 — Form labels.** Missing or implicit on `ga-bills.html:336` (`#billSearch`, placeholder only), `_layouts/election_results.html:204` (`#searchBox`, placeholder only), `federal-reps.html:47`/`:56` and `my-representatives.html:54`/`:63` (wrapping `<label>` with no `for`), and `ga-executive.html`. Correct on `ga-state-reps.html:134`, `elections.html:172`, `ga-congress-trades.html:227-243`.

**3.38 — Keyboard reachability of custom controls.**
- `ga-congress-trades.html:463-511` — member cards are `<div>` + click listener: no `tabindex`, no `role`, no key handler.
- `ga-majority-tracker.html:478-492` — House hemicycle seats are SVG `<circle>` with click listeners, while **the Senate seats on the same page are real `<a>` elements** (`:429-431`). Same page, same interaction, half of it keyboard-reachable.
- `ga-bills.html:573` — bill card headers use `onclick` on a `<div>` with `aria-expanded` correctly toggled (`:609`) but no `role="button"` and no `tabindex="0"`, so the ARIA state is announced to nobody.
- `.tab-btn` implementations across `ga-state-reps.html`, `elections.html`, `ga-bills.html`, `race.html`, `_layouts/election_results.html` are real `<button>`s (reachable ✓) but none carry `role="tab"` / `aria-selected` / `aria-controls`.

**3.39 — Color-only party conveyance.** `ga-majority-tracker.html`'s House hemicycle encodes party solely as `fill: COLOR[party]`, with the name in a tooltip — red/blue at 9px circle size. Add a pattern, shape difference, or focus-triggered text readout. `ga-state-reps.html:172-173` similarly colors the name with no letter or badge.

**3.40 — Alt text.** Generally good — member photos use the person's name (`member.html:896`, `ga-member.html:533`, `race.html:400`); party icons have descriptive alt (`ga-member.html:390-393`, "Donkey logo of the Democratic party"). Two gaps: `404.html:12` uses `alt="Not found"` on a decorative joke image (should be `alt=""`), and `ga-congress-trades.html:475` builds `alt="${name}"` with the name unescaped.

**3.41 — Error regions lack `role="alert"`.** The `.msg` divs on `member.html:294`, `ga-member.html:282`, `elections.html:189`, and `federal-reps.html` are populated asynchronously with no live-region announcement.

---

## Tier 4 — Captured but unsurfaced

Method: enumerated every key with non-null fill rates across all 44 files in `assets/data/`, including nested arrays, then grepped all top-level `*.html` and `assets/scripts/*.js` for each key.

**Headline:** the site surfaces most of what it captures. `ga-member.html`, `member.html`, `ga-bills.html`, and `ga-congress-trades.html` are all quite thorough. The real gaps are one orphaned dataset, cross-linking failures, and the SCOTUS pages.

### 4.1 `ga-campaign-finance-history.json` — 1.1 MB, generated, committed, read by zero pages

| Measure | Value |
|---|---|
| Filer records | 1,545 |
| Cycle years | 11 (2014, 2016, 2018, 2020–2026, 2028) |
| Distinct entities | 1,137 |
| Entities with multi-cycle records | **300** |
| Fill on `totalRaised`/`totalSpent`/`cashOnHand`/`office`/`party`/`electionCycle` | 100% |
| `district` / `committeeName` / `middleName` | 89.9% / 75.3% / 61.5% |
| Names joinable to the current-cycle file | **375** |

Sample record:
```json
{"filerName":"Scott Sanders","office":"State Representative","totalRaised":1285.78,
 "totalSpent":1150.0,"cashOnHand":135.78,
 "electionCycle":"2025 Special Election House District 23","cycleYear":2025}
```

The file ships pre-built `byCycleYear` and `byNormalizedName` indexes that nothing reads, and its own metadata documents the join: *"filerEntityId is NOT shared… Join on office + district + normalized name."*

`ga-member.html` shows only the current-cycle snapshot from `ga-campaign-finance.json` — three cards, no trend.

**Surface:** a "Fundraising over time" chart in the existing `campaignFinance` section of `ga-member.html`, and in the finance comparison tab on `race.html`.
**Effort:** M

---

### 4.2 GA legislator sponsorships never appear on their member page

`ga-bills.json` → `bills[].sponsors[]` is **100% filled** — 32,403 sponsor rows across 5,480 bills. **222 of 250 legislators** in `ga-members.json` match by exact name string (242 distinct sponsor names). Top primary sponsors: Kenya Wicks (462), RaShaun Kemp (449), Tonya Anderson (416).

`ga-member.html` loads `ga-members.json`, `races.json`, `ga-campaign-finance.json`, `curated-ga-bill-votes.json`, and `ga-member-votes.json` — but **never `ga-bills.json`**. The federal equivalent (`member.html`) already has a "Sponsored Legislation" tab driven by `recentSponsored`; the GA member page has no counterpart despite richer data.

**Surface:** a "Bills Sponsored" tab on `ga-member.html` alongside the existing vote-record tabs.
**Effort:** M — mainly because `ga-bills.json` is 9 MB; build a sponsor→bills index at build time rather than fetching the whole file client-side.

> ⚠️ **Caveat before building this or 3.17:** `sponsors[].primary` is `true` on **all 32,403 rows** — the field carries zero signal, and there is no primary/cosponsor distinction in the data. `ga-bills.html:438` treats `sponsors[0]` as the lead sponsor and labels the rest "+N others," which is arbitrary ordering, not a real lead-sponsor determination. Verify against Open States before leaning on sponsor role.

---

### 4.3 SCOTUS: `question`, `conclusion`, and `arguedDate` at 100% fill are never rendered

`assets/data/scotus-decisions.json`, 111 cases:

| Field | Fill | Rendered? |
|---|---|---|
| `question` | 100% | **never** |
| `conclusion` | 100% | **never** |
| `arguedDate` | 100% | **never** |
| `opinions[]` | 78.4% | **never** (see 4.4) |
| `winningParty` | 51.4% | **never** |
| `decisionType` | 51.4% | **never** |
| `decisionDesc` | 51.4% | **never** |
| `description` | 100% | yes — `supreme-court.html:216`, `justice.html:239` |

`supreme-court.html:195-220` renders only name, docket, date, term, vote tally, `description`, vote chips, and links.

Sample of what's dropped — `question`: *"Do the statutory removal protections for members of the Federal Trade Commission violate the separation of powers?"* `conclusion` is a full multi-sentence holding. That is the single most useful sentence about each case, already fetched and committed.

**Surface:** expandable "Question presented / Holding" disclosure on each `supreme-court.html` card (S), or the basis for a proper case-detail page (M). `arguedDate` also enables an argued→decided duration display for free.

---

### 4.4 `opinions[].author` — who wrote the dissent — is invisible on `justice.html`

`cases[].opinions[]` is 78.4% filled:
```json
[{"type":"concurring","label":"Concurring opinion","author":"Gorsuch","justiaUrl":"…"}]
```

`justice.html` builds its per-justice case list from `cases[].votes[]` (`justiceId`, `vote`, `opinionType`) and never touches `opinions[]`. **A justice profile page that can't tell you which opinions that justice authored is missing its most characteristic content.**

**Surface:** an "Opinions authored" section on `justice.html`, keyed on `opinions[].author` matching the justice's last name.
**Effort:** S

---

### 4.5 `cosponsoredLegislation.count` — 100% filled, shown nowhere

`current-members.json` → `cosponsoredLegislation`: `{"count":1334,"url":"…"}`, 100% fill across all 537 members. `member.html:744` displays `sponsoredLegislation.count`; the cosponsored counterpart appears in **zero** files. One line next to the existing sponsored total.
**Effort:** S

---

### 4.6 Prior-chamber / non-consecutive service is captured but flattened away

`current-members.json` → `terms.item[].endYear` is 9.7% filled across 595 term records; **58 of 537 members have more than one term entry** — House-then-Senate transitions and service gaps. `member.html:888-890` collapses this to `min(startYears)`, so a senator who served in the House first shows one number and no chamber history. Only `candidate.html` reads `endYear` at all.

**Surface:** a small "Service history" list on `member.html`.
**Effort:** S

---

### 4.7 Federal votes lack the party tally the GA votes have (capture gap, not surfacing gap)

`federal-member-votes.json` → `votes` (206 records) carries `yea`/`nay`/`result`/`chamber` at 100% but **no `partyTally`**, while `ga-bills.json` enriches every GA vote with one. The GA side has `enrich_bills_with_party_votes.py` with no federal equivalent, so `member.html` can't show the party breakdown `ga-member.html` shows. Same feature missing on half the site.
**Effort:** M

---

### 4.8 Orphan files — generated and committed with zero consumers

| File | Size | Contents | Assessment |
|---|---|---|---|
| `ga-campaign-finance-history.json` | 1.1 MB | 1,545 filers, 11 cycles | **Real value, just unwired** — see 4.1 |
| `ga-legislative-candidates.json` | 565 KB | `{election, electionDate, results, errors, csvFilesProcessed}` | Likely superseded by the `build_results_json.py` / `_data/election_results` pipeline |
| `ga-bills-subjects.json` | 5 KB | per-bill subject map keyed `"HB 1532"` | Likely superseded by `subjects` now living in `ga-bills.json` |
| `curated-ga-bills.json` | 5 KB | `{_note, ga}` | Superseded by `curated-ga-bill-votes.json` (136 KB, live on `ga-member.html`) |
| `ga-ballot-measures.schema.json` | 8 KB | schema | Expected — validation artifact, not page data |

The middle three look like dead weight worth deleting rather than surfacing.

---

### 4.9 Additional data-quality issues found while measuring

- **`ga-bills.json` → `subjects` is only 49.4% filled** (53 distinct subjects; top: Local/Municipal 525, EDUCATION 339, REVENUE AND TAXATION 276). The `ga-bills.html` subject filter works, but selecting any subject silently excludes the half of bills with no subject at all. Add an "unclassified" option or a note. (`TO-DO.md` tracks a related "32 bills lack subject tags" item.)
- **`races.json` has one candidate with `imageurl` (lowercase)** instead of `imageUrl` — 0.1% of 1,194 ballot entries, value `https://jodilewisforgeorgia.com/wp-content/uploads/2026/03/elect-jodi.webp`. The photo is silently dropped on `race.html` / `candidate.html`.

---

### 4.10 Low fill / probably not worth it

- `ga-congress-trades` → `trades[].comment` (13.2%, e.g. `"Filing Status: New\nSubholding Of: SCH1"`) — noisy, low value.
- `vp-tie-votes` → `resultText` / `documentTitle` (100% / 75%, 8 records) — tiny dataset, already well covered by `executive-member.html`.
- `presidential-laws` → `actionText` / `originChamber` (100%, 104 records) — unused but marginal. The bigger question is that `presidential-laws.json` is reachable only through `executive-member.html` and has no standalone browsable page.

---

## Appendix A — Verified clean

These were specifically checked and found correct. No action needed.

- **Ghost OCD IDs are fixed.** 0 of 204 vote-member IDs are missing from `ga-members.json` (down from 11 in prior notes).
- **`campaign-finance.js` and `report_ga_finance_matches.py` genuinely mirror each other.** Compared `gaToks`/`toks`, `gaNicknames`/`nicknames`, `gaFirstNameOk`/`first_name_ok`, `gaCandidatePool`/`candidate_pool`, and `findGaFilers`/`find_filers` line by line — same suffix regex, apostrophe handling, order of operations, surname-suffix comparison, and the same "tiebreak only if it resolves to exactly one, else stay ambiguous" rule. All 52 override keys in `ga-campaign-finance-overrides.json` match the 52 embedded in `ga-campaign-finance.json` exactly.
- **`build_results_json.py` math is sound.** Across all 4 built result files (573 contests), `totalVotes` equals the sum of candidate votes in **every** contest — 0 mismatches. The one `totalVotes: 0` contest is the Aug 25 runoff placeholder, correctly rendered as "No results reported" (`_layouts/election_results.html:175`, `:203`).
- **Vote-index collision risk in `enrich_bills_with_party_votes.py:39-41` is not live.** The `(bill, motionText)` key looked collision-prone, but `motionText` embeds the vote number ("Senate Vote #133 - …"), yielding 2,223 distinct keys for 2,223 votes — 0 collisions.
- **Daily datasets are fresh:** `current-members.json`, `ga-members.json`, `search-entities.json`, `curated-ga-bill-votes.json` (all 2026-08-12); `ga-executive-orders-2026.json` (2026-08-11). Weekly Sunday datasets all stamped 2026-08-09, which was a Sunday.
- **141 of 252 FEC candidate records carry no financial totals** — and this is **handled correctly**. `campaign-finance.js:190-193` uses `?? null`, `fmtMoney(null)` returns `'—'`, and `race.html:335`, `:338` use `|| 0` only for bar scaling and sort order, never for display. No `$0` is shown. Noted only because an "ok" status with all-dash cards is easy to misread as "filed nothing."
- **The `` characters in `ga-election-calendar.json` names are a Windows console artifact**, not file corruption — the bytes are clean UTF-8 em dashes.

---

## Appendix B — Claims checked and rejected

Two findings surfaced during review did **not** survive verification against the source. Recorded here so they aren't re-raised.

1. **"No signed/vetoed filter on `ga-bills.html`."** False. `ga-bills.html:352-364` has an eight-button status bar: All / Signed / Vetoed / Sent to Governor / Passed / In progress / Stalled / Failed.
2. **"Party-line vs. bipartisan classification is derivable but unused."** False. `computePartyLineInfo()` exists at `ga-bills.html:449-465`, the ⚡ badge renders at `:481-506`, and a "⚡ Party-line votes only" toggle sits at the end of the status bar (`ga-bills.html:363`).

*(The underlying data concern about these tallies is real and is captured as finding 1.3 — the feature exists; its inputs are incomplete.)*

---

## Appendix C — Status of prior review docs

Verified against the current codebase: `01-Recommendations for votega.md`, `Site feature survey review.md`, `TO-DO.md`, `RECURRING-TASKS.md`, and the six `*-design.md` files.

### Already done — do not re-raise

| Item | Evidence |
|---|---|
| Attendance / participation stats | marked `[X 7/15/26]` |
| Ballot measures page | `ga-ballot-measures.html` live, linked from hub |
| Governor's bill actions (signed/vetoed/pending) | `ga-bills.html:355-362` status pills + `governorDetailHtml()` |
| Party-line vote analysis | `ga-bills.html:481-506` tallies + ⚡ badge + filter |
| State campaign finance (PeachFile) | `assets/scripts/campaign-finance.js`, live on `ga-member.html:500-524`, `race.html`, `candidate.html` |
| Election admin / voter access page | `ga-voter-access.html` |
| Pre-2023 executive orders | marked DO NOT NEED in `TO-DO.md` |

### Still open — confirmed unimplemented

1. **GA judiciary page** (`01-Rec` #5, `Survey` Tier 2). No `ga-courts.html` exists; `elections.html` has a Courts *tab* only, and `supreme-court.html` / `justice.html` are federal-only. **Still the largest structural coverage gap.**
2. **Address-based district lookup** (`01-Rec` #8) — still county-based everywhere. See 3.13.
3. **Lobbying data** (`01-Rec` #9) — not started.
4. **Local government** (`01-Rec` #13, Tier 4) — *partially* started. `local-officials.html` + `_data/local_officials.yml` exist as Phase 1 but are orphaned (see 3.5). The file's own comment confirms Phase 2 (meetings panel) is pending.
5. **Live Open States API for GA bills** (`01-Rec` #11, `Survey` Tier 3). `TO-DO.md` still says "Replace with `generate_ga_bills_data.py` before 2027 session"; `ga-bills.json` is still built from the static bulk export.
6. **Ghost OCD IDs / party tally undercount** (`TO-DO.md` "Blocked") — **status is stale and now user-facing.** See 1.4.
7. **32 bills lack subject tags** (`TO-DO.md`) — surfaces as bills that never match the subject filter. See 4.9.
8. **Cabinet / executive policy tracking** (`01-Rec` #10, described as a "coming soon" promise). Grep for "coming soon" now returns nothing on `executive-branch.html` / `executive-member.html`, so the promise text appears to have been *removed* rather than fulfilled — worth confirming that was intentional.
9. **`ga-members-overrides.json` stale-leadership review** and **congress/session bump to 120** (`TO-DO.md` Workflows) — recurring, still open.
10. **State budget visualization**, **committee hearing schedules** (Tier 4) — not started.

### Data-spinout candidates

`Site feature survey review.md` lists VP tie-votes, SCOTUS justices + decisions, and GA statewide executives as "not yet built" spinouts. `open-data.html` + `_data/open_data.yml` now exist as the publishing surface, so the page is ready — worth a pass over `_data/open_data.yml` to see which of the three have actually shipped repos.

---

## Additional known gap

**49 members have no `legisGaGovId`, so no official-website link** — 36 of them active, sitting legislators (Akbar Ali, Bryce Berry, Drew Echols, RaShaun Kemp, …), mostly recently seated. Per `CLAUDE.md` these need manual override entries. Not wrong data, but a silent gap on ~15% of member pages.

**Suspended member counted toward party totals as if seated.** `assets/scripts/ga.js:53` filters only `status !== 'Vacant'`; `ga-majority-tracker.html:322` filters only Resigned/Removed/Deceased. Sharon Henderson (House 113, `status: "Suspended"` since 2026-01-22) is counted as a sitting Democrat in the donut chart and the majority-tracker seat math. She *is* visually badged in the member list (`ga.js:129`), so this is a counting-only inconsistency.

**Majority-tracker denominators exclude vacancies without saying so.** `ga.js:53` computes the donut total from non-vacant members only. Active counts are Senate 54 / House 178 (2 and 2 vacant), so the chart center reads 178, not 180.

**Participation rates are not comparable across members.** `ga-member.html:860-895` uses each member's own recorded roll calls as the denominator. That correctly avoids showing false absences, but combined with 1.2 it means a member with 200 recorded votes and one with 1,100 both display a plausible-looking percentage with no indication of the difference in sample size.

**Manually-maintained federal datasets are 3 months stale.** `executive.json` and `supreme-court.json` are both `generatedAt: 2026-05-13`; `ga-executive.json` is `updatedAt: 2026-05-03`. No workflow exists for any of them; each carries a `note` saying it's manual, and `executive-member.html:440` does surface "Data as of." Flagged for a refresh pass, not as a defect.

---

## Suggested sequencing

**First commit — small, high-confidence, user-visible:**
1. `1.1` WSDL bill links (one line + regeneration)
2. `1.5` resigned legislators in search index
3. `3.1` nested HTML document in `federal-reps.html` / `my-representatives.html` (largely a deletion)
4. `3.2` three dead links in `member.html`

**Second — date bombs, before they fire:**
5. `2.1` executive-orders year map
6. `2.2` hardcoded finance cycle
7. `2.3` `races.json` timestamp stamping

**Third — the data-integrity work:**
8. `1.2` voter-ID surname resolution (the root cause)
9. `1.3` coverage ratio + badge suppression
10. `1.4` reconcile `TO-DO.md`

**Fourth — IA and cross-linking, mostly additive:**
11. `3.7` footer sitemap, `3.9` 404 links, `3.5` `local-officials` noindex
12. `3.17` sponsor links (needs the build-time `ocdId` join, which also unblocks `4.2`)
13. `3.4` federal county filter, `3.3` home page entry point

**Fifth — new surfaces:**
14. `4.1` fundraising history chart
15. `4.3` / `4.4` SCOTUS question, holding, and authored opinions
16. `4.2` GA sponsored-bills tab
