# /local/ voter-value roadmap

**Status:** ideas, not yet scoped or started
**Drafted:** 2026-11-21
**Goal:** make `/local/` more useful to the voters who visit it. The section is
a strong *record* today. This roadmap is about what a voter can *do* with it.

> These ideas come from a quick look at `local.html`, `_includes/entity/place.html`
> and `assets/data/local-*`, not a full audit. Check each item against
> [`LOCAL-EXPANSION-SCOPE.md`](LOCAL-EXPANSION-SCOPE.md) before building, because
> property tax and school boards are already mostly built there.

---

## Where /local/ stands today

- 68 places (counties and cities), each with a `/local/<slug>/` page
- Elected officials, constitutional officers (sheriffs) and a public-meetings feed
- Meeting topic badges and topic feeds (`/local/topics/<topic>/`) for data
  centers, land use, ALPR, budget and local taxes
- Vote records for 9 places; counterparties (contracts) for DeKalb
- Millage and school-board includes (see `LOCAL-EXPANSION-SCOPE.md`)

**Main gap:** a voter has to already know which bodies govern them. Nothing
points them to upcoming meetings, upcoming local elections or ways to take part.

---

## Roadmap

### Now: quick wins that reuse data we already have

| # | Item | What it does for voters | Builds on | Est. tokens |
|---|---|---|---|---|
| 1 | **"My local governments" lookup** | Address or ZIP → my county, city and school board pages | ZIP/tract district tables behind Find My Reps; `places.yml` `parentCounty` | ~40–60k |
| 2 | **Next meeting + how to take part** | Next date, location, livestream, public-comment rules, add-to-calendar (.ics) | Meeting JSON and `places.yml` schedule / `agendas_url` | ~40–80k |
| 3 | **Local elections tie-in** | Which local seats are up next, with links to races, candidates and the sample ballot | `local_officials.yml` `next_election`; race and candidate pages | ~30–50k |

### Next: more depth for places already covered

| # | Item | What it does for voters | Depends on | Est. tokens |
|---|---|---|---|---|
| 4 | **Per-official voting record** | "How did my commissioner vote?" on each official's row | `local-*-votes.json` (9 places today) | ~50k for the UI; more places means scraper work |
| 5 | **Follow a place or topic** | RSS per place and per topic; email alerts later | Topic feeds already exist; email needs a third-party service | ~30k (RSS only) |
| 6 | **Property tax in plain terms** | "What this millage rate means for a $300k home" calculator | `millage.html` and `local-taxes` data; check what's already built | ~30–40k |

### Later: wider reach

| # | Item | What it does for voters | Depends on | Est. tokens |
|---|---|---|---|---|
| 7 | **Coverage for all 159 counties** | Every county gets a page with official links and a "request coverage" option, so no voter hits a dead end | County FIPS list; a simple request form or GitHub issue link | ~30k |

Further ideas, not yet sized: plain-language summaries of agenda items,
"what changed this month" digests per place, and a glossary of terms like
millage, variance, rezoning and SPLOST.

---

## Suggested order

1. **#1 lookup**: fixes the "which page is mine?" problem; everything else gets
   more traffic once voters can find their place.
2. **#2 next meeting**: the clearest call to action.
3. **#3 local elections**: links `/local/` to the rest of the site.
4. Then #4–#6 depending on data coverage, and #7 when there's capacity.

## How to save tokens when picking one up

- Do a focused audit of only the templates and data that item touches
  (~10–15k tokens) instead of auditing the whole section (100k+).
- Build one item per session and commit it before starting the next.
- `claude.md` is large (~105 KB), so read only the sections you need.

## Decision log

| Date | Decision |
|---|---|
| 2026-11-21 | Roadmap drafted. Nothing scoped or started yet. |
