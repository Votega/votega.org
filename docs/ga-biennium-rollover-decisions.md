# January 2027 biennium rollover: decisions needed

Drafted 2026-10-27. Decision doc for the team. Nothing here is built yet. Statuses: **Proposed** (a default is suggested and awaits agreement), **Open** (not yet worked through).

The 159th General Assembly convenes on **2027-01-11**, and the 120th Congress in early January. The live roster and several data files turn over, and today's design does not say what happens to the people, bills and records of the outgoing session. This doc lists what happens, what breaks, and what to decide.

## What happens at the rollover (verified from the code and `claude.md`)

- The outgoing roster is frozen into `Votega/ga-legislators` (`freeze-ga-roster` workflow, run before the session bump). Then `update-ga-members --new-biennium` replaces the live roster: it requires the frozen copy, **drops members who do not return**, keeps non-voting-chamber records (Lt. Governor), stamps `metadata.rollover`, and writes `incomingCohort`, `departingCohort` and `newMemberNameReview` review queues. The procedure and deadline are in `RECURRING-TASKS.md` §3, which the code references but which is **not in the repository**; someone needs to confirm the steps from wherever it lives.
- The open-data repos are the archive: `ga-legislators` and `ga-legislation` keep per-session folders that are never overwritten (bills, votes, scorecards, and the roster frozen at sine die). The party-unity page already links to the repo's per-session scorecard instead of keeping old data on the site.
- Member pages (`/ga-legislators/<slug>/`) are generated at deploy from the live roster and are not committed. After the rollover, a non-returning member's page stops being built and its URL returns 404.
- Elections already have an on-site archive (`/results/`, cycles newest-first), which is precedent for keeping history on the site.

## What breaks if we do nothing

- **Georgia Commons links.** `votegaUrl` (live 2026-10-27) gives 236 members a page URL. Georgia Commons' 2025-26 bill pages are permanent, so every sponsor who leaves loses a link.
- **Former members.** About **33 of 236** sitting members are not on their own seat's 2026 general ballot (a name-match against `races.json`; approximate): 17 are on another race's ballot (running for other office), 10 are on no 2026 ballot (retiring), 6 are on their own primary ballot but not the general (lost a primary or runoff, or withdrew). 203 are running again. Plus whoever loses on November 3, and the 11 already resigned. Pages for all of them would disappear.
- **Bill deep links.** Bill numbers restart each General Assembly (HB 943 in 2027 is a different bill). `ga-bills.html` keys each card's anchor on the identifier alone (`bill-HB943`) and matches a bare `?bill=` on identifier, so after the rollover a bare link opens the wrong bill or none.
- **Departure reasons are not recorded.** `status` holds Resigned, Removed and Deceased; nothing records retired, ran for other office, lost a primary or lost the general.

## Decisions

### D1. Preservation model (the umbrella decision) — Proposed
Options: (1) fresh start, archives only in the repos; (2) keep the people, archive the sessions; (3) add frozen "final 2025-2026" snapshot pages; (4) full on-site archive with a site-wide session selector (150k+ tokens, heavy).
**Proposed:** option 2 for members, the bills proposal in D2 for bills, plus option 3 for the party-unity scorecard only. Defer option 4. Questions that settle it: who uses past sessions (journalists and researchers vs ordinary readers), how much old URLs staying in search matters, whether a returning member's page shows several bienniums.

### D2. Bills: keep the dropdown, freeze the old biennium — Proposed (your idea, refined)
`ga-bills.html` already builds a session dropdown from `ga-bills.json`'s `metadata.sessions` and supports `?session=`. At the rollover, freeze the outgoing file as a static `assets/data/ga-bills-2025-2026.json` that nothing regenerates; the new `ga-bills.json` starts with the 2027 sessions; the dropdown gets a second group for the earlier General Assembly that **lazy-loads** the frozen file (so no visitor downloads both; each is about 7 MB). Changes needed:
1. Qualify the card anchor with the session (not `bill-HB943` alone).
2. A bare `?bill=` defaults to the current biennium. Member pages already send `legislationId` (unique across bienniums) and the page matches on it first; on a miss it should open the bill from the frozen file instead of saying "go to legis.ga.gov".
3. Default view is the current session, not "All sessions".
4. `ga-ballot-measures.html:273` links with a bare `?bill=`; add `legislationId` or a session.
5. The server-rendered `ItemList` JSON-LD lists only current sessions.
6. Sponsor links for non-returning sponsors depend on D3.
Estimate 40-60k tokens. Not verified: that every generator tolerates carrying a new biennium forward; the code comments describe the replacement as an operator rule, but this needs a review.

### D3. Former members keep pages after the rollover — Proposed
Same clean URL (`/ga-legislators/<slug>/`) for current and former members, so Georgia Commons links survive. **Source of the page once the live roster and votes are replaced** is the main design question: build from the frozen archive in `ga-legislators` (about 60-100k tokens), or generate the former-member pages before the rollover and commit them (simpler, but breaks the repo's "generated at build, never committed" convention). Decide which.

### D4. Indexing — Proposed
Former-member pages `noindex`, out of the sitemap, until we decide (avoids a thin-content risk; legislator pages already carry a per-member record summary from the thin-content SEO work). Revisit after the rollover.

### D5. Contact details on former members' pages — Proposed
Hide phone, address and email. Today the legacy shell for a resigned member still shows them. Also fix the "This seat is up for election in 2026" banner, which belongs to the seat, not the person.

### D6. Departure taxonomy and wording — Proposed
Keep `status` for mid-term events (Resigned, Removed, Deceased). Add a separate departure classification filled in at the rollover from certified results and then reviewed by a person: `not-seeking-reelection`, `ran-for-other-office` (with that race's result), `lost-primary`, `lost-general`. Show only the fact and the date ("Lost the 2026 Republican primary", "Did not seek re-election"). Use "defeated" only where results say so; never imply a reason for a withdrawal. The `departingCohort` queue is the natural hook, and certified winners are already recorded in `races.json`. Open: exact wording, who reviews and approves, and whether the classification is public in the roster and `ga-legislators`. Estimate 35-50k tokens. Caveat: the classification can't be final until results and any general-election runoff are certified.

### D7. Scope: which bienniums — Open
Keep former members for any biennium Georgia Commons covers, or only the one just ended?

### D8. Site search — Open
Keep former members out of search, or include them labelled.

### D9. Labelling for Removed and Deceased — Open
None exist today; decide the wording before one does (date and the legislature's note only).

### D10. Party-unity and scorecard treatment — Open
Scorecards are per biennium. Proposed: a frozen final scorecard for 2025-2026; the page follows the current biennium. Needs agreement on what a returning member's page shows across bienniums.

### D11. Roster and votes across the rollover — Open
`ga-member-votes.json` (4.1 MB) is replaced at the rollover. Decide whether a returning member's page shows only the current biennium's votes with a link to the archive, or several.

### D12. Federal side — Open
The 120th Congress convenes in January 2027. I have not checked how the federal pages and data archive (members, votes, party unity, stock trades) handle it.

### D13. Georgia Commons — Open
Tell them that links to members who leave office will be preserved, or hold the sponsor-link request until D1-D4 are settled. Include the licensing questions from `docs/georgia-civic-data-collaboration.md`.

## Timeline

| When | What |
|---|---|
| 2026-11-03 | General election |
| After certification | Results known; a general-election runoff is expected (a results file exists; the date is not verified) |
| Early December (target) | Decisions D1-D6 made, so there is time to build |
| Before 2027-01-11 | `freeze-ga-roster`, then the `--new-biennium` run; the former-member and bills changes live before the roster is replaced |

## Effort (rough)

| Item | Tokens |
|---|---|
| D2 bills: freeze, lazy-load, anchors, `?bill=` | 40-60k |
| D3 former-member pages from the archive | 60-100k |
| D6 departure classifier, fields, tests, review queue | 35-50k |
| D10 frozen scorecard snapshot | 40-60k |

## Verified and not verified

Verified from the repo and the live site: the rollover mechanics above (code and `claude.md`), page generation at deploy, the legacy shell rendering a resigned member (checked for Dexter Sharper only), the `ga-bills.html` behavior, the archive layout in the open-data READMEs, and the counts (11 resigned; about 33 not on their own general ballot, by name match).
Not verified: `RECURRING-TASKS.md` (missing from the repo), every generator's handling of a second biennium, the federal pages, the runoff date, and individual name matches (for example, the suspended Rep. Sharon Henderson appears on the Senate 43 ballot, which needs confirming).
