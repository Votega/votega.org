# Federal departure labels, draft (NOT approved)

Drafted 2026-11-23 for the approval step in D6 and D12 of `ga-biennium-rollover-decisions.md`. **Nothing here is approved.** The page reads only `assets/data/federal-departure-labels.json`, which is empty until the site owner approves entries (approval cutoff: 4 January 2027, a week before the GA rollover; the federal pages must be live before 2027-01-03, and they work without labels: the banner then says only that the member served in the 119th Congress).

Rules are the GA batches' (D6): only the fact and a date; "lost" and "did not run", never "retired", "ousted" or "unseated"; no label names the winner of a contest the member lost; vote figures stay in the evidence column; each label links the certified results page that sources it (the page prints "Certified results: ..." after the label).

Sources:
- the roster (`current-members.json`, 16 Georgia members at 2026-11-23);
- `races.json` (every 2026 federal race is `status: certified` with a recorded `winner`; GA-1, GA-11 and GA-10 carry "Open Seat" notes);
- the Secretary of State certified results in `_data/election_results/`: primary (2026-05-19, certified 2026-06-05), primary runoff (2026-06-16, certified 2026-08-20), special (2026-07-28), special runoff (2026-08-25, certified 2026-09-04), general (2026-11-03, certified 2026-11-20). Each results page is `status: certified`.

All 16 members of the delegation were checked against the 2026 ballots:

| Outcome | Members |
|---|---|
| On their own seat's November ballot and won (or not up: Warnock) | 12 |
| Not on their seat's November ballot (below) | 4 |

The 12 who return get no label and no former page: Allen, Bishop, Clyde, Fuller, Jack, Johnson, McBath, McCormick, Scott (A.), Williams, Ossoff and Warnock. Fuller (GA-14) won the April special runoff for Marjorie Taylor Greene's seat and the November general; he is sitting, not former.

## A. Not returning: 4 labels to approve

| bioguideId | Member | Seat | Draft label | Results page(s) linked | Evidence |
|---|---|---|---|---|---|
| C001103 | Earl L. "Buddy" Carter (R) | GA-1 | Ran for U.S. Senate in 2026 (lost the Republican primary on May 19, 2026). | `/ga-primary-results/` | Not on the GA-1 primary ballot (`races.json`: "Open Seat, Buddy Carter vacated to run for U.S. Senate"). US Senate Republican primary: 229,223 votes, 25.1% of 912,696, third of 5 |
| L000583 | Barry Loudermilk (R) | GA-11 | Did not run for re-election in 2026. | `/ga-primary-results/` | Absent from every contest in the certified primary and runoff files, for any office; `races.json` note: "did not file for re-election". **Not checked against the Secretary of State's federal qualifying export, which this repo does not hold** (batch 1 used the state-legislative one). If the owner downloads it, add the closing date as batch 1 did ("qualifying closed March 6, 2026") |
| C001129 | Mike Collins (R) | GA-10 | Ran for U.S. Senate in 2026 (lost the general election on November 3, 2026). | `/ga-general-2026-results/` | Won the Republican primary (369,642 votes, 40.5%) and the June 16 runoff (390,174 to 312,339); general: 1,713,673 votes, 41.0%, second of 2; margin 755,386 |
| B001328 | Everton "EJ" Blair (D) | GA-13 | Won the August 25, 2026 special election runoff to fill the remainder of the term. Ran for the full term in 2026 (lost the Democratic primary on May 19, 2026). | `/ga-special-2026-runoff-results/`, `/ga-primary-results/` | Special runoff: 9,895 votes, 53.9% of 18,342, first of 2 (certified 2026-09-04). Regular Democratic primary: 12,733 votes, 11.6% of 109,581, third of 6. No swearing-in date is claimed: none is in the repo |

## B. Held a seat this Congress, but cannot have a page yet (2)

Both left mid-term and are not in `current-members.json`, so there is no roster record to freeze and no sponsorship slice; only a vote slice exists (`federal-votes/G000596.json`, `S001157.json`). The freeze tool (`freeze_federal_congress.py`) freezes the sitting delegation, so these two get **no page** unless the owner wants one built from a hand-supplied record (see Decisions). Labels drafted so the facts are ready; **neither date is in the repo and neither is stated here**.

| bioguideId | Member | Seat | Draft label | Needs |
|---|---|---|---|---|
| G000596 | Marjorie Taylor Greene (R) | GA-14 | Resigned [date]. | The resignation date, from the Clerk of the House or Congress.gov (`races.json` says only that Fuller "won the April 2026 special election runoff to fill the seat vacated by" her) |
| S001157 | David Scott (D) | GA-13 | Died [date]. | The date, from Congress.gov or the Clerk (`ga-special-2026-results.html` says only that the special election fills the seat "left vacant by the death of Rep. David Scott") |

## Decisions for the owner

1. **Approve, edit or strike each label in A.** Approved entries go into `assets/data/federal-departure-labels.json` under `labels`, keyed by bioguideId, in this form (add each approved batch to `metadata.batches` and update `count`):
   ```json
   "C001129": {
     "name": "Mike Collins", "chamber": "House of Representatives", "district": 10,
     "type": "ran-for-other-office",
     "label": "Ran for U.S. Senate in 2026 (lost the general election on November 3, 2026).",
     "results": [{"title": "Georgia 2026 general election results", "url": "/ga-general-2026-results/"}],
     "sources": ["Georgia Secretary of State certified results (general 2026-11-03, certified 2026-11-20)"]
   }
   ```
   The page needs only `label` and `results` (a `title` and a site-relative `url` for each linked page); the other fields mirror `ga-departure-labels.json`.
2. **Loudermilk's "did not run":** accept on the primary-ballot evidence, or download the federal qualifying export first.
3. **Scott and Greene:** leave without pages (the default), or supply a roster record (name, party, terms, dates) so the freeze can include them. Their old URLs, if they ever had one, did not exist: the site only built pages for the sitting delegation, so nothing is promised.
4. **Blair's label carries two facts** (the special-runoff win and the primary loss), as Henderson's GA label carries two. Strike the second sentence if one fact is preferred.
