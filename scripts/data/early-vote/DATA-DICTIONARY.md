# Georgia Secretary of State early-vote files: data dictionary

What every field means in the Secretary of State (SoS) files that feed
[/ga-early-vote/](https://www.votega.org/ga-early-vote/), how we read it, and the traps in it.

**How this was written.** The SoS does not ship a code book with these downloads (none came with them).
Every meaning below was read off the files themselves: observed values, how fields pair up (for example which
status code goes with which reason), and cross-checks against the SoS's certified results. Each claim is tagged:

- **Observed**: a fact about the values (counts, formats, ranges). Re-checkable against the files.
- **Decoded**: a meaning worked out from how values pair with other fields. Consistent in all three years.
- **Inferred**: a plausible meaning we could not confirm from the data. Treat as unconfirmed.

Observations are from the current file `A-12601-1-VoterAbsentee` (1,561,035 rows, as of 2026-10-22), the 2022
file `A-12054` (2,316,950 rows) and the 2024 file `A-12311` (4,096,244 rows). All three have identical columns.

The voter-level files (sections 1 and 2) contain names and addresses and are never committed or published.
Only county totals leave the machine.

**Provenance.** The files described here are the SoS's absentee-ballot and voter-history downloads, its active/inactive
voter table and its certified results exports. They are not the SoS's voter list products (the Voter List and Statewide
Voter File that are ordered under O.C.G.A. § 21-2-225, whose order form carries a commercial-use warning); VoteGA does not
use those. What VoteGA publishes from these files is county-level aggregates only.

---

## 1. Absentee / early voting file (`A-xxxxx-VoterAbsentee`)

One CSV per county (159) plus `STATEWIDE.csv`, which repeats every county row and is skipped. One row is one
**ballot record**, not one voter: a voter whose mailed ballot was cancelled and re-issued has two rows
(8,476 extra rows this year). The file runs through the **previous day**.

### Voter identity (identifying; never shown or published)

| Field | Meaning | Notes |
|---|---|---|
| `County` | County name, upper case (`DEKALB`, `MCDUFFIE`) | Observed. The generator re-cases a few for display (`DeKalb`, `McDuffie`, `McIntosh`). |
| `Voter Registration #` | The voter's SoS registration number | Observed: the join key within one election. Not zero-padded here; the voter history file pads it to 8 digits. |
| `Last Name`, `First Name`, `Middle Name`, `Suffix` | Name | Middle name 90% filled, suffix 5%. |
| `Street #`, `Street Name`, `Apt/Unit`, `City`, `State`, `Zip Code` | Residence address | `State` is `GA` except 7 blanks. |
| `Mailing Street #`, `Mailing Street Name`, `Mailing Apt/Unit`, `Mailing City`, `Mailing State`, `Mailing Zip Code` | Address the ballot is mailed to | About 75% filled this year (61% in 2024). `Mailing State` is `GA` or blank, nothing else. |

### Application and ballot status

| Field | Meaning | Values | Notes |
|---|---|---|---|
| `Application Status` | Outcome of the absentee application | `A` accepted (1,554,891), `R` rejected (3,805), blank (2,339) | Decoded. Every `R` carries the reason `APPLICATION REJECTED`; blank rows are mostly `APPLICATION CURE PENDING` (2,083 of 2,339), an application the voter can still fix. In-person voters appear as `A`. |
| `Ballot Status` | Where the ballot stands | see the table below | Decoded. **The field the page counts on.** |
| `Status Reason` | Why the status is what it is | see the table below | Decoded. |

**`Ballot Status` codes** (this year's counts in brackets):

| Code | Meaning | Reasons it pairs with | Page treats it as |
|---|---|---|---|
| `A` | Accepted: the ballot counts | blank (mostly mail, about 71,000) or `APPLICATION ACCEPTED` (in person) | **Counted ballot** (accepted) |
| `I` | Issued, not yet returned | `APPLICATION ACCEPTED` | Outstanding (80,321) |
| `C` | Cancelled | `CANCELLED - ...`, `ADMINISTRATIVE CANCELLATION` | Cancelled (5,669) |
| `S` | Spoiled (voter or system error, the ballot is void) | `SPOILED - ...` | Folded into cancelled (91) |
| `R` | Rejected after return (bad signature, ID, late) | `REJECTED - ...` | Rejected (611) |
| `PROV` | Provisional ballot. **Seen in 2022 only** (1,396 rows) | none | Not separately handled (counted as "other") |
| blank | No ballot issued yet: application rejected, awaiting cure, or accepted but not yet issued | `APPLICATION REJECTED`, `APPLICATION CURE PENDING`, `APPLICATION ACCEPTED` | Other / pending (6,563) |

**`Status Reason` values** this year (22 distinct): `APPLICATION ACCEPTED`, `APPLICATION REJECTED`,
`APPLICATION CURE PENDING`, `ADMINISTRATIVE CANCELLATION`; `CANCELLED -` {`OTHER`, `MAILED BALLOT SURRENDERD TO
VOTE-IN PERSON` (sic), `BALLOT WAS UNDELIVERED`, `VOTER REQUESTED`, `ADMINISTRATIVE CANCELLATION`,
`VOTER NO LONGER ELIGIBLE`, `REISSUED COMBINED BALLOT`}; `REJECTED -` {`MISSING ID INFORMATION`,
`INCORRECT ID INFORMATION`, `MISSING SIGNATURE`, `INVALID SIGNATURE`, `INELIGIBLE ELECTOR`}; `SPOILED -`
{`VOTER ERROR`, `OTHER`, `DAMAGED BALLOT`, `INVALID MARKING ON BALLOT`, `REGISTRATION ERROR`}; and blank.
2024 also has `REJECTED - BALLOT RECEIVED AFTER DEADLINE` (4,002), which cannot appear until ballots arrive late.
**The vocabulary changes by year**: 2022 uses unprefixed wording (`BALLOT RECEIVED AFTER DEADLINE`, `OTHER`,
`VOTER REQUESTED`, `PI - PHOTO ID NOT PROVIDED`, `V - PENDING MISSING INFORMATION`) and fills the field for only
0.4% of rows, so reasons cannot be compared across years.

### Dates

All `MM/DD/YYYY`.

| Field | Meaning | Notes |
|---|---|---|
| `Application Date` | When the application was recorded | Decoded. For in-person voters it equals the day they voted (99.9999% of rows). |
| `Ballot Issued Date` | When the ballot was issued | Decoded. In person: same day as the vote. Mail: when it was sent. |
| `Ballot Return Date` | When the voted ballot came back | Decoded. **For in-person rows this is the day the voter voted** (issued = return on every in-person row), so it is the date the whole page is built on. For mail it is the day the ballot was received. Blank until returned (94% filled). |

**Stray dates are in all three years.** Observed ranges, this year: application `2002-08-19` to `2028-08-27`;
return `2026-09-16` to `2029-10-20`. 2022 returns run from `1900-01-01` and 2024 up to `2224`. The generator
drops accepted ballots whose return date is missing or outside the window and reports the count (5 this run).
`Ballot Issued Date` reaches `2026-10-26`, after the file date, so some issue dates are scheduled or mis-keyed.

### Ballot method and flags

| Field | Meaning | Values |
|---|---|---|
| `Ballot Style` | **How the ballot was cast, not the ballot's contents.** The name is misleading. | `EARLY IN-PERSON` (1,396,704), `ABSENTEE BY MAIL` (153,956), `ELECTRONIC BALLOT DELIVERY` (10,375; inferred to be the emailed ballot for military and overseas voters). 2024 has one stray `ELECTION DAY (BMD)`. |
| `Ballot Assisted` | A voter who needed help marking the ballot | `NO` / `YES` (2,522 this year; 2022 had none flagged) |
| `Challenged/Provisional` | Challenged or provisional | This year always `NO`; 2022 had 2,633 `YES`; 2024 none. Do not read a `NO` as "no provisionals existed". |
| `ID Required` | Inferred: the voter must supply ID (for example, a first-time absentee voter whose ID is not on file) | `NO` / `YES` (78 this year). Unconfirmed. |

The page counts `EARLY IN-PERSON` as in person and the other two styles as mail.

### Where the voter lives

| Field | Meaning | Notes |
|---|---|---|
| `Municipal Precinct` | Precinct code for a city that runs its own precinct | Observed: 39% filled; most voters have none. Hundreds of distinct codes. |
| `County Precinct` | County precinct code | Observed: filled for every row; hundreds of distinct codes (the profile stopped counting at 400). Codes repeat across counties (`1` exists in many), so it only means something together with `County`. |
| `CNG` | U.S. congressional district | Observed: 3-digit, `001`-`014`, but with malformed values (`06`, `9`). Normalize before comparing. |
| `SEN` | State Senate district | Observed: 3-digit; 61 distinct spellings for the 56 districts (padding varies). |
| `HOUSE` | State House district | Observed: 3-digit; 180 districts plus 1 blank value (181 distinct). |
| `JUD` | Judicial circuit | Observed: 4-letter codes (52 values plus blank) such as `ATLA`, `COBB`, `STMT`, `GWIN`. Inferred: abbreviations of the judicial circuit names (Atlanta, Stone Mountain). |
| `Combo #` | Precinct combination | Observed: 5-digit code, hundreds of values (the profile stopped counting at 400). Inferred: it identifies the ballot combination (which contests that voter sees), so the same precinct splits share a code. |

### Administrative

| Field | Meaning | Notes |
|---|---|---|
| `Vote Center ID` | The early voting site where an in-person ballot was cast | Observed: 6-digit code, filled on 100% of in-person rows and blank on mail (13 stray exceptions). 319 values. There is **no lookup table** for the ID in these files, so it cannot be turned into a site name from here. |
| `Ballot ID` | Identifier of the ballot record | Identifying; not used. Inferred. |
| `Party` | Party ballot chosen | **Blank in general-election files.** Filled only in primaries (A-12055 for 2022, A-12309 for 2024, A-12600 for 2026). |

---

## 2. Voter history file (`A-xxxxx-VoterHistory`)

One CSV, one row per voter who cast a ballot in that election. Column **order differs by year** (2026 puts
`Election Date` first, 2022 puts `County Name` first), so read by name.

| Field | Meaning | Values |
|---|---|---|
| `Election Date` | The election | One value per file (`11/08/2022`, `11/03/2026`). |
| `County Name` | County, upper case | 159 counties. The 2022 file has one extra blank-county row. |
| `Voter Registration Number` | Registration number, zero-padded to 8 digits | Identifying. Strip the zeros before matching it to the absentee file. |
| `Election Type` | Kind of election | `GENERAL`; 43 blanks in the 2026 file. |
| `Party` | Party ballot | Blank in generals. |
| `Ballot Style` | How the voter voted | 2022: `EARLY IN-PERSON` 2,289,863, `REGULAR` 1,419,617 (election day, in person), `ABSENTEE BY MAIL` 243,761, `ELECTRONIC BALLOT DELIVERY` 4,423, plus small `EARLY` (568) and `ABSENTEE` (65) and 1 blank. 2026 so far: early in person, mail and electronic only. |
| `Absentee` | **Voted before election day, early or by mail**, not mail only | Decoded. In 2022 `Y` (2,538,680) is exactly early in person + mail + electronic + `EARLY` + `ABSENTEE`; `N` is `REGULAR`. In 2026 it is `Y` on every row. |
| `Provisional` | Provisional status | Blank, `N`, `Y`, `CHALLENGE REMOVED`, `CHALLENGE NOT REMOVED` (2022). All blank in 2026. |
| `Supplemental` | Supplemental flag | `N`, `Y` (128 `Y` in 2022). **Meaning unconfirmed**; not used. |

**The 2022 history file is a complete record of who voted** (3,958,298 rows, election-day voters included).
The 2026 file is only the early and mail voters so far. For 2022 it is the file we trust over the absentee dump
for Fulton and Gwinnett: it matches the certified early and mail totals within 0.2%.
We count a voter as having voted early or by mail if their style is any of the early or mail values.

---

## 3. Active/inactive voter table (`activeInactiveTable_excel-*.xlsx`)

| Field | Meaning |
|---|---|
| `Voter Status` / `County` | Row label. The first rows are headers; one `Totals` row is the statewide total. Then 159 counties in upper case. |
| `Totals` | All registered voters in the county. |
| `Active Voters` | Voters with active status. **The denominator of the page's turnout rate.** |
| `Inactive Voters` | Registered voters whose status is inactive (Georgia's list-maintenance category). Their definition comes from the SoS, which we have not quoted here. |

This year: 8,233,259 total, 7,529,742 active, 703,517 inactive. The table is a snapshot of the day it was pulled.
The SoS turnout dashboard shows a slightly later active count (7,532,561 on Oct 24), which is normal.

---

## 4. Certified results export (`export-YYYYNovGen.json`)

One JSON document. Anything we read is committed in distilled form as `results-YEAR.json`.

| Path | Meaning |
|---|---|
| `electionDate`, `electionName`, `createdAt` | The election, its name (`November 8, 2022 - General/Special Election`) and when the export was generated. |
| `results` | Statewide results. Same shape as a county below (295 contests in 2024). |
| `localResults[]` | One object per county (159). `name` is `"Fulton County"`, `id` a GUID. |
| `…ballotItems[]` | One contest. `name` (`Governor`, `President of the US`), `id` (contest number), `type` (`Local` in county results, `State` statewide), `voteFor` (1), `ballotOrder`, `precinctsParticipating` / `precinctsReporting`, `contestType` (`Candidate`; the only value seen), `rankedChoiceResults` (null). |
| `…ballotOptions[]` | One candidate. `name` (`Brian Kemp (I) (Rep)`; `(I)` marks an incumbent), `id`, `ballotOrder`, `voteCount` (the county total), `politicalParty`. |
| `…groupResults[]` | The candidate's votes split by voting method: `groupName`, `voteCount`, `isFromVirtualPrecinct`. |
| `…precinctResults[]` | The same by precinct: `id`, `name`, `isVirtual`, `voteCount`, `reportingStatus`, `groupResults`. |
| `…reportingStatuses[]` | Per county and method, whether reporting is complete (`Fully Reported`). |

**Labels change by year; normalize them.** The voting-method `groupName` is `Advance Voting Votes`,
`Absentee by Mail Votes`, `Election Day Votes`, `Provisional Votes` in 2022, and `Advanced Voting`,
`Absentee by Mail`, `Election Day`, `Provisional` in 2024. We match on substrings (`advance`, `absentee`,
`election day`). `politicalParty` varies in case (`REP`, `DEM`, `LIB` in 2022; `Rep`, `Dem`, `Lib`, `Grn` and
`DEM` in 2024) and can be null for nonpartisan contests, so compare upper-cased.

---

## 5. Traps that have already cost us

1. **`Ballot Style` is the method, not the ballot.** Anyone reading it as "ballot style" will misread it.
2. **For in-person voters, `Ballot Return Date` is the day they voted.** There is no separate vote date.
3. **Rows are ballot records.** Count voters, not rows; keep the record furthest along (accepted over rejected
   over issued over cancelled).
4. **The file runs through the previous day.** Taking today's date as the as-of date overstates progress. The
   as-of date is the latest in-person return date.
5. **Stray dates and `STATEWIDE.csv`.** Drop accepted ballots with an unusable return date, and skip the statewide
   duplicate or every count doubles.
6. **A blank `Ballot Status` is not "nothing".** It is an application not yet resulting in a ballot; counting it as
   nothing hides a pending pipeline.
7. **Status reasons and result labels change by year.** Do not compare reasons across years; normalize result labels.
8. **The 2022 absentee dump is incomplete for Fulton and Gwinnett** (stops after 2022-10-22; the SoS has no
   alternate download). Use the 2022 history file for anything that does not need dates.
9. **District codes are not consistently padded** (`06`, `9`, `006`). Convert to integers first.
10. **The SoS dashboard moves faster than the files.** It can be ahead by a day or more; the page's dashboard
    note says so.
11. **The voter-level files are personal data.** Keep them out of the repository and never publish them; the
    page only ever shows counties.
