# VoteGA.org — Recurring & Manual Tasks

Things that need a human, organized by **what triggers them** rather than by feature area.
For one-time backlog items and step-by-step editing procedures, see `TO-DO.md` — a **maintainer-local** working doc (gitignored, not in the published repo), so the references below are not links.

> Rule of thumb: if a value changes every cycle or session, it should live in a data file,
> not in code. Each hardcoded value listed below is a small refactor opportunity — the
> `elections.html` phase toggle and cycle selection were moved to data this way and no
> longer appear on these lists.

---

## 0. Automated — do NOT do these by hand

These run on a schedule and commit their own data. If one looks stale, check the Actions tab
before editing any JSON by hand; a hand edit will be overwritten on the next run.

| Cadence | Workflows |
|---|---|
| Daily | `update-current-members` (06:00), `update-ga-members` (07:00), `publish-races-to-ga-races-elections` (07:00), `update-ga-executive-orders` (08:15) |
| Tue & Thu | `update-curated-ga-bills` (08:00) &mdash; cron `0 8 * * 2,4`, **not** daily |
| Weekly (Sun) | `update-ga-bills` (07:30), `update-fec-data` (08:00), `update-ga-campaign-finance` (08:30), `update-federal-votes` (09:00), `update-vp-tie-votes` (09:30), `update-presidential-laws` (09:45), `update-scotus-decisions` (10:00), `update-ga-congress-trades` (10:00) |
| Weekly (Mon) | `update-ga-votes` (07:30) &mdash; cron `30 7 * * 1`, deliberately off the Sunday cluster |
| On push to `main` | The five `publish-*` syncs each fire when the `assets/data/*.json` they mirror changes (and are also `workflow_dispatch`-able). `publish-races-to-ga-races-elections` additionally runs on the daily schedule above. |
| Manual dispatch only | `deploy-pages`, `validate-ga-overrides`, `sync-generated-data-on-pr`, the `inspect-*` diagnostics |

All times UTC. Verified against the workflow crons 2026-08-19.

---

## 1. When an election happens

Triggered by: election night, then again at certification.

- [ ] Build the results page from the SOS export CSV — see *Maintenance — Updating Candidate Pages* in `TO-DO.md`.
- [ ] Re-run `python scripts/build_race_results_index.py` and commit
      `assets/data/race-results-index.json`. This feeds the **Earlier This Cycle** tab on
      `race.html`; without it that tab keeps showing the previous election set. The script
      discovers elections from the results page stubs' front matter, so a newly added
      election is picked up automatically — but it only includes elections that already
      have votes, so it must be re-run *after* the results JSON is built. Check its output:
      it prints how many races matched and lists any that didn't.
- [ ] Add an entry for the election to [`_data/election_archive.yml`](_data/election_archive.yml) so it appears on `/results/`.
- [ ] Set that entry's `status` to `unofficial` while results are preliminary.
- [ ] **On certification:** flip `status` to `certified` and update the "Last updated" line on the results page.
- [ ] Advance `activePhase` on affected races in `assets/data/races.json`. The phase toggle on
      `/elections` builds itself from this — a phase appears or disappears based on the data,
      and defaults to the next election that hasn't happened yet. No code change needed.
- [ ] Curate the surviving candidates' profiles (bio, photo, website, withdrawn/disqualified) for the
      next phase. **Federal & other non-regenerated races:** `tools/race-candidate-editor.html`
      (edits `races.json` in place; syncs edits across every phase a candidate appears in).
      **GA state legislative (`ga-house-*`/`ga-senate-*`):** `ga-race-candidate-overrides.json` via
      `ga-overrides-editor.html`, then `python scripts/apply_overrides.py`. See *Maintenance — Updating
      Candidate Pages* in `TO-DO.md`.
- [ ] If a general-election runoff is required (Georgia holds these when no candidate clears 50%),
      set those races to `activePhase: runoff` with the runoff date.
- [ ] **Ballot measures:** once results certify, set each measure's `status` to `passed` or
      `failed` and add its `results` object (`yesPercent`, `passed`, …) in
      [`assets/data/ga-ballot-measures.json`](assets/data/ga-ballot-measures.json). A terminal
      status **must** carry a `results` object (the schema and the publish workflow both enforce
      this). Measures are never deleted — they stay as a permanent record and drop off the page
      only when the next cycle is introduced (see §2).

> **Do not** update a results CSV from an unofficial export once certified numbers exist —
> replace it wholesale with the certified file instead.

---

## 2. When a new election cycle starts (e.g. 2026 → 2028)

Triggered by: qualifying opening for the next cycle.

Each of these still hardcodes the year. Line numbers drift — the entries name a
constant, so `grep` for that rather than trusting the line. Verified 2026-08-19.

| File | What to change |
|---|---|
| [`scripts/build_legislative_races.py`](scripts/build_legislative_races.py) | `CYCLE`, `PRIMARY_DATE`, `GENERAL_DATE` constants near the top — race IDs, the `cycle` field, and both phase dates all derive from these |
| [`scripts/build_general_placeholder.py`](scripts/build_general_placeholder.py) | `CYCLE` constant (drives the cycle filter and the output filename) |
| [`scripts/set_general_candidates.py`](scripts/set_general_candidates.py) | `CYCLE` / `GENERAL_DATE` constants |
| [`_data/election_archive.yml`](_data/election_archive.yml) | add a new `- cycle:` block for the new year |
| `assets/data/races.json` | add races carrying the new `cycle` value (`build_legislative_races.py` writes these) |

> **Corrected 2026-08-19.** This table previously listed four files that are no longer
> hardcoded — `generate_fec_data.py` (now derives the cycle via `target_cycle()` from
> `races.json`), the `election_year=2026` FEC links in `candidate.html` / `member.html`
> (moved into `assets/scripts/campaign-finance.js`, which reads `metadata.cycle`), and a
> `_config.yml` nav label that no longer exists. They are gone from the checklist. The
> two `build_*` generators and the `GENERAL_DATE`/`CYCLE` scattered literals were the
> ones actually missing — hoisted into labeled constants on 2026-08-19 (finding 5.9) so
> each rollover is a one-line edit rather than a hunt. **GA legislative session** hardcodes
> (`GA_SESSION`) are a separate axis — see section 3.

**Already cycle-agnostic — no action needed:**

- `elections.html` derives the active cycle from the newest `cycle` present in `races.json`,
  and builds the phase toggle from the phases actually in use.
- `/results/` renders whatever cycles exist in `election_archive.yml`, newest first.
- **FEC + PeachFile campaign finance** derives its cycle from the data: `generate_fec_data.py`
  reads `target_cycle()` off `races.json`, and `campaign-finance.js` builds the FEC "election_year"
  search link from `metadata.cycle`. No FEC year is hardcoded in a page anymore.
- `/ga-ballot-measures` shows the **focal election** — the nearest upcoming `electionDate` in
  `ga-ballot-measures.json` (or the most recent if none upcoming). Introducing the next cycle's
  measures with the new `electionDate` archives the prior cycle from display automatically; the
  old measures stay in the file. **The one manual step:** add the new proposals (each with its
  `electionDate`) as they're introduced — do not delete the previous cycle's entries.

**Optional at this point:** once a *past* cycle's races are retained in `races.json`, add a
cycle selector to `elections.html`. The pattern is already written — mirror `buildPhaseToggle()`
one level up. Note `loadData()` currently filters to a single cycle at load; a selector needs
that filtering moved to render time.

---

## 3. When a new GA legislative session starts (regular OR special)

Triggered by: a new regular session at the biennium rollover (2025–2026 → 2027–2028),
**or** a special session convened within a biennium (e.g. the 2026 special session).

**All session config now lives in one file:** [`scripts/lib/ga_sessions.py`](scripts/lib/ga_sessions.py).
Both generators and both sibling-repo publishers import it — there is no longer a
`GA_SESSION` constant to edit in each generator. To add a session:

1. Add its `id -> name` to `SESSION_NAMES` (e.g. `"2027_28": "2027-2028 Regular Session"`).
2. Point `ACTIVE_SESSION` at whichever session is currently in progress — the only one
   fetched live. Every other session in `SESSION_NAMES` is treated as **closed and
   preserved** from the existing data file (its bills/votes are never re-fetched).
3. Set `UNTAGGED_SESSION` to the session that on-file records with no `session` tag
   belong to (only relevant the first time an untagged file is migrated).
4. At a full biennium rollover, also update `BIENNIUM`.

Then re-run `update-ga-bills` and `update-ga-votes`. Because only the active session is
fetched and it opens small, the first pull is a few pages — no quota crunch. Also follow
*Maintenance — Curated GA Bills → Session changeover* in `TO-DO.md`.

**How the biennium model works:** each bill/vote record carries a `session` id. The
generators keep closed sessions as a frozen layer and fetch only `ACTIVE_SESSION`, so
`ga-bills.json` / `ga-member-votes.json` cover the whole biennium; `ga-bills.html` and
`ga-member.html` show all sessions (filterable / grouped), and the publishers split the
combined file back into `sessions/<slug>/` archive dirs (regular → `2025-2026`, special
→ `2026-ss`). No member loses their prior-session record at a changeover.

**Get the identifier from the API, don't guess it.** Run the `inspect-ga-sessions`
workflow (dispatch-only, one API request). It lists every GA session Open States knows
about with its exact `identifier`. Guessing a session string produces failures that look
identical to an expired key or an outage.

### Freeze the roster at the biennium's end

The roster archive is a deliberate `freeze-ga-roster` run, keyed to the General Assembly
(the biennium), **not** each special session — the membership is the same across a
biennium's regular and special sessions. Do it at the end of the biennium, BEFORE
`update-ga-members` turns the roster over to the incoming class. Bills and votes archive
themselves per session (the publishers bucket by each record's `session` tag, and past
dirs are never overwritten); the **roster** does not — `ga-members.json` carries no
session name and Open States replaces it gradually after the election.

- Run the **`freeze-ga-roster`** workflow (dispatch-only). Leave the input blank to freeze
  the biennium (`2025-2026`), or pass an explicit slug. It writes
  `sessions/<slug>/{members.json, members.csv, members.schema.json, ROSTER.md}` and never
  touches it again.
- Timing is the whole point: run it while `ga-members.json` still holds the outgoing roster.
  Once the incoming members are seated, that roster is gone from the source and can't be
  reconstructed — only the archive preserves who served in that General Assembly.
- The live roster stays at `data/all.json` (refreshed daily by `update-ga-members`); the
  freeze is purely additive. `latest.json` at the repo root names the biennium, the session
  in progress, and every session's files.

**Known gap:** `ga-member-votes.json` covers ~4,280 of the 2025–26 session's ~5,480
bills (`paginationComplete: false`). A full pass needs ~274 requests against the
250/day cap and the scripts can't resume mid-pagination, so the remaining votes can
only be recovered by adding resume-from-page support or a paid API tier. The session
is closed, so the gap is frozen rather than growing.

---

## 4. Periodic checks

- **GA member overrides** — after each `update-ga-members` run that adds new legislators, check
  whether any lack `legisGaGovId` (no official website link) and patch via
  `assets/data/ga-members-overrides.json`.
- **Vacancies / departures** — resignations and deaths are not tracked by Open States. Set
  `status`, `statusDate`, `statusNote` in the overrides file.
- **Election calendar** — `assets/data/ga-election-calendar.json` needs new dates each cycle.
- **Ballot measures** — `assets/data/ga-ballot-measures.json` is curated by hand; conforms to
  [`ga-ballot-measures.schema.json`](assets/data/ga-ballot-measures.schema.json) and syncs to
  `Votega/ga-legislation` via `publish-ga-ballot-measures-to-ga-legislation` on push. Per-measure
  lifecycle: `potential → certified → passed/failed`. See §1 (record results at certification)
  and §2 (introduce the next cycle to archive the last one).
- **State campaign finance coverage** — `update-ga-campaign-finance` pulls only the cycle
  matching the newest `cycle` in `races.json`. After an election, check that sitting
  legislators still resolve: a member with no filing shows "no filing found", which is
  correct for someone not seeking re-election but also what a broken join looks like.
  `scripts/generate_ga_campaign_finance.py` prints the per-office kept/skipped counts.

---

## 5. Open items

- [x] ~~Regenerate FEC data after the pagination fix.~~ Ran 2026-08-08: 252 candidates
      (was 138), House 214 (was capped at 100), 16 of 17 GA members now resolve.
- [x] ~~Re-run `update-fec-data.yml` after the bioguide-map fix.~~ Ran 2026-08-08: all 15
      current GA members resolve to their own FEC record via bioguide, zero district
      mismatches. The Scott collision is gone.
- [x] ~~**Latent:** `generate_fec_data.py` builds its `byDistrict` buckets from characters 4–5
      of the FEC candidate ID rather than the API's `district` field.~~ Fixed: the bucket key
      is now built from `district_key(office, district)` off the API's `district` field
      (`generate_fec_data.py:376`, with the MTG-06-vs-GA-14 case documented in the comment there).
- [x] ~~Re-run `update-current-members.yml` after the departed-member fix.~~ Ran 2026-08-08:
      545 → 537 members, all 8 `currentMember: false` records removed, GA delegation 17 → 15.
- [x] ~~Handle the GA-13 vacancy.~~ `assets/scripts/congress.js` now takes the seat list from
      `COUNTY_US_HOUSE_DISTRICTS` rather than from whoever is in the member data, so a vacated
      seat renders as "District N - Vacant (no sitting representative)" instead of vanishing
      from the dropdown. Verified against live data 2026-08-08. **Still true:** federal members have no override mechanism 
      (`ga-members-overrides.json` is state-legislature only). If a vacancy ever needs context — successor, special
      election date — that needs a federal equivalent of the overrides file.
- [x] ~~**Certify the June 16 primary runoff.**~~ Certified 2026-08-20: flipped
      `status` to `certified` in both `_data/election_archive.yml` and
      `ga-primary-runoff-results.html` (and bumped its `updated:` stamp). The SoS
      certified export was byte-identical to the unofficial numbers already in
      `_sources/election_results/ga-primary-runoff-results.csv` (81 rows, 0 diffs),
      so no CSV/JSON rebuild was needed.
- [ ] **Nov 3 General Election — replace the placeholder with real results.**
      `ga-general-2026-results.html` currently shows every candidate at 0 votes, built by
      `scripts/build_general_placeholder.py` from `races.json`. Once official results are
      available as a Georgia SoS "Total Votes Results" CSV, run the real builder instead:
      `python scripts/build_results_json.py <official_csv> ga-general-2026-results`
      (see §1 above for the full election-night checklist — archive status, certification, etc.).
      If any candidates change on `races.json` before election night, re-run
      `python scripts/build_general_placeholder.py` to refresh the preview in the meantime.
      **If a Dec 1 runoff is triggered:** add `resultsUrl: /ga-general-2026-runoff-results/` to
      that event in `ga-election-calendar.json` (deliberately left unset since the runoff may
      not happen), and populate `ga-general-2026-runoff-results.html` the same way.
- [x] ~~**Replace `assets/img/avatar-icon.png`.**~~ Still the stock Beautiful Jekyll Octocat
      placeholder, referenced as `avatar:` in `_config.yml`.
