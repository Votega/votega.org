# Georgia General Assembly SOAP service: data dictionary

What the legis.ga.gov web services return, what each field means, and what we do with it.
The service ships WSDL/XSD schemas but **no field documentation**. Meanings here come from
the schemas plus observation of live responses (a 160-bill sample of the 2025-26 biennium
and 2026 special session, taken 2026-11-26) and from the notes in `scripts/lib/ga_soap.py`.
Where a meaning is inferred rather than confirmed, it says so.

- Base: `http://webservices.legis.ga.gov/GGAServices/<Area>/Service.svc` (HTTP only, no key).
- Schema: append `?singleWsdl` to any service URL. Re-pull it when something looks new.
- Client: `scripts/lib/ga_soap.py` (shared), plus a private copy in
  `scripts/generate_ga_bills_soap.py`.
- Namespaces: services `http://www.legis.ga.gov/2009/01/01/services/`, data
  `http://www.legis.ga.gov/2009/01/01/data/`.

**Used** column: ✓ = read by the pipeline (file named), — = not read.

---

## 1. Global gotchas

1. **The `status` string is not an outcome.** A vetoed bill's latest status is
   `House Date Signed by Governor` (code `HDSG`). The outcome is the `Signed Gov` history
   row's description (`Act N` or `Veto VN`). Never show or filter on raw status as
   "signed".
2. **Text fields carry trailing spaces** (`"House Date Signed by Governor "`,
   `"Local Calendar "`). Strip before comparing.
3. **A code covers variants.** `HPA` appears as both `House Passed/Adopted` and
   `House Passed/Adopted By Substitute`; the variant is in `AmSub`. Match on `Code`, not on
   `Description`.
4. **`SOAPAction` is not uniform.** The Session contract takes the bare operation name; the
   others take the namespaced `…/<Contract>/<Op>` form. Read the WSDL.
5. **Session ids must be looked up** (`GetSessions`), never guessed: non-contiguous, not
   date-ordered. `IsDefault` marks the current *regular* session, not the one meeting now.
6. **Parameter names are case-sensitive.** A mis-cased parameter is silently ignored and
   you get the default session.
7. **Faults arrive as HTTP 500.** `RollCallNotPublishedFault` is deterministic (attendance,
   procedural): do not retry it.
8. **Every operation has `…Json` / `…Xml` twins.** We use the SOAP form only.

---

## 2. Legislation service

Operations: `GetLegislationForSession` ✓, `GetLegislationDetail` ✓, `GetTitles` ✓,
`GetLegislationSearchResultsPaged` —, `GetLegislationRange(s)` —,
`GetLegislationDetailByDescription` —.

### 2.1 `LegislationIndex` (from GetLegislationForSession)

| Field | Meaning | Used |
|---|---|---|
| `Id` | legislationId, the stable key for a bill | ✓ |
| `Caption` | short title | ✓ `get_title_index` |
| `Description` | e.g. `HB 14` | — |

### 2.2 `Legislation` + `LegislationDetail` (from GetLegislationDetail)

| Field | Meaning / observed values | Used |
|---|---|---|
| `Id` | legislationId | ✓ |
| `DocumentType` | enum `HB` `HR` `SB` `SR` | ✓ |
| `Number`, `Suffix` | `14`; suffix `EX` marks special-session bills | ✓ |
| **`LegislationType`** | enum `GEN` `CA` `LOC` `PRIV` `NP` (see 2.3) | **—** |
| `Caption` | full title | ✓ `title` |
| `Summary` | abstract, "A BILL to be entitled an Act…" | ✓ `abstract` (cut to 500 chars) |
| `Status` | **latest** history row (`StatusBase`: Code, Date, Description, Id). Not an outcome; see gotcha 1 | ✓ `status`, `statusDate` |
| `StatusHistory` | every action, `StatusListing` rows (2.4) | ✓ governor action only |
| `ActVetoNumber` | act number when signed (on vetoes: not checked) | ✓ `actNumber` |
| `Authors` | `Sponsorship` rows (2.5) | ✓ `sponsors` |
| `Sponsor` | single `Sponsorship`: the other chamber's carrier | ✓ `secondChamberSponsor` |
| `Committees` | one `CommitteeListing` per chamber (Id, Code, Name, Type). The **current** committee: overwritten when a bill is moved or recommitted (HB 520 shows Health after "Move from P&CH to Hth"; HB 1066 shows Governmental Affairs after recommittal). The original referral is not kept anywhere. Ids match GetCommitteesBySession; member records hold committee **names** only, so a member join folds "&"/"and". Moves are recorded by the pipeline in `committeeHistory` (compared with the previous run; from the 2027 session on, no backfill) | ✓ `committees` |
| `Versions`, `LatestVersion` | `DocumentBase` (Url, Version, Description) | ✓ `textUrl` (latest only) |
| `Votes` | `VoteListing` rows for this bill (3.1) | ✓ `passageVotes` (filtered) |
| **`Footnotes`** | free-text procedural notes, `;`-separated: "Modified Structured Rule", "Withdrawn from General Calendar and recommitted…", "Tabled in Senate". 24 of 160 sampled bills | **—** |
| `Session` | `Session` object | — |

### 2.3 `LegislationType`

| Value | Meaning (inferred from sample) | Sample |
|---|---|---|
| `GEN` | general bill (amends the Official Code) | 49: HB/SB |
| `LOC` | local act (one county/city/school district) | 24: HB/SB |
| `CA` | resolution proposing a **Georgia constitutional amendment** | 16: HR/SR, all matched our abstract regex |
| `PRIV` | privileged/simple resolution (honoring, urging) | 60: HR/SR |
| `NP` | non-privileged resolution (study committees, joint resolutions) | 9: HR/SR |

This is the official flag our two-thirds rule (`lib/ga_vote_rules.requires_two_thirds`)
currently infers from abstract text. `LOC` + homestead-exemption abstract identifies a
local tax-exemption act without the "no Official Code reference" heuristic.

### 2.4 `StatusListing` (StatusHistory rows)

Fields: `Code`, `Date` (datetime), `Description`, `Id`, `StatusListingId`, **`AmSub`** —.

`AmSub` observed: `SUB` / `Sub` (by substitute), `CS` (committee substitute), `FA` (floor
amendment), `CSFA` (committee substitute + floor amendment); empty for most rows.
Inconsistent case: fold before use.

Codes observed (H = House, S = Senate; most have both forms):

| Code | Description |
|---|---|
| `HH` / `SH` | Hopper (filed) |
| `HFR` | House First Readers |
| `HSR` / `S2R` | Second Readers / Read Second Time |
| `SRAR` | Senate Read and Referred |
| `HCFR` / `SCFR` | Committee Favorably Reported (± By Substitute) |
| `HTR` / `STR` | Third Readers / Third Read |
| `HPA` / `SPA` | **Passed/Adopted** (± By Substitute, As Amended) |
| `HRA` / `SRA` | Read and Adopted (resolutions, usually voice) |
| `HTRL` | **House Third Reading Lost** |
| `S3RLT` | **Senate Lost** |
| `HNOM` / `SNOM` | Notice to Reconsider (motion filed) |
| `HRECO` / `SRECO` | Reconsidered |
| `SRECP` | Senate Reconsidered Passed/Adopted |
| `HRECL` | House Lost Reconsidered Bill/Resolution |
| `HRECM` / `SR` | Withdrawn, Recommitted / Senate Recommitted |
| `HPOST` | House Postponed |
| `STAB` / `STT` | Senate Tabled / Taken from Table |
| `SENG` | Senate Engrossed |
| `STH` | Senate Transmitted House |
| `HASAS` / `SAHAS` | Agreed to other chamber's Amend or Sub (± As Amended) |
| `HSG` / `SSG` | **Sent to Governor** |
| `HDSG` / `SDSG` | Date Signed by Governor — set for vetoes too |
| `Signed Gov` | Governor's decision; Description `Act N` (signed) or `Veto VN` |
| `EFF` | Effective Date |

### 2.5 `Sponsorship` (Authors and Sponsor)

| Field | Meaning | Used |
|---|---|---|
| `MemberId` | legisGaGovId | ✓ |
| `Sequence` | 1 = first author (our `primary`) | ✓ |
| `MemberDescription` | `"Cannon, Chas 172nd"` | ✓ fallback name |
| **`Type`** | enum `HouseAuthor` `SenateAuthor` `SenateCoAuthor` `HouseSponsor` `SenateSponsor` | ✓ in `Sponsor` only |
| `Id` | row id | — |

Observed: `Authors` rows are always `*Author`; `Sponsor` is always `*Sponsor` and present on
~12% of bills (those that crossed over). `SenateCoAuthor` is in the enum but was not seen.

---

## 3. Votes service

Operations: `GetVotes` ✓, `GetVote` ✓, `GetVotesForLegislation` —.

### 3.1 `VoteListing` / `Vote`

| Field | Meaning | Used |
|---|---|---|
| `VoteId` | roll-call key. **Not a sequence**: tracks record creation | ✓ |
| `Number` | the chamber's own roll-call number, dense from 1 per session | ✓ listings |
| `Branch` | enum `House` `Senate` | ✓ |
| `Caption` | motion text (3.3). Free text, trailing spaces | ✓ passage filter |
| `Date` | **datetime** `2025-04-04T17:33:00`: the time of day is here | ✓ but cut to the date (see 4) |
| `Time` | `"5:33 PM"` | ✓ listings only |
| `Day` | `"April 4, 2025"` | — |
| `Description` | `"House Vote #434 - 2025-2026 Regular Session"` | — |
| `Yeas` `Nays` `Excused` `NotVoting` | official tally | ✓ |
| `Legislation` | bills voted on, free text in the listing; `ItemVotedOn` rows in GetVote | ✓ |

**Unlinked roll calls.** On a few final votes GetVote's `ItemVotedOn` is **empty**, and
GetLegislationDetail then leaves the vote out of the bill's `Votes` too. Only the listing's
`Legislation` text names the bill. 2025-26 + 2026 SS have three: 2026 SS House
`Veto Override` (`HB 1192`, a **2025-26** bill), 2025-26 House `Adopt CCR` (`HB 973`, the
amended FY2026 budget), and 2026 SS House `Local Calendar as a Whole` (text empty; a
procedural vote on how to vote, not a final action: see section 4). Both producers resolve the text with `lib/ga_passage.resolve_listing_bills`
(own session first, else a unique match in the biennium); a vote attached this way carries
`linkedBy: "listing"` in ga-bills.json.
| **`Tag`** (GetVote only) | journal vote key: `hv0434` (House), `sv0114` (Senate) = chamber + `Number` | — |
| `Votes` (GetVote only) | `MemberVote` rows: `Member.Id` + `MemberVoted` | ✓ |
| `Session` | `Session` object | — |

### 3.2 `MemberVoted`

`Yea` `Nay` `NotVoting` `Excused` `Unknown` → project strings `Yea` `Nay` `Not Voting`
`Excused` `Other` (`ga_soap.VOTE_MAP`). Complete.

### 3.3 Caption shapes (2025-26 + 2026 SS)

Kept as passage today (`lib/ga_passage.native_is_passage`):
`PASSAGE…`, `AGREE TO…`, `ADOPT…`, `Local Calendar`, `LOCAL CONSENT CALENDAR`.

Final actions the anchored regex **misses**:

| Caption | Count | What it is |
|---|---|---|
| `SBs 234, 235, & 336 Passage` | 1 | re-vote after reconsideration; the vote that passed them |
| `Veto Override` | 1 | HB 1192, 2026 SS (two-thirds) |
| `Uncontested House Resolutions` | 1 | batch adoption of House resolutions |
| `CONSENT CALENDAR FOR SENATE STUDY COMMITTEES` | 2 | batch adoption |
| `CONSENT CALENDAR EXPRESSING THE WILL OF THE SENATE` | 2 | batch adoption |
| `RECEDE FROM SENATE AMENDMENT` | 1 | concurrence step |

Correctly dropped: `Attendance`, `MORNING ROLL CALL`, `ADOPTION OF AMENDMENT…`,
`MOTION TO…`, `Reconsider` / `Recon …`, `TABLE`, `Immediately Transmit`, confirmations,
Speaker elections, `Move from <committee> to <committee>`.

---

## 4. Known misuse in our pipeline (2026-11-26)

| # | Misuse | Where | Effect |
|---|---|---|---|
| 1 | Raw `Status.Description` shown/filtered as the outcome | `lib/mcp_bills.py`, `mcp/src/tools/bills.ts`, `ga-bills.html` fallback list | 19 vetoed bills read "Signed by Governor" |
| 2 | Passage regex anchored at caption start | `lib/ga_passage.py` | final votes in 3.3 dropped |
| 3 | `Date` truncated to a day; same-day votes sorted by caption | `generate_ga_bills_soap._passage_votes` | "latest vote" can be the wrong one |
| 4 | Two-thirds inferred from abstract text, `LegislationType` ignored | `lib/ga_vote_rules.requires_two_thirds` | regex guesses + hand pins |
| 5 | `get_detail` failure skipped without a count | `generate_ga_bills_soap.main` | a bill can vanish from a live run |
| 6 | Roll calls with an empty `ItemVotedOn` dropped | both producers | HB 1192's override and HB 973's House CCR vote missing |

Fixed: 1–5 in #541/#542, 6 after them. "Local Calendar as a Whole" (2026-06-20, 93-68)
is not a passage vote and is now classed as procedural (`lib/ga_passage.PROCEDURAL_CAPTION`):
the House floor transcript (Georgia Commons, `meeting:2026-06-20/house-floor`) shows it
decided an objection to voting on the local calendar in one block ("All those in favor of
voting on the local calendar as a whole will vote yes … the objection is lost"); the
passage vote on the 66 bills followed as "Local Calendar", 95-67, lost short of two-thirds.
The House Rules do not describe the step; Rule 31(10) only lists "third reading and
passage of uncontested local bills" in the order of business.

---

## 5. Members, Session, Committees (summary)

**Members**: `GetMembersBySession` ✓ (thin `MemberListing`), `GetMember` ✓ (full),
`GetMembersByTypeAndSession` —.
- `District`: `Type` (House/Senate), `Number` ✓; `Post`, `Coverage` —.
- `Party` enum: `Democrat` `Republican` `Independent` `Other`, recorded **per session** in
  `LegislativeService` (party-switch history).
- `DateVacated` gives the date only, never the reason.
- `Birthday` is month and day only. Unread: `Bio`, `Education`, `Religion`, `Spouse`,
  `CellPhone`, `HomePhone`, `Map`, `DistrictMap`, `LegislativeComments`.

**Session**: `GetSessions` ✓; `GetSessionSchedule` ✓ (`ga_soap.get_session_schedule`): the
legislative days of one chamber's calendar, `[[day, date]]`. `Chamber` (House/Senate) is
**required**; without it the service faults. A regular session numbers days 1-40 in EACH
year (2025-26: 80 rows; day 28 = Crossover Day, day 40 = sine die, 2026-04-02); a special
session 1-N (2026 SS: 1-5, Jun 17-23). Stored as ga-bills.json
`metadata.legislativeCalendar` and re-fetched every run (the calendar can change by
adjournment resolution); a failed call keeps the committed calendar. `GetYears` —.

**Committees**: `GetCommitteesBySession` ✓ (top level only); `GetCommittee` —
(`CommitteeDetail`: `SubCommittees`, `Members` with `Role`/`RoleSort`, agenda/minutes/
archive links). This is where the House Appropriations subcommittees live.

---

## 6. Fields the pipeline derives

What our files carry beyond a straight copy of a SOAP field, and how each is built.
Producers: `scripts/generate_ga_bills_soap.py` (ga-bills.json) and
`scripts/generate_ga_votes_soap.py` (ga-member-votes.json).

### 6.1 ga-bills.json, per bill

| Field | Built from | Notes |
|---|---|---|
| `legislationType` | `LegislationType` | GEN / LOC / CA / PRIV / NP (2.3). Decides the two-thirds rule when present (`lib/ga_vote_rules.requires_two_thirds`) |
| `footnotes` | `Footnotes` split on `;` | procedural notes, oldest first |
| `committees` | `Committees/CommitteeListing` | `[{chamber, id, code, name}]`, House first. The **current** committee per chamber (2.2) |
| `committeeHistory` | `committees` compared with the previous run's file | `[{chamber, from, to, seenOn}]`, `from`/`to` = `{id, code, name}`. Appended when a chamber's committee id changes; carried forward run to run. `seenOn` is the day of the run that noticed the move, not the day of the move (a recommittal's date is in `statusHistory`, code `HRECM`). A first referral is not a move. **Starts with the 2027 session; 2025-26 is not backfilled.** A bill that moves twice between two runs records only the net change |
| `stage` | `statusHistory` + `committees` + `passageVotes` + `governorAction` (`lib/ga_bill_stage.py`) | where the bill is: `{kind, label, path, steps}`; `path` "full" = six steps (origin committee, origin floor, other committee, other floor, final version, Governor), "short" = filed/adopted for a simple resolution; each step `[state, headline, detail]`, state done/current/stopped/ahead. A session is adjourned once today is past the last day of its legislative calendar (`metadata.legislativeCalendar`; for the regular session, day 40 of the biennium's second year, since first-year bills carry over), and a dead bill's stopped step names that day; without a calendar the fallback is 45 days with no legislative action on any of its bills; a bill whose session adjourned short of the Governor is dead, so its step becomes `stopped` ("Died in Senate Finance"). Shown on ga-bills (badge, progress bar, "Where this bill is" panel; the calendar also drives the page's "legislative day N of 40" line while a session sits) and in the MCP's `get_bill` |
| `statusHistory` | `StatusHistory/StatusListing` | `[[datetime, code]]`, or `[datetime, code, AmSub]` when AmSub is set; oldest first. Codes in 2.4 |
| `status` | `Status.Description`, stripped | legis.ga.gov's latest action, **not an outcome** (gotcha 1). The MCP index and the page's fallback list replace it with the Governor's decision (`lib/mcp_bills.outcome_status`) and keep the original as `officialStatus` |
| `governorAction` | `StatusHistory` + `ActVetoNumber` | `{status: Signed / Vetoed / Sent to Governor, sentDate, decisionDate, actNumber}` |
| `secondChamberSponsor` | `Sponsor` | the other chamber's carrier, kept out of `sponsors[]` |
| `passageVotes[]` | the bill's `Votes`, filtered by `lib/ga_passage.native_is_passage` | plus `time` (HH:MM, from `Date`), which orders same-day votes. A vote attached from a listing's text (3.1, "Unlinked roll calls") carries `linkedBy: "listing"` |

### 6.2 ga-member-votes.json, per vote record

| Field | Built from | Notes |
|---|---|---|
| `session` | the session the roll call was **held** in | |
| `billSession` | `lib/ga_passage.resolve_listing_bills` | present only when the bill belongs to another session (2026 SS's override of the 2025-26 HB 1192); bill-text links and slice joins use it |
| `rollNumber`, `time` | listing `Number`, `Time` | order roll calls within a day; not recoverable later |
| `result` | `lib/ga_vote_rules.vote_passed` | never yea > nay |

