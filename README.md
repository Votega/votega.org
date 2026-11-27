# VoteGA

**Nonpartisan civic information for Georgia voters.** → [votega.org](https://www.votega.org)

VoteGA publishes accessible, accurate information about Georgia elections, elected
officials, legislation, and executive action — and releases the underlying data as
free, machine-readable, openly licensed files that anyone can use.

No party affiliation. No endorsements. No visitor profiling or data sales. VoteGA is nonpartisan. Contributions must be sourced to official
records and free of advocacy framing.

---

## Open data repositories

These are updated automatically by scheduled workflows. Use them directly: no key, no signup.

Every repository has JSON, a CSV for spreadsheets and a JSON Schema.

| Repository | Contents | Start with | Updated |
|---|---|---|---|
| [ga-legislators](https://github.com/Votega/ga-legislators) | Georgia General Assembly members: the current roster (name, party, district, committees, contact, official page), each session's passage votes, and a derived voting scorecard (party unity and participation). Earlier General Assemblies back to 2017 | `latest.json`, `data/all.json` | Roster daily · votes and scorecard weekly |
| [ga-federal-legislators](https://github.com/Votega/ga-federal-legislators) | Georgia's U.S. Senators and Representatives and every roll call of the current Congress, with a frozen record of each finished Congress | `data/members.json`, `data/votes.json` | Roster daily · votes weekly |
| [ga-legislation](https://github.com/Votega/ga-legislation) | Georgia General Assembly bills and resolutions by session, and every statewide ballot measure | `latest.json`, `ga-ballot-measures.json` | Bills daily during the session (Jan–Apr), weekly otherwise · ballot measures as they change |
| [ga-executive-orders](https://github.com/Votega/ga-executive-orders) | The Governor's executive orders since 2020: date, number, title, category, issuing Governor and PDF link | `data/executive-orders.csv`, `data/<year>.json` | Twice daily |
| [ga-races-elections](https://github.com/Votega/ga-races-elections) | Georgia races and candidates, one folder per election cycle; certified election results; and early-voting turnout by county | `data/races/manifest.json`, `data/results/manifest.json` | Races daily · results after certification · early voting during each voting period |
| [ga-local-government](https://github.com/Votega/ga-local-government) | What Georgia county and city governments discuss on their published agendas and minutes (license-plate readers, data centers, land use, local taxes), classified by keyword with the source document for every mention; current boards and term history of local officials; millage rates | `latest.json` | Twice weekly · millage monthly |
| [ga-district-information](https://github.com/Votega/ga-district-information) | ZIP code, county and census-tract crosswalks to state Senate, state House and U.S. House districts | `data/zips.json`, `data/county-districts.csv` | Monthly |

Each repository's README says which paths are permanent (`sessions/…` and the per-cycle folders) and which are rewritten in place when officeholders turn over (`data/`, `latest.json`). Changes a consumer may need to act on are listed in its `CHANGES.md`, where it has one.

**Sources:** [Georgia General Assembly / legis.ga.gov](https://www.legis.ga.gov/) (GA legislator roster, bills &amp; roll-call votes) · [Open States](https://openstates.org/) (Plural Policy — OCD person IDs in the ID crosswalk, and bill subject tags) · [Congress.gov](https://api.congress.gov/) ·
[Federal Register](https://www.federalregister.gov/developers/api/v1) · [FEC](https://api.open.fec.gov/) ·
[Oyez](https://api.oyez.org/) · [gov.georgia.gov](https://gov.georgia.gov/) · [Georgia Secretary of State](https://sos.ga.gov/) ·
Georgia county & municipal governments (published agendas & minutes)

**Several repositories carry more than one dataset,** each on its own refresh
schedule. Every dataset describes itself in `data/<dataset>/manifest.json`, so
listing `data/*/manifest.json` tells you what a repository holds:

```bash
# What datasets does ga-local-government carry, and how fresh is each?
curl -s https://api.github.com/repos/Votega/ga-local-government/contents/data \
  | python3 -c 'import json,sys; print(*[d["name"] for d in json.load(sys.stdin) if d["type"]=="dir"], sep="\n")'

# One dataset's manifest: files, row count, source, licence, and BOTH timestamps
curl -s https://raw.githubusercontent.com/Votega/ga-local-government/main/data/millage/manifest.json
```

A manifest's `generatedAt` is when the **data** was produced — not when we last
mirrored it, which the repository's own git history already records. A yearly
dataset sitting beside a twice-weekly one is not as fresh as whichever job ran
last, and no single repository-wide timestamp could say so. Manifests carry no
wall-clock time, so an unchanged dataset republishes byte-for-byte identically
instead of adding a commit that says nothing changed.

Full methodology and update schedules: [votega.org/about-the-data](https://www.votega.org/about-the-data)

---

## Quick start

```bash
# Every current Georgia state legislator
curl -s https://raw.githubusercontent.com/Votega/ga-legislators/main/data/all.json

# The current General Assembly's voting scorecard: where its files are
curl -s https://raw.githubusercontent.com/Votega/ga-legislators/main/scorecard-latest.json

# Every Georgia executive order since 2020, one row each (CSV)
curl -s https://raw.githubusercontent.com/Votega/ga-executive-orders/main/data/executive-orders.csv
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

Data corrections are the most valuable contribution — open an issue with the source
you're citing. 

# votega.org

Static Jekyll site on GitHub Pages, with all data prebuilt by
scheduled GitHub Actions workflows.

[![Site](https://img.shields.io/website?url=https%3A%2F%2Fwww.votega.org)](https://www.votega.org)
[![Code: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/code-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)
[![Data: CC BY-SA 4.0](https://img.shields.io/badge/data-CC%20BY--SA%204.0-lightgrey)](https://creativecommons.org/licenses/by-sa/4.0/)

## What's here

- **Find my reps** — federal and state legislator lookup with profiles, committees, and voting history
- **Elections** — races, candidates, and campaign finance for Georgia state and federal contests
- **Legislation** — GA General Assembly bill tracking for the current General Assembly
- **Executive & judicial** — federal executive orders, cabinet, signed legislation, Supreme Court decisions
- **Flock / ALPR** — records and coverage of automated license plate readers in Georgia

Data sources, methodology, and update schedules: [about-the-data](https://www.votega.org/about-the-data)

## Architecture

```
_data/               Jekyll site data
_layouts/            Page templates (Beautiful Jekyll)
_posts/              Analysis and election results posts
assets/
  data/              Generated JSON consumed by page scripts
  scripts/           Client-side JS
  img/, docs/        Images, PDFs
scripts/             Build-time Python generators (run by Actions)
.github/workflows/   Scheduled data pipelines
```

## Data pipeline

| Workflow | Generates | Schedule |
|---|---|---|
| `update-current-members.yml` | Federal Congress members | Daily 06:00 UTC |
| `update-ga-members.yml` | GA state legislators | Daily 07:00 UTC |
| `update-ga-bills.yml` | GA bills | Daily 05:30 UTC January–April; weekly, Sun 07:30 UTC, May–December |
| `update-ga-votes.yml` | GA passage votes | Weekly, Mon 07:30 UTC |
| `update-federal-votes.yml` | Federal roll call votes | Weekly, Sun 09:00 UTC |
| `update-scotus-decisions.yml` | SCOTUS decisions | Weekly, Sun 10:00 UTC |

These are the main ones; every workflow is in `.github/workflows/`, and a failed scheduled run opens an issue (`notify-workflow-failure.yml`). Several of these also publish to the public
[community data repos](https://github.com/Votega) so the data is usable outside this site.

## License

Site code: [PolyForm Noncommercial 1.0.0](LICENSE). Published datasets: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — attribute VoteGA and license any adaptations you distribute under the same terms (see each repository's `LICENSE`).
Underlying data remains subject to the terms of its original sources.

## Contact

[admin@votega.org](mailto:admin@votega.org)
