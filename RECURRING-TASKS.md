# VoteGA.org — Recurring & Manual Tasks

Things that need a human, organized by **what triggers them** rather than by feature area.
For one-time backlog items and step-by-step editing procedures, see [TO-DO.md](TO-DO.md).

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
| Daily | `update-current-members` (06:00), `update-ga-members` (07:00), `publish-races-to-ga-races-elections` (07:00), `update-curated-ga-bills` (08:00), `update-ga-executive-orders` (08:15) |
| Weekly (Sun) | `update-ga-bills` (07:30), `update-fec-data` (08:00), `update-ga-votes` (08:00), `update-federal-votes` (09:00), `update-presidential-laws` (09:45), `update-scotus-decisions` (10:00), `update-ga-congress-trades` (10:00), `update-vp-tie-votes` (09:30) |
| Manual dispatch only | `deploy-pages`, `validate-ga-overrides`, `sync-generated-data-on-pr`, the `inspect-*` diagnostics, and the `publish-*` repo syncs |

All times UTC.

---

## 1. When an election happens

Triggered by: election night, then again at certification.

- [ ] Build the results page from the SOS export CSV — see *Maintenance — Updating Candidate Pages* in [TO-DO.md](TO-DO.md).
- [ ] Add an entry for the election to [`_data/election_archive.yml`](_data/election_archive.yml) so it appears on `/results/`.
- [ ] Set that entry's `status` to `unofficial` while results are preliminary.
- [ ] **On certification:** flip `status` to `certified` and update the "Last updated" line on the results page.
- [ ] Advance `activePhase` on affected races in `assets/data/races.json`. The phase toggle on
      `/elections` builds itself from this — a phase appears or disappears based on the data,
      and defaults to the next election that hasn't happened yet. No code change needed.
- [ ] If a general-election runoff is required (Georgia holds these when no candidate clears 50%),
      set those races to `activePhase: runoff` with the runoff date.

> **Do not** update a results CSV from an unofficial export once certified numbers exist —
> replace it wholesale with the certified file instead.

---

## 2. When a new election cycle starts (e.g. 2026 → 2028)

Triggered by: qualifying opening for the next cycle.

Each of these still hardcodes the year:

| File | What to change |
|---|---|
| [`scripts/generate_fec_data.py`](scripts/generate_fec_data.py) L37 | `CYCLE = 2026` |
| [`candidate.html`](candidate.html) L433, L446 | FEC fallback links: `election_year=2026` |
| [`member.html`](member.html) L608 | FEC fallback link: `election_year=2026` |
| [`scripts/set_general_candidates.py`](scripts/set_general_candidates.py) L74 | cycle filter in the helper's error output |
| [`_config.yml`](_config.yml) L30 | nav section label `2026 Election Cycle:` |
| [`_data/election_archive.yml`](_data/election_archive.yml) | add a new `- cycle:` block for the new year |
| `assets/data/races.json` | add races carrying the new `cycle` value |

**Already cycle-agnostic — no action needed:**

- `elections.html` derives the active cycle from the newest `cycle` present in `races.json`,
  and builds the phase toggle from the phases actually in use.
- `/results/` renders whatever cycles exist in `election_archive.yml`, newest first.

**Optional at this point:** once a *past* cycle's races are retained in `races.json`, add a
cycle selector to `elections.html`. The pattern is already written — mirror `buildPhaseToggle()`
one level up. Note `loadData()` currently filters to a single cycle at load; a selector needs
that filtering moved to render time.

---

## 3. When a new GA legislative session starts

Triggered by: the biennium rolling over (2025–2026 → 2027–2028).

| File | What to change |
|---|---|
| [`scripts/generate_ga_bills_data.py`](scripts/generate_ga_bills_data.py) L33–34 | `GA_SESSION = "2025_26"`, `SESSION_NAME` |
| [`scripts/generate_ga_votes_data.py`](scripts/generate_ga_votes_data.py) L41–42 | same two constants |

Then follow *Maintenance — Curated GA Bills → Session changeover* in [TO-DO.md](TO-DO.md),
and re-run both workflows so the new session's data lands before the pages reference it.

---

## 4. Periodic checks

- **GA member overrides** — after each `update-ga-members` run that adds new legislators, check
  whether any lack `legisGaGovId` (no official website link) and patch via
  `assets/data/ga-members-overrides.json`.
- **Vacancies / departures** — resignations and deaths are not tracked by Open States. Set
  `status`, `statusDate`, `statusNote` in the overrides file.
- **Election calendar** — `assets/data/ga-election-calendar.json` needs new dates each cycle.
- **Ballot measures** — `assets/data/ga-ballot-measures.json` is curated by hand.

---

## 5. Open items

- [x] ~~Regenerate FEC data after the pagination fix.~~ Ran 2026-08-08: 252 candidates
      (was 138), House 214 (was capped at 100), 16 of 17 GA members now resolve.
- [ ] **Re-run `update-fec-data.yml`** after the bioguide-map fix. The map was keyed by
      surname alone, so Georgia's two Representatives named Scott collided and David Scott's
      page showed a challenger's fundraising totals. Now keyed by seat + surname.
- [x] ~~Re-run `update-current-members.yml` after the departed-member fix.~~ Ran 2026-08-08:
      545 → 537 members, all 8 `currentMember: false` records removed, GA delegation 17 → 15.
- [x] ~~Handle the GA-13 vacancy.~~ `assets/scripts/congress.js` now takes the seat list from
      `COUNTY_US_HOUSE_DISTRICTS` rather than from whoever is in the member data, so a vacated
      seat renders as "District N - Vacant (no sitting representative)" instead of vanishing
      from the dropdown. Verified against live data 2026-08-08.
      **Still true:** federal members have no override mechanism (`ga-members-overrides.json`
      is state-legislature only). If a vacancy ever needs context — successor, special
      election date — that needs a federal equivalent of the overrides file.
- [ ] **Certify the June 16 primary runoff.** `_data/election_archive.yml` still lists it as
      `unofficial`, and `ga-primary-runoff-results.html` carries the unofficial notice.
- [ ] **Replace `assets/img/avatar-icon.png`.** Still the stock Beautiful Jekyll Octocat
      placeholder, referenced as `avatar:` in `_config.yml`.
