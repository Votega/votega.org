# VoteGA × Georgia Civic Data / Georgia Commons: working notes

Last updated 2026-10-27. A memory of the collaboration idea, what is already built, and the steps VoteGA still has to take to make it work. The partnership brief itself is a separate document; this file is for whoever (human or agent) picks the work up next.

## The idea

VoteGA knows who represents Georgians and how they voted. Georgia Civic Data (GCD) knows how their communities are doing (education, Census, immigration, keyed by county, school district, school, tract). Georgia Commons, an independent project of GCD, publishes bills with AI-written plain-language summaries and committee-meeting coverage. Joined on geography and on bill and member identifiers, the three answer questions none can alone, always as records side by side, never as claims about cause.

Ground rules: records only (votes, bills, outcomes as published); nonpartisan; no ratings. AI-written text is always labelled as such and is never presented as part of the record.

## What is already done (merged to `main` and published)

- **`Votega/ga-district-information` 2.0.0.** Every county code is the 5-digit FIPS (`13013`), the form GCD and the Census use. Added `data/district-counties.csv` (district to counties, with share of the district, share of the county and `coverage` full/partial), `data/county-codes.csv` (5-digit FIPS, the 3-digit suffix used before 2.0.0, name, slug), and a `coverage` column on `county-districts.csv`. Catalogued on `/open-data`; sibling README updated. Source files (`scripts/data/ga-tract-districts.json`, `assets/data/ga-zip-districts.json`) now carry 5-digit codes too. Test: `scripts/test_publish_ga_district_information.py`.
- **Tract bridge verified.** GCD's `tracts` dimension has the same 2,796 tracts and the same 2020 population (10,711,908) as our tract table, with the same 11-digit GEOIDs. GCD's `school_attendance_zone_tracts` covers 175 of 180 standard school districts (1,907 schools); the five without zone data are Griffin-Spalding, Meriwether, Newton, Union and Whitfield. Charters and state entities have no zones.
- **Newton County pilot corrected.** Under the 2023 plans Newton is covered by House 113 (Henderson, suspended; 52.8% of the county), 114 (Fleming) and 118 (Crowe), Senate 42 (Strickland) and 43 (Anderson), Congress 10 and 13. The brief's ZIP-based list wrongly included House 112, House 144 and Senate 25 and left out 113. All six chamber totals in the brief match our roll-call data.
- **Suspended members.** Data dictionary and `about-the-data.md` define `Suspended` (keeps the title and seat, cannot act, no replacement unless felony conviction; Ga. Const. Art. II, Sec. III). The majority tracker shows a suspended seat separately and keeps the majority line at 91 and 29 (Art. III, Sec. V, Para. V: a bill needs a majority of all members the chamber is entitled to). A daily report-only signal (`scripts/lib/ga_suspension_signals.py`) flags suspension orders the roster has not recorded.
- **`votegaUrl` on roster records (live 2026-10-27).** Each member record in `assets/data/ga-members.json` and in the published `Votega/ga-legislators` files (`data/all.json`, the final column of `data/members.csv`, `data/members.schema.json`, and links in `ROSTER.md`) carries the absolute URL of the member's VoteGA page, or `null` when there is no page. Of 247 members, 236 have a URL; the 11 nulls are the resigned members. Derived by `scripts/lib/ga_legislator_pages.py`; `scripts/test_ga_legislator_pages.py` runs the real page builder and fails if the two disagree. Statewide executives are no longer carried in the legislator roster (251 to 247 members).
- **Tract-table builder re-run end to end (2026-10-26)** and reproduced the committed table against the reapportionment office's packets and county reports.

## What Georgia Commons offers (checked 2026-10-23 on HB 943)

- Bill pages at `https://georgiacommons.org/bills/2025-2026/hb943` with "In plain language", "What the bill does", "Who it affects", "Why it matters", "Key provisions", excerpts from the bill, votes, sponsors, and per-meeting summaries. Markdown (`/bills/2025-2026/hb943.md`), raw text, an API (`/api`) and an MCP server (`mcp.georgiacommons.org/mcp`).
- Summaries are AI-written (the page names an Anthropic model) and say they are not part of the bill. **No license or reuse terms are stated on the page.**
- Sponsors are shown as name, party, chamber and district, with the primary sponsor marked. They are not hyperlinked and show no member ID.
- Join key: our `legislationId` equals the number in their link to the official record (HB 943 is 72141). Their URL slug is the identifier lowercased with no space (`HB 943` becomes `hb943`) under the session `2025-2026`. Special-session bills such as `HB 10EX` (176 of our 5,656) are not mapped yet.

## Steps VoteGA has to take to make it functional

### A. Member pages and bill summaries, linked both ways (Georgia Commons)
1. **Add `votegaUrl` to each roster record** (`assets/data/ga-members.json`, then published in `ga-legislators` `all.json` and its schema), keyed by `legisGaGovId`, `null` where a member has no page (**done**, live 2026-10-27: `scripts/lib/ga_legislator_pages.py`, written by the roster producer, published in `ga-legislators` `all.json`, `members.csv` and the schema). The slug is name plus chamber plus district (`deborah-silcox-house-53`), computed by `slugify_member()` in `scripts/generate_ga_members_soap.py` to match `build_entity_pages.py`. Page URL: `https://www.votega.org/ga-legislators/<slug>/`.
2. **Add a drift test** that every member's `votegaUrl` equals the permalink `build_entity_pages.py` generates (including the collision case, where the builder appends `mid[:8]`), so a link never points at a missing page (**done**: `scripts/test_ga_legislator_pages.py`, which runs the real page builder).
3. **Optional stable redirect** such as `/ga-legislators/legis/<legisGaGovId>/`, as a small stub page per member, because the slug changes if a member's name or district changes. GitHub Pages cannot redirect on the server. **Not needed now:** `votegaUrl` is the primary link, and the legacy `ga-member.html?id=<ocd-person-id>` shell already redirects to the clean page (JavaScript, `noindex`; it takes the OCD ID, not the legis.ga.gov number). Legislator pages also carry a per-member record summary from the thin-content SEO work, so avoid adding new indexable legislator URLs.
4. **Ask Georgia Commons to link each sponsor** (now unblocked: `votegaUrl` is published) to `votegaUrl` (matching on `legisGaGovId` if they hold it, otherwise chamber and district), and confirm what member ID they store.
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
- Would GCD accept a joint product released under CC BY-SA 4.0? Would they want our geographic tables under CC BY or CC0 so they can load them?
- For the school attendance zones and any dataset sourced from Pew, MPI, CMS or Georgia Insights: what upstream terms apply to redistribution of figures derived from them?

## Licensing: CC BY-SA 4.0 (VoteGA) and CC BY 4.0 (GCD)

Added 2026-10-23. A reading of the license text, not legal advice; have counsel confirm before any joint publication.

**The rule.** CC BY-SA 4.0 is one-way compatible with CC BY. GCD data can flow into a VoteGA adaptation released as BY-SA (we already do this; see `NOTICE.md`). VoteGA data cannot flow into a GCD dataset released as CC BY, because any adaptation of our BY-SA material must stay BY-SA. A combined work built from both is BY-SA overall; GCD's originals stay CC BY at their source.

| Path | License impact |
|---|---|
| Join on shared keys (county FIPS, tract GEOID, `legisGaGovId`), link out, chain MCP servers | None. Nothing is redistributed, so ShareAlike never triggers. |
| Query-time joins (a page or assistant pulls from both, stores neither) | None. Attribute each source. |
| Joint published product (e.g. district profiles from GCD Census facts weighted by our tract populations) | Product is BY-SA, both credited. GCD must accept that. |
| GCD ingests our tables into their star schema | Only if we also license those tables to them under CC BY or CC0 (dual license; our decision, and it gives up share-alike on those tables). |
| VoteGA ingests Georgia Commons text | Blocked until they state a license. |

**What GCD's own terms say (checked 2026-10-23 via their MCP server).** The catalog-level `license` object is CC BY 4.0, attribution "Georgia Civic Data (georgiacivicdata.org)", and its scope reads: it covers GCD's "cleaning, standardization, compilation, and documentation. Source data stays under its original publisher's terms; each dataset names its source." Terms page: `https://georgiacivicdata.org/about#license`. The per-dataset ODCS contracts carry no license field, only `source` and `source_url`, so the rule for any dataset is: GCD's CC BY covers GCD's work, and the upstream publisher's terms cover the rest.

- **Safe to build on:** the Census-derived topics (ACS, P.L. 94-171, TIGER) and `school_attendance_zone_tracts`, a GCD-built crosswalk from Census blocks and district/vendor zone maps. The zone maps' own terms are not stated; ask GCD before publishing zone-based figures.
- **Check upstream before reuse:** `undocumented_population_estimates` (Pew, MPI, Center for Migration Studies; DHS is public), `undocumented_population_characteristics`, `ccrpi_*` and other "georgia insights" education topics, and anything from the Deportation Data Project. GCD cannot license a third party's figures to us, so a CC BY label here is not a clearance.
- **Public record, no issue:** GOSA education files, DHS/OHSS, EOIR, ICE FOIA releases, DOL OFLC, State Department refugee data.

**Other points.**
- Facts get thin protection in the US (and the EU database right does not reach us), so BY-SA bites mainly on our original text and our arrangement of data. Treat it as binding regardless.
- Our own inputs are mixed: legis.ga.gov, FEC and Census are public records; the `openstates/people` crosswalk is CC0; PeachFile terms are unverified. Our BY-SA label covers only what we author.
- PolyForm Noncommercial applies to site code only and does not touch data sharing.
- Georgia Commons: no license means all rights reserved. Link-out is fine. If they choose CC BY or CC0 we can use the text; BY-NC or BY-ND would not be compatible with BY-SA reuse. AI-written text has unsettled copyright, so ask what they claim.

**Recommended position.** Keep the integration loose (keys, link-outs, chained MCP). If a joint dataset is wanted, release it BY-SA and ask GCD whether they accept that. Optionally offer our purely geographic tables (tract to district, county to district) to GCD under CC BY or CC0. Get a license from Georgia Commons before touching their text.

## Caveats to keep in view
- **The January 2027 rollover will break links to former members.** `votegaUrl` pages are built from the live roster, which drops non-returning members at the rollover, so Georgia Commons' sponsor links to them would 404. Decisions are in `docs/ga-biennium-rollover-decisions.md`; settle them before asking Georgia Commons to launch the sponsor links.
- County shares are 2020 population shares under the 2023 plans and must be rebuilt if Georgia redraws. `build_ga_tract_district_table.py` now emits 5-digit codes and was re-run end to end on 2026-10-26: every district total and county x district row reconciled exactly against the office's packets and county reports, and the output matched the committed table apart from `generatedAt`. Its inputs are not in the repo; download them from https://www.legis.ga.gov/joint-office/reapportionment (block-equivalency xlsx, packets and county reports as PDFs, run through `pdftotext -layout`; the Census `ga2020.pl.zip` supplies `gageo2020.pl`). The office also publishes a Congress-2023 packet that the script does not read yet.
- A county is not a district: most House districts take only part of one. Never imply a county's outcomes belong to one legislator.
- Do not claim votes caused outcomes. Show them side by side.
