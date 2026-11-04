# Election-results source CSVs

Raw Georgia SoS "Total Votes Results" exports — the **build-time inputs** for the
results pages. They are **not** served: this directory sits under `_sources/`,
which Jekyll excludes from the published site (underscore-prefixed directories
are not copied to `_site`). Moved here from `assets/data/` where they were being
served publicly and where unofficial drafts sat next to certified files — see
CODEBASE-REVIEW-2026-08-18.md finding 5.7.

## What the site actually serves

`scripts/build_results_json.py` parses one of these CSVs into
`_data/election_results/<key>.json`, which the `election_results` layout renders.
The committed JSON is the served artifact; these CSVs only need to exist when
you (re)build it.

```
python scripts/build_results_json.py _sources/election_results/<file>.csv <data-key>
```

## Convention

- One certified file per election. Keep only the certified export — replace an
  unofficial draft wholesale once certified numbers exist (RECURRING-TASKS.md §1).
- Hyphenated, no spaces. Certified primary/statewide files carry an `-official`
  suffix.

| File | Election | Built into (`_data/election_results/`) |
|------|----------|----------------------------------------|
| `ga-primary-results-official.csv`       | May 19 2026 general primary        | `ga-primary-results.json` |
| `ga-primary-runoff-results.csv`         | Jun 16 2026 primary runoff         | `ga-primary-runoff-results.json` |
| `ga-special-2026-results-official.csv`  | Jul 28 2026 CD-13 special          | `ga-special-2026-results.json` |
| `ga-special-2026-runoff-results.csv`    | Aug 25 2026 CD-13 special runoff   | `ga-special-2026-runoff-results.json` |

## Election night

Use the **JSON feed**, which lives at a stable URL all night:

```
https://results.sos.ga.gov/cdn/results/Georgia/export-11032026GeneralAndSpecialElection.json
```

That is what the publish workflow can fetch on its own. The XLSX workbook the
results site offers is the same data, but its download name carries a fresh GUID
every time, so it can only be fetched by hand — three sheets, of which
`Total Votes` is the one parsed (the CSVs above are that sheet saved out by
hand). The builder reads all three forms, by content rather than file extension,
and prefers the feed's own `createdAt` for the page's "last updated" stamp.

The feed can be short a race: on the 11:17pm run it carried 273 contests against
the workbook's 274, missing District Attorney - Waycross Judicial Circuit. That
is why `fill_missing` stays on — the race keeps reading "Awaiting Results"
instead of disappearing.

Don't do it by hand. The **Publish election results** workflow
(`.github/workflows/publish-results.yml`) runs this whole sequence from the
Actions tab or the GitHub mobile app — fetch the export, rebuild, validate,
commit, deploy — and verifies the deploy started, which a push from a workflow
does not do on its own (see that file's header). Leave its `fill_missing` input
ON while results are unofficial: the data file is rebuilt wholesale, so an
export carrying only the contests that have reported would otherwise delete
every other race from the page instead of leaving it "Awaiting Results".

Unofficial exports are not committed here by default (`commit_csv: false`): a
200KB file rewritten every twenty minutes is churn, and the JSON it built is
the served artifact. Commit the certified export, once, with `commit_csv: true`.
