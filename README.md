# votega.org

Source for [votega.org](https://www.votega.org) — a nonpartisan civic information site
for Georgia voters. Static Jekyll site on GitHub Pages, with all data prebuilt by
scheduled GitHub Actions workflows.

[![Site](https://img.shields.io/website?url=https%3A%2F%2Fwww.votega.org)](https://www.votega.org)
[![Update Congress.gov current members data](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml)
[![Update Georgia General Assembly member data](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

## What's here

- **Find my reps** — federal and Georgia state legislator lookup with profiles, committees, and voting history
- **2026 elections** — races, candidates, campaign finance, ballot measures, the voter access/election calendar, and primary & runoff results
- **GA Legislation** — bill & resolution tracker for the 2025–26 General Assembly session, plus a majority-vote tracker
- **Executive & judicial** — federal executive branch (President/VP/Cabinet), federal executive orders, signed legislation, VP tie-breaking votes, Georgia executive orders, and Supreme Court justices/decisions
- **Congressional stock trades** — STOCK Act disclosures for Georgia's federal delegation
- **Flock / ALPR** — records and coverage of automated license plate readers in Georgia

Data sources, methodology, and update schedules for all of the above: [about-the-data](https://www.votega.org/about-the-data)

## Architecture

```
_data/           Jekyll site data
_layouts/        Page templates (Beautiful Jekyll)
_posts/          Analysis and election-results posts
tools/           Standalone admin pages for editing override files and candidate profiles (most are gitignored, local-only)
assets/
  data/          Generated JSON consumed by page scripts
  scripts/       Client-side JS
  img/, docs/    Images, PDFs
scripts/         Build-time Python generators (run by Actions)
.github/workflows/   Scheduled data pipelines
```

**Design rule:** no API keys ever reach the browser. Every keyed source is fetched
server-side by a scheduled workflow, written to `assets/data/*.json`, and committed
back to the repo. Pages read the static JSON. Keyless public APIs
(Federal Register, FEC, Oyez, CourtListener) are the only ones fetched live at page load.

## Data pipeline

Around twenty scheduled workflows in `.github/workflows/` keep `assets/data/*.json`
current — federal and GA legislators, voting history, GA bills, executive orders
(federal and GA), SCOTUS decisions, VP tie-breaking votes, signed legislation, FEC
figures, and congressional stock trades. Full source-by-source detail and the exact
cadence for each: [about-the-data → Data Freshness](https://www.votega.org/about-the-data#data-freshness).

Several of these also publish to public community repos so the data is usable outside this site:

| Repo | Contents |
|---|---|
| [ga-legislators](https://github.com/Votega/ga-legislators) | GA General Assembly roster + voting record |
| [ga-federal-legislators](https://github.com/Votega/ga-federal-legislators) | GA's federal delegation + voting record |
| [ga-executive-orders](https://github.com/Votega/ga-executive-orders) | GA Governor's executive orders, 2023–present |
| [ga-legislation](https://github.com/Votega/ga-legislation) | GA bills & resolutions, 2025–26 session |
| [ga-races-elections](https://github.com/Votega/ga-races-elections) | 2026 race and candidate data |

## Local development

```bash
bundle install
bundle exec jekyll serve
# → http://localhost:4000
```

To regenerate data locally (optional — generated JSON is committed):

```bash
export CONGRESS_API_KEY=...   # api.congress.gov
export OPENSTATES_API_KEY=... # openstates.org
python3 scripts/generate_current_members_data.py assets/data/current-members.json
python3 scripts/generate_ga_members_data.py assets/data/ga-members.json
```

Keys live in repo secrets and are never committed.

## Contributing

Data corrections are the most valuable contribution — open an issue with the source
you're citing. Please file legislator/bill/executive-order corrections on the relevant
[community repo](#data-pipeline) above rather than here, so the fix flows into
both the data feed and the site.

**Editorial standard:** VoteGA is nonpartisan. Contributions must be sourced to official
records and free of advocacy framing.

## License

Site code: MIT. Published datasets are licensed in their own repositories.
Underlying data remains subject to the terms of its original sources.

## Contact

[admin@votega.org](mailto:admin@votega.org)
