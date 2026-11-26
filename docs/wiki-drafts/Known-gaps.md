What the data does not cover, and what is easy to misread. If you find something missing from this list, open an issue.

## State votes

- **Passage votes only.** Amendments, procedural motions and committee votes are not included, so `rollNumber` has gaps.
- **Check close votes against the official status.** Some failed votes are marked `"Pass"`. A Georgia bill needs a [majority of the chamber's total membership](https://www.georgiaencyclopedia.org/articles/government-politics/legislative-process-overview/) (91 in the House, 29 in the Senate), and a state constitutional amendment needs two-thirds (120 and 38). If an `HB`, `SB` or amendment vote marked `"Pass"` is below its number, check the measure on [legis.ga.gov](https://www.legis.ga.gov/). A low tally alone is not proof: a few such bills are officially recorded as passed.
- **Bundled calendars repeat.** One floor vote appears once per bill with identical tallies.
- **Use `chamber`, not the motion text.** "Agree to Senate Substitute" is a House vote.
- **Two votes on one bill in one day happen.** Use `rollNumber` and `time` to order them.
- **Older sessions hold less.** The 2017-2024 backfill has regular-session votes and a roster only.

## Rosters

- `data/all.json` includes members who have left during the General Assembly. Filter on `status`: `null` is sitting, `"Suspended"` still holds the seat.
- `status` is maintained by hand, because the legislature's service records who held a seat and not who left it.

## Districts and ZIP codes

- A ZIP lists every district it touches, and many touch more than one.
- ZIP shares are estimates.
- PO-box ZIPs carry no districts.

## Federal

- Voice votes and unanimous consent leave no roll call, so they are absent.
- An en bloc Senate vote covers a group of nominations. It does not show a view on any one nominee.
- `memberVotes` can include members who have left. In an election of the Speaker, `vote` is a person's name.
- `district` is `null` for Senators.

## Elections

- A race in `races.json` has no `winner` until certification has been recorded, and not every decided race has one. Judicial and district attorney races in particular may not; look for them in the [certified results](https://github.com/Votega/ga-races-elections#election-results).
- A candidate listed in an earlier phase may no longer be on the ballot. Check the race's `activePhase`.
- Only certified elections are in `results/`. Unofficial counts are on the [VoteGA results pages](https://www.votega.org/results/).
- `winner` and `outcome` in the results are derived by VoteGA from certified counts. In a primary, `winner` means the nominee.
- A blank vote count is not zero. In the 2026 general, the Waycross Judicial Circuit District Attorney contest is `not-reported`.
- Some counties report no vote-method split, so adding the method columns can fall short of `votes`.
- Results have no precinct breakdown.
- Early-voting files are refreshed by hand. Check `asOf`.
- Georgia voters don't register by party, so early-voting data cannot say which party's voters turned out.
- The 2022 early-voting comparison is limited because the state's source file is incomplete. See the [early-voting notes](https://github.com/Votega/ga-races-elections#early-voting-early-vote2026-general).

## Local government

- Coverage is partial: only some counties and cities are scanned. See `data/coverage.json`.
- A mention means a topic appeared on an agenda or in minutes. It does not mean the government approved or plans anything.
- Agendas are posted ahead of meetings, so some mentions are dated in the future.
- Excerpts are withheld for some sources.
- Officials' history is not backfilled. It starts at `metadata.historyStartsAt` in `officials-history.json`.
- Some fields, including term dates and contacts, are blank where no source gives them.

## Executive orders

- 2020 to present.
- `category` comes from title keywords and can be wrong.
- `issuedBy` is worked out from the date and each Governor's term, and is `null` until confirmed for a new Governor.

## Dates when "current" changes

| Date | What changes |
|---|---|
| 3 January 2027 | Federal `data/` becomes the 120th Congress |
| From 1 January 2027 (published 4 January) | Local officials elected in 2026 appear on the current board |
| 11 January 2027 | State `data/` and `latest.json` move to 2027-2028 |

Each repository's `CHANGES.md`, where present, has the details.
