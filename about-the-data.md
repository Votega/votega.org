---
layout: page
title: About The Data
subtitle: Where our information comes from and how it's kept current
---

VoteGA.org is a static website. We run automated workflows that pull data from trusted public sources and publish it as static files that power the site. A few data sources, federal executive orders and select biography data, are fetched live from public APIs when you visit a page. Here's what we use and why.

{: .box-note}
**Looking to _reuse_ our data?** Our machine-readable datasets are open for anyone to use and are catalogued on the **[Open Data](https://www.votega.org/open-data)** page.

**Federal legislator** (U.S. House & Senate) data comes from the Congress.gov API. **Georgia legislator** (General Assembly) data comes from the Open States API. 

Each source covers only its own level of government.

---
## Federal Legislators

**Source:** [Congress.gov API](https://api.congress.gov/) (U.S. Library of Congress)

Congress.gov is the official legislative information system of the United States Congress,
maintained by the Library of Congress. Member data including: name, party, state, chamber,
district, term dates, and official photo is pulled.

- **Contact info:** We pull in contact information and link directly to each member's official House or Senate website where contact info is maintained by the member's office.
- **Freshness:** Fetched daily

---

## Federal Legislator Voting History, GA Delegation only

**Sources:** [Congress.gov API](https://api.congress.gov/), [Clerk of the U.S. House](https://clerk.house.gov/), [U.S. Senate](https://www.senate.gov/)

Voting history is displayed on each Georgia federal legislator's profile page, showing how they voted on every roll call tied to a bill that was <u>signed into law</u> during the current Congress (119th, 2025–2027).

**How it works:**

1. The Congress.gov API is queried for all public laws enacted during the current Congress.
2. For each enacted bill, we pull the associated roll call vote URLs from the bill's action history via the Congress.gov API.
3. Roll call XML files are fetched directly from the Clerk of the House (House votes) and Senate.gov (Senate votes). These are the  official government sources.
4. Georgia delegation members are identified by their state attribute in the XML. House XML includes an ID (bioguide) directly. Senate XML uses LIS Senator IDs, which are mapped to bioguide IDs via the [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) project.

- **Scope:** Only votes on bills that were <u>signed into law</u>. Votes on bills that failed, were vetoed, or are still pending are not included.
- **Coverage:** Georgia's 2 U.S. Senators and 14 U.S. House Representatives.
- **Freshness:** Fetched weekly

---

## [GA Federal Delegation — Published for Reuse](https://github.com/Votega/ga-federal-legislators)

Georgia's federal delegation roster `data/members.json`, is filtered from the full U.S. Congress to only include Georgia's delegation. 

`current-members.json` and the GA members voting records on signed legislation - `data/votes.json` - are published as an open, machine-readable dataset. 

See **[Open Data](https://www.votega.org/open-data)** for the repository, file links, and update schedule.

---

## Georgia General Assembly Legislators

**Primary source:** [Open States API](https://openstates.org/) (Plural Policy)

Open States is a nonpartisan, nonprofit project that collects and standardizes legislative data from all 50 U.S. states. Georgia member data including: name, party, chamber, district, committee assignments, and official legislative page is pulled from the Open States API (v3) daily.

- **Legislative page URLs:** Constructed from `legis.ga.gov` using the member's official Georgia legislature ID, which is reliably maintained by the Georgia General Assembly.
- **Term start dates:** Not consistently available from Open States for Georgia. We maintain a manual override file to fill in known values.
- **Freshness:** Fetched daily

---

## Georgia State Legislator Voting History

**Source:** [Open States API](https://openstates.org/) (Plural Policy)

Voting history is displayed on each Georgia state legislator's profile page, showing how they voted on passage votes during the current General Assembly session (2025–2026).

**How it works:**

We leverage the Open States API and scrape all Georgia bills in the current session, collecting vote events where the motion was passed (classification is `passage` basically the final up-or-down votes on a bill). For each passage vote, individual member votes are recorded using each legislator's Open States identifier. This is the same identifier used throughout our member data, so no name matching or bridging is required.

- **Scope:** Passage votes only (final floor votes on a bill). Procedural motions, amendments, and committee votes are not included.
- **Coverage:** All current members of the Georgia House of Representatives and Georgia Senate.
- **Freshness:** Fetched weekly

**Voting participation:** Each profile also shows a voting participation figure, the share of recorded passage-vote roll calls in the member's chamber on which they cast a "Yea" or "Nay". 

If a member was non-voting, abstained, absent, excused, or had a vote recorded as "Other" it counts against their voting participation figure. Only the member's own chamber's votes are counted, and duplicate roll-call entries are de-duplicated by vote ID. Presiding officers (such as the Speaker of the House) vote only to break ties or on select matters by custom (watch for that to change soon), a member who almost never casts a Yea or Nay across a full slate of roll calls is will be labeled a presiding officer rather than shown a misleadingly low percentage. Participation reflects the passage votes in our data for the current session; if a weekly refresh has not finished fetching every bill, the figure is based on the votes collected so far.

**Party voting alignment:** Each profile with a known party also shows how often the member voted with their own party's majority but only on **party-line votes**, roll calls where a majority of Republicans voted opposite a majority of Democrats. Votes where both parties largely agreed are excluded, since counting those would inflate every member's score toward 100% without saying anything about partisanship (most legislation that reaches a floor vote passes with broad, often unanimous, support). This mirrors the standard "party unity score" used in political science and journalism. The party's majority position on each roll call is computed from every member's individual vote which is already collected for the voting-history feature above.

---

## [Georgia General Assembly Bills & Resolutions](https://github.com/Votega/ga-legislation)

**Source:** [Open States](https://openstates.org/) (Plural Policy)

The [GA Bills & Resolutions](https://github.com/Votega/ga-legislation) tracker covers all 5,480+ bills and resolutions introduced during the 2025–26 regular session of the Georgia General Assembly.

**How it works:**

Fetched weekly, pulls every bill for the session directly from the Open States API and writes a compact static file that the browser loads directly. The script:

- Strips the full per-bill action history (too large for client-side use), leaving only the latest action as `status` / `statusDate`.
- Derives the Governor's action (signed, vetoed, or sent and still pending) as a structured `governorAction` field (see below), read from Open States' explicit action classifications rather than guessed from free text.
- Keeps passage vote counts (yes/no/not voting) and the roll call motion text (i.e., Senate Vote #148) for each chamber vote.
- Preserves Open States subject tags where available. For bills with no subject tag, which are predominantly county-specific local legislation, we auto-assign a **"Local / Municipal"** tag when the bill title starts with a Georgia county name.

**What's included per bill:**

| Field | Description |
|---|---|
| `identifier` | Bill number (e.g. HB 112, SR 23) |
| `billType` | `bill` or `resolution` |
| `chamber` | `lower` (House) or `upper` (Senate) |
| `title` | Official bill title |
| `abstract` | Bill description (up to 500 characters) |
| `status` | Last recorded action (free text, e.g. "Effective Date") |
| `statusDate` | Date of last action |
| `subjects` | Subject tags from Open States, or `["Local / Municipal"]` if auto-tagged |
| `sponsors` | Array of sponsor names; first entry is the lead/introducing legislator |
| `passageVotes` | Passage vote counts per chamber, with roll call motion text |
| `governorAction` | Governor's disposition, `null` if not yet sent to the Governor |
| `billUrl` | Link to the bill on legis.ga.gov |
| `textUrl` | Link to the bill text (PDF, where available) |

**Governor's Action:** Georgia bills that pass both chambers are sent to the Governor, who signs, vetoes, or lets a bill become law without signature. The `governorAction` field is derived from Open States' `executive-receipt`, `executive-signature`, and `executive-veto` action tags.

```
{ "status": "Signed" | "Vetoed" | "Sent to Governor",
  "sentDate": "2026-04-07", "decisionDate": "2026-05-11" | null,
  "actNumber": 484 | null }
```

A quirk: a vetoed bill's transmittal record still carries an "executive-signature"-tagged action dated the same day as the veto. So, a veto always takes precedence when both are present for the same bill.

**Status classification** Derived client-side, `governorAction` takes precedence, with the free-text `status` field as a fallback for bills not yet sent to the Governor:

- **Signed**: `governorAction.status` is `"Signed"`
- **Vetoed**: `governorAction.status` is `"Vetoed"`
- **Sent to Governor**: `governorAction.status` is `"Sent to Governor"` and awaiting a decision
- **Failed**: status contains `"Lost"` 
- **Stalled**: status contains `"Withdrawn"` or `"Recommitted"` 
- **Passed**: passage votes exist for both chambers but not yet sent to the Governor 
- **In progress**: all other bills

**Subjects:** Open States provides subject tags for approximately 81% of actual bills. The auto-tagger adds "Local/Municipal" for a further 9%, bringing total coverage to around 90% of bills (excluding resolutions, which are separated into their own tab).

**Party-line classification:** We then join each `passageVotes` entry with individual member votes and party affiliation (from `ga-member-votes.json` and `ga-members.json`) to add a `partyTally`,the Yea/Nay count by party, to each recorded vote. VoteGA's [Bills Tracker](https://www.votega.org/ga-bills) uses this to flag **party-line votes**: roll calls where a majority of Republicans voted opposite a majority of Democrats. 

A bill is tagged "⚡ Party-line" if any of its recorded passage votes met this bar; votes where both parties largely agreed are not flagged, since most legislation that reaches a floor vote passes with broad support and labeling all of it "party-line" would be meaningless. Bills can be filtered to show only those with at least one party-line vote.

- **Scope:** All bills and resolutions from the 2025–26 regular session.
- **Freshness:** Current and periodically refreshed, given the 2025-2026 Regular Georgia Legislative Session has ended.

---

## [GA Legislators — Published for Reuse](https://github.com/Votega/ga-legislators)

Our Georgia General Assembly roster (`data/all.json`) and each legislator's passage-vote history (`data/votes.json`) are published as an open, machine-readable dataset covering the 158th (2025–2026) General Assembly. 

See **[Open Data](https://github.com/Votega/ga-legislators)** for the repository, file links, and update cadence.

{: .box-note}
**Spot an error?** A wrong phone number, a missing email, an outdated office, open an issue or pull request on the [ga-legislators repository](https://github.com/Votega/ga-legislators). Corrections are reviewed, incorporated into our manual overrides, and flow back into Votega.org on the next daily update.

---

## Federal Executive Branch

**Sources:** Manual curation, [Federal Register API](https://www.federalregister.gov/developers/api/v1), (Office of the Federal Register, National Archives)

The [Federal Executive Branch](https://www.votega.org/executive-branch) page displays the current President, Vice President, and Cabinet. Profile data (names, roles, party, term dates, confirmation dates) is manually maintained in a static data file and verified against official White House and Senate confirmation records.

**Executive Orders**  The Federal Register is the official journal of the U.S. federal government, published by the Office of the Federal Register. It is the authoritative source for presidential documents, including executive orders, presidential memoranda, and proclamations.

**How it works:**

The Federal Register API is queried at page load time, filtered to executive orders signed on or after the current administration's inauguration date. No API key is required — the Federal Register API is free and publicly accessible.

- **Scope:** Executive orders issued during the current presidential term.
- **Signed legislation:** Laws signed by the President during the current term are pulled from the Congress.gov API and stored in a prebuilt static file. Each law entry includes its public law number, bill label, title, signing date, policy area, and origin chamber.
- **VP tie-breaking votes:** The Vice President casts a tie-breaking vote when the Senate is deadlocked 50–50. These are recorded in Senate roll call XML files under a `<tie_breaker>` element. We scan the vote list for each session, identify tied tallies, fetch the detail XML for each, and extract VP tie-breaking votes into a prebuilt static file updated weekly.
- **Cabinet data:** Names, roles, departments, and Senate confirmation dates are manually maintained.
- **Agency rules & regulations:** Each Cabinet member's profile shows recent final and proposed rules from their department, fetched live from the Federal Register API and filtered to that department's agency ID (`conditions[agency_ids][]`) and document type (`RULE` and `PRORULE`, i.e. final and proposed rules — routine notices are excluded to keep the list focused on substantive regulatory actions). Agency IDs were resolved from the Federal Register's `/agencies.json` endpoint and are hardcoded per department in `executive-member.html`, the same way executive orders are already fetched for the President. 
- **Data Quark** The Office of the Director of National Intelligence has no Federal Register agency listing. So its profile links to their official department website instead.
- **Freshness:** Executive orders and agency rules are fetched from the Federal Register API at page load time. VP tie-breaking votes, signed legislation, and cabinet membership are fetched weekly

---

## Officeholder ID Crosswalk

**Sources:** [Open States](https://openstates.org/) (Plural Policy), [Congress.gov](https://api.congress.gov/), [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) (public domain), [Georgia Ethics Commission PeachFile](https://peachfile.ethics.ga.gov/public/cf/publiccandidate)

Five systems assign an identifier to the same Georgia officeholder, and none of them share a key: Open States issues an OCD person ID, legis.ga.gov a numeric member ID, Congress.gov a bioguide ID, the FEC a candidate ID, and the state Ethics Commission a PeachFile filer entity ID. Joining them is what makes a member page able to show a legislator's votes and their fundraising side by side.

Those joins already happened inside this site; they were just never written down. [`id-crosswalk.json`](/assets/data/id-crosswalk.json) records them as data — one entry per officeholder, with every identifier we hold and, for each one, how it was arrived at.

**Why it might be useful to you.** The federal half largely restates `unitedstates/congress-legislators`, which is public domain and already maps bioguide to FEC, GovTrack and OpenSecrets; we carry those so a consumer needs one file rather than two. The Georgia half has no upstream equivalent. Nothing published anywhere maps an Open States legislator to their Georgia campaign finance filing, so if you want to join state legislative behavior to state campaign money, this is the missing key.

**Every derived link carries its provenance.** Each identifier is tagged with the method that produced it:

- `authoritative` — the upstream source publishes this ID for this person directly.
- `reviewed` — a human confirmed the match, recorded in a public overrides file. This includes `confirmed-none`: someone checked and there is genuinely no filing, which is a different claim from nobody having looked.
- `seat+surname` — derived by matching within the person's seat or statewide office, requiring the surname.

**Ambiguity is never resolved by guessing.** Where more than one filing matches a person, the identifier is left null and the case is listed in the file's `metadata`, because attributing one official's fundraising to another is the failure this join exists to prevent.

**Committees follow the office sought, not the office held.** A campaign committee is registered against the office a candidate is seeking, and PeachFile files it that way. So a sitting state representative running for the Senate has their committee under the Senate seat, not the House one. The crosswalk matches against the office sought first and falls back to the seat currently held — which is how it resolves the sitting statewide executives on the 2026 governor's ballot, whose committees sit under "Governor" rather than under the office they occupy today.

**Identifiers are stable.** Each person gets an opaque `vgId` minted once and held in a committed, append-only ledger. A legislator who changes chamber or name, or whose Open States record is reissued, keeps the same `vgId`, and an ID published once never comes to mean a different person.

- **Coverage:** 264 officeholders — 249 rows from `ga-members.json` (sitting legislators plus the four statewide executives that file carries) and Georgia's 15-member federal delegation. PeachFile IDs resolve for 228 of the 249 state records. Non-incumbent candidates are not yet covered; they appear only as back-references from the officeholders they face.
- **Freshness:** Rebuilt weekly, after the campaign finance and roster data it reads.

---

## Supreme Court

**Sources:** [Oyez.org API](https://api.oyez.org/) (free, no key required), [CourtListener](https://www.courtlistener.com/) (Free Law Project), Manual curation

The [Supreme Court](https://www.votega.org/supreme-court) page displays current justices and recent decisions. Justice profile data (names, titles, appointing president, confirmation dates and votes, law school, home state) is manually maintained. Case decisions and per-justice vote breakdowns are fetched weekly from the Oyez API.

**How it works:**

1. The Oyez API is queried for all cases in the current and most recent SCOTUS terms.
2. Only decided cases (those with a "Decided" event in the timeline) are included.
3. For each decided case, the full case detail is fetched to retrieve the per-justice vote breakdown (majority, dissent, and concurrence) along with the case description, docket number, decision date, and vote tally.
4. CourtListener's public search API is queried to cross-reference docket numbers with opinion page URLs, where available.

**Individual justice profiles** show a voting record filtered from the decisions dataset, and a live biography tab fetched from the Oyez API at page load time.

- **Scope:** Current SCOTUS term plus the immediately preceding term.
- **Vote breakdown:** Majority, dissent, and concurrence positions for each justice on each decided case.
- **Freshness:** Justice roster is manually maintained. Decision data is fetched weekly.

---

## [Georgia Executive Orders](https://github.com/Votega/ga-executive-orders)

Georgia Governor's executive orders are fetched daily from the [Georgia Governor's website](https://gov.georgia.gov/executive-action/executive-orders). New orders are detected and added automatically. Data is organized as one JSON file per year, with each order including the date, order number, title, category, and a direct link to the official PDF.

**Coverage:** 2023–present. Earlier years (2022 and prior) used a different URL structure on gov.georgia.gov and are not included (and likely won't be).

**Categories:** Orders are automatically classified by title keyword into one of seven categories: State of Emergency, Writ of Election, Suspension, Appointment, Authorization, Flag at Half-Staff, or Other.

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

Published for reuse — see **[Open Data](https://www.votega.org/open-data)** for the repository and downloads.

{: .box-note}
**Want to contribute?** If an order is missing or miscategorized, open an issue or pull request on the [ga-executive-orders repository](https://github.com/Votega/ga-executive-orders).

---

## Georgia Congressional Stock Trades

**Source:** [kadoa-org/congress-trading-monitor](https://github.com/kadoa-org/congress-trading-monitor) (open dataset), [House Clerk eFD system](https://disclosures-clerk.house.gov/), [Senate eFD system](https://efts.senate.gov/)

Federal lawmakers are required to disclose personal stock trades within 45 days of the transaction under the STOCK Act (Stop Trading on Congressional Knowledge Act). These disclosures, called Periodic Transaction Reports (PTRs), are filed with the House Clerk (for House members) or the Senate eFD system (for Senators).

We display stock trades filed by Georgia's Federal Congressional Delegation on the [Georgia Congressional Stock Trades](https://www.votega.org/ga-congress-trades) page.

**How it works:**

The `kadoa-org/congress-trading-monitor` open dataset aggregates STOCK Act PTR disclosures from the official House and Senate filing systems and publishes them in a structured format. We run a process weekly that pulls the latest data for Georgia's House and Senate members and processes it into our static data file.

**What's included:**
- Ticker symbol and asset name (with asset type: stock, crypto, government security, corporate bond, or other)
- Transaction type (Purchase or Sale)
- Transaction date and filing date
- Amount range (dollar amounts are ranges per the STOCK Act, not exact figures)
- Days to file, and a late-filing flag for disclosures filed after the 45-day window
- Ownership type where indicated (member, spouse, joint, or dependent child)

**Coverage:** All current members of Georgia's congressional delegation (House and Senate) who <u>**have filed**</u> disclosures.

- **Freshness:** Fetched weekly

{: .box-note}
Dollar amounts are self-reported ranges, not exact figures. Trades may be filed up to 45 days after the transaction date. Data is sourced from official House and Senate disclosure systems via the kadoa-org/congress-trading-monitor open dataset.

---

## [2026 Election Races & Candidates](https://github.com/Votega/ga-races-elections)

**Sources:** [Georgia Secretary of State](https://sos.ga.gov/),Manual curation

Race and candidate information for the 2026 election cycle is maintained in a curated data file (`races.json`) that powers the race pages and candidate profiles on the site.

**Georgia State Legislative Candidates** (GA House and Senate) are sourced from the Georgia Secretary of State's candidate filing system, which publishes official candidate registration data for each primary and general election. We process that data to build one race entry per district, including candidate names, party affiliation, occupation, and county of residence.

**Georgia judicial candidates** (Superior Court, Court of Appeals, and Supreme Court of Georgia) are sourced from the Georgia Secretary of State's candidate qualification data. Races are organized by court and seat. Superior Court races are grouped by judicial circuit. All judicial races in Georgia are non-partisan.

**Federal candidates** (U.S. House and Senate) are manually researched and entered. Incumbents are linked directly to their Congress.gov member record so their photo, party, and legislative history populate automatically. Challengers' bios, photos, and websites are sourced from candidates' official campaign websites and entered manually.

**Incumbent enrichment:** When a candidate is the current officeholder, their profile photo and member record link are automatically pulled from our existing legislator data (Congress.gov for Federal, Open States for State). No duplicate data entry required. Judicial incumbents are identified from the SoS qualification data but do not link to a separate legislator profile.

- **Scope:** 2026 primary, general, runoff, and special election races for Georgia's federal delegation, all 236 Georgia General Assembly districts, and all 2026 Georgia judicial races (84 Superior Court seats across 41 circuits, 5 Court of Appeals seats, and 2 Supreme Court seats).
- **Freshness:** GA legislative and judicial candidate data is updated when the Secretary of State publishes new filing data. Federal challenger data is manually maintained.

---

## Georgia Ballot Measures

**Sources:** [Georgia Secretary of State](https://sos.ga.gov/),[Georgia General Assembly](https://www.legis.ga.gov/), Manual curation

Statewide ballot measures, constitutional amendments and statewide referendums that Georgia voters decide, are maintained in a curated data file (`assets/data/ga-ballot-measures.json`) that powers the [Ballot Measures page](https://www.votega.org/ga-ballot-measures.html).

Each measure records a plain-language summary, subject tags, and a link to the enabling legislation (the constitutional amendment resolution or referendum bill) on [legis.ga.gov](https://www.legis.ga.gov/). Measures are labeled **Certified** once the Secretary of State certifies them for the ballot, or **Potential** if the enabling legislation has passed the General Assembly but has not yet been certified (for example, a bill awaiting the Governor's signature).

- **Coverage:** Statewide measures on the ballot for the current general election. Vote results are added to each measure after the election is certified.
- **Freshness:** Manually updated as measures are certified and as results are reported.

---

## Voter Access & Election Calendar

**Sources:** [Georgia Secretary of State](https://sos.ga.gov/), Manual curation

The [Voter Access & Election Calendar](https://www.votega.org/ga-voter-access.html) page maintains a curated data file (`assets/data/ga-election-calendar.json`) covering each election in the current cycle: election date, early voting window, and voter registration deadline. The page also links directly to the Georgia Secretary of State's official tools for checking registration status, polling place, and ballot status (My Voter Page), and for registering to vote or updating a registration.

The "Next Election" highlight and each election's Upcoming/Completed status are computed in the browser from the visitor's current date. They are not stored in the data file, so the page stays accurate without a rebuild as elections pass.

- **Coverage:** All elections in the 2026 cycle (primary, general, runoff, and special).
- **Freshness:** Manually updated when the Secretary of State publishes or revises election dates.

---

## Campaign Finance

**Sources:** [Federal Election Commission (FEC)](https://www.fec.gov/), [Georgia Government Transparency & Campaign Finance Commission](https://ethics.ga.gov/) (PeachFile)

Campaign finance figures, total raised, total spent, and cash on hand, appear on candidate profiles and on member pages for sitting legislators. On each race page, a **Campaign Finance** tab lays every candidate in the race side by side so you can compare their fundraising and spending directly, with bars scaled to the highest figure in each column.

- **Federal candidates and members** (U.S. House and Senate): Sourced from the [FEC API](https://api.open.fec.gov/), the authoritative record for federal campaign finance disclosures. We fetch it on a schedule and publish it as a static file rather than calling the API from your browser, so no API key is ever exposed in the page. Federal profiles also show the top donors grouped by employer.
- **Georgia state candidates and legislators** (GA House, Senate, and statewide offices): Sourced from [PeachFile](https://peachfile.ethics.ga.gov/public/cf/publiccandidate), the Georgia Ethics Commission's disclosure system, using its public endpoints. Collected on a schedule and published as a static file for the same reason.

**Coverage:** 2026 election cycle.

**A note on Georgia state figures.** PeachFile is the Commission's current e-filing system and holds filings from January 1, 2026 forward. Filings from before that date remain in the Commission's separate [Records Search](https://ethics.ga.gov/records-search-all/), which we do not currently publish.

**Why a legislator may show no filing.** We match a legislator to a filing by their seat, chamber and district, and then by surname. We deliberately do not match on name alone across the whole state, because Georgia seats several unrelated legislators who share a surname, and a looser match would attribute one person's fundraising to another. 

So "no filing found" means exactly that, and usually has an ordinary explanation: the legislator is not seeking re-election, has not filed yet, or is running for a different office (in which case their committee is registered under that office instead of their current seat). When in doubt, search PeachFile directly.

A small number of candidates cannot be resolved this way. Usually because the ballot name differs from the committee's registered name (Rick for Richard, Bill for William). Those are reviewed by hand and recorded in a public overrides file alongside the data: currently 6 candidates matched manually to a specific filing, and 46 confirmed as having no filing on record.

**Why the three figures may not add up.** Raised minus spent will often not equal cash on hand, and that is how the law defines the report rather than an error. Under [O.C.G.A. § 21-5-34(b)(1)(D)](https://ethics.ga.gov/wp-content/uploads/2026/05/2026-Campaign-Finance-Act-SEC-Website-Final-2.pdf), contributions and expenditures are totaled for a single *election cycle*, while "net balance on hand" is carried forward from the previous cycle. An election cycle runs from the day after one election to the next election for that same office (§ 21-5-3(10)), so a long-serving legislator's cash on hand can reflect years of accumulated funds while the raised and spent figures cover only the current cycle.

**How current the figures are.** State disclosure reports are due January 31, April 30, July 31, and October 20, with a five-day grace period, plus additional reports before runoffs and near elections (§ 21-5-34(c)). Figures therefore reflect each committee's most recent required report and can be several months old. A candidate who raised money last week will not show it until their next report is due.

**Figures are summary totals only.** We show what each committee reported raising, spending, and holding. We do not publish individual donor records or contributor personal information from the state system.

---

## Data Freshness

| Data | Source | Update Schedule |
|---|---|---|
| Federal executive branch (President/VP/Cabinet) | Manual curation | Manually maintained |
| Federal executive orders | Federal Register API (live) | Real-time, fetched on page load |
| Presidential signed legislation | Congress.gov API | Weekly, Sundays 09:45 UTC |
| VP tie-breaking votes | Senate.gov roll call XML | Weekly, Sundays 09:30 UTC |
| Supreme Court justices | Manual curation | Manually maintained |
| Supreme Court decisions & votes | Oyez.org API + CourtListener | Weekly, Sundays 10:00 UTC |
| Federal Congress members | Congress.gov API | Daily, 06:00 UTC |
| Georgia state legislators | Open States API | Daily, 07:00 UTC |
| GA legislators community repo | Published from above | Daily, after GA member update |
| Federal legislator voting history | Congress.gov API + Clerk/Senate XML | Weekly, Sundays 09:00 UTC |
| GA state legislator voting history | Open States API | Weekly, Sundays 08:00 UTC |
| GA bills & resolutions (2025–26 session) | Open States API | Weekly, Sundays 07:30 UTC |
| GA curated bills (Key Votes) | Open States API | Daily, 08:00 UTC |
| GA executive orders | gov.georgia.gov (scraped) | Daily, 08:15 UTC (committed when new orders are found) |
| GA congressional stock trades | House/Senate eFD via kadoa-org/congress-trading-monitor | Weekly, Sundays 10:00 UTC |
| 2026 GA legislative candidates | GA Secretary of State | Updated when SOS publishes new filing data |
| 2026 GA judicial candidates | GA Secretary of State | Updated when SOS publishes new filing data |
| 2026 federal race/candidate data | Manual curation | Manually maintained |
| Georgia ballot measures | GA Secretary of State + legis.ga.gov | Manually maintained; results added after certification |
| Federal campaign finance | FEC API | Weekly, Sundays 08:00 UTC |
| Georgia state campaign finance | GA Ethics Commission (PeachFile) | Weekly, Sundays 08:30 UTC |
| Officeholder ID crosswalk | Derived from the rosters + finance data above | Weekly, Sundays 09:15 UTC |

---

## What We Don't Do

- **No tracking or analytics beyond standard page metrics.** We do not build profiles of visitors or sell data.

---

## Corrections and Feedback

See an error? Have a data question? Feature request? Reach out to us at [admin@votega.org](mailto:admin@votega.org)
or open an issue on [github.com/Votega/ga-legislators](https://github.com/Votega/ga-legislators)
for Georgia legislator corrections. 
Or [github.com/Votega/ga-executive-orders](https://github.com/Votega/ga-executive-orders) for executive order corrections.
