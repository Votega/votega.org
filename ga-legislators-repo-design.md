# `ga-legislators` — Repo Design

A machine-readable, publicly available dataset of Georgia General Assembly members,
published and maintained by votega.org. Intended as a civic resource others can freely consume.

---

## Goals

- Publicly available, versioned JSON of current GA House and Senate member data
- Always reflects what is live on votega.org — never a source of risk to the site
- Open license so journalists, researchers, and other civic apps can use it freely
- Accepts community-reported corrections via Issues, reviewed and applied upstream before publishing

---

## Data Flow

```
Open States API
      ↓
votega.org GitHub Actions workflow
      ↓  generates + validates
assets/data/ga-members.json  ──→  votega.org (live site)
      ↓  also pushes
ga-legislators/data/all.json  ──→  community consumers
      ↑
  Issues / PRs from community
  (reviewed by maintainer, corrections applied upstream in votega.org)
```

**votega.org is the source of truth.** ga-legislators is a downstream read replica.
Community corrections never touch votega.org directly — they are reviewed, applied
upstream in the votega.org generator or override file, and flow out on the next publish.

---

## Repo Structure

```
ga-legislators/
├── README.md                        # What this is, how to use the data, how to report corrections
├── LICENSE                          # CC0 (public domain — maximally reusable)
│
├── data/
│   ├── all.json                     # Full dataset — published by votega.org workflow
│   ├── house.json                   # House members only (split from all.json for convenience)
│   └── senate.json                  # Senate members only
│
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   └── correction.md            # Structured template for reporting data errors
│   └── workflows/
│       └── split.yml                # On push to main: splits all.json → house.json + senate.json
```

No `seed.py`, `build.py`, or editable source files — the data comes from votega.org,
not from scripts inside this repo.

---

## Member Schema

Each record in `all.json` follows this shape, matching the `ga-members.json`
schema used by votega.org.

```json
{
  "id":               "ocd-person/938f2479-c51f-446a-87f0-76d4f07c61e5",
  "name":             "Akbar Ali",
  "firstName":        "Akbar",
  "lastName":         "Ali",
  "party":            "Democratic",
  "chamber":          "House of Representatives",
  "district":         106,
  "title":            "Representative",
  "phone":            "404-656-0116",
  "address":          "Room 409-E, Coverdell Legislative Office Building, Atlanta, GA 30334",
  "email":            "akbar.ali@house.ga.gov",
  "officialWebsiteUrl": "https://www.legis.ga.gov/members/house/5089",
  "imageUrl":         "https://www.legis.ga.gov/api/images/default-source/portraits/ali-akbar-5089.jpg",
  "birthDate":        "2003-01-29",
  "birthYear":        2003,
  "termStart":        "2025-01-13",
  "termStartYear":    2025
}
```

### Field notes

| Field | Notes |
|---|---|
| `id` | Open Civic Data ID from Open States — primary key |
| `chamber` | `"House of Representatives"` or `"Senate"` |
| `officialWebsiteUrl` | Constructed from `extras.georgia_id` via Open States |
| `email` | From Open States top-level email field |
| `termStart` / `termStartYear` | From `current_role.start_date` in Open States; null if not available |

---

## How votega.org Publishes It

The existing `update-ga-members.yml` workflow gains one step after generating
and committing `ga-members.json`:

```yaml
- name: Publish to ga-legislators repo
  uses: dmnemec/copy_file_to_another_repo_action@main  # or equivalent
  with:
    source_file: assets/data/ga-members.json
    destination_repo: Votega/ga-legislators
    destination_folder: data
    destination_branch: main
    user_email: actions@github.com
    user_name: votega-bot
    commit_message: "Publish GA member data from votega.org"
```

No changes to `ga.js`, `ga-member.html`, or anything else on the votega.org side.
The ga-legislators repo has no influence over what votega.org serves.

---

## Community Contributions

Community members report corrections by opening an Issue using the correction template,
which captures: member name, field(s) in error, correct value, and source.

The maintainer reviews the report, applies the fix upstream in votega.org
(either in the Open States generator or a manual overrides file), and the
corrected data flows to ga-legislators on the next workflow run.

PRs that modify `all.json`, `house.json`, or `senate.json` directly are **not accepted** —
a note in the README and PR template explains why and directs contributors to Issues instead.

---

## CI Workflows

### `split.yml` (runs on push to main)
Splits `all.json` into `house.json` and `senate.json` for consumers who only
want one chamber. Lightweight — no validation needed since data comes from
the trusted votega.org workflow.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Community submits a PR with bad data | PRs to data files are rejected by policy; corrections go through Issues only |
| votega.org workflow fails — ga-legislators gets stale | `all.json` carries a `metadata.generatedAt` timestamp; consumers can check freshness |
| ga-legislators repo goes unmaintained | CC0 license means anyone can fork and self-host; consumers can switch to the votega.org raw URL directly |
| Open States data is wrong | Community reports via Issue → maintainer fixes upstream → flows out on next publish |

---

## License Decision

**Recommended: CC0 (public domain dedication)**

Means anyone can use the data without attribution or restriction — maximally useful for
civic apps, journalism, and research. The tradeoff is you can't require attribution, but
for a civic dataset that's usually the right call.

Alternative: **CC-BY 4.0** if you want attribution required.
