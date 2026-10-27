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
Same clean URL (`/ga-legislators/<slug>/`) for current and former members, so Georgia Commons links survive. Pages are still **built at deploy**, so the repo's "generated at build, never committed" rule holds; what changes is their source once the live roster and votes are replaced.
**Proposed source: a former-members index written at the final freeze.** At the final `freeze-ga-roster` (see Timing below), and whenever a member departs, write a compact committed index: identity (`legisGaGovId`, roster id), name, party, chamber, district, term dates, departure classification (D6), successor, and page URL. Freeze each former member's per-member vote and sponsorship files alongside it (small ID-keyed files the generators already produce; the 11 resigned members have both today). The page builder reads the index plus those files, and survives the roster replacement.
Not verified: whether the generators delete those per-member files for members dropped at the rollover, which determines how much needs freezing. Estimate 60-100k tokens.

### D4. Indexing — Proposed
Former-member pages `noindex`, out of the sitemap, until we decide (avoids a thin-content risk; legislator pages already carry a per-member record summary from the thin-content SEO work). Revisit after the rollover.

### D5. Contact details on former members' pages — Proposed
Hide phone, address and email. Today the legacy shell for a resigned member still shows them. Also fix the "This seat is up for election in 2026" banner, which belongs to the seat, not the person.

### D6. Departure classification and wording — Proposed, worked through 2026-10-27
**Principle.** `status` keeps recording mid-term events (Resigned, Removed, Deceased) and stays hand-maintained. A **separate** `departure` classification records how a member's service ends at the rollover. The pipeline proposes, a person confirms (the same rule as suspensions), and only the fact and date are shown.

**Categories.** Wording is the display text; use "lost" and "did not run", never "retired", "ousted" or "unseated".

| `departure.type` | Meaning | Display text (example) | Evidence |
|---|---|---|---|
| `resigned`, `removed`, `deceased` | Left mid-term (existing `status`) | "Resigned March 9, 2026" | Roster `status` and `statusDate` (legislature's date) |
| `did-not-run` | No 2026 ballot for any office | "Did not run for re-election in 2026" | Absent from `races.json` ballots and certified results |
| `ran-for-other-office` | On another office's ballot; carries `office` and `result` (`won`, `lost-primary`, `lost-primary-runoff`, `lost-general`, `pending`) | "Ran for Secretary of State in 2026 (won the Republican nomination)" | The other office's certified result |
| `lost-primary` | Lost the primary or its runoff for their own seat | "Lost the 2026 Democratic primary runoff" | Certified primary and runoff results |
| `lost-general` | Lost the November election for their own seat | "Lost the 2026 general election" | Certified general results (after November 3 and any runoff) |
| `unresolved` | The pipeline cannot tell; a person must decide | (not shown until resolved) | n/a |

Wording choices to confirm: whether labels name the winner (default: no, link to the results page); "did not run" vs "not seeking re-election"; a member who withdrew after qualifying needs a source (the Secretary of State's withdrawal list) before the label says so, otherwise use "Not on the 2026 ballot".

**Matching rules.** Match on the roster member's full name, chamber and district, never surname alone. Do **not** trust the results files' `incumbent` flag.

**Why (evidence from the 2026 primary data).** Two automated methods disagreed, and a person had to settle each case:
- The results' `incumbent` flag found only 2 incumbents who lost (House 117 Santos, House 157 Werkheiser). It missed **Alvin Payton** (House 177, seated by special election, flagged non-incumbent, lost both the primary and the runoff) and **Ed Harbison** (Senate 15, in office since 1993, flagged non-incumbent, lost to Tremaine "Teddy" Reese). So four members lost primaries.
- Surname matching put **Edna Jackson** (House 165) on a primary ballot: a false match on other Jacksons. She appears on no 2026 ballot.
- **Freddie Powell Sims** (Senate 12) is on a `races.json` primary ballot but absent from the certified primary results: unresolved (withdrew or not certified).
- Of the 33 sitting members not on their own seat's general ballot: 11 did not run (the 10 found earlier plus Jackson), 4 lost primaries, 1 is unresolved, and 17 ran for another office. By the results, 11 of those 17 appear to have won a nomination (Wade, Miller, Draper, Romman, J. Clark, Fleming, Gaines, Reese, McLaurin, Dolezal, Strickland), 6 trailed (D. Jackson, D. Clark, Henderson in Senate 43, E. Jones, Tillery, Gooch). The final outcome of the 11 is pending the general election. Matching here is by name and approximate.

**Process.**
1. A classifier reads the roster, `races.json` and the certified results, and writes a review queue (extending `departingCohort`) with the evidence for each member.
2. A person confirms or corrects each entry in an overrides file keyed by `legisGaGovId`, the way `ga-members-overrides.json` works for statuses.
3. **Hard gate:** the rollover run fails if any departing member has an `unresolved` or unconfirmed classification.
4. Confirmed entries flow into the former-members index (D3).
Build the classifier and queue now against the primary and runoff data; finish after the general election and any runoff are certified.

**Open decisions:** (a) the exact wording above; (b) who approves entries and by when; (c) whether `departure` is public in the live roster and `ga-legislators` or only in the former-members index and pages (proposed: index and pages only; the live roster until the member actually leaves); (d) whether the hard gate is acceptable. Estimate 35-50k tokens.

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

### D14. Entry points to former members and past sessions — Proposed
- **A "Former Legislators" card on `/find-my-reps`.** The page is a hub of entry cards (Federal Representatives, Georgia State Representatives) in a two-column grid, so a third card would be a full-width strip. Name it for what is behind it (people, not sessions); it is accurate today because 11 members have already resigned. It links to a directory of former members grouped by session and chamber (name, party, district, term dates, how they left, successor, page link).
- **A "Previously held by …" row in the address lookup**, per district, linking to that seat's former member. The lookup shows only sitting members today ("No sitting … found" for an empty seat). It relies on district numbers staying the same, which holds under the 2023 plans; label it with the plan if Georgia redraws.
- **Optional "Past sessions" hub** for 2025-2026: former members, the final scorecard (D10), bills (`ga-bills` with its session dropdown, D2), and the roster as frozen at sine die.
- Federal former members (the two vacated congressional seats, for example) follow the same pattern, so the card should say legislators broadly; D12 is still unchecked.
Depends on D3 (the index), D6 (wording) and D4 (indexing).

## Timing: when to run the final freeze

**What exists today (checked 2026-10-27).** `Votega/ga-legislators/sessions/2025-2026/members.json` is already published, but it is a **provisional snapshot from 2026-08-22**, generated from the retired Open States producer: 250 members (236 sitting, 10 Resigned, 3 Vacant placeholders, 1 Suspended). It predates the SOAP roster, the 11th resignation, the executives removal and `votegaUrl`. The workflow's own comments call the freeze a deliberate action at sine die.

**The guard checks existence, not freshness.** `--new-biennium` refuses to run unless `sessions/<slug>/members.json` returns HTTP 200 (`outgoing_archived()` in `generate_ga_members_soap.py`). The August snapshot already satisfies that, so the rollover could proceed against a stale freeze, and the code notes that once it writes "the outgoing roster is gone from the repo."

**What changes after sine die, so a sine-die-only freeze misses it:** resignations, suspensions and deaths; special-election successors seating (Alvin Payton now holds House 177); and the 2026 election outcomes, which decide who returns. The roster's departure classification (D6) can only be filled in once results are certified.

**What a freeze is for.** It records who served in the General Assembly. Returning members are not "former" in it. The classification belongs in the former-members index (D3), not in edits to the snapshot.

| Option | When | Good | Bad |
|---|---|---|---|
| A. Sine die only (as designed) | Once, at the end of the session | Fixes "who served"; no more votes arrive | Misses everything after; today's file is already stale |
| B. After the election only | After certification and any runoff, before the rollover | Knows outcomes and final statuses | A single run before a hard deadline; no safety net if the date is missed |
| **C. Two steps (proposed)** | Refresh now as a safety net, then re-freeze after results are certified | The final file is current and the early one protects against an early rollover | Two runs; the re-freeze overwrites the first (the publisher updates existing files; I have not tested an overwrite) |

**Proposed sequence**
1. **Now:** re-run `freeze-ga-roster` for 2025-2026 so the archive reflects the SOAP-era roster (11 Resigned, `votegaUrl`, current statuses).
2. **After certification and any general-election runoff:** final `freeze-ga-roster` (overwrites step 1), then generate the departure classification (D6) and the former-members index (D3) from the certified results.
3. **Before 2027-01-11:** confirm the frozen file matches the live roster (same IDs and statuses). Then run `update-ga-members` with `new_biennium` once legis.ga.gov lists the new session (not verified how soon it does).
4. **Strengthen the guard (about 10-15k tokens):** replace the existence check with a freshness check, for example the frozen roster's member IDs and statuses must equal the live roster's, and fail with the differences. It also makes the final freeze impossible to forget.
5. Assign an owner and a calendar reminder for steps 2-3.

Open: the exact dates (certification and runoff dates are not verified), whether another special session could still be called before January, and whether the final freeze should also snapshot votes.

## Timeline

| When | What |
|---|---|
| 2026-11-03 | General election |
| After certification | Results known; a general-election runoff is expected (a results file exists; the date is not verified). **Final freeze (step 2 above)** |
| Early December (target) | Decisions D1-D6 made, so there is time to build |
| Before 2027-01-11 | `freeze-ga-roster`, then the `--new-biennium` run; the former-member and bills changes live before the roster is replaced |

## Effort (rough)

| Item | Tokens |
|---|---|
| D2 bills: freeze, lazy-load, anchors, `?bill=` | 40-60k |
| D3 former-member pages from the archive | 60-100k |
| D6 departure classifier, fields, tests, review queue | 35-50k |
| D10 frozen scorecard snapshot | 40-60k |
| D14 card, seat-history row, directory page | 20-35k |
| Freeze guard (freshness check) | 10-15k |

## Verified and not verified

Verified from the repo and the live site: the existing 2026-08-22 roster archive and the existence-only freeze guard, the `/find-my-reps` card layout, the rollover mechanics above (code and `claude.md`), page generation at deploy, the legacy shell rendering a resigned member (checked for Dexter Sharper only), the `ga-bills.html` behavior, the archive layout in the open-data READMEs, and the counts (11 resigned; about 33 not on their own general ballot, by name match).
Not verified: `RECURRING-TASKS.md` (missing from the repo), every generator's handling of a second biennium, the federal pages, the runoff date, and individual name matches (for example, the suspended Rep. Sharon Henderson appears on the Senate 43 ballot, which needs confirming).
