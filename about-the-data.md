---
layout: page
title: About The Data
subtitle: Where our information comes from and how it's kept current
---

VoteGA.org is a static website — there is no server, no database, and no real-time API calls
from your browser. Instead, automated workflows run daily that pull data from trusted public sources,
and publish it as static files that power the site. Here's what we use and why.

---

## Federal Legislators

**Source:** [Congress.gov API](https://api.congress.gov/) (U.S. Library of Congress)

Congress.gov is the official legislative information system of the United States Congress,
maintained by the Library of Congress. Member data — including name, party, state, chamber,
district, term dates, and official photo — is pulled from the Congress.gov API daily.

- **Contact info:** The Congress.gov API does not provide member contact information (phone, office address). We link directly to each member's official House or Senate website where contact info is maintained by the member's office.
- **Freshness:** Updated daily via an automated GitHub Actions workflow.

---

## Georgia General Assembly Legislators

**Primary source:** [Open States API](https://openstates.org/) (Plural Policy)

Open States is a nonpartisan, nonprofit project that collects and standardizes legislative
data from all 50 U.S. states. Georgia member data — including name, party, chamber, district,
committee assignments, and official legislative page — is pulled from the Open States v3 API daily.

- **Legislative page URLs:** Constructed from `legis.ga.gov` using the member's official Georgia legislature ID, which is reliably maintained by the Georgia General Assembly.
- **Term start dates:** Not consistently available from Open States for Georgia. We maintain a manual override file to fill in known values.
- **Freshness:** Updated daily via an automated GitHub Actions workflow.

---

## GA Legislators — Community Data Repository

We publish a copy of our Georgia legislator data to a public community repository:

[GitHub GA Legislators Repository](https://github.com/Votega/ga-legislators)

This repository is updated automatically each time our daily workflow runs. It is intended as
a free, open, machine-readable source of current Georgia General Assembly member data that
anyone can use — civic apps, researchers, journalists, or other organizations that need
structured legislator data without the overhead of maintaining their own pipeline.

The data is published as `data/all.json` and follows the same schema that we use for votega.org. See the repository README for field definitions.

{: .box-note}
**Want to contribute?** If you spot missing or incorrect information — a wrong phone number,
a missing email address, or an outdated office — you can open an issue or pull request on
the [ga-legislators repository](https://github.com/Votega/ga-legislators). Corrections
submitted there are reviewed and incorporated into our manual overrides, so they flow back
into votega.org on the next daily update.

---

## Data Freshness

| Data | Source | Update Schedule |
|---|---|---|
| Federal Congress members | Congress.gov API | Daily, 06:00 UTC |
| Georgia state legislators | Open States API | Daily, 07:00 UTC |
| GA legislators community repo | Published from above | Daily, after GA member update |

---

## What We Don't Do

- **No real-time API calls from your browser.** All data is pre-fetched and served as static files. This fast page loads for you.
- **No tracking or analytics beyond standard page metrics.** We do not build profiles of visitors or sell data.

---

## Corrections and Feedback

See an error? Have a data question? Feature request? Reach out to us at [admin@votega.org](mailto:admin@votega.org)
or open an issue on [github.com/Votega/ga-legislators](https://github.com/Votega/ga-legislators)
for Georgia-specific data corrections.
