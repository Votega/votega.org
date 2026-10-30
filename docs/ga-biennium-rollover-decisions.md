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

### D6. Departure classification and wording — Proposed; label wording decided 2026-10-29 (process still open)
**Principle.** `status` keeps recording mid-term events (Resigned, Removed, Deceased) and stays hand-maintained. A **separate** `departure` classification records how a member's service ends at the rollover. The pipeline proposes, a person confirms (the same rule as suspensions), and only the fact and date are shown.

**Categories.** Wording is the display text; use "lost" and "did not run", never "retired", "ousted" or "unseated".

| `departure.type` | Meaning | Display text (example) | Evidence |
|---|---|---|---|
| `resigned`, `removed`, `deceased` | Left mid-term (existing `status`) | "Resigned March 9, 2026" | Roster `status` and `statusDate` (legislature's date) |
| `did-not-run` | No 2026 ballot for any office | "Did not run for re-election in 2026" | Absent from `races.json` ballots and certified results |
| `ran-for-other-office` | On another office's ballot; carries `office` and `result` (`won`, `lost-primary`, `lost-primary-runoff`, `lost-general`, `pending`) | "Ran for Secretary of State in 2026 (won the Republican nomination)" | The other office's certified result |
| `withdrew` | Qualified for their own seat, then withdrew (a category of its own, decided 2026-10-29) | "Withdrew her candidacy for re-election on March 23, 2026" | Secretary of State qualifying record (`Declaration__c: Withdrawn`), plus a dated source for the day (the export has no withdrawal date) |
| `lost-primary` | Lost the primary or its runoff for their own seat | "Lost the 2026 Democratic primary runoff" | Certified primary and runoff results |
| `lost-general` | Lost the November election for their own seat | "Lost the 2026 general election" | Certified general results (after November 3 and any runoff) |
| `unresolved` | The pipeline cannot tell; a person must decide | (not shown until resolved) | n/a |

**Wording decided 2026-10-29.**
- "Did not run for re-election" (not "Not seeking re-election") for a member who never qualified.
- `withdrew` is its own category, for a member who qualified and then withdrew (Sims, Edna Jackson). Where the day is not sourced, say "withdrew after qualifying" with no date.
- Labels do **not** name the winner of a contest a member lost; each links to the certified results page.
- Harbison: "Announced in March 2026 he would retire after the 2026 session. Appeared on the 2026 Democratic primary ballot and received 5,574 votes." "Retire" is allowed here only because it is his own announced word, from the Senate Press Office release; the general rule against "retired" stands for labels we word ourselves.
- Henderson (House 113): the label carries both facts, his Suspended status and that he lost the Senate 43 Democratic primary.
- White Carden (Senate 7): "Won the June 16, 2026 special election for this seat and was sworn in June 26, 2026. Served the remainder of the term and did not run for the full term."

**The 11 members who won another office's nomination (decided 2026-10-29).** All 11 get a label, written only after the November results are certified (and any general runoff): never an interim "nominee" or "pending" text. Nine contests decide them: Attorney General (Miller D vs Strickland R, so one of the two loses), Lieutenant Governor (McLaurin D vs Dolezal R, same), Secretary of State (Fleming), US House 13 (J. Clark), US House 10 (Gaines), and state Senate 7 (Romman), 15 (Reese), 44 (Draper) and 51 (Wade). Verified against the certified files: Miller, Strickland, J. Clark, Gaines, Draper and Reese won their nominations outright (58.8% to 84.6%); McLaurin (210,842 to 173,370 over Nabilah Parkes), Dolezal (375,012 to 316,900), Fleming (430,455 to 236,920), Romman (4,638 to 3,076) and Wade (18,265 to 11,579) won runoffs.

*Proposed refinements (agreed in conversation, to be built with the classifier):*
- Say the member **won**; do not say they hold or represent the seat until sworn in. The state Senate seats are sworn in with the General Assembly on January 11; the statewide and federal swearing-in dates are not verified. Once the new officeholder page exists the label links to it.
- A winner who stays in the General Assembly (Wade, Romman, Draper and Reese move from the House to the Senate) is **not a former member**. The former-members index lists only people missing from the new roster; the label is independent of it and appears on the page of any member whose 2026 outcome differs from a plain re-election. Example: "Won the 2026 general election for State Senate District 44."
- Wording by outcome: won, "Won the 2026 general election for Secretary of State"; lost, "Ran for State Senate District 44 in 2026 (lost the general election)"; decided in a runoff, "general election runoff" and that date. Both members in the Attorney General and Lieutenant Governor races are labelled from the same certified contest, so the labels cannot disagree.
- Prerequisites: a member-to-candidate link for all 11 (only Romman, J. Clark, Fleming and Strickland are linked in `races.json` today), certified November results for the nine contests, and `propose_race_winners.py` as the source of recorded winners.

**Decided 2026-10-30, approval:** Claude drafts every label and its list with sources; the site owner approves all of them before anything publishes. Labels are written in two batches: those already settled (resigned/removed/deceased, did not run, withdrew, lost the primary or runoff) can be drafted now, and those that depend on November (the 11 pending nominations, lost-general) after certification. Approval cutoff: **4 January 2027**, a week before the 11 January rollover (agreed 2026-10-30).

**Decided 2026-10-30, placement:** labels appear only on the former-members index and former members' pages, not on sitting members' pages (note that a mover who wins is not in the index, per the refinement above).

**Decided 2026-10-30, hard gate:** the rollover refuses to run while any departing member is unresolved.

**Qualifying export:** the site owner downloads it from the Secretary of State when needed. The May 19 primary report's candidate list closed with that primary, and the 2026-10-30 re-download matched the committed file, so no further pull is expected for the primary-based labels. The November report is the one that may need pulling, after certification, for any label that depends on it.

**Still undecided:** nothing in the D6 process; the remaining D6 work is writing the labels (batch 1 now, batch 2 after November certification).

**Sources for the cases above.**
- Sims: notarized Affidavit for Withdrawal of Candidacy dated 2026-03-23 (a scanned PDF; per the user it came from the WALB article below, which is the citable source); WALB, 2026-03-23, https://www.walb.com/2026/03/23/state-sen-freddie-powell-sims-announces-resignation-due-husbands-illness/ (announced she would leave at the end of her current term).
- Harbison: WTVM, 2026-03-04, https://www.wtvm.com/2026/03/04/longtime-georgia-senator-not-seeking-re-election/ (not seeking re-election; nothing about the ballot); Senate Press Office release of 2026-03-06, https://senatepress.net/dean-of-the-senate-announces-retirement-following-more-than-33-years-of-public-service.html ("retire after the 2026 legislative session"; nothing about the ballot).
- White Carden: Senate Press Office, https://senatepress.net/sen-adrienne-white-carden-officially-sworn-in-as-georgia-state-senator.html (sworn in Friday, June 26, 2026; datelined June 29); Capitol Beat, 2026-06-29, https://capitol-beat.org/2026/06/new-state-senator-fills-vacancy-restores-senate-to-capacity/ (won the June 16 special election with just over 51% against Aizaz Shahbaz Shaikh (R); succeeded Nabilah Parkes (D), who resigned to run for lieutenant governor; serves the remainder of that term; the November full-term race is Shaikh against Ruwa Romman).
- Edna Jackson, Sims and Harbison's qualifying status: the Secretary of State qualifying export, as below. The Members service (`GetMember`, checked for Harbison and Sims) has no candidacy field and no `DateVacated`.

Sourcing for withdrawals: a member who withdrew after qualifying needs a source before the label says so, and now has one: the Secretary of State's qualifying export, which we already hold as `assets/data/ga-legislative-candidates.json` (a `Declaration__c` status of Qualified, Withdrawn or Disqualified for every candidate, as of its `updatedAt` of 2026-05-06). It is a manual download of the qualifying report from the Secretary of State, not a scheduled pull, so it does not refresh itself and a withdrawal after the download will not appear until someone downloads it again. A second download of the May 19 primary report was compared on 2026-10-30 (`Qualified Candidates(1).csv`, 2,380 rows): for the State House and Senate it matches the committed file on every candidate and status (532 Qualified, 10 Withdrawn, 3 Disqualified; the only differences are name spellings, such as "BRIAN L PRINCE" against "BRIAN LAMAR PRINCE"), and it has no withdrawal dates either. A November-election download holds fewer candidates, so the primary report is the one to use for withdrawals. It carries no withdrawal date, so a dated label also needs a second source. Where there is no source, use "Not on the 2026 ballot".

**Matching rules.** Match on the roster member's full name, chamber and district, never surname alone, and handle nicknames in quotes (Tremaine "Teddy" Reese) and a roster name that differs from the ballot name ("White Carden" vs "White", "Powell Sims" vs "Powell"). Do **not** trust the results files' `incumbent` flag: besides Payton and Harbison, it also omits Nelson (House 130), Mason (House 94), Thomas (Senate 53) and Halpern (Senate 39), all on their own ballots.

**Why (evidence from the 2026 primary data).** Two automated methods disagreed, and a person had to settle each case:
- The results' `incumbent` flag found only 2 incumbents who lost (House 117 Santos, House 157 Werkheiser; both also have editorial notes in `ga-race-candidate-overrides.json`). It missed **Alvin Payton** (House 177, seated by special election, flagged non-incumbent, lost both the primary and the runoff; no editorial note) and **Ed Harbison** (Senate 15, flagged non-incumbent, second in the primary with 5,574 votes behind Tremaine "Teddy" Reese). **Harbison needs a fact-only label.** The overrides file says he "announced March 4, 2026 he would not seek re-election," and the Senate Press Office release of March 6, 2026 says he "will retire after the 2026 legislative session" (neither says anything about the ballot). The Secretary of State's qualifying export shows he **qualified on 03/06/2026 and was never withdrawn**, and the certified results have him on the ballot with 5,574 votes. His `"withdrawn": true` flag in `ga-race-candidate-overrides.json` was unsupported and was removed on 2026-10-29. Label (decided 2026-10-29): "Announced in March 2026 he would retire after the 2026 session. Appeared on the 2026 Democratic primary ballot and received 5,574 votes." Do not label him `did-not-run` (he was on the ballot) or "lost" alone (it implies he campaigned).
- Surname matching put **Edna Jackson** (House 165) on a primary ballot: a false match on other Jacksons. She is not on the certified ballot. The qualifying export shows she **qualified on 03/04/2026, then withdrew** (status Withdrawn, incumbent), and the overrides file records that she announced her retirement on March 19, 2026. That is `withdrew`, not `did-not-run`, and her race note was updated on 2026-10-29 to say so.
- **Freddie Powell Sims** (Senate 12): the repo's race note said she "resigned effective March 23, 2026," which was wrong. A notarized **Affidavit for Withdrawal of Candidacy**, dated March 23, 2026, withdraws her candidacy for Senate 12 in the 2026 primary and general elections; the qualifying export shows "Freddie Powell", incumbent, qualified 03/03/2026, **Withdrawn**; and WALB reported on March 23 that she announced she would step down at the end of her current term. `ga-members-overrides.json` is right that she is still the sitting senator (legis.ga.gov, and no `DateVacated` in the Members service). Her race note was corrected on 2026-10-29. Classification: `withdrew`. The affidavit's provenance (who published it) should be recorded before it is cited.
- Both primary files are certified (May 19, last updated June 5; the June 16 runoff, last updated August 20), and the committed primary results match the SoS export exactly for all 543 of 544 contests (one name spelling differs: "Andra" vs "Andre" Stafford, House 42). The runoff confirms **Payton lost the Democratic runoff 611 to 858**, Santos lost 531 to 3,832, and the runoff file confirms five nominations: Wade (Senate 51), Romman (Senate 7), McLaurin (Lieutenant Governor, D), Dolezal (Lieutenant Governor, R) and Fleming (Secretary of State).
- Of the 33 sitting members not on their own seat's general ballot (re-checked 2026-10-29 against the certified files and the qualifying export): **18 ran for another office** (the earlier list of 17 omitted Bill Cowsert, who lost the Republican Attorney General primary with 241,391 votes), **11 are on no primary ballot for their own seat**, and **4 are on their own primary ballot** (Santos, Werkheiser, Payton lost; Harbison above). The 11 break down as: 8 never qualified (absent from the qualifying export: Dunahoo, Jan Jones, Cannon, Lynn Smith, McClain, Mack Jackson, Gilliard, Parent), 2 qualified and withdrew (Sims, Edna Jackson), and **Adrienne White Carden** (Senate 7), who won the **special election** of June 16, 2026 (qualifying export: "Adrienne Annice White", Qualified, Senate 7 special; certified count 8,510 to 8,131 over Shaikh, 51.1%; it was a head-to-head special election, not a runoff, and appears in the June 16 runoff file only because it was held that day) and did not run for the full term. She succeeded Nabilah Parkes (resigned March 13, 2026), was sworn in on June 26, 2026, and serves the remainder of Parkes's term; the November full-term race is Shaikh against Romman. She has no 2026 override note. Sources are listed above. Of the 18, 11 won a nomination (Wade, Miller, Draper, Romman, J. Clark, Fleming, Gaines, Reese, McLaurin, Dolezal, Strickland) and 7 trailed (D. Jackson, D. Clark, Henderson in Senate 43, E. Jones, Tillery, Gooch, Cowsert). The final outcome of the 11 is pending the general election. Henderson (House 113) is also Suspended; decide whether his label carries both. Matching here is by name, chamber and district.

**Process.**
1. A classifier reads the roster, `races.json` and the certified results, and writes a review queue (extending `departingCohort`) with the evidence for each member.
2. A person confirms or corrects each entry in an overrides file keyed by `legisGaGovId`, the way `ga-members-overrides.json` works for statuses.
3. **Hard gate:** the rollover run fails if any departing member has an `unresolved` or unconfirmed classification.
4. Confirmed entries flow into the former-members index (D3).
Build the classifier and queue now against the primary and runoff data; finish after the general election and any runoff are certified.

**Open decisions:** (a) the label wording is decided for every case, including the 11 pending nominations (written after November is certified; the refinements above are proposed); (b) who approves entries and by when; (c) whether `departure` is public in the live roster and `ga-legislators` or only in the former-members index and pages (proposed: index and pages only; the live roster until the member actually leaves); (d) whether the hard gate is acceptable; (e) where the qualifying export comes from and how it is refreshed (it is dated 2026-05-06 and has no withdrawal dates), and who records the provenance of the Sims affidavit. Estimate 35-50k tokens.

**Page behavior to fix alongside (found 2026-10-29, not yet scheduled).** The member page's "Running for…" banner (`_includes/entity/ga-legislator.html`) does not read results, so Henderson and Gooch, who lost their primaries, still show it; it appears for only 6 of the 18 members who ran for another office, because the races builder links a candidate to a roster member only for the seat's own incumbent and cross-office links are hand-added; and the seat banner ("This seat is up for election in 2026") describes the seat, not the person. The Senate 7 special election has no race record in `races.json`. Alvin Payton's candidate link was fixed on 2026-10-29 (the incumbent name rule failed on "Jr").

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

### D12. Federal side — Partly decided 2026-10-29 (checked from the code, nothing run)
The 120th Congress convenes **January 3, 2027**, eight days before the General Assembly. What the code does at the turnover:
- `lib/congress_session.py` derives the Congress number from the UTC date, so the four generators switch to the 120th at 00:00 UTC on January 3, about 11 hours before it convenes at noon Eastern.
- The votes pipeline and publisher were built for a new Congress (empty start exempt from the id-set check, no roll-call floor, empty votes non-fatal), **but nothing archived the 119th**: a run builds only the 120th and the sibling repo's `data/` is replaced in place.
- The roster generator exits without committing if more than 25 members are flagged no longer serving (`generate_current_members_data.py`); a normal turnover exceeds 25, so expect that run to fail until someone intervenes. Not verified against Congress.gov's actual timing.
- `curated-federal-bills.json` is the 119th's list; the 120th has no key votes until one is curated.
- `/us-congress/<slug>/` pages build from `current-members.json`, so a departed member's page disappears (the federal side of D3). Georgia's House members not returning: Carter (GA-1) and Loudermilk (GA-11), not on their seats' November ballots; Collins (GA-10), running for Senate; Blair (GA-13), who won the special election (July 28, runoff August 25) after David Scott's death but finished third in the regular primary. Clay Fuller (GA-14) won the April special and is the nominee.

**Decided 2026-10-29: freeze the 119th into `sessions/119th/` of `Votega/ga-federal-legislators`, Georgia delegation only, sibling repo only (no on-site copy), in two freezes.** Built: `publish_federal_delegation.py freeze [slug] [--final] [--overwrite]` and the manual workflow `freeze-federal-delegation.yml`. It writes the roster, votes, flat CSVs, the party-unity scorecard, and each member's full sponsorship record (raw compact slices plus a flat `sponsorship.csv`), with per-path schemas, a manifest (`freeze.json`) and a README, and refuses to file one Congress's data under another's name. Daily publishes cannot write into `sessions/`, and every live CSV now ends with a `congress` column. **Provisional freeze now; the FINAL freeze must run by January 2, 2027,** after the last roster, votes and sponsorship runs have committed and before the first run of the new Congress. Dry-run output and tests verified; the first real publish has not been run.

**Still open:** whether departed federal members keep a page, the transition guard on the roster run, who curates the 120th's key votes, and whether the D6 departure labels extend to federal members.

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
