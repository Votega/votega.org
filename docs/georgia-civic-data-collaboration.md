# VoteGA × Georgia Civic Data / Georgia Commons: working notes

Last updated 2026-10-23. A memory of the collaboration idea, what is already built, and the steps VoteGA still has to take to make it work. The partnership brief itself is a separate document; this file is for whoever (human or agent) picks the work up next.

## The idea

VoteGA knows who represents Georgians and how they voted. Georgia Civic Data (GCD) knows how their communities are doing (education, Census, immigration, keyed by county, school district, school, tract). Georgia Commons, an independent project of GCD, publishes bills with AI-written plain-language summaries and committee-meeting coverage. Joined on geography and on bill and member identifiers, the three answer questions none can alone, always as records side by side, never as claims about cause.

Ground rules: records only (votes, bills, outcomes as published); nonpartisan; no ratings. AI-written text is always labelled as such and is never presented as part of the record.

## What is already done (merged to `main` and published)

- **`Votega/ga-district-information` 2.0.0.** Every county code is the 5-digit FIPS (`13013`), the form GCD and the Census use. Added `data/district-counties.csv` (district to counties, with share of the district, share of the county and `coverage` full/partial), `data/county-codes.csv` (5-digit FIPS, the 3-digit suffix used before 2.0.0, name, slug), and a `coverage` column on `county-districts.csv`. Catalogued on `/open-data`; sibling README updated. Source files (`scripts/data/ga-tract-districts.json`, `assets/data/ga-zip-districts.json`) now carry 5-digit codes too. Test: `scripts/test_publish_ga_district_information.py`.
- **Tract bridge verified.** GCD's `tracts` dimension has the same 2,796 tracts and the same 2020 population (10,711,908) as our tract table, with the same 11-digit GEOIDs. GCD's `school_attendance_zone_tracts` covers 175 of 180 standard school districts (1,907 schools); the five without zone data are Griffin-Spalding, Meriwether, Newton, Union and Whitfield. Charters and state entities have no zones.
- **Newton County pilot corrected.** Under the 2023 plans Newton is covered by House 113 (Henderson, suspended; 52.8% of the county), 114 (Fleming) and 118 (Crowe), Senate 42 (Strickland) and 43 (Anderson), Congress 10 and 13. The brief's ZIP-based list wrongly included House 112, House 144 and Senate 25 and left out 113. All six chamber totals in the brief match our roll-call data.
- **Suspended members.** Data dictionary and `about-the-data.md` define `Suspended` (keeps the title and seat, cannot act, no replacement unless felony conviction; Ga. Const. Art. II, Sec. III). The majority tracker shows a suspended seat separately and keeps the majority line at 91 and 29 (Art. III, Sec. V, Para. V: a bill needs a majority of all members the chamber is entitled to). A daily report-only signal (`scripts/lib/ga_suspension_signals.py`) flags suspension orders the roster has not recorded.

## What Georgia Commons offers (checked 2026-10-23 on HB 943)

- Bill pages at `https://georgiacommons.org/bills/2025-2026/hb943` with "In plain language", "What the bill does", "Who it affects", "Why it matters", "Key provisions", excerpts from the bill, votes, sponsors, and per-meeting summaries. Markdown (`/bills/2025-2026/hb943.md`), raw text, an API (`/api`) and an MCP server (`mcp.georgiacommons.org/mcp`).
- Summaries are AI-written (the page names an Anthropic model) and say they are not part of the bill. **No license or reuse terms are stated on the page.**
- Sponsors are shown as name, party, chamber and district, with the primary sponsor marked. They are not hyperlinked and show no member ID.
- Join key: our `legislationId` equals the number in their link to the official record (HB 943 is 72141). Their URL slug is the identifier lowercased with no space (`HB 943` becomes `hb943`) under the session `2025-2026`. Special-session bills such as `HB 10EX` (176 of our 5,656) are not mapped yet.

## Steps VoteGA has to take to make it functional

### A. Member pages and bill summaries, linked both ways (Georgia Commons)
1. **Add `votegaUrl` to each roster record** (`assets/data/ga-members.json`, then published in `ga-legislators` `all.json` and its schema), keyed by `legisGaGovId`, `null` where a member has no page. The slug is name plus chamber plus district (`deborah-silcox-house-53`), computed by `slugify_member()` in `scripts/generate_ga_members_soap.py` to match `build_entity_pages.py`. Page URL: `https://www.votega.org/ga-legislators/<slug>/`.
2. **Add a drift test** that every member's `votegaUrl` equals the permalink `build_entity_pages.py` generates (including the collision case, where the builder appends `mid[:8]`), so a link never points at a missing page.
3. **Optional stable redirect** such as `/ga-legislators/legis/<legisGaGovId>/`, as a small stub page per member, because the slug changes if a member's name or district changes. GitHub Pages cannot redirect on the server.
4. **Ask Georgia Commons to link each sponsor** to `votegaUrl` (matching on `legisGaGovId` if they hold it, otherwise chamber and district), and confirm what member ID they store.
5. **Link our bill and member pages out to Georgia Commons**: `https://georgiacommons.org/bills/<session>/<hbNNN>`, labelled "Plain-language summary (AI-written), Georgia Commons". Map session `2025_26` to `2025-2026`. Show only "In plain language" and "What the bill does", not "Why it matters" (evaluative). Spot-check a sample against the bill text before relying on it.
6. **Do not copy or store their summary text until they confirm a license and API terms.** Link-out needs no permission; fetch-at-view-time or ingestion does.

### B. County, district and tract joins (GCD)
7. **Point GCD at `Votega/ga-district-information`** for county and tract tables; `county_fips` there now joins to theirs directly.
8. **Optional: add a slim `counties: [{fips, share}]` field to sitting members' records**, generated from the district-to-county table in the same run, with a drift test. Roughly +25-30 KB on a 661 KB file loaded by many pages; no counties for departed members.
9. **Optional: district profiles** from GCD's tract-grain Census facts weighted by our tract populations (split tracts make these estimates; say so). **Optional: school district to legislative district** via `school_attendance_zone_tracts` and our tract table for 175 of 180 standard districts, counties as the fallback.
10. **Newton pilot page**: rebuild the vote table from the county table and roll calls (done in the brief); state the time gap, since the votes are 2026 and the outcome data runs through 2024.

### C. MCP server (`docs/superpowers/specs/2026-10-23-mcp-server-design.md`)
11. Move `find_my_representatives` into v1, return `county_fips` and `votegaUrl` from the member and county tools, and return the Georgia Commons bill URL from the bill tool, so an assistant can chain our MCP server to theirs and to GCD's.

### Questions to put to Georgia Civic Data / Georgia Commons
- What license covers the summaries and meeting accounts? May we fetch or store them, with attribution?
- API terms and rate limits? Do they hold legis.ga.gov member IDs for sponsors?
- How should VoteGA credit their data, and what do they want from us?
- Do they have legislative-district boundaries? (We have tract to district.)

## Caveats to keep in view
- County shares are 2020 population shares under the 2023 plans and must be rebuilt if Georgia redraws. `build_ga_tract_district_table.py` now emits 5-digit codes, but it needs inputs that are not in the repo, so that two-line change has not been run end to end.
- A county is not a district: most House districts take only part of one. Never imply a county's outcomes belong to one legislator.
- Do not claim votes caused outcomes. Show them side by side.
