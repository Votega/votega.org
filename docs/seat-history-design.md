# Seat history: design

Status: **draft.** Only Phase 0 (staging the January 2027 executive turnover) is done. Written 2026-11-20; revised the same day with that work's findings and the 2023 scope decision.

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
- **Gap:** a period when a seat has fewer holders than its capacity (a vacancy). Gaps are computed from holds, not stored (see open decision D2).

## The identity rule: redistricting

This is the decision everything else depends on.

**Rule: a districted seat's id includes its plan, and a seat never carries over to a new plan automatically.** House District 15 under the 2021 plan and House District 15 under the 2023 plan are different seats. The same number does not make them the same constituency, and the site must never present one lineage across two maps as if nothing changed.

- Seat ids: `ga-house-15@2023`, `ga-senate-7@2021`, `us-house-ga-6@2023`. Statewide and other non-districted seats have no plan suffix: `ga-governor`, `ga-psc-4`.
- Plans in scope: `ga-house-2021`, `ga-senate-2021`, `us-house-ga-2021` (the 2023–24 General Assembly and the 118th Congress) and `ga-house-2023`, `ga-senate-2023`, `us-house-ga-2023` (from January 2025). Each records the first election it governed and the date it took effect.
- At the boundary, every districted hold that was running closes with `endedBy: redistricted`, and the same person's new hold opens under the new plan, even if the district number did not change.
- **Lineage between plans is optional and curated.** A `successorSeats` link (old seat → new seat) can be added by a person with a `_note` saying why. It is never inferred from the district number. Without a link, a page says "District 15 was redrawn in 2023; holders before that represented a different map" rather than listing them as predecessors.
- **Measuring 2021→2023 overlap needs data we don't have committed.** `scripts/data/ga-tract-districts.json` assigns tracts to the **2023** districts only. Giving a link a population-overlap figure would need the 2021 block-equivalency files run through the same builder (see D5).

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
  - `inferred` or `unknown`.

  A null date with no basis is not allowed.
- `endedBy` must come from **one list, shared by every domain:** `term-ended | lost | did-not-run | resigned | removed | deceased | appointed-elsewhere | redistricted`. Today `scripts/test_executive_identity.py` carries its own copy without `redistricted` (executive seats aren't districted). The shared validator replaces that copy; see D8.

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
    { "id": "ga-house-15@2023", "body": "ga-house", "district": 15, "plan": "ga-house-2023",
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
    { "seatId": "ga-house-15@2023", "vgId": "<vgId>",
      "ids": { "legisGaGovId": "<legisGaGovId>" },
      "start": "2025-01-13", "startBasis": "convening",
      "end": null, "endBasis": null, "endedBy": null,
      "party": "R", "provisional": false,
      "source": "legis.ga.gov GetMember", "note": null }
  ]
}
```

- **The person key is `vgId`**, with domain ids alongside. A hold whose person has no `vgId` can't be written as settled. It may exist only as a provisional hold with `vgId: null` and a note saying why (Tanya Miller is the live example; see "Merging vgIds that already exist").
- `party` is party during the hold. A party switch mid-hold is a list (`partyHistory`), not a new hold.
- **Provisional holds** carry `provisional: true`, a reserved id (`execId` for executives), and `name` / `party` because the person has no record of their own yet. A seat has at most one, it is the newest holder, and its `start` equals the current holder's `end`. **The current holder is the first holder that is not provisional.** That rule depends on the data, not today's date, so nothing changes on its own on inauguration day. At the swearing-in, a person promotes the stub: adds the official to `ga-executive.json` under the reserved id and drops `provisional`, `name` and `party`.
- `metadata.historyFrom` states, per body, where the record starts. A page must never imply a seat had no earlier holders when the record simply doesn't go back that far.
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

Tanya Miller has two vgIds: `000222` (her House record, PeachFile filing 102734) and `000376` (her AG candidacy, filing 102716, committee "Tanya For Georgia, Inc."). PeachFile registers one committee per office, which is exactly why `sameAs` exists. **But `sameAs` cannot fix this case.** It only joins keys before a vgId is assigned: `ledger.alias()` never overwrites an existing entry, so `peachfile:102716` would stay on `000376`, and `validate_id_crosswalk.py` would fail with "sameAs … did not merge".

Merging two ids that are already published needs a new ledger concept:

- A `mergedInto` record, for example `000376 → 000222`. The old id stays in the ledger forever (append-only) and forwards to the surviving one.
- The builder writes nothing under the retired id, the validator checks that every forward points at a live id, and consumers (news `?entity=` links, the published crosswalk) follow it.
- The override still needs positive evidence in its `_note` (a shared committee, website or filing address). What's on file today is a name and party match, which is not enough under the rule.

Seat history makes this more pressing, because a hold keyed on the wrong one of two vgIds splits a person's seat record.

## Validation

Tier 1 (gates the commit, because these mean the file contradicts itself):

- A seat never has more concurrent settled holds than its `capacity`.
- `end` is after `start` when both are present; every recorded `end` has an `endedBy` from the shared list, an `endBasis` and a `source` (already enforced for executive seats in `test_executive_identity.py`).
- Every `seatId` exists in the registry. Every settled hold has a `vgId` that exists in the crosswalk ledger, and **one person never resolves to two vgIds across their holds.**
- **A closed hold is immutable.** Compared against HEAD, the same way the ledger and `vgId`s are checked. Correcting one needs an explicit override with a `_note`, never a silent edit.
- A districted seat's hold falls within its plan's effective period; holds running at a plan's end are closed `redistricted`.
- `successorSeats` links point at seats under a later plan, never the same plan.
- **Provisional holds:** at most one per seat, newest first, `start` equal to the current holder's `end`, a reserved id not used by any settled holder, and a `name`, `startBasis` and `source`. Already enforced for executive seats; the shared validator takes over these checks.

Tier 2 (reported, commit proceeds):

- A seat with no current or incoming holder (vacancy).
- A gap longer than 180 days.
- A hold with a null date and `unknown` basis.
- A provisional hold whose `start` has passed and has not been promoted. This is reported, never gated: a gate tied to the date would turn CI red on inauguration day.
- A hold the source supports but the overrides haven't approved closing (the "proposed, not disposed" queue).

## What it unlocks (later, not part of the first phases)

1. **Open seat derived from data:** the seat's current holder isn't on the race's active ballot. This replaces the planned `openSeat` field and the `_note` text inference.
2. **Race and legislator pages:** "Previously held by …" with dates, stopping honestly at a plan boundary or at `historyFrom`.
3. **Majority tracker on any date since 2023,** including vacancies.
4. **Rollover becomes hold changes, not overwrites.** The January legislature rollover closes and opens holds; the freeze in `ga-bienniums` remains the page-permanence mechanism.
5. **Published dataset** to a sibling repo: Georgia seat holders with dates and how each hold ended, keyed on `legisGaGovId` / `vgId`. Publish to the sibling repo first, then add the catalog entry (the open-data rule).

## Phasing

0. **Done 2026-11-20 (uncommitted):** staged the January 2027 executive turnover in `ga-executive-seats.json` from the unofficial 2026 general results.
   - **Outgoing holders (9):** each has an `end`, `endedBy`, `endBasis`, `note` and `source`. The end is 2027-01-11 (`reported`) for the eight constitutional officers and 2027-01-01 (`term-rule`) for PSC District 5.
   - **Incoming winners (9):** staged as provisional holders with reserved execIds, vgIds and candidate ids.
   - **Test:** `test_executive_identity.py` now pins the end-record and provisional rules.
   - **Still to do at the swearing-in** (checklist in `RECURRING-TASKS.md`): confirm the dates against the certified results and the actual oath dates, and promote the stubs.
1. **Registry and plans:** write `seats.json` with the 2021 and 2023 plans and the statewide seats.
2. **Legislature holds from 2023:** derive from SOAP for 2023–24 and 2025–26, closing every hold at the 2025 plan boundary. Tier-1 validator and tests with a fake SOAP response, like the existing generators.
3. **Executives:** fold `ga-executive-seats.json` into the shared files, provisional holders included. Retire the executive-only checks in favour of the shared validator.
4. **Federal and local:** map into the same files; local keeps its YAML as the editing surface.
5. **UI and publish:** open-seat derivation first, since it has the most immediate use.

Phases 1–2 shouldn't run alongside the January legislature rollover. Waiting loses nothing, because the 2023–26 holds can be derived afterwards from `ga-bienniums/2025_26` and SOAP.

## Later: backfill before 2023

Deferred on purpose. When it is taken up:

- **GA legislature:** SOAP goes back to 2001, so the data is cheap. The real limit is confirming each earlier plan's effective dates from the reapportionment office: 2001–2004 court-drawn, 2011–2012, and any mid-decade amendments. A wrong boundary mislabels every hold in that period.
- **Federal:** `congress-legislators` historical files, with the same plan-boundary rule for congressional maps.
- **Executives:** no source has been chosen; holders before 2023 would be curated by hand.
- Moving `historyFrom` back per body is the only contract change. Holds currently marked `before-history` get real starts.

## Open decisions

- **D1: plan granularity.** Is a mid-decade amendment that touches a few districts a new plan for every seat in the chamber, or only for the districts it changed? Not hit inside the 2023 scope, so it can wait until a backfill.
- **D2: vacancies stored or computed.** Computing gaps keeps holds clean. Storing them as holds with no person lets a vacancy carry a writ or an interim note. The lean is computed gaps plus a separate `vacancyNotes` keyed by seat and date.
- **D3: suspended members.** They still hold the seat (and stay listed today). Does a suspension stay a status inside the hold, or become its own span? The lean is a status inside the hold.
- **D4: appointed interim holders** (PSC, judicial, local appointments): is an appointment a hold with `startBasis: official` and `endedBy` set on the next election, or a separate kind?
- **D5: 2021→2023 lineage links.** Run the 2021 block-equivalency files through the tract builder so each link carries a measured overlap, or publish no lineage until there's a reason to? The scope means pages will hit this boundary immediately.
- **D6: published scope.** One combined `seat-holds` dataset, or per-domain files in the existing sibling repos?
- **D7: merging vgIds that already exist.** Build the ledger `mergedInto` forwarding mechanism, which Tanya Miller's case needs before her AG hold is settled, and decide which id survives (lean: the older `000222`, which carries her legislator history).
- **D8: one `endedBy` list.** Adopt the shared list above and retire the copy in `test_executive_identity.py` when the shared validator lands (Phase 3).

## Out of scope

- History before 2023 (see "Later: backfill").
- Judicial seats (no matching for judicial races yet).
- School boards (to be handled when that roster is finished).
- Any display change to pages before phase 5.
