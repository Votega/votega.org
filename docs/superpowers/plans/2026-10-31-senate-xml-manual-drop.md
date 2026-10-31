# Senate Roll-Call XML Manual Drop — Scope

> **Status: SCOPE ONLY — not approved for implementation.** No code has been
> written. This document defines what would be built and why; the decision to
> build it has not been made.

**Goal:** Let a human-saved copy of the Senate's official roll-call XML feed the
federal vote pipeline, so the site's Senate record comes from the official
source rather than from Voteview, while senate.gov refuses automated clients.

**Architecture:** Both Senate generators resolve each Senate URL through a
lookup that checks a committed directory of hand-saved XML first and falls
through to HTTP, then to Voteview. Parsing is untouched: a dropped file is the
same bytes `fetch_raw` would have returned.

**Tech Stack:** Python 3 standard library only (`run-script-tests.yml` installs
no pip packages).

## Background — why this exists

senate.gov has answered every automated request with an Akamai WAF 403 since
2026-10-25. Verified 2026-10-31:

- The block covers the whole `/legislative/` tree. `/general/` and `/reference/`
  still return 200, so it is path-scoped, not a UA or IP problem.
- **The endpoints did not change.** The paths in our generators still match
  senate.gov's own XML_Availability page, and the live homepage links to
  `vote_119_2_00254/255/256.htm` — the three most recent roll calls, which are
  exactly the three we hold.
- **The XML is not retired.** Confirmed in a browser 2026-10-31: both
  `vote_menu_119_2.xml` and `vote_119_2_00256.xml` render, with every element
  our parsers read, unchanged — including `<tie_breaker>` and
  `<amendment_purpose>No Statement of Purpose on File.</amendment_purpose>`,
  which still matches `SENATE_NULL_TEXT` at `generate_federal_votes_data.py:112`.
- A 404 seen when following the "XML" link on XML_Availability.htm is a **typo
  on senate.gov's page**, not a removal: that row's href is
  `v/legislative/LIS/...` (stray leading `v`, no leading slash), which resolves
  relative to `/general/common/generic/` and 302s to the 404 page. The HTML link
  in the same row is also broken (`.htm1`). Both point at a 2010 sample file.

A browser reaches the files; automated clients do not. So a human saving the XML
is the sanctioned path, not a workaround.

### Alternatives considered and rejected

- **Congress.gov API** — no Senate endpoint. The Library of Congress changelog
  covers House roll call votes only (beta May 2025, GA Dec 2025, 117th added
  April 2026). Nothing for the Senate, planned or released.
- **unitedstates/congress scraper** — builds the identical URLs
  (`roll_call_lists/vote_menu_%s_%d.xml`, `roll_call_votes/vote%d%d/vote_%d_%d_%05d.xml`),
  no mirror, no alternate host. Same request, same 403.
- **GovTrack bulk data** — behind a Cloudflare JS challenge (403 to all three
  paths tried).
- **govinfo CREC** — viable and official; carries the roster, the roll call
  number, and the VP's tie-break direction. Kept in reserve as the automated
  option if the WAF never lifts. Rejected for now as ~5x the effort of this,
  and its question/bill text is prose rather than fields.
- **Browser-rendering senate.gov in CI** — deliberately defeats the operator's
  access control. Not pursued.

## Decisions taken

1. **Hand-saved XML is committed to the repo.** CI runs on a fresh checkout, so
   an untracked local folder could never be read by the weekly job. Committing
   also gives a permanent, auditable archive of the official record.
2. **Voteview stays wired in underneath.** Nothing else can tell us that votes
   exist upstream which have not been pasted; a skipped week would otherwise
   leave a silent gap.

## Global Constraints

- A dropped file is the **official record**: it is immutable, and it must
  *replace* any Voteview-derived row for the same roll call rather than being
  recorded as provisional in `metadata.senateRollsFromVoteview`.
- Precedence is fixed: **committed XML > senate.gov HTTP > Voteview.**
- No parser changes. `parse_senate_vote()` (`generate_federal_votes_data.py:452`)
  and the `<tie_breaker>` read (`generate_vp_tie_votes.py:174-178`) must receive
  identical bytes and stay untouched.
- The existing reuse layer still governs: a roll call already in the committed
  JSON and not provisional is never re-read from any source.
- No new pip dependencies.

## Scope

### Task 1: Resolver library
A small helper that, given (congress, session, number) or the session index,
returns local bytes if the corresponding file is present in the drop directory,
else `None`. Filenames mirror senate.gov exactly
(`vote_menu_119_2.xml`, `vote_119_2_00256.xml`) so a saved file needs no renaming.

### Task 2: Wire into the federal votes generator
Two call sites: the index at `generate_federal_votes_data.py:542` and
`senate_vote_url()` at `:563`. The `if indexes[1]:` branch at `:643` must also
treat a locally-present index as reachable, so a dropped index does not fall
into the Voteview path.

### Task 3: Wire into the VP tie-break generator
Same two URLs at `generate_vp_tie_votes.py:41-42`, consumed at `:130` and `:308`.
This is the task that restores true tie-break detection: `<tie_breaker>` is
present in the official XML, so dropped files remove the need to infer a
tie-break from an equal tally on a question that carried, and make a VP "Nay"
detectable for the first time.

### Task 4: Provisional-row replacement
A dropped file for a roll call currently marked in
`metadata.senateRollsFromVoteview` must overwrite that record and drop it from
the provisional set.

### Task 5: Tests and docs
- A dropped file beats both HTTP and Voteview.
- A dropped file replaces a provisional Voteview row.
- Absent drop directory changes nothing (today's behaviour exactly).
- A short README in the drop directory: where to click (the "XML" link at the
  top-right of each vote page — *not* the availability page's broken link),
  what to name the file, that `Save As` or view-source is required because
  copying from the browser's XML tree view yields rendered text, not XML.

## Out of scope

- Any CREC/govinfo work.
- Backfilling the 915 roll calls already held — the reuse layer means only new
  votes are ever needed, and there are currently **zero** outstanding (the
  Senate's last roll call was 2026-09-30, vote 256, which we hold).
- Removing Voteview.
- Contacting the Senate webmaster (worth doing in parallel; the broken links on
  XML_Availability.htm are concrete, reportable bugs alongside the WAF block).

## Review Focus

- Precedence is genuinely XML > HTTP > Voteview under every combination.
- A dropped file never lands in the provisional set.
- The `if indexes[1]:` guard does not mis-route when only a local index exists.
- No behaviour change at all when the drop directory is empty or missing.

## Known costs

- Converts an automated weekly job into a manual chore on weeks the Senate
  votes. Volume is low (0 outstanding today; typically single digits per week in
  session), but a missed week leaves a gap that only the Voteview backstop
  would reveal.
- Repo growth: ~10-30 KB per roll call.

**Estimated effort:** ~30-50k tokens.
