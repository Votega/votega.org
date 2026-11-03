# /local/ expansion scope — property tax & school boards

**Status:** mostly built. See **Where this stands** immediately below; the
phased detail is further down and still accurate.
**Scoped:** 2026-11-01 · **Last updated:** 2026-11-02
**Scope owner:** Justin Mays

---

## Where this stands (read this first)

Everything below this section is the original scope plus findings recorded as the
work happened. This block is the resume point.

### Shipped and on `main`

| | |
|---|---|
| **1a** millage parser | DOR Digest Consolidated Summaries XLSX → **12,186 rows, 2019–2025, all 159 counties**. 2019 bridged from the one clean-text PDF. |
| **1b** per-place section | **Property tax rates** on all 62 visible place pages, server-rendered, 7 columns, 61/62 with a combined rate (Muscogee cannot have one — §4.5.1). |
| **1d** explainer | `/property-tax/` — mills, the 45-day appeal, the rollback rate and the three advertised hearings. Every statutory claim verified from DOR or the Code. |
| publish + refresh | `update-ga-millage.yml` monthly → `ga-local-government`, via `publish_ga_millage.py`. First run succeeded. |
| **3a** registry | `_data/school_districts.yml` — all **180 districts** (159 county + 21 city), `validate_school_districts.py` + 52 invariants in CI. |
| **3a** drafter | `draft_school_boards.py` — **77 districts / 215 members** drafted from SoS results, 0 errors. |
| **3a** board section | `_includes/entity/school-boards.html` — collapsible panel per board, wired into `place.html`. **Renders nothing until a roster is human-confirmed**, verified on a full Jekyll build: 0 of 1,484 pages carry the section today. |
| **3b** census | Detector gained a Simbli fingerprint. **15 of 23 reachable districts are Simbli, 0 BoardDocs.** |
| **3c** Simbli adapter | `scripts/lib/simbli.py` + 60 pinned invariants on a real captured listing. **Verified live end to end: 50 real Newton meetings parsed through the adapter's own retry.** Not wired to a surface — that is 3e. |
| infrastructure | Per-dataset manifests (`data/<dataset>/manifest.json`) across all 6 co-tenant publishers; `test_no_third_party_imports.py` guard; `claude.md` scaling section re-measured. |

### Next actions, highest value first

1. **Board rosters** — the renderer is in place and gated, so every district the
   owner confirms turns on by itself. Drafter output in `draft_school_boards.py`
   is the starting point; nothing displays until `members:` lands.
2. **Publish the district registry** to `ga-local-government` (decision 2:
   registry lives in this repo, machine-readable copy published).
3. **`/local/<slug>/taxes/` URL split** — owner liked the idea; capacity is a
   non-issue (~4 MB for 68 pages). Property tax is 78% of a place page's content
   and has the highest search intent, so it is competing with officials for the
   page title today.
4. **Inline-`<script>` refactor** — the live REVISIT item in `claude.md`.
   ~130 MB of a 312 MB site; first question to answer is whether the 177 KB
   legislator / 126 KB candidate blocks are per-page templated or identical.
5. **3e** wire board meetings to a surface — the adapter (3c) is built and
   verified; nothing reads it yet. Needs a district→Simbli-id mapping (the
   detector already extracts the id) and a decision on where board meetings
   render: a section on `/local/<slug>/` beside the board roster, or their own
   page per district.
6. **Budgets as a fifth topic** — `millage-budget` fires on 59 of 59 places and
   has no page; 40% of what it flags is noise ("to be paid from the facilities
   management budget"). Scoped in `docs/BUDGET-TOPIC-SCOPE.md`: retire the tag,
   replace it with a narrower `budget` topic that earns a page.
7. **1c** HB 581 opt-out registry · **1e** statewide millage comparison.
8. **3b loose ends** — 8 districts matched no signature, 17 never tested, 10
   blocked by the dev container's egress proxy. Re-running from CI would firm up
   the zero-BoardDocs result.

### Owner is doing

Adding board rosters to `_data/school_districts.yml`, one district per PR, using
`draft_school_boards.py` output as the starting point.

### Hard-won facts not to re-derive

- **Join on `(countyCode, districtCode, taxYear, occurrence)`**, never on a name.
  District names drift for ~15% of districts between years; DOR also abbreviates
  county names per row (191 names for 159 codes).
- **Assert on CONTENT, never on response size or an injected-marker substring.**
  Both of my wrong calls about Simbli came from that (a byte count, then
  `'ncapsula' in html` matching Incapsula's script tag on *served* pages).
- **`scripts/test_*.py` must be stdlib-only** — CI installs no pip packages. Use
  the `try: import yaml / except ImportError: sys.modules[...] = stub` pattern.
  `test_no_third_party_imports.py` enforces this.
- **No wall-clock time in a published artifact**, or every scheduled run
  republishes and churns the sibling repo.
- **Georgia school boards may be partisan OR nonpartisan, per district, by law**
  ([Ballotpedia](https://ballotpedia.org/Party_labels_in_Georgia_school_board_elections)).
  71 of 77 drafted districts are partisan. Do not assume either way.
- **A Superintendent is hired by the board, not elected** — `voting: false`
  required, never counted against `board_size`.
- **A city place carries no `fips` in `places.yml`; a county or consolidated one
  does.** That is what the board renderer branches on — no name matching. A city
  place resolves to the boards of the county it sits in, with its own system
  (`primaryPlace`) leading. 22 visible places resolve to more than one board.
- **A topic badge's PRESENCE does not discriminate, and no count threshold fixes
  it.** Measured over the 59 flagged places: `local-taxes` is on 56 and
  land-use-or-data-center on 56, so two of the three pills a `/local/` card showed
  were on nearly every card. Gating on a raw count fails too — `landUseCount >= 5`
  still fires on 45 of 59, because land use is genuinely busy almost everywhere.
  Ranking on the raw count just moves the problem: land use then leads 48 of 59
  cards. What works is scoring each topic against **its own statewide median**, so
  a pill earns its slot by being busy *for that subject* (leading pill then spreads
  21 land use / 14 data centers / 12 ALPR / 2 local taxes). The hub computes the
  medians client-side from `local-flags.json` itself, so they recalibrate as places
  are added.
- **`millage-budget` must never be ranked against the narrow subjects**, until it
  is retired and replaced (`docs/BUDGET-TOPIC-SCOPE.md`), which removes this
  special case.** Its
  lexicon includes `budget` and `fiscal year`, which appear on nearly every agenda,
  so it outscores them everywhere (Fulton: millage-budget 36, local-taxes 19). It
  is a vocabulary-wide tag, not a watch topic. It carries a count for consistency
  and no pill. `scripts/test_flag_entry_counts.py` pins both terms, so if they ever
  leave the lexicon the exclusion can be revisited.
- **A `*Count` in `local-flags.json` must not be computed from a `*Items` list** —
  those are sliced to 20 for sidecar size, so counting them saturates and a place
  with 35 land-use meetings reported the same number as one with 20. The counts
  come from the unsliced collections in `build_summary`.
- **`primaryPlace` was set on only 1 of 21 city systems** (Atlanta). Carrollton,
  Social Circle and Thomasville are the other three whose city is itself a place
  in `places.yml`; they are now set. The remaining 17 city systems have no
  matching city place, so they render on their county pages only.

---

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

### 3.5.1 Phase 3b: the platform census — RESULT

Run 2026-11-02 with `scripts/detect_meeting_platform.py`, which gained a
**Simbli fingerprint** for this (BoardDocs was already in it, under the
adapter-less `_NO_SCRAPER` list).

**Verdict: build the Simbli adapter (3c). Defer BoardDocs (3d).**

| Result | Districts |
|---|---|
| **Simbli** | **15** |
| no signature matched | 8 |
| not fetchable *from this container* | 10 |
| **BoardDocs** | **0** |

Of the 23 districts that returned a page, **15 are Simbli and none are
BoardDocs.** Two spot checks outside the sweep agree: Bulloch (`S=4020`) and
**Fulton (`S=36031609`) — the district that migrated *off* BoardDocs**, which is
now confirmed landed.

#### What was and was not tested

The sweep covered the school districts of the **33** currently-visible places
whose domain follows the `<county>.k12.ga.us` convention. **17 did not resolve**
and were not tested — overwhelmingly the metro districts on custom domains
(Cobb, Fulton, DeKalb, Chatham, Bibb, Hall, Richmond, Columbia, Houston,
Whitfield, Carroll, Fayette, Oconee, Tift, Gordon, Walker, Bacon). Finishing
those is a URL lookup per district, not a technical problem.

#### Three caveats that limit the conclusion

1. **The 10 unfetchable districts are this container's fault, not theirs.** The
   errors were `Tunnel connection failed: 502 Bad Gateway` and
   `Connection reset by peer`, and the agent proxy's own
   `__agentproxy/status` endpoint lists those exact hosts under
   `recentRelayFailures` (`connect_rejected`, `ws_closed_mid_exchange`). They
   should be re-run from CI or an ordinary network before being treated as
   anything. Do not record them as district-side blocks.
2. **"No signature matched" is not "not Simbli".** The detector follows agenda
   links up to three hops; a district homepage that does not surface its
   board-meetings page within that will come back clean. Each of those 8 wants
   one look at its actual board page.
3. **Zero BoardDocs hits is not proof of zero BoardDocs.** 27 of the 50 places
   were either untested or unfetchable, and Fulton's migration shows districts
   move. Historical meetings may also still sit on BoardDocs after a district
   switches.

#### Two findings that change the 3c/3d estimates

**Simbli is scrapable, and the config key is right there.** Every Simbli link on
a district site — including policy-manual links — carries the same `S=<id>`
district key, so the detector extracts it without needing the meetings page.

**A false alarm, recorded so it is not repeated.** Starting 3c I briefly
concluded Simbli was blocked by Imperva/Incapsula and wrote that here. It was
wrong, twice over:

- The first check looked at a **byte count** and called a 6,650-byte response
  "fetches fine". It was an Incapsula challenge page.
- The correction then tested `'ncapsula' in html` and concluded every page was
  blocked. On top of that, one district returned a genuine transient challenge,
  and one id I tested (`S=3920`) was a number I had invented, so its error page
  was not a block at all.

  > **Partly corrected while building 3c.** I wrote that the marker matched
  > *normally-served* pages too. Measured against a captured 150 KB served
  > listing, it does not: that page contains no `_Incapsula_Resource` reference
  > and the block page does, so the marker would in fact have separated these
  > two. The substring test was wrong for a plainer reason — it asks about the
  > vendor's infrastructure rather than about what the response IS, and the
  > answer is the vendor's to change. The conclusion stands; the stated reason
  > for it was overspecified.

What is actually true, measured with a content check (does the page contain a
meeting grid?): **the project's own `lib.http.fetch_bytes` retrieves the listing
at ~150 KB with all 50 meetings.** Four of five real district ids served on the
first attempt and the fifth served on a retry, so **transient challenges happen
and the adapter needs a retry**, which is all. The lesson for any future adapter:
assert on *content*, never on response size or an injected-marker substring.

**The listing's mechanics, confirmed from the page and its own JavaScript:**

Each row of `SB_MeetingListing.aspx?S=<district>` carries everything needed:

```html
<td><span title='11/03/2026 - 08:30 AM'>11/03/2026 - 08:30 AM</span></td>
<td><a onclick='ViewMeeting("4122","140227","1","0","P",event)'>Regular Session …</a></td>
<td><a onclick='ViewMinutes("4122","140227","UNPUBLISHED","0","P","0",event)'>UnPublished</a></td>
```

- the **date and time** from the span,
- the **title** from the anchor text,
- the **district id** and a **meeting id** from the `ViewMeeting` arguments,
- a **status flag** (`"1"`) and the **minutes state** (`UNPUBLISHED` / published).

`SB_MeetingListingJS.js` resolves those to real URLs:
**`/SB_Meetings/ViewMeeting.aspx?S=<district>&MID=<meeting>`** for the agenda,
and `/Meetings/PrintMinutes.aspx` for minutes. Its own guard is
`meetingStatus == "1" && isLoggedInUser == "0"`, i.e. **published meetings are
viewable without an account** — so no login is involved.

> **CORRECTED while building 3c.** The minutes URL above is wrong. That file
> contains TWO `ViewMinutes` definitions: an older one, commented out, that opens
> `/Meetings/PrintMinutes.aspx`, and immediately below it the live one, which
> opens **`/SB_Meetings/ViewMeeting.aspx?S=…&MID=…&T=1`** — the agenda URL plus
> `&T=1`. The first reading took the dead copy. `lib/simbli.py` uses the live
> shape and `test_simbli.py` pins it.

The anchors are `href="javascript:void(0)"`, so a naive link scraper finds
nothing; the URLs have to be built from the `onclick` arguments. That is the
actual work in 3c, and it is ordinary parsing.

**Still true from 3b:** some districts use a vanity path with no id — Walton's
link is `simbli.eboardsolutions.com/walton` — so the adapter must accept both a
vanity slug and an `S=` id, or it will silently miss those districts.

**BoardDocs will need a headless browser, which 3d's estimate did not assume.**
`go.boarddocs.com` answers **403 via CloudFront** to both `curl` and the repo's
own `lib.http.fetch_bytes`. Detection still works, because it reads the outbound
`go.boarddocs.com/ga/<slug>/` link from the district's own HTML rather than
fetching the portal — but *scraping* it would need the Playwright path the
SharePoint and Wix adapters already use. That pushes 3d above its ~60–90k
estimate and reinforces deferring it.

(Incidentally `lib.http.fetch_bytes` returns `None` on a 403 rather than raising,
so a caller doing `len(...)` gets a `TypeError` instead of a clear error. The
detector wraps its own fetch so it reports cleanly; worth tidying if anything
else grows a dependency on that function.)

### 3.5.2 Phase 3a: the roster drafter

`scripts/draft_school_boards.py` turns Secretary of State results into reviewable
draft blocks, the same "assisted" contract `generate_local_officials.py` uses: it
prints YAML to paste and never writes the data file.

**Statewide run: 77 districts drafted, 215 members, 0 errors.** 82 counties have
no 2024 board contest — Georgia boards are 4-year staggered and the API only
carries local offices from ~2024, so that is expected, not a failure.

`generate_local_officials.py` deliberately skips these contests (its
`_SKIP_OFFICE` excludes `board of education|boe|school|superintendent`) because it
drafts county commissions. This is the other half, reusing its SoS helpers.

**Partisanship is derived, and only in the direction the evidence supports.**
Georgia law lets each district choose partisan or nonpartisan school-board
elections, so the SoS results reveal which mode was used. A party label proves a
partisan ballot → `partisan: true` is emitted with its evidence. **Absence proves
nothing** — an unopposed candidate with no recorded party looks identical — so
that emits a *commented* `# partisan: false` for the curator to confirm. Result:
71 partisan, 6 suggested nonpartisan.

**What it refuses to infer:**

- **no Superintendent, ever** — they are hired by the board, so they cannot come
  from election results
- **no role above Board Member** — a chair is chosen by the board from among its
  members, not elected as chair by voters
- **no term dates** — set per district with no machine source, emitted blank with
  the reason
- **a sub-50% leader is flagged, not drafted as the winner** — Georgia's majority
  rule sends it to a runoff the portal does not carry (1 case statewide)
- **a party label that is neither Rep nor Dem is not guessed.** `map_party()`
  funnels those to "Nonpartisan", which on a ballot that *did* print a label is
  wrong — an independent belongs under `Independent`. So the raw abbreviation is
  shown and the party left for the curator (1 case: Talbot's `Ind`).

**Three real office shapes, all handled:** `County BOE - District 2` (Cobb,
Jackson, Newton, Whitfield), `Board of Education - District 4` (Thomas), and
`County Board of Education - District 5` (Talbot).

**Two bugs the statewide run exposed**, both now fixed and pinned by tests:
two-word counties were silently lost because the registry key stripped the
hyphen (`benhill`) while `slug_of()` keeps it (`ben-hill`) — Ben Hill and Jeff
Davis, the latter a real 3-member partisan board; and the unmapped-party guess
above.

**Verified end to end:** a drafted Newton block pasted into the registry parses
and passes `validate_school_districts.py` with zero errors and zero warnings.

### 3.5.3 Phase 3c: the Simbli adapter — RESULT

`scripts/lib/simbli.py`, 60 invariants in `scripts/test_simbli.py`, fixtures in
`scripts/fixtures/simbli-*.html`. **Verified live end to end**, not only against
the fixture: a run through `fetch_simbli_meetings('4122')` fetched and parsed all
**50 real Newton County meetings**, with agenda URLs on every row and minutes on
the published ones.

**What a listing gives you.** 50 rows, no pagination controls, spanning roughly a
year each side of today (Newton: 2025-12-16 → 2026-11-03). There is no archive to
walk, so that window is what the platform offers and the adapter does not try to
page past it. Every Newton row's meeting type was "Board Meeting".

**`body` is not taken from the grid.** The fourth column is a meeting TYPE, and
the output schema's `body` names the governing body, so it defaults to
`Board of Education` and is overridable per district. The type survives as the
title's fallback for a row with empty anchor text.

**A real bug the live data exposed.** Newton held two meetings on 2026-10-27, at
5:30 PM and 7:00 PM, and **their meeting ids sort the opposite way from their
times** — so sorting by `(date, id)` put the evening session above the afternoon
one. The adapter parses the 12-hour time into a 24-hour sort key, and the fixture
was deliberately cut to include that pair so the ordering is pinned by real rows.

**A blocked district raises; it does not report an empty board.** `fetch_listing`
retries and then raises `SimbliBlocked`. This matters more than it looks: the
silent-failure mode here is recording "this board has no meetings", which is a
false statement about a government body. A fetcher-level failure (lib.http
already exhausted its own policy) returns `None` instead, which callers treat as
"no data this run".

**Egress reputation, measured 2026-11-02 from the dev container: 1 of 12 probes
served the listing, 11 were Incapsula block pages.** Earlier the same day it was
4 of 5. That is this container's IP, not the districts — but it means a CI run
needs the retry budget, and **the per-district success rate from a CI runner is
still UNVERIFIED.** Worth measuring before 3e commits to a schedule.

**`is_listing` asks one question: does the response contain a meeting grid?** Not
its size (the first wrong call about this platform read a 6,650-byte challenge
page as a good fetch), and not a vendor marker (see the correction in §3.5.1).

**Still unverified:** that an individual `ViewMeeting.aspx` agenda and its `&T=1`
minutes page are reachable anonymously. The platform's own JS says they are — its
anonymous branch builds exactly those URLs, gated on `meetingStatus == "1"` and
`minutesStatus == "PUBLISHED"` — and the adapter emits a URL only when those hold.
But every attempt to fetch one from this container was blocked, so the JS is the
evidence, not a fetch. **Retried 14 times against each of an agenda and its
minutes page on 2026-11-02; every single attempt was a block.** Confirm from CI
and do not spend more attempts from a dev container.

(The meeting picked for that test was Newton's `Special Called Meeting - Millage
Rate`, 2026-07-27 — an incidental but useful signal for 3e: board agendas carry
exactly the tax-and-budget items the topic enrichment is built to surface.)

**The vanity-path branch is likewise unverified live.** Some districts link only
`simbli.eboardsolutions.com/<slug>` with no `S=` key, so `resolve_district_id`
fetches that path and reads the key out of whatever comes back — every Simbli
link on a district's pages carries the same `S=<id>`, including policy links.
Exercised by its test; never reached a live vanity path through the blocks.

**Not wired to anything.** Simbli serves school boards, and a board is a district
in `_data/school_districts.yml`, not a place — so `platform: simbli` in
`places.yml` is still correctly rejected by `validate_place_meetings`. Surfacing
board meetings is 3e, and it needs a district→Simbli-id mapping plus a decision
on where they render.

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
| **3a** | County systems scaffolded (180 districts) · validator + 52 invariants in CI · **SoS drafter: 77 districts / 215 members** · board section shipped (`_includes/entity/school-boards.html`). Remaining: confirmed rosters, and publishing the registry to `ga-local-government`. | done but for rosters |
| **3b** | ~~Platform census~~ **DONE** — see §3.5.1. Verdict: build Simbli, defer BoardDocs. | **done** |
| **3c** | ~~Simbli adapter~~ **DONE** — `lib/simbli.py`, see §3.5.3. Verified live: 50 real meetings parsed. | **done** |
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

**2019 is in, from the PDF (added 2026-11-02).** `scripts/lib/dor_millage_pdf.py`
bridges the one year the workbooks miss. The hard part is that the PDF has
**neither a county nor a district code**, and the published key is
`(countyCode, districtCode, taxYear, occurrence)` — so codes are borrowed from
the adjacent workbook year by **exact normalised name**, and the match rate was
measured rather than assumed: **1,458 of 1,474 rows carrying a rate, 98.9%, with
zero ambiguity.** Adjacent-year drift is far below the 15% two-year drift that
motivated §4.1.2's rule, which is why this works — and why the reference year
must stay 2020.

A row that does not resolve is **dropped and reported, never given an invented
code**: 17 of them, all real 2019-only sub-districts (Henry's per-city
`COUNTY INC - <CITY>` lines, Cherokee fire sub-districts, a DeKalb annexation,
Muscogee downtown service districts), none of them a line a place page shows.

Row counts reconcile: 1,560 PDF rows = 1,543 kept + 17 dropped, and
1,560 + the 159 countywide roll-up rows the workbooks synthesise + ~6 districts
genuinely added in 2020 ≈ 2020's 1,725.

**2019 carries millage ONLY** — no tax levied, no assessed value, and no
countywide roll-up. Since a null elsewhere in this dataset means "the
jurisdiction reported none", every row now carries **`dataSource`**
(`digest-xlsx` or `millage-pdf`) so that null cannot be misread. Anything summing
tax or assessed value by year must filter on it.

**Deeper history:** `sso.dor.ga.gov/rtdc/` (§4.4.1) goes back to **1990** but
carries no millage. So the practical coverage is **millage 2019–2025, tax and
assessed value 2020–2025**, and **digest/exemption detail back to 1990** if
wanted.

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
| **1b** | ~~Per-place millage history section on `/local/<slug>/`~~ **DONE** — see §4.5.1. Remaining: a workflow to refresh it when DOR publishes. | **done** (~40–60k est.) |
| **1c** | HB 581 opt-out registry (SoS filings + agenda corroboration + L1–L9 exemption series) | ~60–90k |
| **1d** | Explainers: reading your assessment, the 45-day appeal, what a millage rate is | ~25–40k |
| **1e** | Statewide millage comparison / ranking page | ~40–60k |
| **1f** | *Optional.* `rtdc` HTML parser for pre-2020 digest history (back to 1990). No millage. | ~60–90k |

### 4.5.1 Phase 1b: BUILT

| File | Role |
|---|---|
| `scripts/lib/millage.py` | statewide dataset → one place's levy lines (stdlib only) |
| `scripts/build_millage_places.py` | bakes `_data/millage.json`, 62 places |
| `_includes/entity/millage.html` | the rendered section |
| `scripts/test_millage_view.py` | 40 offline invariants |
| `scripts/fixtures/millage-places.json` | 10 real places |

**Server-rendered, not fetched.** Property tax is the highest-search-intent topic
in `/local/`, so the figures are in the HTML a crawler sees — the same reasoning
that keeps officials server-rendered while meetings load client-side. The data
goes in `_data/` so Liquid can read it; `_data` already holds generated files
(`executive.json`, `featured_races.json`, `results_updated.json`).

**Verified by a real Jekyll build** (`build_entity_pages.py` then `jekyll build`):
the section renders on Covington (city), Newton (county) and Columbus-Muscogee.
62 of 62 visible places have a view; 61 show a combined rate for every year.

**What the section shows.** One row per government that levies on the resident,
one column per year, plus a combined total:

> Covington 2025: County (inside a city) 8.567 + County school district 15.500 +
> City of Covington 6.406 = **30.473 mills** — down from 39.890 in 2020.

Every other district in the county sits in a `<details>`, so the page is complete
without implying a resident pays all of it.

#### The five modelling rules, each a bug that reached the page first

1. **A city and its county show different county rates.** An owner inside a city
   pays the county's INCORPORATED rate; one outside pays the UNINCORPORATED rate.
   This is the most common way such a table is wrong.
2. **A city school district replaces the county system.** Atlanta residents pay
   Atlanta Public Schools, not Fulton County Schools. Listing both would
   double-count ~17 mills.
3. **The county line is a fallback chain, not a lookup.** Consolidated
   governments have no incorporated/unincorporated split — Macon-Bibb and
   Athens-Clarke publish only an incorporated line, Columbus-Muscogee only a
   countywide one — and Echols County has no incorporated municipality at all.
   Before the chain, Macon-Bibb showed no county rate.
4. **One line is ONE district.** Five counties levy their general rate through
   several same-kind districts (Carroll files `COUNTY INC - CARROLLTON`,
   `- BREMEN`, `- OTHER`; Fayette has five). Blending them put Carroll's
   `OTHER` rate on Carrollton's page. A city page now prefers the county's
   variant named for that city.
5. **Special-purpose beats territorial in classification.** `COUNTY UNINC FIRE
   DISTRICT` (Hall), `SSD UNINCORPORATED` (Henry) and `COUNTY UNINC DEVELOPMENT
   SVC` (Hall) all contain "UNINCORPORATED" but are fire/SSD/development
   districts. Matched in the wrong order they were read as the county's general
   levy and added to the resident's rate.

#### The state line is excluded, deliberately

Across all 953 state rows in 2020–2025, **every one that reports a rate reports
0.000 — not one is non-zero — and 126 report nothing at all.** Including it added
zero while voiding the combined rate for whole county-years under the
all-components-present rule (Carrollton 2025 was exactly that). The page states
the state rate is zero instead.

#### The combined rate is conservative, and says when it cannot be given

Emitted only for a year where **every** line reports a rate; a partial sum would
understate a tax bill. It excludes all special districts, because whether one
applies depends on the parcel. Where no combined rate is possible the view
carries a reason rather than a blank — Columbus-Muscogee splits its county levy
across urban, rural and Fort Benning service districts at different rates, so no
single county figure exists to add, and inventing one would be a wrong claim
about someone's taxes.

#### Wired up (2026-11-02)

`.github/workflows/update-ga-millage.yml` — **monthly**, 9th at 09:50 UTC, plus
manual dispatch. It regenerates the statewide dataset, rebuilds
`_data/millage.json`, checks every visible place still has a view, commits if
changed, and mirrors the open data.

**Monthly, not annually.** DOR posts one workbook per tax year, but not on a
fixed date: the 2024 sheet is named `2024 Digest Status 2.7.2024` (February) and
the 2025 one `2025 Digest Export 4.6.26` (April). A yearly cron could miss a new
year by eleven months; monthly catches it within weeks. Each run re-downloads
every year (~14MB) because the cache is in `RUNNER_TEMP` — cheap at this cadence,
and it means a *corrected reissue of an old year* is picked up too, which a
"only fetch years we lack" cache would silently miss.

**No new secret or repo access needed.** `scripts/publish_ga_millage.py` reuses
the existing `GA_LOCAL_GOVERNMENT_TOKEN` and the existing
`Votega/ga-local-government` repo, per decision 1.

**Dataset discovery (revised 2026-11-02).** An earlier version of this wiring
listed the millage paths statically inside the mentions publisher's
`latest.json`. That was wrong: `latest.json` is stamped with *that* job's clock,
so naming another dataset's files there told consumers a monthly dataset was as
fresh as a twice-weekly run. It has been replaced by a per-dataset manifest
convention — `lib/sibling_publish.add_dataset_manifest` writes
`data/<dataset>/manifest.json`, one writer per path, carrying `generatedAt` — the
data's own timestamp, and **no wall-clock time at all**, so an unchanged dataset
republishes byte-identically rather than churning the sibling repo (an earlier
draft stamped a `publishedAt`, which broke `test_publish_early_vote`'s
byte-identity check — and that check was right). All six publishers targeting
a shared repo now emit one: `agenda-mentions`, `millage`, `races`, `early-vote`,
`bills`, `ballot-measures`. `ga-legislation`'s `latest.json` keeps its existing
meaning as a bills pointer and is untouched.

**Why a second publisher rather than extending `publish_ga_local_government.py`:**
that one runs twice weekly, because a county can reskin its site any time.
Millage changes once a year and rebuilding it costs a 14MB download, so bolting
it on would do that ~100 times a year for nothing. Splitting is safe because
`lib.sibling_publish._publish` PUTs each artifact path through the Contents API
individually — an upsert, not a tree replace — so the millage job leaves the
agenda-mention data untouched. It therefore must **not** write `latest.json`,
which the mentions publisher owns; that index lists the millage paths statically
instead, since they are stable whichever job ran last.

Published artifacts: `data/millage.json`, `data/millage.csv`,
`data/millage.schema.json` (closed schema, every field documented, with the
join warnings in the field notes), `data/millage-places.json` (the per-place
reduction) and `MILLAGE.md`.

**Guards.** `min_items` refuses a build with fewer than 1,500 rows — below one
year of the workbook, so a gutted transform is caught while DOR dropping a year
is not mistaken for corruption. The workflow is registered in
`notify-workflow-failure.yml` (the repo's own
`validate_workflow_triggers.py` enforces that). `publish_or_dry_run` fails
loudly rather than dry-running green if the token is empty in CI — the behaviour
added after that token went empty and the repo silently went stale for three
weeks in 2026-09. `assets/data/ga-millage.{json,csv}` are gitignored so a local
run with default paths cannot commit the 1.8MB file.

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
