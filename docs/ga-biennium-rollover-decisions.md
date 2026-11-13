# January 2027 biennium rollover: decisions needed

Drafted 2026-10-27; D7-D11 and D13 given proposals 2026-10-30, so every decision now has one. Decision doc for the team. Nothing here is built yet. Statuses: **Proposed** (a default is suggested and awaits agreement), **Open** (not yet worked through).

The 159th General Assembly convenes on **2027-01-11**, and the 120th Congress in early January. The live roster and several data files turn over, and today's design does not say what happens to the people, bills and records of the outgoing session. This doc lists what happens, what breaks, and what to decide.

## What happens at the rollover (verified from the code and `claude.md`)

- The outgoing roster is frozen into `Votega/ga-legislators` (`freeze-ga-roster` workflow, run before the session bump). Then `update-ga-members --new-biennium` replaces the live roster: it requires the frozen copy, **drops members who do not return**, keeps non-voting-chamber records (Lt. Governor), stamps `metadata.rollover`, and writes `incomingCohort`, `departingCohort` and `newMemberNameReview` review queues. The procedure and deadline are in `docs/RECURRING-TASKS.md` §3 (lines 311-444; read 2026-11-04). It has six steps: tag departure overrides with `_session`, freeze the outgoing roster, bump `lib/ga_sessions.py` together with the rollover run, run `update-ga-members` with `new_biennium`, work the review queues, and mind the sibling bills and votes halves. It has **no step for freezing the on-site copies this doc proposes** (see Timing).
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

### D3. Former members keep pages after the rollover — **Decided 2026-11-13: see `docs/superpowers/specs/2026-11-13-ga-legislator-page-permanence-design.md`** (one page per person, biennium switch built now, every member's data frozen per biennium, the 11 resigned members get pages now)
Same clean URL (`/ga-legislators/<slug>/`) for current and former members, so Georgia Commons links survive. Pages are still **built at deploy**, so the repo's "generated at build, never committed" rule holds; what changes is their source once the live roster and votes are replaced.
**Proposed source: a former-members index written at the final freeze.** At the final `freeze-ga-roster` (see Timing below), and whenever a member departs, write a compact committed index: identity (`legisGaGovId`, roster id), name, party, chamber, district, term dates, departure classification (D6), successor, and page URL. Freeze each former member's per-member vote and sponsorship files alongside it (small ID-keyed files the generators already produce; the 11 resigned members have both today). The page builder reads the index plus those files, and survives the roster replacement.
Not verified: whether the generators delete those per-member files for members dropped at the rollover, which determines how much needs freezing. Estimate 60-100k tokens.

**Revision proposed 2026-11-04: one page per person with a biennium selector, not a separate former-member page.** Same direction as the federal proposal in D12, adapted for the General Assembly. The `/ga-legislators/<slug>/` URL stays single; a member who served in more than one biennium gets a selector (`?biennium=2025-2026`), defaulting to their latest, and a member with one sees a plain label. A returning member's page and a departed member's page are therefore the same template, and the former-members index (above) lists only people missing from the new roster.
- **Everything follows the selection**, not just votes: chamber, district, seat, committees, leadership, party, term dates, the D6 label, sponsorship and scorecard. This matters more here than federally: Wade, Romman, Draper and Reese move from the House to the Senate, so the header changes between selections. No cross-biennium totals or averages (D10). Contact details show only for the live biennium (D5).
- **Identity is `legisGaGovId`**, never the roster `id` (opaque) or the slug. The selector resolves a person across bienniums by it.
- **Bill numbers restart each biennium**, so sponsorship rows carry the biennium and bill links use `legislationId` (D2).
- **Data layout needed (checked 2026-11-04 against the files and the include):** all three per-member datasets are single-biennium today, and each is keyed differently, so the per-biennium work is not uniform.
  - **Votes:** `ga-votes-index.json` (1.2 MB, `metadata.biennium` "2025-2026") plus `ga-votes/<roster id slug>.json` (about 14 KB). Keyed by the opaque roster `id`.
  - **Sponsorship:** `ga-sponsorship-index.json` (`metadata.biennium` "2025-2026") plus `ga-sponsorship/<legisGaGovId>.json`. Keyed by `legisGaGovId`, the identity key, and already groups bills by session id (`2025_26`, `2026_ss`) *inside* a biennium. The page renders one biennium heading and per-session subheadings.
  - **Party unity:** one file, `ga-party-unity.json` (about 117 KB, `metadata.biennium` "2025-2026"), with no session dimension, read by the member page and by `ga-party-unity.html`. `members` is a flat list of 235 records, one per roster `id`, each with `name`, `party`, `chamber`, `district`, `totalRollCalls`, `cast`, `missed`, `participationRate`, `partyUnity`, `partyLineVotes`, `votedWithParty`, `independenceRate` and `presidingOfficer`. Chamber, district and party are inside the record, so a frozen file per biennium is self-describing and a mover is simply two records in two files. It is small enough to freeze one file per biennium (D10).
  - So the work is a per-biennium path for each (for example `ga-votes/<biennium>/`), the frozen 2025-26 set placed there at the final freeze, and a per-member list of bienniums served. Because votes are keyed on the roster `id` and sponsorship on `legisGaGovId`, the selector must resolve both for a person; the roster `id` never changes once assigned, so it is stable across bienniums, but a member first seated in 2027 may be `legis-<n>` and have no 2025-26 votes. The lazy-loaded slices make the selector free until used.
  - **Other consumers (checked 2026-11-04):** `ga-majority-tracker.html` and `ga.js` fetch only `ga-members.json` and (tracker) `races.json`, so they are unaffected by per-biennium vote files; they depend on the live roster being the sitting General Assembly, which the rollover already guarantees, and the tracker filters out Resigned, Removed and Deceased members. `publish_ga_bills.py` already archives per session under `sessions/<slug>/` with a `latest.json` pointer and re-emits closed sessions byte-stable, and `lib/ga_sessions.py` fixes `BIENNIUM = "2025-2026"` as a constant, so the publisher is session-aware but the biennium constant is a rollover edit (RECURRING-TASKS §3 territory).
  - **Generators and the rollover (checked 2026-11-04, read from the code, nothing run):** the SOAP bills, votes and members producers are all driven by one module, `scripts/lib/ga_sessions.py` (`SESSION_NAMES`, `ACTIVE_SESSION`, `BIENNIUM`, with `LEGIS_SESSIONS` as an offline fallback). Their docstrings state the design: at the rollover `SESSION_NAMES` holds only the new biennium, so nothing is preserved and the run is a single-session fetch with no full refresh. So the rollover is a **config edit plus a run**, and the outgoing biennium is *dropped from the live files*, not carried forward. That answers D2's open item, with a consequence for this proposal: the old biennium survives only in the publishers' `sessions/<slug>/` archives, so **every frozen on-site copy (bills, vote index and slices, sponsorship, party unity) must be made before the config edit**, and nothing will regenerate them afterwards. Preservation inside the producers is within a biennium (closed session carried forward, active session re-fetched), not across bienniums.
  - **The slice builders delete stale slices.** `build_member_votes_slices.py` and `build_sponsorship_slices.py` both clear their output directory before writing (the sponsorship one names a biennium rollover as the reason). After the rollover, a non-returning member's live slices are removed, which confirms D3's "not verified" item: former members' per-member files must be frozen at the final freeze, into a per-biennium path the builders do not clear, or they are gone.
  - **`enrich_bills_with_party_votes.py` is safe across the rollover but must not be re-run on a frozen file.** It joins a bill's passage votes to roll calls on (normalized bill, ISO date, yea, nay, caption) within the one votes file it is given, and tallies by party using the *live* `ga-members.json` (`party_map`). After the rollover both inputs are the new biennium, so bill-number reuse cannot collide. Run against the frozen 2025-26 bills file it would look up departed members in the new roster and undercount their party's votes, so the frozen file's baked-in `partyTally` is the record and the enricher must never touch it. The generator docstring already notes closed sessions are carried forward to keep this enrichment.
  - **`generate_party_unity.py` (checked 2026-11-04, read from the code and the committed files, not run):** it scores only members who are in the live `ga-members.json`, hold a voting-chamber seat and are not in `DEPARTED_STATUSES` (Resigned, Removed, Deceased, Vacant), using the live roster for party. Two consequences. (1) **The committed 2025-26 scorecard already omits the 11 Resigned members** (235 scored of 247 roster rows; the 12 missing are the 11 Resigned plus one with no status), although they cast votes. A "final" frozen scorecard made with this script is therefore incomplete for exactly the people D3 gives former-member pages to, so freezing needs either a flag to include departed members or a separate generation from the frozen roster. (2) After the rollover the live roster no longer holds the outgoing class, so it can only produce the new biennium; re-running it against the old votes file would drop every non-returning member and mis-tally party lines. The frozen scorecard must be generated before the bump and never regenerated.
  - **`generate_curated_ga_bills.py` (same basis):** the curated list is 9 bills, 7 from `2025_26` and 2 from `2023_24`. It keys everything on (session, identifier), so a repeated identifier across bienniums cannot collide, and it reads the live `ga-bills.json` and `ga-member-votes.json` first, then falls back to SOAP for a session those do not cover. After the bump, all seven 2025-26 entries fall out of the local record and are re-fetched over SOAP like the 2023-24 ones already are (`legis_session_id` resolves a `YYYY_YY` tag from `ga-legis-sessions.json`, so no code edit). Two losses: party breakdowns use the live roster's `party` lookup, so departed members are missing from the counts, and status tags come only from the live bills file, so an older bill shows none. A bill it cannot source keeps its previously published record. So the key-votes data degrades quietly rather than failing; the frozen 2025-26 bills file (D2) should be added as a second local source, or the 2025-26 curated output frozen as it stands.
  - **The rollover sequence** is `docs/RECURRING-TASKS.md` §3, which was read but not run; nothing in this section has been executed.
- **Template weight:** `_includes/entity/ga-legislator.html` is about 222 KB, mostly one inline script. Adding a selector is the natural moment to move that script to a cached external file (the live item in `claude.md`'s scaling section), but it can be done separately.
- **One abstraction for both sides.** Build a generic "term" parameter (a Congress or a biennium) once, with the frozen index, frozen per-member files and retired-record rule shared by D3 and D12.
- Estimate 70-110k tokens including the per-biennium data paths (the earlier 60-100k for separate pages was similar; the selector trades new pages for template changes). Rough, not measured.

### D4. Indexing — **Reversed 2026-11-13: former-member pages are indexed and in the sitemap** (Georgia Commons links them; see the page-permanence spec). Original proposal kept below for the record
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

### D7. Scope: which bienniums — Proposed 2026-10-30
Keep former members for any biennium Georgia Commons covers, or only the one just ended?

**Proposed: the biennium just ended (2025-2026) only, and make the scope a property of the former-members index (D3) rather than of the page builder**, so widening it later is a data change rather than a code change.

Georgia Commons publishes under a per-session URL space and today covers `2025-2026` (`docs/georgia-civic-data-collaboration.md`, checked 2026-10-23), so that is the only biennium whose sponsor links this rollover can break — which is the thing D13 exists to protect. Every earlier biennium's roster already lives in `Votega/ga-legislators/sessions/`, which D1 treats as the archive, and no earlier biennium has a frozen on-site roster to build pages from. The SOAP service reaches back to 2001, so widening this stays possible; doing it now would be building for a reader nobody has asked about.

Settles it: whether Georgia Commons backfills earlier sessions, and whether anyone asks for pre-2025 member pages.

### D8. Site search — Proposed 2026-10-30
Keep former members out of search, or include them labelled.

**Proposed: keep them out — and note that the mechanism already exists and needs no new search code.**

`VoteGA.entityUrls.isRetired()` (`assets/scripts/entity-urls.js`) is generic over entity type: it maps `rec.category` through `MAP_FOR_CATEGORY`, which already contains `'GA Legislator' -> 'ga-legislator'`, then looks the id up in `maps.retired[kind]`. `_includes/search.html` filters every entity record through it. So writing a `retired['ga-legislator']` bucket into `entity-urls.json` hides former members from site search the same way 256 off-ballot candidates are hidden today, with no change to the search include at all.

That also collapses D4 (noindex) and this into one rule, which is the point: a former member's page keeps working for whoever already holds the link, and is not advertised. The D14 directory is the deliberate way in.

**The candidate precedent carries a warning worth repeating here: hide the record, never delete it.** The page builders read `search-entities.json` back to decide which pages to generate, so dropping a record deletes the page — the opposite of what D3 is for.

Not verified: that `search-entities.json` still carries a record for a member the live roster no longer lists. That depends on `generate_search_corpus.py` reading D3's index, which does not exist yet, so it is a requirement on D3 rather than a separate decision.

### D9. Labelling for Removed and Deceased — Proposed 2026-10-30
None exist today; decide the wording before one does (date and the legislature's note only).

**Proposed, following D6's principle that only the fact and the date are shown:**
- Deceased: "Died in office, <date>."
- Removed: "Removed from office, <date>." — plus the legislature's own note where there is one, quoted and attributed, never paraphrased.
- No inferred reason, no link to coverage, and no euphemism ("left office").

Also suppress the election framing for these two: a member who died or was removed did not lose a race, and the "This seat is up for election" banner belongs to the seat rather than the person — the same correction D5 makes.

Settles it: a person reviewing the first real case. None exist today, which is exactly why the wording is worth agreeing now rather than under time pressure.

### D10. Party-unity and scorecard treatment — Proposed 2026-10-30
Scorecards are per biennium. A frozen final scorecard for 2025-2026; the page follows the current biennium. Needs agreement on what a returning member's page shows across bienniums.

**Proposed: freeze a final 2025-2026 scorecard and keep the live page on the current biennium** (option 3 in D1, for this page only, as D1 already proposes).

Cheaper than it looks: `assets/data/ga-party-unity.json` is 117 KB, already carries `metadata.biennium` (`"2025-2026"`) and a per-session vote count, and `ga-party-unity.html` already builds its open-data link from that biennium (`scorecardRepoUrl()`). The page is biennium-aware today, so this is a static copy plus a selector, not a redesign.

**A returning member's page shows the current biennium's score with a link to the frozen one, and never an average across bienniums** — different chamber, different colleagues and a different universe of votes make a combined figure a number with no referent.

### D11. Roster and votes across the rollover — Proposed 2026-10-30
`ga-member-votes.json` (4.0 MB) is replaced at the rollover. Decide whether a returning member's page shows only the current biennium's votes with a link to the archive, or several.

**Proposed: the current biennium only, with a link to the archive.**

Measured 2026-10-30: `ga-member-votes.json` is 4.0 MB for one biennium — 2,418 roll calls across 246 members, already on the compact v2 schema — and every `/ga-legislators/<slug>/` page fetches the whole file. Carrying two bienniums doubles the largest download on that page for a minority of readers, and `Votega/ga-legislators/sessions/` already holds the history in a form a researcher can take away.

For a **former** member, freeze their own slice at the final freeze, as D3 proposes, rather than keeping the monolith alive to serve a handful of people.

**Correction 2026-11-04: the paragraph above overstated the page's cost.** The GA member page does NOT fetch the 4.0 MB monolith. It fetches `ga-votes-index.json` (1.2 MB) plus one member slice from `assets/data/ga-votes/<id>.json` (about 14 KB at most; 245 slices), as `_includes/entity/ga-legislator.html` documents. No browser fetches the monolith (checked 2026-11-04: the mentions in `ga.js` and `ga-majority-tracker.html` are comments; they fetch `ga-members.json`). It is a build-time input only, read by the update workflows and `enrich_bills_with_party_votes.py`. So per-member slicing exists already, and the prerequisite for several bienniums is not slicing but making the index and slices per-biennium (see the revision under D3). The selector in D3 therefore reopens this decision: showing a past biennium costs one extra lazy slice, not a second 4 MB download.

### D12. Federal side — Partly decided 2026-10-29 (checked from the code, nothing run)
The 120th Congress convenes **January 3, 2027**, eight days before the General Assembly. What the code does at the turnover:
- `lib/congress_session.py` derives the Congress number from the UTC date, so the four generators switch to the 120th at 00:00 UTC on January 3, about 11 hours before it convenes at noon Eastern.
- The votes pipeline and publisher were built for a new Congress (empty start exempt from the id-set check, no roll-call floor, empty votes non-fatal), **but nothing archived the 119th**: a run builds only the 120th and the sibling repo's `data/` is replaced in place.
- The roster generator exits without committing if more than 25 members are flagged no longer serving (`generate_current_members_data.py`); a normal turnover exceeds 25, so expect that run to fail until someone intervenes. Not verified against Congress.gov's actual timing.
- `curated-federal-bills.json` is the 119th's list; the 120th has no key votes until one is curated.
- `/us-congress/<slug>/` pages build from `current-members.json`, so a departed member's page disappears (the federal side of D3). Georgia's House members not returning: Carter (GA-1) and Loudermilk (GA-11), not on their seats' November ballots; Collins (GA-10), running for Senate; Blair (GA-13), who won the special election (July 28, runoff August 25) after David Scott's death but finished third in the regular primary. Clay Fuller (GA-14) won the April special and is the nominee.

**Decided 2026-10-29: freeze the 119th into `sessions/119th/` of `Votega/ga-federal-legislators`, Georgia delegation only, sibling repo only (no on-site copy), in two freezes.** Built: `publish_federal_delegation.py freeze [slug] [--final] [--overwrite]` and the manual workflow `freeze-federal-delegation.yml`. It writes the roster, votes, flat CSVs, the party-unity scorecard, and each member's full sponsorship record (raw compact slices plus a flat `sponsorship.csv`), with per-path schemas, a manifest (`freeze.json`) and a README, and refuses to file one Congress's data under another's name. Daily publishes cannot write into `sessions/`, and every live CSV now ends with a `congress` column. **Provisional freeze now; the FINAL freeze must run by January 2, 2027,** after the last roster, votes and sponsorship runs have committed and before the first run of the new Congress. Dry-run output and tests verified; the first real publish has not been run.

**Proposed 2026-11-04: a 119th Congress delegation roster, and one page per member with a Congress selector.**
- **Roster page** (for example `/federal-reps/119th/`): everyone who served from Georgia in the 119th, grouped by chamber, each with a status (re-elected, not returning, won another office) worded by the D6 rules. Scope is the Georgia delegation only (16 members plus anyone who held a seat mid-term, such as Blair and Fuller). Build it around a congress-slug parameter so the 121st reuses it, and so it can later serve former GA legislators (D3), which has the same shape: a frozen index, frozen per-member files, and a retired-record rule for search and the sitemap.
- **One page per person, not two.** A member in both Congresses keeps a single `/us-congress/<slug>/` URL with a Congress selector (`?congress=119`). The default is the member's latest Congress, so a departed member opens on the 119th and a returning member on the 120th. The selector appears only when a member has more than one Congress; otherwise the page shows a plain "119th Congress" label. Votes, sponsorship, scorecard, key votes, committees, leadership, term dates and the status label all follow the selection; contact details show only for the live Congress; there is no cross-Congress total or average (D10).
- **Why it fits the data:** sponsorship slices already carry `congress`, the vote slices are per member (about 7 KB) and lazy-loaded, so the selector costs nothing until used.
- **Reverses the 2026-10-29 "sibling repo only, no on-site copy" decision.** The page builder reads local files at deploy, so a compact copy of the frozen 119th delegation data goes under something like `assets/data/federal-119th/`. Committees, leadership and term values for the 119th must come from the frozen roster, since `current-members.json` holds only the live snapshot.
- **Costs:** `_includes/entity/federal-legislator.html` assumes one Congress (the `R_*` and `FV_*` constants, the key-votes sidecar, `curated-federal-bills.json`) and needs parameterizing, with a per-Congress curated-bills file. The page builder needs each member's list of Congresses. New fetches follow the `getBasePath()` and `?v=` cache-busting rules, and need testing on a clean `/us-congress/<slug>/` URL.
- **Indexing:** departed members' pages `noindex` and out of the sitemap, as in D4; the roster page itself may be indexed.
- **Timing:** the data comes from the freeze, so the `--final` freeze (by 2 January 2027) is the hard dependency; the page can be built and tested now against the provisional freeze output. Estimate 65-105k tokens (the two-page version was 50-80k; the include refactor adds 15-25k). Rough, not measured.

**Still open:** the transition guard on the roster run, who curates the 120th's key votes, and whether the D6 departure labels extend to federal members. Whether departed federal members keep a page is answered by the proposal above, pending agreement.

### D13. Georgia Commons — Proposed 2026-10-30. **Update 2026-11-12: their sponsor links are already live**, so the ordering below is moot; tell them URLs are preserved once the page-permanence spec's rollout step 1 ships
Tell them that links to members who leave office will be preserved, or hold the sponsor-link request until D1-D4 are settled. Include the licensing questions from `docs/georgia-civic-data-collaboration.md`.

**Proposed: tell them the URLs will be preserved, with two caveats, and ask the licensing questions in the same message — but do not ask them to launch the sponsor links until D3 is BUILT, not merely agreed.**

D1-D4 now have proposals, and D3 keeps `/ga-legislators/<slug>/` serving for a former member, which is exactly what their sponsor links need. The two caveats to state plainly:
1. The guarantee starts at the 2025-2026 biennium (D7), the only session they publish today.
2. Former-member pages will be `noindex` (D4), so a link works for a reader but carries no search value for them.

The ordering matters more than the message. A preserved-URL promise that 404s in January is worse for them than no link at all, and the mirror-image mistake is already recorded in `claude.md`: advertise an artifact only once it exists.

### D14. Entry points to former members and past sessions — Proposed
- **A "Former Legislators" card on `/find-my-reps`.** The page is a hub of entry cards (Federal Representatives, Georgia State Representatives) in a two-column grid, so a third card would be a full-width strip. Name it for what is behind it (people, not sessions); it is accurate today because 11 members have already resigned. It links to a directory of former members grouped by session and chamber (name, party, district, term dates, how they left, successor, page link).
- **A "Previously held by …" row in the address lookup**, per district, linking to that seat's former member. The lookup shows only sitting members today ("No sitting … found" for an empty seat). It relies on district numbers staying the same, which holds under the 2023 plans; label it with the plan if Georgia redraws.
- **Optional "Past sessions" hub** for 2025-2026: former members, the final scorecard (D10), bills (`ga-bills` with its session dropdown, D2), and the roster as frozen at sine die.
- Federal former members (the two vacated congressional seats, for example) follow the same pattern, so the card should say legislators broadly; D12 is still unchecked.
Depends on D3 (the index), D6 (wording) and D4 (indexing).

### D15. Key Votes start empty in the new biennium and the tab hides until there is data — Decided 2026-11-04 (owner's decision; not built)
The risk: a newly elected member was not in office when the 2025-26 curated bills were voted on, and the curated generator would re-fetch those bills and show every new member's record against votes they could not have cast. **At the rollover the live curated list starts empty and the owner curates it as the new session's legislation passes.**

What this needs, checked 2026-11-04 against the code (nothing run):
- **List:** empty the `ga` array in `assets/data/curated-ga-bills.json` at the rollover (all nine entries, including the two 2023-24 ones). The generator copes (an empty list writes an empty `bills` array and does not exit 1, because the failure exit needs every bill to fail), and `validate_curated_ga_bills.py` already treats an empty list as a tier-2 report, not a gate, and says emptying it on purpose is fine. Not checked: the sibling-repo publish of the curated file, in case a floor rejects an empty set.
- **Page change (the real work):** `_includes/entity/ga-legislator.html` renders the Key Votes button unconditionally and makes it the default tab (`DEFAULT_TAB = 'curatedBills'`). `loadCuratedBills()` returns silently on an empty list, which today would leave a blank default tab. It needs to (1) hide the button and panel when the file has no bills, (2) fall back to Voting History as the default tab, and (3) make a `#curatedBills` deep link fall through rather than activate a hidden panel. The existing hidden In the News tab (`hidden` until it has content) is the pattern to copy.
- **The 2025-26 key votes are not lost:** freeze the current `curated-ga-bill-votes.json` at the final freeze (Timing step 5), and the D3 biennium selector shows it for 2025-26 only, so the key votes appear only against a biennium whose members were in office.
- **Same rule on the federal side:** the 120th has no curated key votes either (D12), so `federal-legislator.html` should hide its Key Votes tab on an empty list for the same reason.
- **Mid-biennium has the same risk, smaller:** a member seated by special election after a curated vote shows a vote they did not have the chance to cast. Worth deciding separately whether a curated row should show "Not in office" for a member seated after the vote date; the roster has `termStart` to drive it.

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
5. **Freeze the on-site copies before the `lib/ga_sessions.py` bump (new, 2026-11-04).** `docs/RECURRING-TASKS.md` §3 freezes only the roster; the producers then drop the outgoing biennium from the live files, and the slice builders delete stale slices. If the D2, D3, D10 and D12 selectors are built, the frozen sets must exist first: the 2025-26 bills file (D2), the vote index and per-member vote and sponsorship slices (D3), `ga-party-unity.json` (D10), and, for the federal side, the 119th set under `assets/data/federal-119th/` (D12, due by 2 January 2027). Put them under per-biennium paths the builders do not clear, and never re-run the party-vote enricher on a frozen bills file. Add this as step 2b of `RECURRING-TASKS.md` §3 when it is built.
6. Fold two items from `docs/RECURRING-TASKS.md` §3 step 5 into the same plan: work `newMemberNameReview` before the first entity-page build of the new biennium (a newcomer's URL is slugged from the formal legis.ga.gov name, and fixing it later moves the URL), and confirm or replace the carried-forward Lt. Governor record, since a new Lt. Governor takes office in January 2027.
7. Assign an owner and a calendar reminder for steps 2-3 and 5.

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
| D3 former-member pages from the archive (revised: one page per person with a biennium selector, 70-110k) | 60-100k |
| D12 119th roster page and Congress selector | 65-105k |
| D6 departure classifier, fields, tests, review queue | 35-50k |
| D10 frozen scorecard snapshot | 40-60k |
| D14 card, seat-history row, directory page | 20-35k |
| Freeze guard (freshness check) | 10-15k |

## Verified and not verified

Verified from the repo and the live site: the existing 2026-08-22 roster archive and the existence-only freeze guard, the `/find-my-reps` card layout, the rollover mechanics above (code and `claude.md`), page generation at deploy, the legacy shell rendering a resigned member (checked for Dexter Sharper only), the `ga-bills.html` behavior, the archive layout in the open-data READMEs, and the counts (11 resigned; about 33 not on their own general ballot, by name match).
Not verified: every generator's handling of a second biennium, the federal pages, the runoff date, and individual name matches (for example, the suspended Rep. Sharon Henderson appears on the Senate 43 ballot, which needs confirming).

Added for D7-D11 and D13 on 2026-10-30, all read from the repo or the live data:
`VoteGA.entityUrls.isRetired()` resolves the bucket from `rec.category` through `MAP_FOR_CATEGORY`, which already maps `'GA Legislator'`, so hiding former members from search needs no change to `_includes/search.html`; `ga-member-votes.json` is 4.0 MB holding 2,418 roll calls for 246 members on schema v2; `ga-party-unity.json` is 117 KB and carries `metadata.biennium` and per-session vote counts, and `ga-party-unity.html` already derives its repo link from that biennium; the federal votes are sliced per member and the GA votes are not; Georgia Commons publishes under a per-session URL space currently covering `2025-2026`.
Still not verified for those five: that `generate_search_corpus.py` will carry a record for a member the live roster has dropped (it depends on D3's index, which does not exist), and the cost of slicing GA votes per member.
