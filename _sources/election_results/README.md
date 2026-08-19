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
