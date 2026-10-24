# Early-vote page inputs

Inputs for `scripts/generate_ga_early_vote.py`, which writes `_data/early_vote/ga-general-2026.json` for
[/ga-early-vote/](https://www.votega.org/ga-early-vote/). The Secretary of State's site is behind a bot
challenge, so every download is manual, in a browser. This folder keeps the small aggregates so a refresh does
not mean re-finding them.

What every field in the SoS files means, and the traps in them, is in [DATA-DICTIONARY.md](DATA-DICTIONARY.md).

## In this folder (committed)

| File | What it is | Replace when |
|---|---|---|
| `registration-YYYY-MM-DD.csv` | Active and total registered voters by county (SoS "active/inactive" table, as a CSV) | each refresh: download a fresh table and re-distill |
| `results-2022.json` | 2022 general, Governor: county totals by voting method + county winner | never (certified) |
| `results-2024.json` | 2024 general, President: same | never (certified) |

The county Census context (citizen adults, bachelor's share) is separate: `scripts/data/ga-county-context.json`,
from `scripts/build_ga_county_context.py`. Rebuild it when a new ACS 5-year vintage appears.

## NOT in the repo, never commit

The absentee and voter history files are **voter-level** (names, addresses). Keep them in a local folder outside
the repository and unzip each one into its own directory.

| Download | Used for | Changes? |
|---|---|---|
| Current absentee file (this cycle: `A-12601-1-VoterAbsentee`) | this year's ballots by county and day | every refresh: it runs through the previous day |
| 2022 absentee file (`A-12054`) | 2022 daily pace and per-county counts | no. **Incomplete**: Fulton and Gwinnett stop after 2022-10-22. The SoS has no other download for it (single-county downloads return the same truncated file), so 2022 is compared at 17 days out |
| 2022 voter history (`A-12054`, the history CSV) | 2022 repeat-voter figure | no. Complete for Fulton and Gwinnett (within 0.2% of official) |
| 2024 absentee file (`A-12311`) | 2024 daily pace, per-county counts and repeat-voter figure | no |

## Refresh

1. Download the newest absentee file and the active/inactive table.
2. Re-distill the registration table (past results do not change):

   ```bash
   python scripts/distill_early_vote_inputs.py registration <active-inactive>.xlsx --date YYYY-MM-DD
   ```

3. Run the generator, with `<LOCAL>` the folder holding the unzipped voter-level files:

   ```bash
   python scripts/generate_ga_early_vote.py \
     --absentee <LOCAL>/A-12601-1-VoterAbsentee --election-date 2026-11-03 \
     --registration scripts/data/early-vote/registration-YYYY-MM-DD.csv \
     --prior 2022=<LOCAL>/A-12054-absentee:2022-11-08 --prior 2024=<LOCAL>/A-12311-absentee:2024-11-05 \
     --prior-last-good 2022=2022-10-22 \
     --prior-history 2022=<LOCAL>/A-12054-history/A-12054.csv \
     --prior-json 2022=scripts/data/early-vote/results-2022.json \
     --prior-json 2024=scripts/data/early-vote/results-2024.json \
     --prior-active 2022=6961501 --prior-active 2024=7267985
   ```

   `--prior-active` is the statewide active-voter count on each past election day, from the SoS turnout
   dashboard (the Data Hub for that election). It does not change.

4. Read the warnings it prints (they are also kept in the output's `metadata.quality`). The expected ones are the
   2022 Fulton/Gwinnett shortfall, a handful of accepted ballots with a bad return date, and merged repeat records.
   Any error stops the run without writing.
5. Check the page locally, then commit `_data/early_vote/ga-general-2026.json` (and the new registration CSV).

## After election night

The SoS posts a results export for the current election once counting begins (before that it is all zeros).
Distill it the same way as 2022 and 2024 (`results ... --year 2026 --election-date 2026-11-03`) and add it as another
`--prior-json` once the 2026 election becomes a "past year" for a later cycle.

## Credits

County Census figures: U.S. Census Bureau, American Community Survey, compiled by Georgia Civic Data
(georgiacivicdata.org), CC BY 4.0. Election results and voter files: Georgia Secretary of State.
