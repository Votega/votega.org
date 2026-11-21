# Departure labels, batch 2 (draft for approval)

Drafted 2026-11-21 for the approval step in D6 of `ga-biennium-rollover-decisions.md`. Nothing here is built or published, and `assets/data/ga-departure-labels.json` is unchanged until these are approved. Approval cutoff: 4 January 2027. The rules are batch 1's: only the fact and a date; "lost", never "ousted" or "unseated"; no label names the winner of a contest; vote figures stay in the evidence column.

Sources:
- the roster (`ga-members.json`);
- `races.json` (each own-seat race is `status: certified`, with a recorded `winner`);
- the Secretary of State general election results (`_data/election_results/ga-general-2026-results.json`; election 2026-11-03; the results page was marked certified on 2026-11-20).

All 236 members still on the roster were checked:

| Outcome | Members |
|---|---|
| Won re-election to their own seat | 185 |
| Not on their own seat's November ballot (batch 1, plus the 11 nominees below) | 33 |
| Lost their own seat | 17 |
| In the December 1 runoff | 1 |

**Scope: 28 labels now, 1 pending.**
- 17 lost their own seat.
- 3 lost a race for another office.
- 4 won another office and leave the General Assembly.
- 4 won a State Senate seat and stay in the General Assembly.
- Cheokas waits for the December 1 runoff.

## A. Lost the general election for their own seat (17)

| legisGaGovId | Member | Seat | Draft label | Evidence |
|---|---|---|---|---|
| 5051 | Bethany Ballard (R) | House 147 | Lost the general election on November 3, 2026. | General: 10,996 votes, 47.6%, second of 2; margin 1,098 |
| 823 | Bill Hitchens (R) | House 161 | Lost the general election on November 3, 2026. | General: 10,670 votes, 48.2%, second of 2; margin 818 |
| 4887 | Deborah Silcox (R) | House 53 | Lost the general election on November 3, 2026. | General: 14,403 votes, 48.8%, second of 2; margin 718 |
| 184 | Don Parsons (R) | House 44 | Lost the general election on November 3, 2026. | General: 13,415 votes, 48.0%, second of 2; margin 1,128 |
| 5091 | Eric Gisler (D) | House 121 | Lost the general election on November 3, 2026. | General: 12,805 votes, 47.5%, second of 2; margin 1,320 |
| 4936 | Joseph Gullett (R) | House 19 | Lost the general election on November 3, 2026. | General: 13,786 votes, 48.1%, second of 2; margin 1,118 |
| 5030 | Kimberly New (R) | House 40 | Lost the general election on November 3, 2026. | General: 12,476 votes, 49.0%, second of 2; margin 509 |
| 4886 | Matt Dubnik (R) | House 29 | Lost the general election on November 3, 2026. | General: 7,780 votes, 49.6%, second of 2; margin 135 |
| 5040 | Matt Reeves (R) | House 99 | Lost the general election on November 3, 2026. | General: 9,739 votes, 41.5%, second of 2; margin 3,964 |
| 5075 | Noelle Kahaian (R) | House 81 | Lost the general election on November 3, 2026. | General: 12,693 votes, 46.2%, second of 2; margin 2,078 |
| 219 | Ron Stephens (R) | House 164 | Lost the general election on November 3, 2026. | General: 11,243 votes, 47.4%, second of 2; margin 1,218 |
| 5077 | Sandy Donatucci (R) | House 105 | Lost the general election on November 3, 2026. | General: 9,854 votes, 39.3%, second of 2; margin 5,396 |
| 4899 | Scott Hilton (R) | House 48 | Lost the general election on November 3, 2026. | General: 13,636 votes, 49.2%, second of 2; margin 450 |
| 5042 | Soo Hong (R) | House 103 | Lost the general election on November 3, 2026. | General: 11,981 votes, 49.9%, second of 2; margin 35 (inside 0.5%: check for a recount) |
| 4982 | Clint Dixon (R) | Senate 45 | Lost the general election on November 3, 2026. | General: 35,924 votes, 47.6%, second of 2; margin 3,622 |
| 203 | Ed Setzler (R) | Senate 37 | Lost the general election on November 3, 2026. | General: 46,232 votes, 49.2%, second of 2; margin 1,421 |
| 5016 | Shawn Still (R) | Senate 48 | Lost the general election on November 3, 2026. | General: 36,580 votes, 47.1%, second of 2; margin 4,469 |

## B. Ran for another office and lost the general election (3)

| legisGaGovId | Member | Seat | Draft label | Evidence |
|---|---|---|---|---|
| 835 | Brian Strickland (R) | Senate 42 | Ran for Attorney General in 2026 (lost the general election on November 3, 2026). | General: 1,858,115 votes, 44.4%, second of 2; margin 464,249 |
| 4925 | Greg Dolezal (R) | Senate 27 | Ran for Lieutenant Governor in 2026 (lost the general election on November 3, 2026). | General: 1,835,227 votes, 44.0%, second of 2; margin 497,503 |
| 5046 | Tim Fleming (R) | House 114 | Ran for Secretary of State in 2026 (lost the general election on November 3, 2026). | General: 1,849,034 votes, 44.3%, second of 2; margin 474,872 |

## C. Won another office, leaving the General Assembly (4)

None of the four is sworn in yet, so the labels say "won", never that they hold the office.

| legisGaGovId | Member | Seat | Draft label | Evidence |
|---|---|---|---|---|
| 5029 | Tanya Miller (D) | House 62 | Won the general election for Attorney General on November 3, 2026. | General: 2,322,364 votes, 55.6%, first of 2; margin 464,249 |
| 4942 | Josh McLaurin (D) | Senate 14 | Won the general election for Lieutenant Governor on November 3, 2026. | General: 2,332,730 votes, 56.0%, first of 2; margin 497,503 |
| 4955 | Houston Gaines (R) | House 120 | Won the general election for U.S. House District 10 on November 3, 2026. | General: 174,845 votes, 53.6%, first of 2; margin 23,720 |
| 4953 | Jasmine Clark (D) | House 108 | Won the general election for U.S. House District 13 on November 3, 2026. | General: 248,094 votes, 79.8%, first of 2; margin 185,414 |

## D. Won a State Senate seat, staying in the General Assembly (4)

These four move from the House to the Senate on January 11, so they are **not former members** and will not be in the former-members index. See question 3.

| legisGaGovId | Member | Seat | Draft label | Evidence |
|---|---|---|---|---|
| 5039 | Ruwa Romman (D) | House 97 | Won the general election for State Senate District 7 on November 3, 2026. | General: 45,729 votes, 66.0%, first of 2; margin 22,173 |
| 5050 | Teddy Reese (D) | House 140 | Won the general election for State Senate District 15 on November 3, 2026. | General: 36,680 votes, 71.2%, first of 2; margin 21,876 |
| 5038 | Saira Draper (D) | House 90 | Won the general election for State Senate District 44 on November 3, 2026. | General: 81,092 votes, 92.5%, first of 2; margin 74,491 |
| 4988 | Will Wade (R) | House 9 | Won the general election for State Senate District 51 on November 3, 2026. | General: 70,190 votes, 79.1%, first of 2; margin 51,617 |

## E. Pending: the December 1 general election runoff (1)

| legisGaGovId | Member | Seat | Draft label | Evidence |
|---|---|---|---|---|
| 81 | Mike Cheokas (R) | House 151 | Written after the runoff is certified. No label if he wins; "Lost the general election runoff on December 1, 2026." if he loses. | General: 9,403 votes, 47.9%, first of 3; margin 1,381. No majority, so a runoff against Ethan Wolfe (D) |

## Questions for approval

1. **Wording.**
   - Lost their own seat: "Lost the general election on November 3, 2026."
   - Lost another office: "Ran for <office> in 2026 (lost the general election on November 3, 2026)." This matches the form of batch 1's primary losses.
   - Won: "Won the general election for <office> on November 3, 2026."

   No label names a party, since a general election is not a party contest.
2. **Data shape for winners.** `scripts/test_ga_departure_labels.py` has no type for a win. The options are:
   - (a) keep `ran-for-other-office` and add the `result` field the D6 table describes (`won`, `lost-general`);
   - (b) add a `won-other-office` type.

   Proposed: (a), which matches D6.
3. **Where the section D labels appear.** On 2026-10-30, D6 decided that labels appear only on the former-members index and on former members' pages. Its proposed refinement says a mover's label appears on their own page. The four in section D are sitting members, so under the decided rule their labels would never be shown. Decide whether to show them on their pages or only record them.
4. **House 103 (Soo Hong).** She lost by 35 votes (50.1% to 49.9%), inside Georgia's 0.5% margin for requesting a recount. I have not checked whether a recount was requested or completed. Confirm that before approving her label.
5. **When the leavers' labels show.** The 24 members in sections A to C leave the General Assembly on January 11. Until then they are sitting members, so under the placement rule nothing shows for them before the rollover.
