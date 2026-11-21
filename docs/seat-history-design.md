# Seat history: design

Status: **design settled; Phases 0, 1 and 2 built.** Every open decision (D1-D9) was decided on 2026-11-20. Built: Phase 0 (the staged January 2027 executive turnover), Phase 1 (the seat registry, `assets/data/seats.json`) and Phase 2 (General Assembly holds since January 2023, `assets/data/seat-holds.json`). Phase 3 (executives) is next.

## The question

Should VoteGA keep the history of every elected seat it covers (who held it, from when to when, and how each hold ended), and if so, in what shape?

Short answer: yes, provided the seat identity rule is settled first. Most of the data already exists, and the history only grows as officials turn over. The cost is mostly one-time design work. The real risk is publishing a seat lineage that is wrong, especially across redistricting, in an append-only file that can't be quietly corrected later.

## Scope: history from January 2023

**Decided 2026-11-20:** the first version records seat history from the start of 2023 only. The point is to build all the plumbing (registry, holds, validator, publish) on a short, well-understood stretch, and decide on backfill later.

| Body | `historyFrom` | Why that date |
|---|---|---|
| GA House / Senate | 2023-01-09 | Convening of the 2023–24 General Assembly |
| US House / Senate (GA) | 2023-01-03 | The 118th Congress convened |
| Statewide executives | 2023-01-09 | The current terms began then (inaugurated the week of the 2023 convening) |
| Local | unchanged | `local_officials.yml` already holds what it holds; nothing is dropped and nothing is backfilled for this |

What this scope pulls in, which is deliberate:

- **One redistricting boundary.** The 2023–24 General Assembly and the 118th Congress sat on the **2021** maps; from January 2025 the **2023** maps apply. So the first version must carry two plans per districted body and close every legislative and congressional hold at the boundary. That tests the identity rule on real data from the start, rather than leaving it for a later backfill.
- **Holds already running in January 2023.** Anyone in office before that date (Governor Kemp since 2019, a legislator since 2015) gets `start: null` with `startBasis: before-history`. A null start means "not recorded", never "started here".

Backfill before 2023 is deferred (see "Later: backfill" below). Nothing in the contract has to change to add it, because `historyFrom` is per body and moves back.

## What exists today

Three seat models, built separately, none read by the others:

| Domain | Where | Shape | History |
|---|---|---|---|
| Local officials | `_data/local_officials.yml`, `scripts/lib/local_terms.py` | One row per person, per seat, per term: `seat_id`, `takes_office`, `leaves_office`, `leave_reason`; `seat_capacity` for shared seats | **Yes.** Rows are never deleted; former rows publish to `ga-local-government`. Overlapping holds fail CI. |
| Statewide executives | `assets/data/ga-executive-seats.json` | 13 seats, `holders[]` newest first | **Started 2026-11-20** (Phase 0, below): 9 outgoing holders have staged ends and 9 incoming winners are staged as provisional holders. Every `start` is still null. `ga-executive.html` reads `presidesOver` from it. |
| GA legislature | `ga-legislator-ledger.json`, `ga-bienniums/<tag>/` | Keyed on the **person** (`legisGaGovId`); the district is a roster field | **Indirect only.** The ledger keeps URLs, the freeze keeps departed members' records; neither models the seat. |
| US Congress (GA delegation) | `current-members.json` | Person records with `terms.item[]` | Per person, not per seat. |

The local model is already the right shape. The proposal below takes the local model, keeps its rules, and extends it to the other three domains.

## Terms

- **Seat:** one office as a body elects it. For example, House District 15 under one district plan, the Governor, or Palmetto at-large council (capacity 6).
- **Plan:** a district map (for example the 2023 state House plan). Only districted seats have one.
- **Hold:** one person's continuous time in one seat. A re-elected incumbent's hold continues; it is not one hold per term.
- **Provisional hold:** an incoming winner staged before they take office, while results await certification or the person has no record of their own yet.
- **Gap:** a period when a seat has fewer holders than its capacity (a vacancy). Gaps are computed from holds, never stored; facts about a vacancy go in `vacancyNotes` (see "Vacancies").

## The identity rule: redistricting

This is the decision everything else depends on.

**Rule: a districted seat is its set of census blocks.** A new map does not create a new seat for a district whose blocks did not change: that seat, and every hold on it, simply continues. A district whose blocks changed is a new seat, even if it kept its number. Identity is decided by comparing the two plans' block-equivalency files, so it is exact and needs no judgment. (Decided 2026-11-20, replacing a "whole plan is new" reading that the data disproved.)

- **Seat ids carry the map that first drew the seat,** and that suffix is never renamed, like the local `m1`. So today's House District 15, unchanged since 2021, is `ga-house-15@2021`, while a district the 2023 map redrew is `ga-house-61@2023`. Current seats therefore carry mixed suffixes; that is accurate (the suffix says when the constituency was drawn), and nothing reads the id as a date. Statewide and other non-districted seats have no suffix: `ga-governor`, `ga-psc-4`. Full examples and the rules for ids versus URLs are in the next section.
- **The same number never means the same seat.** Measured 2026-11-20 against the official block-equivalency files: 2021 GA-6 is mostly 2023 GA-7 (75.7% of its blocks), 2021 SD 28 is 86% of 2023 SD 6, and 30 redrawn legislative districts are mostly inside a differently numbered district. Linking by number would join the wrong constituencies.
- **An identical constituency under a new number is a new seat** with an exact 100% lineage link, because the number is part of what voters and pages see. One case: 2021 HD 149 is block-for-block 2023 HD 133. Its holder's hold closes `redistricted` and reopens on the new seat.
- Plans in scope: `ga-house-2021`, `ga-senate-2021`, `us-house-ga-2021` (the 2023-24 General Assembly and the 118th Congress) and `ga-house-2023`, `ga-senate-2023`, `us-house-ga-2023` (from January 2025). Each records the first election it governed, the date it took effect, the districts it **newly drew**, and the districts it **carried over** unchanged.
- **What the 2023 maps actually changed** (block-equivalency comparison, 2026-11-20):

  | Chamber | Carried over unchanged | Newly drawn | Blocks that moved |
  |---|---|---|---|
  | GA Senate | 41 of 56 | 15 | 20,658 (8.9%) |
  | GA House | 119 of 180 | 61 (incl. 149 -> 133, identical but renumbered) | 25,981 (11.2%) |
  | US House | 5 of 14 (GA-1, 2, 3, 8, 12) | 9 | 34,108 (14.7%) |

  Treating 2023 as an all-new map would have falsely closed 165 holds as `redistricted`.
- **A mid-decade amendment follows the same rule (D1).** Whatever it is called, a district whose blocks change is a new seat and one whose blocks don't is the same seat, so a member whose district was not touched keeps one continuous hold. One chamber can therefore have seats drawn by several maps at once. This is the same model as local maps.
- At a boundary, only holds on seats the new map **redrew** close with `endedBy: redistricted`; the same person's new hold opens on the new seat. Holds on carried-over seats continue untouched.
- **Inputs** (not committed; kept in `data-inputs/redistricting/`, listed with sources and checksums in `data-inputs/README.md`; originally from https://www.legis.ga.gov/joint-office/reapportionment): the 2021 plans as passed November 2021 (the `congress-prop1-2021`, `senate-prop1-2021` and `house-prop1-2021` block-equivalency workbooks, plus `congress-prop1-2021-shape.zip`, whose attribute table carries each district's official population for reconciliation) and the 2023 `*-block-equiv` workbooks already used by `build_ga_tract_district_table.py`. All six workbooks cover the same 232,717 blocks.
- **No lineage links at launch (decided 2026-11-20, was D5).** Pages say the seat was redrawn and never list earlier holders as predecessors. Measured links are a separate, later task (below), started when a page needs "previously held by" across a redraw.
- **Lineage between plans is optional and curated.** A `successorSeats` link (old seat → new seat) can be added by a person with a `_note` saying why. It is never inferred from the district number. Without a link, a page says "District 61 was redrawn in 2023; holders before that represented a different map" rather than listing them as predecessors.
- **Measuring 2021→2023 overlap needs data we don't have committed.** `scripts/data/ga-tract-districts.json` assigns tracts to the **2023** districts only. Giving a link a population-overlap figure would need the 2021 block-equivalency files run through the same builder, reconciled to the 2021 plans' official totals the way the 2023 tables were. When links are added, each carries that measured overlap, not a judgment.

## Seat ids, hold ids and URLs

Three different things, kept apart on purpose:

| | What it names | Who sees it | Can it change? |
|---|---|---|---|
| **seatId** | The office, shared by every holder past and future | Data files, joins, validators | **Never.** Written once, like an execId or a `vgId` |
| **hold id** (if one is needed) | One person's continuous time in one seat | Data files | Never |
| **URL slug** | A page about a seat or a person | Visitors and search engines | Yes, through the ledger's redirect pattern |

**A seatId never contains a person's name or a term year.** `ga-governor-bottoms-2027` names a hold, not a seat: the next Governor would need a new id, and the seat's history would stop joining. It also breaks two rules the repo already follows. Ids are never built from names, because a respelling would mint a new identity (the reason execIds are written once and race candidate ids are not keys). And ids are never parsed, which is why the roster `id` is an opaque handle. The person on a hold is identified by its `vgId`, never by the id.

### Examples

| Seat | seatId | Notes |
|---|---|---|
| Governor | `ga-governor` | Statewide: no map |
| Lieutenant Governor | `ga-lt-governor` | Facts about the office (`presidesOver: Senate`) live on the seat |
| Secretary of State | `ga-secretary-of-state` | Matches the existing `officeId` in `ga-executive.json` |
| PSC District 5 | `ga-psc-5` | Elected statewide, so the PSC "district" is a residency rule, not a map |
| GA House District 15 | `ga-house-15@2021` | Unchanged by the 2023 map, so one seat from 2023 to today |
| GA House District 61, 2023-24 | `ga-house-61@2021` | Redrawn in 2023, so a different seat from the one below |
| GA House District 61, current | `ga-house-61@2023` | |
| GA House District 133, current | `ga-house-133@2023` | Identical to 2021 HD 149 but renumbered: a new seat with a 100% link to `ga-house-149@2021` |
| GA Senate District 14 | `ga-senate-14@2021` | Unchanged in 2023 |
| US House GA-6, current | `us-house-ga-6@2023` | Redrawn; 2021 GA-6 (`us-house-ga-6@2021`) is mostly today's GA-7 |
| US Senate, Ossoff's seat | `us-senate-ga-class-2` | Senate seats differ by class, not district: Ossoff holds class 2, Warnock class 3 |
| Palmetto at-large council | `local:palmetto:at-large` | One shared seat with capacity 6, never `at-large-1…6` |
| Covington East Post 1 | `local:covington:east-post-1@m1` | A geographic post, so it is on a map |
| Newton County Commission District 3 | `local:newton:district-3@m1` | Local prefix + the jurisdiction `id` + its `seat_id` (both already in `local_officials.yml`) + the local map (see "Local maps") |
| Newton County Commission Chair | `local:newton:at-large` | Declared jurisdiction-wide, so no map |
| A countywide numbered post | `local:<county>:post-1` | No map only once declared in `jurisdiction_wide`; the label alone doesn't say so |

Not seatIds:

| Wrong | Why |
|---|---|
| `governor-bottoms-2027` | That's a hold, and it's built from a name |
| `ga-house-15` | No map, so it silently joins two constituencies |
| `ga-house-district-15-2023-map` | A URL slug, not an id; slugs may change, ids may not |
| `district-3` | Only unique inside one jurisdiction |
| `local:newton:district-3` | A districted local seat with no map; it would silently join constituencies across a redraw |
| `local:newton:district-3@2022` (once published as `@m1`) | A map label is never renamed when its adoption year is found; the year goes on the map record |

**Hold ids,** if one is ever needed (to key an override or a correction), are the seat plus the start date: `ga-governor:2027-01-11`. A hold with an unknown start (`before-history`) uses the seat plus `historyFrom`. Never a name.

### URLs and search

The seatId is never shown to search engines, so it needs no SEO design. Findability comes from three places, all generated from the data:

1. **Person pages already exist** (legislators, candidates, Congress, executives) and are what people find when they search a name. Seat history should add a line to them ("Governor since January 2027; succeeded Brian Kemp") rather than compete with them.
2. **Seat pages, if built,** serve searches by office ("Georgia House District 15 representative", "who is the Georgia insurance commissioner"). Their slugs should read like that query: `/offices/governor/`, `/offices/ga-house-district-15/` for a seat on the current map, with a redrawn seat's earlier version under its own path (`/offices/ga-house-district-61/2021-map/`). The `@` is a data-file convention and never appears in a URL. Slugs are built by `build_entity_pages.py` and kept alive by the same append-only URL ledger the legislator pages use, so they can be redesigned without breaking links.
3. **Structured data.** Each person page's JSON-LD can describe every hold as a schema.org `Role` (`roleName`, `startDate`, `endDate`), which tells search engines who held what and when. It costs nothing once the holds file exists.

### Local maps

**Decided 2026-11-20 (was D9):** local seats follow the same rule as state and federal seats. Counties, cities and school boards redraw their districts too, usually by local act after each census and sometimes mid-decade, so a districted local seat's id carries its map from the day it is first published. Adding a map suffix later would change every local seatId, which is exactly what the "never changes" rule forbids, so the slot has to exist from the start.

**Every local seat is on the jurisdiction's map unless it is declared jurisdiction-wide.** The two possible mistakes don't cost the same. Treating a districted seat as countywide is the costly one: its seatId goes out with no map suffix, and adding one later changes the id. Treating a countywide seat as districted is cheap: it carries an unneeded `@m1`, and declaring it jurisdiction-wide before the first publish fixes it. So the default is "on a map", and the jurisdiction lists the exceptions.

**The seat_id helps draft the list but never decides it.** In the 71 jurisdictions today the shapes are `district-N` (310 rows), `at-large` (52), `post-N` (30), `mayor` (16), `ward-N` (8) and a long tail (`east-post-N`, `super-district-N`, `district-N-post-N`, Baker County's named districts such as `milford-district`). A seat_id containing `at-large` is reliably jurisdiction-wide, and so are `mayor` and a chair. The reverse doesn't hold: some counties elect numbered `post-N` seats countywide with only a residency rule. The label can't be fixed after the fact either, because `seat_id` is already published to `ga-local-government` and the YAML forbids renaming one. So a helper beside `suggest_seat_id()` in `scripts/lib/local_terms.py` pre-fills `jurisdiction_wide` from those obvious cases, and a person confirms it and adds the countywide posts the label doesn't reveal. Code reads the declaration, never the id string (ids are never parsed).

Proposed fields in `local_officials.yml` (jurisdiction level; the YAML stays the editing surface and the publisher composes the global seatId):

```yaml
- id: newton
  jurisdiction_wide: [at-large]   # no map: mayor, chair, at-large, countywide posts
  maps:
    - id: m1                      # written once, never renamed
      adopted: null               # e.g. the local act, once found
      effective: null             # first day officials elected under it serve
      effectiveBasis: unknown     # same vocabulary as hold dates
      firstElection: null
      source: null
      supersededBy: null          # m2 when the next redraw is recorded
```

Rules:

- **Map ids are opaque, per jurisdiction, and need no research up front.** The map in force when a jurisdiction's history is first published is `m1`, with its dates `null` and `effectiveBasis: unknown`. When the adoption act and effective date are found, they go on the map record. The id is never renamed to a year, because that would change every seatId on it. (State and federal plans keep year labels like `@2023` because their years are known before publishing.)
- **Every seat not in `jurisdiction_wide` is on the map in force,** so a map needs no seat list. A seat that exists only under one map (a district added when a board grows) is placed by its rows' dates.
- **A redraw adds a map, it never edits one.** Record the new map (`m2`) with its effective date, set `supersededBy` on the old one, and the publisher closes every hold running on the old map that day with `endedBy: redistricted`, then opens the same people's holds on the new seats.
- **A change of status is a new seat.** A county that converts at-large posts to districts (a resized board, a local act, a Voting Rights Act settlement) adds new seat_ids under the new map, and the at-large seat's holds close `redistricted`. Remove the old seat_id from `jurisdiction_wide` only if it is reused for a districted seat, which should be avoided.
- **Member rows don't name their map.** A row's map is the one in force on its `takes_office` date. Only a row the dates can't place (blank `takes_office` straddling a recorded redraw) carries an explicit `map:`, and the validator asks for one.
- **Seat_ids don't change across a redraw.** `district-3` stays `district-3` in the YAML; the map tells the two apart. This keeps the existing "never rename a seat_id" rule intact.
- **The same rule covers school boards** (`_data/school_districts.yml`) and any future local body. Countywide constitutional officers (sheriffs in `_data/county_officers.yml`) are on no map.
- **Validation:** tier 1, a jurisdiction publishing history with no `maps` while it has any seat outside `jurisdiction_wide`; a `jurisdiction_wide` entry naming a seat_id the jurisdiction doesn't have; a seat_id containing `at-large` that is NOT declared jurisdiction-wide (the one direction the label is reliable); or two maps in force on the same day. Tier 2, a map with `effectiveBasis: unknown`, and any `post-N` seat on a map, both reported as research to confirm, never gated.
- **Spotting a redraw is a recurring task,** because no feed announces one: after each census (maps from roughly 2031–2033) and after any General Assembly session (local redistricting acts pass as local legislation), check the jurisdictions we cover and record new maps. Add this to `RECURRING-TASKS.md` when Phase 4 lands.

Rolling this out needs no date research up front: Phase 4 adds `maps: [{id: m1}]` and a helper-drafted `jurisdiction_wide` list to every jurisdiction, a person confirms the countywide posts, and every map date stays `null` until found.

## Date semantics

One definition across all domains, each with a stated basis:

- `start` is the **first day in office**, not the election or certification date.
- `end` is the **first day no longer in office**. It is normally the successor's `start` (the local file already uses this convention).
- `startBasis` / `endBasis` record how the date was known:
  - `official`: the source states it.
  - `convening`: the biennium's convening date, for legislators whose source gives a session, not a date.
  - `writ`: a governor's writ of election.
  - `term-rule`: a fixed rule, such as PSC terms beginning 1 January (O.C.G.A. 46-2-1).
  - `reported`: a published but not official date, such as a press-reported inauguration.
  - `before-history`: the hold was already running at `historyFrom`.
  - `roster-termStart`: a mid-term joiner's start taken from `ga-members.json` `termStart`, accepted only when it falls after the predecessor's end and inside the biennium.
  - `inferred` or `unknown`.

  A null date with no basis is not allowed.
- `endedBy` answers **one question: why did this hold on this seat end?** It must come from one list, shared by every domain:

  | Value | Meaning |
  |---|---|
  | `term-limited` | Barred from another consecutive term (the Governor: two consecutive terms). Takes precedence over `did-not-run`: being ineligible is the reason, even if they then sought another office |
  | `did-not-run` | Eligible, but did not seek this seat again (retired, or ran for something else) |
  | `lost` | Lost this seat's election (primary, general or runoff) |
  | `resigned` | Left mid-term, including to take another office |
  | `removed` | Removed from office |
  | `deceased` | Died in office |
  | `redistricted` | A new map redrew this seat (its blocks changed, or it was renumbered); the same person's next hold, if any, is on a new seat. Never used for a carried-over seat |
  | `term-ended` | The term ran out with no election choice involved (for example an appointed interim term expiring, D4) |

  **What happened elsewhere is derived, never stored.** "Won a Senate seat" is the same vgId's next hold starting on or near this hold's end; "ran for governor and lost" is a candidacy in the crosswalk with no hold after it. Storing either here would conflate a win with a loss (a single "sought other office" value can't tell them apart) and copy a fact that can drift from its source. So `appointed-elsewhere`, which named a destination, is dropped: that case is `resigned` plus the next hold. Today `scripts/test_executive_identity.py` carries its own copy of this list; the shared validator replaces it (D8).

Legislature caveat: the SOAP `GetMember` service gives the sessions each member served, with party and district inside each session record, but no start date. A hold therefore starts at the convening of the first session served in scope (`startBasis: convening`), unless an override or a writ gives the real date for someone who joined mid-term. `dateVacated` from the service gives an end where it exists. The departure itself still comes only from the editorial overrides, as today.

## Proposed contract

One seat registry plus one holds file. Both use the same schema across every domain, and the local file is converted into this shape when it is published (`local_officials.yml` stays the editing surface).

`assets/data/seats.json`:

```json
{
  "metadata": { "generatedAt": "…", "count": 0, "plans": [
    { "id": "ga-house-2021", "body": "ga-house", "firstElection": "2022-11-08", "effective": "2023-01-09", "supersededBy": "ga-house-2023" },
    { "id": "ga-house-2023", "body": "ga-house", "firstElection": "2024-11-05", "effective": "2025-01-13", "supersededBy": null } ] },
  "seats": [
    { "id": "ga-house-15@2021", "body": "ga-house", "district": 15, "plan": "ga-house-2021",
      "capacity": 1, "successorSeats": [], "facts": {} },
    { "id": "ga-lt-governor", "body": "ga-executive", "district": null, "plan": null,
      "capacity": 1, "facts": { "presidesOver": "Senate" } }
  ]
}
```

`assets/data/seat-holds.json`:

```json
{
  "metadata": { "generatedAt": "…", "count": 0,
                "historyFrom": { "ga-house": "2023-01-09", "ga-senate": "2023-01-09",
                                 "us-house-ga": "2023-01-03", "us-senate-ga": "2023-01-03",
                                 "ga-executive": "2023-01-09" } },
  "holds": [
    { "seatId": "ga-house-15@2021", "vgId": "<vgId>",
      "ids": { "legisGaGovId": "<legisGaGovId>" },
      "start": null, "startBasis": "before-history",
      "end": null, "endBasis": null, "endedBy": null,
      "party": "R", "provisional": false,
      "source": "legis.ga.gov GetMember", "note": null }
  ]
}
```

- **The person key is `vgId`**, with domain ids alongside. A hold whose person has no `vgId` can't be written as settled. It may exist only as a provisional hold with `vgId: null` and a note saying why. A hold always stores the surviving vgId, never a retired one (see "Merging vgIds that already exist").
- `party` is party during the hold. A party switch mid-hold is a list (`partyHistory`), not a new hold.
- **An appointed holder is an ordinary hold (decided 2026-11-20, was D4)** with `appointed: true` and `startBasis: official` (the appointment's effective date). It ends like any other: `term-ended` when the appointed term runs out, `lost` if they ran in the next election and lost, `did-not-run` if they chose not to. One kind of hold means one code path; `appointed` is what a page reads to say "appointed" rather than "elected". An appointment that ends with the appointee winning the seat is NOT a new hold: the hold continues and `appointed` describes how it began.
- **Provisional holds** carry `provisional: true`, a reserved id (`execId` for executives), and `name` / `party` because the person has no record of their own yet. A seat has at most one, it is the newest holder, and its `start` equals the current holder's `end`. **The current holder is the first holder that is not provisional.** That rule depends on the data, not today's date, so nothing changes on its own on inauguration day. At the swearing-in, a person promotes the stub: adds the official to `ga-executive.json` under the reserved id and drops `provisional`, `name` and `party`.
- `metadata.historyFrom` states, per body, where the record starts. A page must never imply a seat had no earlier holders when the record simply doesn't go back that far.
### Vacancies

**Decided 2026-11-20 (was D2): a vacancy is computed, and what is known about it is a note beside it.** A gap is the time between one hold's `end` and the next hold's `start` on the same seat (or, for a shared seat, any time it has fewer holders than its capacity). Holds therefore only ever contain people: no null-`vgId` holds, and capacity checks stay simple.

The facts a vacancy carries live in `vacancyNotes` in `seat-holds.json`, keyed by the seat and the day the gap began (`from`, which equals the departing hold's `end`):

```json
"vacancyNotes": [
  { "seatId": "ga-senate-7@2021", "from": "<departing hold's end>",
    "kind": "writ", "date": "<date issued>", "ref": "<EO number>",
    "source": "ga-executive-orders-*.json", "note": null },
  { "seatId": "ga-senate-7@2021", "from": "<same>",
    "kind": "special-election", "date": "<election day>", "raceId": "<races.json id>",
    "source": "races.json", "note": null }
]
```

- **`kind`:** `writ` (the governor's writ of election), `special-election`, `special-runoff`, `appointment-pending` (an appointment the law requires but has not been made), or `note` (anything else, which must have `note` text).
- **Several notes per gap** are normal: a writ, then a special election, then a runoff.
- **Sources are derived where they exist.** Writs come from the committed executive orders, which already corroborate all 11 departures in 2025–26 to within 1–17 days. Specials come from `races.json`. A person adds anything else. Senate writs say "Georgia STATE Senate", so a matcher that looks for "Georgia Senate" misses them.
- **A note never closes or opens a gap.** Only holds do. A special-election note does not imply anyone won; the winner's hold does.
- `vacancyNotes` are append-only like holds: a note on a closed gap is not edited without an override and a `_note`.

### Suspensions

**Decided 2026-11-20 (was D3): a suspension is a status inside the hold, not a span of its own.** A suspended member still holds the seat: the site already lists them with a badge, the seat is not vacant, and no successor is seated. Splitting the hold in two would invent an end and a restart that never happened, and would make the seat look vacant to anything that computes gaps.

A hold carries an optional list:

```json
"suspensions": [
  { "start": "2026-01-22", "startBasis": "official", "end": null, "endBasis": null,
    "endedBy": null, "ref": "EO 01.22.26.02",
    "source": "ga-members-overrides.json (status Suspended)", "note": null }
]
```

- **`endedBy`** for a suspension is `reinstated` or `hold-ended`. `hold-ended` means the hold itself ended while suspended (resigned, removed, term over), and the hold's own `endedBy` says which.
- **Source:** the roster override that already records it (`status: "Suspended"`, `statusDate`, `statusNote` with the governor's executive order). Sharon Henderson (HD 113, suspended 2026-01-22 by executive order) is the one case in scope.
- **What it changes downstream:** the seat counts as held for capacity, gaps and party composition. A consumer that needs who could vote on a date (participation, the majority tracker's "voting members" line) reads the suspension. Votes during a suspension are absent, not "missed".
- **A suspension never opens a gap** and never needs a vacancy note.

- `ga-executive-seats.json` is folded into these two files. Its seats become registry rows and its `holders` become holds, provisional ones included.

## Where each domain's history comes from

| Body | Source | Getting to 2023 | Ongoing |
|---|---|---|---|
| GA House / Senate | `GetMembersBySession` for 2023–24 and 2025–26 (plus the 2023 special session), and `GetMember` per person for district and party per session. No auth, no quota. Departures from `ga-members-overrides.json`; mid-term dates from the governor's writs already committed in `ga-executive-orders-*.json`. | **Two or three session listings plus one `GetMember` per person seen.** | Derived on every roster run; closing a hold is proposed, then a person approves it (same rule as departures today). |
| US House / Senate (GA) | `unitedstates/congress-legislators` (CC0), current and historical files, with term start/end dates per member. | The 118th and 119th Congresses. | Derived from the daily roster. |
| Statewide executives | `ga-executive.json` (hand-maintained) + `races.json` winners. | Current holders from 2023 (`before-history` starts); the January 2027 turnover is already staged. | Hand entry at each turnover, prompted by `propose_race_winners.py`. |
| Local | `local_officials.yml` (already holds history). | As entered. | Unchanged; the publisher maps rows into the shared shape. |

### Trap: a person who moves between domains keeps their vgId only through the right key

`lib/ga_identity.py::executive_keys()` resolves an executive with `legacyRosterId`, then `legis:<legisGaGovId>`, then the execId, and the first key found in the ledger wins. **Sitting legislators are in the ledger under their roster id (`ocd-person/…`), not `legis:<gid>`.** So an executive record that carries only `legisGaGovId` finds no key and is given a brand-new vgId. Found 2026-11-20 with Josh McLaurin (Lt. Governor-elect, SD 14) and Tanya Miller (AG-elect, HD 62): both stubs now carry `legacyRosterId`, and both resolve to their legislator vgIds (`000115` and `000222`).

The seat-holds builder will meet this whenever someone changes domain (a legislator who wins statewide or federal office, or an executive who returns to the legislature). It must look the person up by the same key order the crosswalk uses, never mint a new id itself, and fail the build if one person resolves to two vgIds across their holds.

### Merging vgIds that already exist

**Built 2026-11-20 (was D7).** `sameAs` alone could not join two vgIds that were both already assigned: `Ledger.alias()` never overwrites an existing entry. The ledger now carries a forward, `merged: {<retired>: <survivor>}`, written by `Ledger.merge()` only when an explicit `sameAs` key already sits on a different vgId. Assignments are never rewritten; the retired id keeps its keys and every lookup follows the forward (`Ledger.canonical()`). The crosswalk publishes the map as `metadata.mergedVgIds`; no record carries a retired id; the news hub (`ga-news.html?entity=`) and feed bindings follow it. `validate_id_crosswalk.py::merge_errors()` gates each forward: one hop, between issued ids, backed by a `sameAs` with a `_note`, never dropped or changed against HEAD.

First use: Tanya Miller, `000376` (AG candidacy, filing 102716, committee "Tanya For Georgia, Inc.") -> `000222` (HD 62 legislator, filing 102734). The older id survives because it carries her legislator record. Choosing the direction for future merges (it is permanent) follows the rule in CLAUDE.md: durable key over a campaign filing, then the older id, then the more-referenced one. The filings share no committee, website or address on file, so the evidence in the `_note` is the reporting that the sitting HD 62 representative is the AG nominee and winner (Fox 5 Atlanta, Atlanta News First).

**Four more people already have a stale second vgId** in the ledger: McLaurin (`peachfile:100828` -> `000329`, person `000115`), Derrick Jackson (`peachfile:100008` -> `000299`, person `000062`), Everton Blair (`000303`, person `000685`) and Will Wade (`000672`, person `000236`). Those ids appear on no record, because the builder attaches each filing to the owner it found and ignores the stale assignment; so today they are harmless orphans. They could be given forwards too, so that a consumer holding one is pointed at the right person, but each needs its own `sameAs` and evidence. Not done yet. **Never use `alias()`'s return value to pick a record's vgId:** doing so splits these four people in two.

The seat-holds builder relies on this: a hold keyed on the wrong one of two vgIds splits a person's seat record, so holds must resolve every vgId through the forward.

## Validation

Tier 1 (gates the commit, because these mean the file contradicts itself):

- A seat never has more concurrent settled holds than its `capacity`.
- `end` is after `start` when both are present; every recorded `end` has an `endedBy` from the shared list, an `endBasis` and a `source` (already enforced for executive seats in `test_executive_identity.py`).
- Every `seatId` exists in the registry. Every settled hold has a `vgId` that exists in the crosswalk ledger, and **one person never resolves to two vgIds across their holds.**
- **A closed hold is immutable.** Compared against HEAD, the same way the ledger and `vgId`s are checked. Correcting one needs an explicit override with a `_note`, never a silent edit.
- A districted seat's hold falls within the period its seat exists (from the map that drew it until a map redraws it); a hold running when its seat is redrawn closes `redistricted`, and no hold on a carried-over seat does. Every district of a new plan is listed as exactly one of newly drawn or carried over, and a carried-over claim must match the block-equivalency comparison.
- `successorSeats` links point at seats under a later plan, never the same plan.
- **Suspensions:** each lies inside its hold (`start` on or after the hold's start; `end`, if any, on or before the hold's end); suspensions on one hold don't overlap; an open suspension on a closed hold is an error (it must end `hold-ended`).
- **Vacancy notes:** every note's `(seatId, from)` matches a computed gap (a hold on that seat ends on `from` and the seat is then under capacity); its `date` is on or after `from`; `kind` is from the list; a `note` kind has text; a `raceId` exists in `races.json`.
- **Provisional holds:** at most one per seat, newest first, `start` equal to the current holder's `end`, a reserved id not used by any settled holder, and a `name`, `startBasis` and `source`. Already enforced for executive seats; the shared validator takes over these checks.

Tier 2 (reported, commit proceeds):

- A seat with no current or incoming holder (vacancy).
- A gap longer than 180 days.
- A gap on a legislative seat with no `writ` note after 30 days (the governor normally issues one within days; the 2025–26 writs came 1–17 days after each departure).
- A gap whose `special-election` date has passed with no hold starting since.
- A suspension still open after 365 days, reported as a prompt to check for reinstatement or removal.
- A hold with a null date and `unknown` basis.
- A provisional hold whose `start` has passed and has not been promoted. This is reported, never gated: a gate tied to the date would turn CI red on inauguration day.
- A hold the source supports but the overrides haven't approved closing (the "proposed, not disposed" queue).

## What it unlocks (later, not part of the first phases)

1. **Open seat derived from data:** the seat's current holder isn't on the race's active ballot. This replaces the planned `openSeat` field and the `_note` text inference.
2. **Race and legislator pages:** "Previously held by …" with dates, stopping honestly at a plan boundary or at `historyFrom`.
3. **Majority tracker on any date since 2023,** including vacancies.
4. **Rollover becomes hold changes, not overwrites.** The January legislature rollover closes and opens holds; the freeze in `ga-bienniums` remains the page-permanence mechanism.
5. **Published dataset** in `Votega/ga-district-information` (decided 2026-11-20, was D6): the seat registry with its maps, and every hold with its dates and how it ended, keyed on `vgId` with `legisGaGovId` / bioguide alongside. Publish to the sibling repo first, then add the catalog entry (the open-data rule).

## Publishing

**Decided 2026-11-20 (was D6): one combined dataset, in `Votega/ga-district-information`.** Not `ga-legislators`, for two reasons. Seat history spans every body (statewide executives, the federal delegation and local seats as well as the legislature), so people who change domains would leave a legislators repo's scope partway through their record. And `ga-legislators` is built around each General Assembly (`data/` overwritten at every rollover, history in `sessions/<biennium>/`), while holds are one append-only ledger across bienniums. `ga-district-information` already publishes the maps, the tract populations and `district-counties.csv`, so the registry sits with the geography it describes, and measured lineage (D5) would be built from that repo's own tract table.

- **Files:** `data/seats.json` (registry and maps), `data/seat-holds.json` (holds and `vacancyNotes`), CSV twins, and JSON Schemas whose `$id` is their own published path.
- **Attribution:** `REPO_SOURCES` in `scripts/lib/sibling_publish.py` is keyed by target repo, so the `ga-district-information` entry must add the new upstreams: legis.ga.gov, unitedstates/congress-legislators, the Secretary of State's results, and VoteGA's editorial overrides.
- **Cadence:** the repo has only changed on redistricting until now. Holds change whenever someone leaves or is seated, so its publisher also runs after roster updates. A quiet day must publish nothing.
- **Pointers, not copies:** `ga-legislators` member records carry the vgId and a link to the person's holds (optionally a filtered legislators-only `holds.csv` generated from the same file). `ga-local-government` does the same for local seats. There is one source of truth.
- The repo's name undersells it once it holds tenure; its README says what is in it.

## Later: measured lineage links

Deferred by D5. Links are needed only for the 85 redrawn seats (the 165 carried-over seats need none, and 149 -> 133 is an exact 100%). The 2021 block-equivalency files are now in hand; what is still missing is Census block population (`gageo2020.pl` from `ga2020.pl.zip`) to turn block shares into population shares. Run both through `build_ga_tract_district_table.py`, require the roll-up to match each 2021 district's official population exactly (for Congress, the shapefile's `POPULATION`), then publish a `successorSeats` link only where the overlap is measured, with the share carried on the link.

## Phasing

0. **Done 2026-11-20 (uncommitted):** staged the January 2027 executive turnover in `ga-executive-seats.json` from the unofficial 2026 general results.
   - **Outgoing holders (9):** each has an `end`, `endedBy`, `endBasis`, `note` and `source`. The end is 2027-01-11 (`reported`) for the eight constitutional officers and 2027-01-01 (`term-rule`) for PSC District 5.
   - **Incoming winners (9):** staged as provisional holders with reserved execIds, vgIds and candidate ids.
   - **Test:** `test_executive_identity.py` now pins the end-record and provisional rules.
   - **Still to do at the swearing-in** (checklist in `RECURRING-TASKS.md`): confirm the dates against the certified results and the actual oath dates, and promote the stubs.
1. **Registry and plans. BUILT 2026-11-20.** `assets/data/seats.json` (350 seats: 335 districted, 2 US Senate, 13 statewide) is generated by `scripts/build_seat_registry.py` from `scripts/data/seat-plans.json` (hand-kept: each map's dates and source file) and `scripts/data/seat-plan-comparison.json` (GENERATED by `--compare` from the block-equivalency files in `data-inputs/redistricting/`, with each input's MD5). Carried-over districts keep their `@2021` seat; redrawn ones get an `@2023` seat with `redrawnBy` set on the old one; 2021 HD 149 carries an exact `successorSeats` link to 2023 HD 133. `scripts/validate_seats.py` and `scripts/test_seat_registry.py` (offline, stdlib, runs in CI) enforce the tier-1 rules, including append-only against HEAD. Nothing reads the registry yet. **On redistricting:** add the new plan to `seat-plans.json`, put its block file in `data-inputs/`, run `--compare`, then the build.
2. **Legislature holds from 2023. BUILT 2026-11-20.** `assets/data/seat-holds.json` (336 holds; 236 open, one per current seat) is built offline by `scripts/build_seat_holds.py` from the committed session snapshot `scripts/data/ga-members-by-session.json` (`scripts/fetch_ga_members_by_session.py`, legis.ga.gov GetMembersBySession for every session from 2023), `seats.json`, `ga-members.json` (2025-26 departures by `status`, the suspension, joiners' `termStart`) and `assets/data/seat-hold-overrides.json` (13 hand-researched end reasons with sources: 8 retirements in January 2025 from carried-over seats, 5 mid-2023-24 departures). 76 holds end `redistricted` at the 2025 convening; 3 joiners have an unknown start (reported). The 26 members who served only in 2023-24 got vgIds from the crosswalk (`role.status: "former"`, keyed `legis:<id>`; Farooq Mughal's key joins his existing candidate vgId through a `sameAs`). Rules and tier-1 checks: `scripts/lib/seat_holds.py`; `scripts/validate_seat_holds.py`; `scripts/test_seat_holds.py`. `vacancyNotes` is populated (2026-11-21): 20 vacancies, each with its writ and special election, and 14 runoffs; see claude.md for the derivation and its traps. **After a roster change** run, in order: `fetch_ga_members_by_session.py`, `build_id_crosswalk.py`, `build_seat_holds.py`. Not yet automated.
3. **Executives:** fold `ga-executive-seats.json` into the shared files, provisional holders included. Retire the executive-only checks in favour of the shared validator.
4. **Federal and local:** map into the same files; local keeps its YAML as the editing surface and gains `maps` (`m1`) and `jurisdiction_wide` on every jurisdiction, as described in "Local maps".
5. **UI and publish:** open-seat derivation first, since it has the most immediate use. Then publish to `ga-district-information` (see "Publishing").

Phases 1–2 shouldn't run alongside the January legislature rollover. Waiting loses nothing, because the 2023–26 holds can be derived afterwards from `ga-bienniums/2025_26` and SOAP.

## Later: backfill before 2023

Deferred on purpose. When it is taken up:

- **GA legislature:** SOAP goes back to 2001, so the data is cheap. The real limit is confirming each earlier plan's effective dates from the reapportionment office: 2001–2004 court-drawn, 2011–2012, and any mid-decade amendments. A wrong boundary mislabels every hold in that period.
- **Federal:** `congress-legislators` historical files, with the same plan-boundary rule for congressional maps.
- **Executives:** no source has been chosen; holders before 2023 would be curated by hand.
- Moving `historyFrom` back per body is the only contract change. Holds currently marked `before-history` get real starts.

## Decisions (all decided 2026-11-20)

- ~~**D1: plan granularity.**~~ Decided: a seat is its block set, for any new plan or amendment; only districts whose blocks change become new seats. Measured on the 2023 maps. See "The identity rule".
- ~~**D2: vacancies stored or computed.**~~ Decided: computed gaps plus `vacancyNotes` keyed by seat and gap start. See "Vacancies".
- ~~**D3: suspended members.**~~ Decided: a status inside the hold (`suspensions[]`). See "Suspensions".
- ~~**D4: appointed interim holders.**~~ Decided: an ordinary hold with `appointed: true`. See "Proposed contract".
- ~~**D5: 2021→2023 lineage links.**~~ Decided: no links at launch; measured links are a later task. See "Later: measured lineage links".
- ~~**D6: published scope.**~~ Decided: one combined dataset in `Votega/ga-district-information`. See "Publishing".
- ~~**D7: merging vgIds that already exist.**~~ Built: the ledger's `merged` forward. Miller's `000376` -> `000222`. See "Merging vgIds that already exist".
- **D8: one `endedBy` list.** List decided 2026-11-20 (see "Date semantics"): `term-limited` is its own value, the list describes only this seat, and outcomes elsewhere are derived. Still to do: retire the copy in `test_executive_identity.py` when the shared validator lands (Phase 3).
- ~~**D9: local maps.**~~ Decided: every local seat carries an opaque per-jurisdiction map id (`@m1`) from first publish unless declared jurisdiction-wide. See "Local maps".

## Out of scope

- History before 2023 (see "Later: backfill").
- Judicial seats (no matching for judicial races yet).
- School boards (to be handled when that roster is finished).
- Any display change to pages before phase 5.
