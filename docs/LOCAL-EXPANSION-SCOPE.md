# /local/ expansion scope — property tax & school boards

**Status:** scope, not yet built. Decisions recorded; implementation phased below.
**Date:** 2026-11-01
**Scope owner:** Justin Mays

This document scopes two additions to the `/local/` section:

1. **Property tax & millage** — statewide millage history and HB 581 homestead
   opt-out status.
2. **School boards** — Georgia boards of education as a new domain of a place.

It also records the demand research that led here, so a later reader can see why
these two and not the alternatives. See `LOCAL-GOVERNMENT-IA.md` for the existing
place/domain model this builds on.

---

## 1. Why these two

### What `/local/` is today

A strong **archive**: 62 places (46 counties, 12 cities, plus consolidated),
officials and constitutional officers per place, scraped agendas and minutes, and
four topic indexes (ALPR/surveillance, data centers, land use, local taxes &
referenda). What it lacks is a reason to come back — it is retrospective, and it
only rewards a visitor who already knows to look.

### What the demand research says

- **Demand is large and badly served.** ~80% of Americans are at least somewhat
  interested in news about local laws and policies and ~70% in local elections,
  but only about **a quarter** are satisfied with the local-government coverage
  they get, and most do *not* find it easy to get the information they need to
  take part in local politics (Pew, 2024).
- **Topic ranking.** Weather (90%) → **crime (77%)** → local government (68%),
  then arts, economy, **schools**, sports. Pew's older ranking put **zoning and
  development last (30%)**. *Caveat: that zoning figure is from 2011.* The
  durable read is that land use is **high-stakes but narrow-audience** — it
  mobilises the affected neighbourhood, not the county — while taxes and schools
  are broad-audience.
- **Property tax is the proven traffic magnet.** Philadelphia's property
  assessment site was the single most-visited city government site, 280k+ unique
  views in a month. Across municipal analytics the recurring winners are property
  tax, utility billing, permits and jobs.
- **Distribution is word of mouth.** The #1 source for local political news is
  **friends, family and neighbours**; government websites are only 32%. Shareable
  single items matter more than a well-organised site.
- **Down-ballot roll-off is an information failure.** Voters skip local races
  mainly because they cannot find anything about the candidates, and existing
  voter guides do not cover all down-ballot races.
- **Georgia is a news desert.** 17 of 159 counties have **no** newspaper; 123
  have only one; ~28% of Georgia's papers have closed in two decades. *Caveat:
  the 17-county count traces to 2020 data and has been repeated since.*

### The conclusion

The current topic set is **supply-driven** — it tracks what is tractable to
classify in agenda text. The demand data says to add one **pocketbook** topic
(property tax) and one **kids** topic (school boards). Land use and ALPR stay:
they are the differentiation and they serve an intense minority well. They just
should not be the whole front door.

### Also considered, not scoped here

Ranked ideas that came out of the same pass and remain open:

| Idea | Note |
|---|---|
| Per-place and per-topic **RSS/Atom feeds** | No alerting of any kind exists today. Static files, no backend, no PII — fits the no-profiling stance exactly. Strongest candidate after these two. |
| **Upcoming** meetings + `.ics`, not just "most recent on file" | A voter can only act *before* the vote. |
| "This week in Georgia local government" digest | Near-zero new data; a sort and a render. |
| Address/ZIP → my places | `build_usps_ga_zips.py` already exists. |
| Per-mention **share cards** | `build_share_cards.py` already exists; neighbours are the #1 channel. |
| Explainers (how a rezoning works, what a SPLOST is) | Closes the satisfaction gap; pure content. |
| Down-ballot candidate coverage for local offices | Biggest strategic bet; separate scope. |
| Public safety budgets & policy | Crime is the #2 most-followed local topic; ALPR is a narrow slice of it. |
| Utility & fee increases | Hits renters, whom property-tax content misses. |
| **News-desert-first coverage order** | Expand into the 17 no-newspaper and 123 one-newspaper counties rather than by population. Costs nothing but a reordered backlog; stronger grant and partnership story. Will be technically harder — small counties have worse sites and more `unknown` platforms. |
| Project-level threading (replacing mention-level) | Gets much easier once applicant/parcel/district are extracted. |

Explicitly **out of scope**: jobs, permits and trash pickup (service delivery,
not accountability); weather (belongs to the NWS). Emergency management is the
one adjacent sliver worth revisiting later.

---

## 2. Decisions taken

| # | Decision |
|---|---|
| 1 | **Millage data folds into `ga-local-government`.** No new open-data repo. |
| 2 | **`school_districts.yml` lives in this repo**, beside `local_officials.yml` and `county_officers.yml`. A machine-readable copy is **also published to `ga-local-government`** so consumers get it without parsing Jekyll data. |
| 3 | **The city-system exception list is committed now**, ahead of everything else — see `_data/school_districts.yml`. |

---

## 3. School boards

### 3.1 The structural question

A board of education is a separately elected body with its own meetings, its own
millage and its own ESPLOST. The question was whether a place page needs a third
card alongside the commission/council and the constitutional officers.

**Answer: it is a fourth _domain_ of a place, not a new place type** — a pattern
this repo has already run twice. `local_officials.yml`'s own header states that
officials is *a domain of a place*, joined by `jurisdiction.id == places.yml
slug`. `county_officers.yml` is the exact precedent: a separately elected body
that does not sit on the commission, rendered as its own section and explicitly
*"never mixed into its `members:` list."* `_includes/entity/place.html` already
renders three such `<h2>` sections. School board is the same move a third time.

### 3.2 The structure of Georgia school districts

180 active standard districts, and the shape is far simpler than it looks:

- **159 county systems — exactly one per county, always.** Every county has one;
  no county has two. Fully derivable, no curation needed.
- **21 city systems**, sitting inside **20 counties**. This is the entire
  irregular set, it is closed, and it changes essentially never.

Jackson County is the only county with two city systems (Commerce and Jefferson)
on top of its county system.

| County | City system(s) |
|---|---|
| Jackson | Commerce City, Jefferson City |
| Bartow | Cartersville City |
| Carroll | Carrollton City |
| Chattooga | Trion City |
| Cobb | Marietta City |
| DeKalb | City Schools of Decatur |
| Floyd | Rome City |
| Fulton | Atlanta Public Schools |
| Gordon | Calhoun City |
| Gwinnett | Buford City |
| Hall | Gainesville City |
| Haralson | Bremen City |
| Laurens | Dublin City |
| Lowndes | Valdosta City |
| Mitchell | Pelham City |
| Thomas | Thomasville City |
| Toombs | Vidalia City |
| Walker | Chickamauga City |
| Walton | Social Circle City |
| Whitfield | Dalton Public Schools |

Committed as `_data/school_districts.yml`. The 159 county systems are generated
in phase 3a rather than enumerated.

### 3.3 Two corrections to watch

Both emerged from the full 180-row data and both would have caused bugs:

**(a) `county_fips` upstream is the OFFICE's county, not the service area.** The
NCES/GOSA dimension assigns each district one county — where its LEA office sits.
Atlanta Public Schools is the clearest case: upstream it is a Fulton district,
but **APS also serves part of DeKalb**. So a per-county district count built from
the upstream assignment is a planning approximation, not a boundary truth. The
`counties` field in `school_districts.yml` is therefore a human-confirmed
rendering hint and may be longer than the upstream assignment.

**(a-iii) The audit ran, and it corrected four entries.** §4.1.0's millage
dataset was used to audit `school_districts.yml` as this doc said it should be.
It found **exactly the same 21 city systems** — independent confirmation — but
**four of the `counties` lists were wrong**, each recorded as single-county when
DOR shows the system levying in two: **Bremen** (+Carroll), **Buford** (+Hall),
**Social Circle** (+Newton) and **Vidalia** (+Montgomery). Atlanta's
Fulton+DeKalb was already right. So there are **five** multi-county systems, not
one. Montgomery County was added to `places.yml` as a hidden placeholder to carry
the new reference. Re-run the audit whenever DOR publishes a new year.

**(a-ii) Forward references — found, then resolved.** 7 of the 20 counties with
a city system were missing from `places.yml` (**chattooga, floyd, haralson,
jackson, laurens, mitchell, toombs**), which would have broken a validator that
copied `validate_local_officials.py`'s strict slug cross-check. They are now
registered as `hidden: true` placeholders, so **every slug in the district
registry resolves and the validator can stay strict** — an unresolvable slug is a
typo, not a forward reference.

The remaining subtlety: a resolvable slug is not a *visible* place. A hidden
place emits no `/local/<slug>/` page, so the renderer must skip a board whose
every listed place is hidden rather than linking into a 404. These 7 are also the
**first users of the `hidden` flag** — `build_entity_pages.py`,
`generate_search_corpus.py`, `publish_ga_local_government.py`, the three
enrichers and `local.html` all check it at the top of their places loop (verified),
so if one ever surfaces publicly the bug is in a new consumer that forgot.

Corollary: **"which school board is mine?" is an address question, not a place
question.** A city system's boundary is not the city limits, and the county
system serves everything the city system does not. Route it to an
attendance-zone lookup (`lookup_school_zone` on the Georgia Civic Data server).
Do not build a place → district promise on the registry.

**(b) District name does not determine type.** County systems with city-styled
names: **Savannah-Chatham County, Griffin-Spalding County, Thomaston-Upson
County**. City systems with no "City" in the name: **Atlanta Public Schools,
Dalton Public Schools, City Schools of Decatur**. `type` must be curated. GOSA
codes do separate cleanly today (county 601-759, city 761-793) but that is an
accident of numbering, not a contract — use it as a cross-check only.

### 3.4 Identity: use the GOSA district code

Keying a board by place slug breaks for all 20 exception counties. Use the
**GOSA `district_code`** as `id`: it is the primary key of the Georgia Civic Data
`districts` dimension, so enrollment, demographics and attendance zones become a
join rather than a project. Carry `districtCensusId` and `officeCountyFips`
alongside for cross-dataset linking and provenance.

### 3.5 Ingestion: better than county sites, not worse

Georgia school boards concentrate on **two** platforms, neither in the current
adapter list:

- **Simbli** (eBOARDsolutions) — **a subsidiary of the Georgia School Boards
  Association**, originally built for GSBA. Georgia penetration is therefore
  unusually high.
- **BoardDocs** (Diligent).

Districts migrate between them — Fulton County Schools moved BoardDocs → Simbli
and is still backfilling older meetings — so both adapters are needed and
`places.yml` must tolerate a platform switch on one body.

**Two adapters plausibly cover most of the 46 counties already served**, and the
corpus is *more* uniform than the ~20 platforms handled for counties and cities
today. **"Plausibly" must become a number before the adapters are funded:** run
`scripts/detect_meeting_platform.py` across the school districts of the covered
counties first. That census gates phases 3c/3d, and if Simbli dominates as the
GSBA ownership suggests, the BoardDocs adapter may be deferrable.

### 3.6 Topic work is nearly free

`meeting_topics.py` is corpus-agnostic. Pointing the existing classifier at board
agendas immediately yields `local-taxes` (ESPLOST is already a keyword),
`millage-budget`, `contract` and `appointment` hits. New rules worth adding:
**attendance-zone redistricting, superintendent contract, school calendar,
curriculum/media policy, school construction**. One new `schools` topic in
`topics.yml` plus a handful of `TOPIC_RULES` entries — not a new taxonomy.

**The shape of this work is ~90% ingestion, ~10% classification.**

### 3.7 Phasing

| Phase | Work | Est. |
|---|---|---|
| **3a** | County systems generated into `school_districts.yml`; validator (strict slug cross-check, like `validate_local_officials.py`); board section in `_includes/entity/place.html`; publish machine-readable copy to `ga-local-government`. **Officials only, no scraping.** | ~50–70k |
| **3b** | Platform census via `detect_meeting_platform.py` across covered districts. **Gates 3c/3d.** | ~20–30k |
| **3c** | Simbli adapter | ~60–90k |
| **3d** | BoardDocs adapter | ~60–90k |
| **3e** | `schools` topic rules + per-district page wiring | ~40–60k |

**3a ships standalone and is the right first commit.** It follows the existing
"onboard officials-first, wire up the meetings adapter later" guidance, and it
delivers "who is on my school board" — a real unmet need — at zero scraping risk.

---

## 4. Property tax & millage

### 4.1 The source: DOR's Digest Consolidated Summaries (XLSX)

**Georgia DOR publishes the whole thing as machine-readable spreadsheets.** No
PDF parsing, no OCR, no scraping.

> https://dor.georgia.gov/local-government-services/digest-compliance/digest-consolidated-summaries

One `.xlsx` per year, **2020–2025**, ~2.3 MB each. (Served with a `.xls`
extension but they are real OOXML — `openpyxl` reads them once renamed, which is
the only gotcha.)

**Verified shape** (2025 and 2023 both downloaded and parsed): a single flat
sheet, **~1,815 rows × 425 columns**, one row per **county × tax district**:

| Col | Header |
|---|---|
| 1–5 | `County Name`, `County Code`, `District Name`, `District Code`, `Tax Year` |
| 6–419 | parcels, acreage and assessed value per property class; exempt property; **state (S*) and local (L1–L9) homestead exemptions**, each split M&O / Bond |
| 420–421 | `Total Assessed Value-M&O`, `Total Assessed Value-Bond` |
| **422–423** | **`Millage Rate-M&O`, `Millage Rate-Bond`** |
| **424–425** | **`Total Tax-M&O`, `Total Tax-Bond`** |

**The millage columns are populated** — 1,240 of 1,814 rows in 2025, 1,211 of
1,782 in 2023 (the blanks are the county header row and genuine zero-levy
districts like `STATE` and small unlevied cities). And **2025 is populated**,
which is the year the millage PDF is unreadable.

**Cross-checked against the PDF and they agree exactly.** 2023 Appling:
`SCHOOL 12.243`, `COUNTY INCORPORATED 11.924`, `BAXLEY 4.896`,
`COUNTY FIRE DIST 0.470` — identical in both sources.

It also carries what the PDF does **not**: `Total Tax` in dollars, the full
property-class breakdown, and the homestead-exemption detail. One parser, one
file per year, everything.

### 4.1.0 Status: BUILT

Phase 1a is implemented and passing (2026-11-02):

| File | Role |
|---|---|
| `scripts/lib/xlsx.py` | minimal stdlib `.xlsx` reader (zipfile + ElementTree) |
| `scripts/lib/dor_digest.py` | workbook → tidy records, district classification |
| `scripts/generate_ga_millage.py` | discover, download, build `ga-millage.json` + `.csv` |
| `scripts/test_dor_digest.py` | 53 offline invariants over two real-data fixtures |
| `scripts/fixtures/dor-digest-{2023,2025}.xlsx` | six counties, all 425 columns |

**Built output:** 10,643 rows, 2020–2025, **all 159 counties**, 0 unclassified
districts. 1.6 MB JSON / 891 KB CSV. Per year: 1,725 / 1,752 / 1,772 / 1,782 /
1,798 / 1,814.

**Cross-checked against the PDF and all four spot values agree exactly** (2023
Appling: SCHOOL 12.243, COUNTY INCORPORATED 11.924, BAXLEY 4.896, COUNTY FIRE
DIST 0.470).

**No third-party imports anywhere in the chain.** `run-script-tests.yml`
installs no pip packages by design, so an `openpyxl`-based reader could never be
tested in CI — which is why `lib/xlsx.py` exists. It handles the four traps that
silently corrupt a naive reader: sparse rows (the Nth `<c>` is not column N, so
every cell's own ref is the only safe index), shared strings, rich-text runs, and
inline strings.

Not yet done: publishing into `ga-local-government` (that repo is not attached to
this session) and the per-place slices, which are 1b.

### 4.1.2 Join on the district CODE, never the district name

Verified across the 2023 and 2025 files, and this is the single most important
parser rule:

- **`(County Code, District Code)` is stable.** 1,768 of ~1,800 pairs appear in
  both years.
- **`District Name` drifts for 15% of them** — 274 pairs share a code but carry a
  different name — and the drift is **not a consistent transform**. Only 2 of the
  274 differ by a clean `<County> - ` prefix. It moves in *both* directions
  (Appling's school district is `SCHOOL` in 2023 and `Appling County - SCHOOL` in
  2025; Newton's is `Newton County - Newton School` in 2023 and `SCHOOL` in 2025),
  and wording and casing change too (`COUNTY WIDE LIBRARY` →
  `Countywide Library`).

So: **key every record on `(County Code, District Code, Tax Year)`** and treat
the name as a display label, resolved from the most recent year a code appears.
A name-based join would silently split 15% of the series into fragments.

- **Districts also come and go.** 14 code pairs exist only in 2023 and 46 only in
  2025 — annexations, new fire and special districts. The district registry must
  be a **union across years with first-seen / last-seen**, not a single snapshot.

**And the key is *almost* unique — the one exception is real.** Across all six
years exactly one `(county, district, year)` repeats: **Cherokee 2022 district 18,
`HOLLY SPRINGS FIRE`**, listed once at $898,991,358 assessed / $2,682,590.21 tax
and once at $8,264,691 / $24,661.84, both at 2.984 mills. Summing them would be
inventing a tax figure and dropping one would lose money, so both rows are
published with an **`occurrence` ordinal** that keeps the identity unique and the
anomaly visible, and the generator prints the group on every run. Every other row
in six years is occurrence 1. The uniqueness guard found this, which is the whole
reason it exists.

**One coverage caveat:** DOR publishes the 2020 workbook as
`2020-digest-excluding-charlton`. All 159 counties do appear in it, but treat 2020
Charlton figures with suspicion.

### 4.1.3 District type is derived, and only codes 0–3 are trustworthy

Verified across all 159 counties in 2025: **code 1 = STATE** (158 rows, zero
off-pattern), **code 2 = county SCHOOL system** (158, zero off-pattern), **code
3 = COUNTY INCORPORATED** (154). Above that, codes are per-county arbitrary —
**code 15 is `COUNTY UNINCORPORATED` in 24 counties and a city in others**, with
100 distinct names. So 0–3 classify by code and everything else by name.

The 16 derived types, with statewide counts across 2020–2025: `city` 3,769 ·
`county_incorporated` 993 · `countywide` 953 · `state` 953 · `school` 953 ·
`county_unincorporated` 944 · `tad` 640 · `fire` 418 · `ssd` 336 · `cid` 215 ·
`city_school` 156 · `development_authority` 125 · `recreation` 67 · `hospital`
57 · `bid` 40 · `library` 24. An unmatched row is reported as `unclassified`
rather than guessed into a bucket; there are currently none.

**Code 0 is not always empty.** Every county has a code-0 countywide roll-up row
and the millage is usually blank — but 2 of 159 carry a rate in 2025, so the row
is classified and kept, never dropped as a header.

### 4.1.1 What this replaces

The earlier plan to parse the **"County Ad Valorem Tax Digest Millage Rates"
PDFs** (PTS-R006-OD, 2019–2025) is **obsolete for 2020 onward.** Those PDFs had
a nasty profile — 2019/2020/2022/2023 clean text, **2021 and 2024 scanned
(OCR)**, and **2025 a Type 3 font with no ToUnicode that `pdftotext` renders as
mojibake**. All of that work disappears.

Keep the PDFs for two narrow jobs only:

1. **2019** — the XLSX series starts at 2020, and the 2019 PDF is clean text. One
   year, cheap.
2. **Spot cross-checks** of the XLSX, which is prudent on a tax figure.

**Deeper history:** `sso.dor.ga.gov/rtdc/` (§4.4.1) goes back to **1990** but
carries no millage. So the practical coverage is **millage + tax 2019–2025**, and
**digest/exemption detail back to 1990** if wanted.

### 4.2 The genuinely novel dataset: HB 581 opt-out status

**No complete public list of who opted out exists.** Opting out of the statewide
floating homestead exemption requires **three public hearings plus notice to the
Secretary of State by March 1** (O.C.G.A. § 48-5-44.2(i), per ACCG guidance).
Published estimates conflict badly — a GSSA survey reportedly found **~86 school
districts (~78%)** intending to opt out; another source says ~68% of districts
and ~30% of counties. Sources also disagree on whether opting *in* is
irreversible and on who must re-opt-out annually.

That disagreement is the opportunity. "Did my county, city and school board opt
out of the homestead cap, and when were the hearings?" is a pocketbook question
with proven search demand, no authoritative public answer, and **three separate
taxing bodies per address**. SoS filings are ground truth; ACCG and GMA are
secondary. It recurs every March, making it a durable annual franchise rather
than a one-off.

**The accountability angle:** those three hearings appear on agendas already
being scraped, so the existing corpus can corroborate the filings — and flag any
body that opted out without holding the required hearings. No one else in Georgia
is positioned to do that.

**Now much stronger than when first scoped**, because the XLSX carries **local
homestead exemption L1–L9 counts and exempted value per district per year**. That
turns the registry from "who opted out" into "who opted out *and what it did to
exempted value*". Hypothesis to test before relying on it: check a county known
to have opted in against one known to have opted out, and confirm the floating
exemption surfaces as an identifiable code.

### 4.3 The rollback rate — the one thing no central source has

Neither the XLSX nor the PDFs nor `rtdc` carry the **rollback rate** or the
**advertised tax increase**. Those live in the per-jurisdiction **"Current Tax
Digest and Five-Year History of Levy"** notice.

**Those are NOT centralized.** They are a *newspaper advertisement* obligation
under **O.C.G.A. § 48-5-32**, with the tax-increase notice under **§ 48-5-32.1**
— published by each levying authority, then posted on its own site. Confirmed
scattered across county, city and school-district sites (Augusta, Savannah,
Fulton, Commerce, Thomasville, Bremen, Eatonton, Walton and Murray schools, …).
DOR's digest-compliance index lists no central archive of them.

So: **do not plan to scrape 180+ sites for rates we already have.** The five-year
notices are worth pursuing only for the rollback/increase disclosure, and the
XLSX's own year-over-year millage series already approximates the five-year
history for free.

**The authoritative spec**, if that work is ever taken up, is DOR's *Compliance
Guide: Advertising the Digest History and Public Hearings for Increase* (rev.
April 2025). It also makes the requirement **auditable**: the increase ad must
run **at least one week before each hearing**, be **at least 30 square inches**,
and **not sit in the legal-notices section**. A body that misses those is a
reportable finding — Murray County had to re-run an ad that came in just under
30 square inches.

### 4.4 Verify before building on it

- **SB 33 "HOME Act" (2026)**, reportedly making the inflation cap mandatory
  statewide from 2027 — **single low-quality source only.** Check against
  legis.ga.gov; the `ga-legislation` pipeline can do this directly.
- **Confirm the exact O.C.G.A. cite** for the rollback-rate requirement before
  putting it on a page (§ 48-5-32 for the five-year history and § 48-5-32.1 for
  the increase notice are from secondary sources, not read directly).
- **Resolved: a machine-readable source exists after all.** An earlier draft of
  this doc said no CSV or XLS existed for any year. That was true of the
  *millage-rates* page only — the *Digest Consolidated Summaries* page serves
  XLSX. The old `etax.dor.ga.gov/ptd/download/` portal is still dead (host
  resolves, connection resets), but it no longer matters.
- **Decide which districts and levy types to publish.** The XLSX includes
  `STATE`, county incorporated/unincorporated, each city, school, fire, and
  special districts. Richer than needed; unbounded scope if not decided.
- **One more central file to look at:** `2023-local-exemptions-appling-worth`
  (PDF, 23 MB) on the digest-compliance index — a statewide listing of **local**
  exemptions, directly relevant to §4.2.

### 4.4.1 `sso.dor.ga.gov` — probed: deep history, no millage

`sso.dor.ga.gov/rtlhext/` is the **County Services Portal**, an authenticated
(AWS Cognito) portal for county staff — two of its three buttons are gated. The
third is not:

> **`https://sso.dor.ga.gov/rtdc/` — "Digest Consolidation Online", public, no login.**

**It carries no millage.** Each county/year page ends in a `TAX LEVIED` table
with columns `TYPE | ASSESSED VALUE | MILLAGE | TAX` and rows `M & O` / `BOND` —
and **the MILLAGE and TAX columns are empty**, verified for 2025, 2023 *and*
2019, so it is structural rather than a current-year lag. It publishes the
digest, not the levy.

Its value is **reach**: **1990–2025, 36 years**, all 159 counties, plus a
sub-county district selector, as clean HTML. For 2020–2025 the XLSX supersedes it
entirely, so this is the **pre-2020 deep-history** source and nothing more.
Mechanics if needed: `POST /rtdc/Digest.do` with `operation=viewConsolidation`,
`dc_tax_yr`, `dc_txpyr_id` (3-digit county code, `001`=Appling, alphabetical),
after a GET for the session cookie.

**Parser cautions, observed across the 2019/2023/2025 responses:**
- **Schema drifts between years.** 2019 has one "HOMESTEAD AND PROPERTY
  EXEMPTIONS" block (with a literal `DO NOT USE CODES L1-L9 ON STATE SHEET`
  divider); 2023 and 2025 split it into three. Match section headers, not
  positions.
- **Blank is not zero, and the convention changes.** 2023 writes a literal `0`;
  2025 leaves the cell empty. Preserve the distinction.
- **2025 may be preliminary.** Appling's 2025 class totals differ sharply from
  2023 (Agricultural 161.0M vs 81.9M; Conservation Use V4 433 parcels /
  9,377 acres vs 65 / 1,273). Reclassification or an incomplete filing — do not
  present a 2025 figure as final without checking a second county.

### 4.5 Phasing

| Phase | Work | Est. |
|---|---|---|
| **1a** | ~~Digest Consolidated Summaries XLSX → millage dataset, 2020–2025~~ **DONE** — see §4.1.0. Remaining: the 2019 PDF for one extra year, and publishing into `ga-local-government`. | **done** (~40–60k est.) |
| **1b** | Per-place millage history section on `/local/<slug>/` (county + city + school lines) | ~40–60k |
| **1c** | HB 581 opt-out registry (SoS filings + agenda corroboration + L1–L9 exemption series) | ~60–90k |
| **1d** | Explainers: reading your assessment, the 45-day appeal, what a millage rate is | ~25–40k |
| **1e** | Statewide millage comparison / ranking page | ~40–60k |
| **1f** | *Optional.* `rtdc` HTML parser for pre-2020 digest history (back to 1990). No millage. | ~60–90k |

### 4.6 Supporting facts

- **Assessment mechanics (verified):** bills are **40% of fair market value ×
  millage**; appeals are due **within 45 days** of the notice date. Millage is set
  *after* the appeal window closes, so the notice structurally cannot tell a
  homeowner their bill.
- **The 2026 information vacuum:** Gwinnett reports state legislation **removed
  estimated taxes, assessed values and estimated rollback rates from the 2026
  notice**, replacing them with an estimate of tax savings. *Confirm this is
  statewide before publishing it as such.*
- **Supporting source:** DOR's **Property Tax Administration Annual Report** for
  digest totals and context.

## 5. Recommended order

**1a → 3a → 1b → 1d**, with **3b** run before committing to 3c/3d.

1a is now the cheapest of the four as well as the highest-leverage, so there is
no reason to sequence it later.

- **1a is the highest-leverage item in either scope**, and it got much cheaper:
  one spreadsheet parser, statewide coverage including the current year, the
  highest-demand topic, and it feeds the school-board work too. No OCR, no
  mojibake, no gap between "we have history" and "we have 2025".
- **3a is the lowest-risk**: YAML plus a template section, no scraping, ships on
  its own, answers "who is on my school board".

Together ~120–170k, and they move `/local/` from 46 counties to statewide on the
topic voters actually search for.

Hold the adapters until 3b reports the real platform mix.

---

## 6. Standing caution

Everything here must keep the existing accuracy posture. The topic pages already
carry **"a listing marks discussion, not action"**, and the ALPR classifier
already tiers evidence high/medium rather than overclaiming. Two specific traps
in this scope:

- A **wrong millage figure or opt-out status** is a pocketbook claim about
  someone's money — worse than a vague one. Parse conservatively, show the source
  document for every number, and leave a cell empty rather than inferred.
- **"Which school board is mine"** must never be answered from the registry's
  `counties` field. See §3.3.

---

## 7. Sources

**Demand research**
- Pew Research Center, *How Americans Get Local Political News* (July 2024) —
  https://www.pewresearch.org/journalism/2024/07/24/how-americans-get-local-political-news/
- Pew, *Consumption and Sources of Local Political News* —
  https://www.pewresearch.org/journalism/2024/07/24/consumption-and-sources-of-local-political-news/
- Pew, *Attitudes Toward Local Political News* —
  https://www.pewresearch.org/journalism/2024/07/24/attitudes-toward-local-political-news-interest-satisfaction-and-ease-of-access/
- Nieman Lab summary — https://www.niemanlab.org/2024/07/most-americans-follow-local-political-news-but-few-are-satisfied-with-the-coverage-they-get-a-pew-report-finds/
- Reg Murphy Center (CCGA), *News deserts grow as local newspapers close* —
  https://www.ccga.edu/reg-murphy-publications/news-deserts-grow-as-local-newspapers-close/
- *17 Georgia counties have no newspaper* — https://datawrapper.dwcdn.net/Wed9m/6/
- Technical.ly, *phila.gov analytics* — https://technical.ly/civic-news/phila-gov-analytics.md
- Austin top-50 pages dataset — https://catalog.data.gov/dataset/top-50-pages-by-pageviews-on-austintexas-gov
- KQED, *Do voters care about down-ballot races?* — https://giving.kqed.org/news/11138329/do-voters-care-about-down-ballot-races

**Property tax**
- DOR **Digest Consolidated Summaries** (XLSX, 2020-2025) — https://dor.georgia.gov/local-government-services/digest-compliance/digest-consolidated-summaries
- DOR **Summary of Ad Valorem Taxes Levied in Georgia Counties** — https://dor.georgia.gov/local-government-services/digest-compliance/summary-ad-valorem-taxes-levied-georgia-counties
- DOR **Compliance Guide: Advertising the Digest History and Public Hearings for Increase** (rev. Apr 2025) — https://dor.georgia.gov/document/publication/compliance-guide-advertising-digest-history-and-public-hearings-increase/download
- O.C.G.A. § 48-5-32.1 — https://law.justia.com/codes/georgia/title-48/chapter-5/article-1/section-48-5-32-1
- DOR millage rate reports (2023, PDF; superseded) — https://dor.georgia.gov/document/document/2023-georgia-county-ad-valorem-tax-digest-millage-rates/download
- DOR millage rate reports (2022) — https://dor.georgia.gov/document/document/2022-georgia-county-ad-valorem-tax-digest-millage-rates/download
- DOR Property Tax Administration Annual Report — https://dor.georgia.gov/local-government-services/digest-compliance/property-tax-administration-annual-report
- ACCG, *HB 581 opt-out guidance and model resolution* — https://accg.org/links/HB%20581%20Opt%20Out%20Guidance%20and%20Model%20Resolution.pdf
- City of Savannah, *HB 581 opt-out period ends March 1* — https://agenda.savannahga.gov/content/files/local-government-hb-581-opt-out-period-ends-march-1.pdf
- Newton County, *HB 581 — Save the Homes Act* — https://www.newtoncountyga.gov/695/House-Bill-581---Save-the-Homes-Act
- Times-Georgian, *2027 will be critical year for HB 581* — https://www.times-georgian.com/news/local/2027-will-be-critical-year-for-hb-581/article_36daf2a0-3441-595e-96ce-5da18c555ccd.html
- Gwinnett Tax Assessor FAQ — https://www.gwinnettcounty.com/government/departments/financial-services/tax-assessor/faqs

**School boards**
- Georgia Civic Data `districts` dimension v1.2.0 (GOSA codes; NCES CCD LEA
  directory SY 2025-26) — https://georgiacivicdata.org — CC BY 4.0
- eBOARDsolutions / Simbli (GSBA subsidiary) — https://eboardsolutions.com/
- Diligent, *How school boards leverage agenda management* — https://www.diligent.com/insights/agenda-management-public-education/how-school-boards-leverage-agenda-management-system
- Fulton County Schools board meeting calendar (BoardDocs → Simbli) — https://www.fultonschools.org/fcs-board-of-education/meeting-calendar
- Bulloch County Schools agendas on Simbli — https://www.bulloch.k12.ga.us/boardpackets
