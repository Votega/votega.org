---
layout: page
title: About The Data
subtitle: Where our information comes from and how it's kept current
---

VoteGA.org is a static website. We run automated workflows daily that pull data from trusted public sources, and publish it as static files that power the site. The only exception is campaign finance data, which is pulled live when a visitor opens the page. Here's what we use and why.

---

## Federal Legislators

**Source:** [Congress.gov API](https://api.congress.gov/) (U.S. Library of Congress)

Congress.gov is the official legislative information system of the United States Congress,
maintained by the Library of Congress. Member data — including name, party, state, chamber,
district, term dates, and official photo — is pulled from the Congress.gov API daily.

- **Contact info:** We pull in contact information and link directly to each member's official House or Senate website where contact info is maintained by the member's office.
- **Freshness:** Updated daily via an automated GitHub Actions workflow.

---

## Federal Legislator Voting History (GA Delegation)

**Sources:** [Congress.gov API](https://api.congress.gov/) · [Clerk of the U.S. House](https://clerk.house.gov/) · [U.S. Senate](https://www.senate.gov/)

Voting history is displayed on each Georgia federal legislator's profile page, showing how they voted on every roll call tied to a bill that was signed into law during the current Congress (119th, 2025–2027).

**How it works:**

1. The Congress.gov API is queried for all public laws enacted during the current Congress.
2. For each enacted bill, we retrieve the associated roll call vote URLs from the bill's action history via the Congress.gov API.
3. Roll call XML files are fetched directly from the Clerk of the House (House votes) and Senate.gov (Senate votes) — these are the authoritative, official government sources.
4. Georgia delegation members are identified by their state attribute in the XML. House XML includes bioguide IDs directly; Senate XML uses LIS senator IDs, which are mapped to bioguide IDs via the [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) project.

- **Scope:** Only votes on bills that were signed into law. Votes on bills that failed, were vetoed, or are still pending are not included.
- **Coverage:** Georgia's 2 U.S. Senators and 14 U.S. Representatives.
- **Freshness:** Updated weekly via an automated GitHub Actions workflow.

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

## Georgia State Legislator Voting History

**Source:** [LegiScan](https://legiscan.com/) (bulk legislative dataset)

Voting history is displayed on each Georgia state legislator's profile page, showing how they voted on every roll call tied to a bill that was signed into law during the current General Assembly session.

**How it works:**

LegiScan aggregates and standardizes legislative data from all 50 states, including full roll call vote records for the Georgia General Assembly. We use LegiScan's bulk dataset — which includes bills, people, roll calls, and individual vote records — and process it locally to build the voting history file.

Georgia legislators are matched between the LegiScan dataset and our member data using their chamber and district (e.g., House District 137, Senate District 24). Member votes are then keyed to each legislator's unique Open States identifier so they can be looked up on their profile page.

- **Scope:** Only votes on bills that were signed into law (enacted). Votes on bills that failed or are still in committee are not included.
- **Coverage:** All current members of the Georgia House of Representatives and Georgia Senate.
- **Freshness:** Updated periodically when a new LegiScan dataset is published.

---

## GA Legislators — Community Data Repository

We publish a copy of our Georgia legislator data to a public community repository. **NOTE:** Only includes GA Legislators from the 158th (2025-2026) General Assembly. Future legislators will continue to be added, but prior year members will not be added in the immediate future. 

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

## GA Executive Orders — Community Data Repository

We publish Georgia Governor's executive orders to a public community repository:

[GitHub GA Executive Orders Repository](https://github.com/Votega/ga-executive-orders)

Executive orders are sourced from the [Georgia Governor's website](https://gov.georgia.gov/executive-action/executive-orders) and organized as one JSON file per year. Each order includes the date, order number, title, category, and a direct link to the official PDF.

**Coverage:** 2023–present. Earlier years (2022 and prior) used a different URL structure on gov.georgia.gov and are not yet included.

**Categories:** Orders are automatically classified by title keyword into one of seven categories — State of Emergency, Writ of Election, Suspension, Appointment, Authorization, Flag at Half-Staff, or Other.

**Schema:**
```json
{
  "date":     "2024-09-24",
  "number":   "09.24.24.01",
  "title":    "Declaring a State of Emergency for Tropical Storm Helene",
  "category": "State of Emergency",
  "url":      "https://gov.georgia.gov/document/2024-executive-order/09242401/download"
}
```

{: .box-note}
**Want to contribute?** If an order is missing or miscategorized, open an issue or pull request on the [ga-executive-orders repository](https://github.com/Votega/ga-executive-orders).

---

## 2026 Election Races & Candidates

**Sources:** [Georgia Secretary of State](https://sos.ga.gov/) · Manual curation

Race and candidate information for the 2026 election cycle is maintained in a curated data file (`races.json`) that powers the race pages and candidate profiles on this site.

**Georgia state legislative candidates** (GA House and Senate) are sourced from the Georgia Secretary of State's candidate filing system, which publishes official candidate registration data for each primary and general election. We process that data to build one race entry per district, including candidate names, party affiliation, occupation, and county of residence.

**Federal candidates** (U.S. House and Senate) are manually researched and entered. Incumbents are linked directly to their Congress.gov member record so their photo, party, and legislative history populate automatically. Challengers' bios, photos, and websites are sourced from candidates' official campaign websites and entered manually.

**Incumbent enrichment:** When a candidate is the current officeholder, their profile photo and member record link are automatically pulled from our existing legislator data (Congress.gov for federal, Open States for state) — no duplicate data entry required.

- **Scope:** 2026 primary and general election races for Georgia's federal delegation and all 236 Georgia General Assembly districts.
- **Freshness:** GA legislative candidate data is updated when the Secretary of State publishes new filing data. Federal challenger data is manually maintained.

---

## Campaign Finance

**Sources:** [Federal Election Commission (FEC)](https://www.fec.gov/) · [Georgia Government Transparency & Campaign Finance Commission](https://ethics.ga.gov/)

Campaign finance figures — total raised, total spent, and cash on hand — are displayed on each candidate profile page.

- **Federal candidates** (U.S. House and Senate): Data is fetched live from the [FEC API](https://api.open.fec.gov/) when you visit a candidate's page. The FEC is the authoritative source for federal campaign finance disclosures. Figures reflect the candidate's most recent filing and are updated as new reports are submitted to the FEC.
- **Georgia state candidates** (GA House, Senate, and statewide offices): Georgia campaign finance filings are managed by the Georgia Government Transparency & Campaign Finance Commission. We link directly to their search portal since no public API is available.

- **Coverage:** 2026 election cycle.
- **Freshness:** Federal figures are live — pulled from FEC at page load time. State figures link to the Georgia Ethics Commission search.

---

## Data Freshness

| Data | Source | Update Schedule |
|---|---|---|
| Federal Congress members | Congress.gov API | Daily, 06:00 UTC |
| Georgia state legislators | Open States API | Daily, 07:00 UTC |
| GA legislators community repo | Published from above | Daily, after GA member update |
| Federal legislator voting history | Congress.gov API + Clerk/Senate XML | Weekly, Sundays 09:00 UTC |
| GA state legislator voting history | LegiScan bulk dataset | Periodically, when new dataset is available |
| GA executive orders | gov.georgia.gov | Manually maintained |
| 2026 GA legislative candidates | GA Secretary of State | Updated when SOS publishes new filing data |
| 2026 federal race/candidate data | Manual curation | Manually maintained |
| Federal campaign finance | FEC API (live) | Real-time, fetched on page load |

---

## What We Don't Do

- **No tracking or analytics beyond standard page metrics.** We do not build profiles of visitors or sell data.

---

## Corrections and Feedback

See an error? Have a data question? Feature request? Reach out to us at [admin@votega.org](mailto:admin@votega.org)
or open an issue on [github.com/Votega/ga-legislators](https://github.com/Votega/ga-legislators)
for Georgia legislator corrections. 
Or [github.com/Votega/ga-executive-orders](https://github.com/Votega/ga-executive-orders) for executive order corrections.
