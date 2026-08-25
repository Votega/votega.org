1. Votega/.github/profile/README.md (org landing page)
markdown
# VoteGA

**Nonpartisan civic information for Georgia voters.** → [votega.org](https://www.votega.org)

VoteGA publishes accessible, accurate information about Georgia elections, elected
officials, legislation, and executive action — and releases the underlying data as
free, machine-readable, openly licensed files that anyone can use.

No party affiliation. No endorsements. No visitor profiling or data sales.

---

## Open data repositories

These are updated automatically by scheduled workflows. Use them directly — no key,
no signup, no rate limit.

| Repository | Contents | Format | Updated |
|---|---|---|---|
| [ga-legislators](https://github.com/Votega/ga-legislators) | Current GA House & Senate members (158th General Assembly) — name, party, district, committees, contact, official page | `data/all.json` | Daily |
| [ga-federal-legislators](https://github.com/Votega/ga-federal-legislators) | Georgia's 2 U.S. Senators and 14 U.S. Representatives | JSON | Weekly |
| [ga-legislation](https://github.com/Votega/ga-legislation) | GA General Assembly bills, 2025–26 session (adapted from Open States) | JSON | Daily |
| [ga-executive-orders](https://github.com/Votega/ga-executive-orders) | Georgia Governor's executive orders, 2023–present — date, number, title, category, PDF link | One JSON file per year | On publication |
| [ga-races-elections](https://github.com/Votega/ga-races-elections) | 2026 Georgia races and candidates | JSON | As SOS publishes |

**Sources:** [Open States](https://openstates.org/) (Plural Policy) · [Congress.gov](https://api.congress.gov/) ·
[Federal Register](https://www.federalregister.gov/developers/api/v1) · [FEC](https://api.open.fec.gov/) ·
[Oyez](https://api.oyez.org/) · [gov.georgia.gov](https://gov.georgia.gov/) · [Georgia Secretary of State](https://sos.ga.gov/)

Full methodology and update schedules: [votega.org/about-the-data](https://www.votega.org/about-the-data)

---

## Quick start

```bash
# Every current Georgia state legislator
curl -s https://raw.githubusercontent.com/Votega/ga-legislators/main/data/all.json

# Georgia executive orders signed in 2026
curl -s https://raw.githubusercontent.com/Votega/ga-executive-orders/main/data/2026.json
```

```python
import urllib.request, json

URL = "https://raw.githubusercontent.com/Votega/ga-legislators/main/data/all.json"
members = json.load(urllib.request.urlopen(URL))["members"]

senate = [m for m in members if m["chamber"] == "Senate"]
print(f"{len(senate)} Georgia state senators")
```

---

## Who this is for

- **Civic app developers** — structured GA data without building or maintaining a pipeline
- **Journalists** — a current, citable roster and bill list you can join against your own data
- **Researchers** — daily snapshots with a stable schema and full commit history
- **Anyone** — attribution appreciated, not required beyond the license terms

## Contributing

Spot a wrong district, a stale phone number, a missing email? Open an issue or PR on the
relevant repo. Accepted corrections flow into our override files and appear on votega.org
on the next scheduled run.

We accept: data corrections, schema suggestions, bug reports, new source ideas.
We don't accept: partisan framing, endorsements, or advocacy content.

## Contact

[admin@votega.org](mailto:admin@votega.org)
2. Votega/votega.org/README.md (site repo)
markdown
# votega.org

Source for [votega.org](https://www.votega.org) — a nonpartisan civic information site
for Georgia voters. Static Jekyll site on GitHub Pages, with all data prebuilt by
scheduled GitHub Actions workflows.

[![Site](https://img.shields.io/website?url=https%3A%2F%2Fwww.votega.org)](https://www.votega.org)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

## What's here

- **Find my reps** — federal and state legislator lookup with profiles, committees, and voting history
- **2026 elections** — races, candidates, and campaign finance for Georgia state and federal contests
- **Legislation** — GA General Assembly bill tracking (2025–26 session)
- **Executive & judicial** — federal executive orders, cabinet, signed legislation, Supreme Court decisions
- **Flock / ALPR** — records and coverage of automated license plate readers in Georgia

Data sources, methodology, and update schedules: [about-the-data](https://www.votega.org/about-the-data)

## Architecture

_data/ Jekyll site data
_layouts/ Page templates (Beautiful Jekyll)
_posts/ Analysis and election results posts
assets/
data/ Generated JSON consumed by page scripts
scripts/ Client-side JS
img/, docs/ Images, PDFs
scripts/ Build-time Python generators (run by Actions)
.github/workflows/ Scheduled data pipelines


**Design rule:** no API keys ever reach the browser. Every keyed source is fetched
server-side by a scheduled workflow, written to `assets/data/*.json`, and committed
back to the repo. Pages read the static JSON. Keyless public APIs
(Federal Register, FEC, Oyez) are the only things fetched live at page load.

## Data pipeline

| Workflow | Generates | Schedule |
|---|---|---|
| `update-current-members.yml` | Federal Congress members | Daily 06:00 UTC |
| `update-ga-members.yml` | GA state legislators | Daily 07:00 UTC |
| `update-ga-votes.yml` | GA passage votes | Weekly, Sun 08:00 UTC |
| `update-federal-votes.yml` | Federal roll call votes | Weekly, Sun 09:00 UTC |
| `update-scotus.yml` | SCOTUS decisions | Weekly, Sun 10:00 UTC |

Several of these also publish to the public
[community data repos](https://github.com/Votega) so the data is usable outside this site.

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
python3 scripts/generate_current_members_data.py
python3 scripts/generate_ga_members_data.py
```

Keys live in repo secrets and are never committed.

## Contributing

Data corrections are the most valuable contribution — open an issue with the source
you're citing. Please file legislator/bill/EO corrections on the relevant
[community repo](https://github.com/Votega) rather than here, so the fix flows into
both the data feed and the site.

**Editorial standard:** VoteGA is nonpartisan. Contributions must be sourced to official
records and free of advocacy framing.

## License

Site code: MIT. Published datasets are licensed in their own repositories.
Underlying data remains subject to the terms of its original sources.

## Contact

[admin@votega.org](mailto:admin@votega.org)