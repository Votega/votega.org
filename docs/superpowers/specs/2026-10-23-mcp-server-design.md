# VoteGA MCP Server (Cloudflare Workers) — Design Spec

Status: Draft for review · Written 2026-10-23 · Revised 2026-11-21

**Revision 2026-11-21.** Nothing has been built yet: no `mcp/` directory, index script, workflow
or `mcp.votega.org` DNS record exists. This revision brings the spec in line with
`docs/georgia-civic-data-collaboration.md` item 11 and with data changes since October:
- `find_my_representatives` moves into v1, for ZIP and county input only (§6.2).
- A new §5.5 defines the identifiers each tool takes and returns. The roster's `id` and positional
  races.json candidate ids are never used as identity.
- Results carry `votegaUrl`, `county_fips` (5-digit) and, for bills, a Georgia Commons link (§6.3).
- A new §7 covers former members, frozen bienniums and the January 2027 turnover in both legislatures.
- The local-government topics are read from the data, not hard-coded. There are four topic pages now.
- File sizes are re-measured, and the rollout and open questions are updated.
Items marked **Proposed** still need a decision.

**Second revision 2026-11-21 (open questions settled).** §12 is now a record of decisions, with
the evidence behind each.
- **Audience:** the first audience is the general public asking an AI assistant about their own
  representatives and ballot. Tools for that question come first (§6, §13).
- **Federal:** federal members *and their votes* are in v1.
- **New tool:** `find_local_officials` (county commission or city council, plus the sheriff) is in v1.
- **Deferred:** seat history moves to v2.
- **Spike checks:** Phase 0 gains two (§12.9).

## 1. Summary

A **remote, read-only, unauthenticated MCP server** at `https://mcp.votega.org/mcp`
(Streamable HTTP), running on **Cloudflare Workers (free tier)**. It lets any MCP-capable AI
assistant look up Georgia legislators (state and federal, with their votes), county and city
officials, bills, races and candidates, executive orders and local-government mentions from
VoteGA's published open data. It can also say which districts a ZIP code or county touches. The
first audience is a member of the public asking an assistant who represents them and what is on
their ballot. Every answer carries a source link and an "as of" date.

It is designed to chain with the two partner servers: Georgia Civic Data
(county, tract and school data, keyed on 5-digit `county_fips` and 11-digit tract GEOIDs) and
Georgia Commons (`mcp.georgiacommons.org/mcp`, bill pages and plain-language summaries). The
shared keys are what make chaining work. VoteGA's server never calls theirs.

This matches the project's stance: no key, no signup, nonpartisan, sourced to official records.

## 2. Goals / Non-goals

**Goals**
- Public data lookups over the existing datasets: legislators (state and federal) and their votes,
  county and city officials, bills, races, candidates, EOs, local mentions, and the districts
  touching a ZIP or county.
- Return the keys partner servers join on (`county_fips`, `legisGaGovId`, `votegaUrl`, bill
  session + number).
- No new data pipeline in v1 beyond small precomputed index files.
- Always-current data (no stale copy inside the Worker).
- Stay inside Workers free limits.

**Non-goals (v1)**
- **Street-address lookup.** Turning an address into its exact districts needs a geocoder, which
  would send a voter's address to a third party (Census). Deferred to v2 as its own decision.
  ZIP and county lookups in v1 return the districts those areas touch, never "your district" (§6.2).
- Maintainer/ops tools (freshness of workflows, run status). These would need auth and the GitHub API.
- Any write operation, user accounts, or tracking of queries.
- Endorsements, rankings, or advocacy framing. Tools return facts and sources only.
- Fetching, storing or quoting Georgia Commons or Georgia Civic Data text. v1 returns links only
  (§6.3).

## 3. Constraints that drive the design

| Constraint | Consequence |
|---|---|
| Free tier: ~10 ms CPU/request, 100k req/day, 128 MB memory | Worker must **not** `JSON.parse` multi-MB files per request |
| Large source files (measured 2026-11-21: `ga-bills.json` 7.2 MB, `current-members.json` 1.6 MB, `races.json` 1.3 MB, `id-crosswalk.json` 1.3 MB, `ga-votes-index.json` 1.2 MB, `ga-members.json` 0.7 MB, `ga-zip-districts.json` 0.3 MB) | Worker reads only **small precomputed indexes** and **per-entity slices** |
| Site is static Jekyll on GitHub Pages; data also in `Votega/ga-*` repos | Worker fetches published JSON over HTTPS and caches it at the edge |
| KV free tier: 1k writes/day | No KV in v1; use the Cache API instead |
| Roster, bills and Congress number all change in January 2027 | Indexes carry their session/Congress; tools take an optional `session` (§7) |

## 4. Architecture

```
AI client ──MCP (Streamable HTTP)──▶ mcp.votega.org  (Cloudflare Worker)
                                        │
                                        ├─ Cache API (per-colo, TTL by dataset)
                                        └─ fetch ─▶ www.votega.org/assets/data/mcp/*.json   (indexes)
                                                  └▶ www.votega.org/assets/data/<slice>   (per-entity slices)
```

- **Runtime:** TypeScript, the MCP TypeScript SDK, and Cloudflare's `agents` package, using
  `createMcpHandler` in **stateless** mode (§12.1). It needs no Durable Objects, which avoids
  their free-tier limits. `McpAgent` is not used.
- **Stateless:** every request is self-contained; no sessions.
- **Routing:** `POST /mcp` (MCP), `GET /` (a human landing page with the tool list), `GET /health`.
- **Repo location:** a new top-level `mcp/` directory (its own `package.json` and `wrangler.toml`),
  excluded from the Jekyll build via `exclude:` in `_config.yml`.
- **Deploy:** a GitHub Action on changes to `mcp/**` that runs `wrangler deploy` with a scoped
  `CLOUDFLARE_API_TOKEN` secret. DNS: an `mcp` CNAME pointing at the Worker's custom domain.
  Renaming that workflow later means updating `notify-workflow-failure.yml` in the same commit.

## 5. Data access layer

### 5.1 MCP index files (new, generated at site build)
A new script, `scripts/build_mcp_index.py` (same pattern as the existing `scripts/build_*`),
writes compact, search-ready files under `assets/data/mcp/`. Each targets **< ~150 KB**
gzipped, so parse cost stays inside the CPU budget:

| File | Contents (per row) | Source |
|---|---|---|
| `members-index.json` | key (§5.5), `vgId`, name, chamber, party, district, `status`, `votegaUrl`, session/Congress | `ga-members.json`, `current-members.json`, `id-crosswalk.json` |
| `former-members-index.json` | same row shape, plus the biennium served and the departure fact | `ga-legislator-ledger.json`, `ga-bienniums/<tag>/ga-members.json` (§7) |
| `bills-index.json` | `legislationId`, `session`, `identifier`, short title, status, status date, sponsor `legisGaGovId`s, subjects | `ga-bills.json` |
| `races-index.json` | race id, office, district, date, active phase, candidate refs | `races.json` |
| `candidates-index.json` | candidate id, `vgId` (null when none), name, party, race id | `races.json`, `ga-legislative-candidates.json`, `id-crosswalk.json` |
| `eo-index.json` | number, date, title, category, PDF url | `ga-executive-orders-*.json` |
| `local-mentions-index.json` | place slug, topic, date, title, source url | `local-topics-*.json` |
| `zip/<zip3>.json` | each ZIP under that 3-digit prefix: `kind`, counties (`county_fips`, share), state Senate / House / US House districts (with shares) | `ga-zip-districts.json` |
| `counties-index.json` | `county_fips`, name, state Senate / House / US House districts, each with its population `share` | `scripts/data/ga-tract-districts.json`, rolled up by `counties_doc()` in `scripts/publish_ga_district_information.py` (imported, not copied; §12.6) |
| `local-officials-index.json` | per county or city (`places.yml` slug + `county_fips`): commission/council members with seat and role, the sheriff, source URLs, last-reviewed date | `_data/local_officials.yml`, `_data/county_officers.yml` |
| `federal-votes-index.json` (existing, not new) | positional roll-call rows; read only for `get_legislator_votes` on a federal member | `build_federal_votes_slices.py` |
| `meta.json` | dataset → `generatedAt`, last checked, source, license, session/Congress; the list of local topics | `_data/data_freshness.yml`, `_data/freshness/*.json`, file metadata |

If an index would go over budget (bills is the likely one), **shard** it (`bills-index-<A..Z|status>.json`)
and have the Worker choose shards from the query. ZIPs are sharded by their first 3 digits from
the start. The whole ZIP file is only 0.3 MB, but one shard per lookup keeps the parse cost trivial.

### 5.2 Per-entity slices (existing)
Detail calls fetch the existing slice directories by ID: `ga-votes/`, `ga-sponsorship/`,
`federal-votes/`, `federal-sponsorship/`, `agency-actions/`, `eo-text/`, and the frozen
`ga-bienniums/<tag>/` trees (same file names as the live ones). The slice file names use
different keys, so the index has to carry the slice key:
- `ga-votes/` is keyed by a slug of the roster `id` (`ocd-person-<uuid>.json` for most members).
- `ga-sponsorship/` is keyed by `legisGaGovId`.
- The federal slices are keyed by `bioguideId`.

Never rebuild a slice name from a person's name.

### 5.3 Caching
- Cache API, keyed on URL. TTLs follow each dataset's cadence: roster and bills 1 h, races
  15 min (election season), EOs 6 h, local mentions 6 h, ZIP and county tables 24 h, meta 5 min.
- `stale-while-revalidate` on upstream failure: serve the stale copy and flag it `stale: true`.
- Index files carry a content hash in `meta.json`, so clients and tests can detect drift.

### 5.4 Search
In the Worker, over the small indexes only: normalized lowercase substring and token match,
simple field weights, and a hard cap on results (default 10, max 25). No embeddings in v1.

### 5.5 Identifiers (what tools take and return)
Every id a search tool returns must work as input to the matching get tool, and must keep
meaning the same thing over time.

| Entity | Key the tools use | Never use |
|---|---|---|
| GA legislator | `legisGaGovId` (as `ga:<n>`) | the roster `id` (an opaque handle; CLAUDE.md forbids interpreting it) |
| Federal legislator | `bioguideId` (as `us:<id>`) | — |
| A person, across roles | `vgId`, following `metadata.mergedVgIds` forwards in `id-crosswalk.json` | `alias()` results, names |
| GA bill | `session` + `identifier` (`2025_26/HB 1`); `legislationId` also accepted | a bare `HB 1` (numbers restart every biennium) |
| Candidate | the races.json candidate id for lookup, plus `vgId` when the person has one | the candidate id as identity (it is positional: CLAUDE.md, "Never key identity on a races.json candidate ID") |
| Place | `places.yml` slug | — |
| County | 5-digit FIPS (`13217`) | the 3-digit suffix or the county name |

Results also return `votegaUrl` (or the entity's page URL from `entity-urls.json`), so an
assistant can cite the page.

## 6. Tools (v1)

All tools: `readOnlyHint: true`, `openWorldHint: false`. Inputs validated with `zod`.
Every result includes `source_url`, `as_of` (from `meta.json`) and `license: "CC BY-SA 4.0"`.

### 6.1 Tool list

| Tool | Inputs | Returns |
|---|---|---|
| `search_legislators` | `query?`, `chamber?` (house/senate/us_house/us_senate), `party?`, `district?`, `county_fips?`, `include_former?` (default false), `limit?` | Matching members: key, `vgId`, name, party, chamber, district, `status`, `votegaUrl` |
| `get_legislator` | `id` (§5.5), `session?` | Profile, committees, contact (sitting members only), official page, `votegaUrl`, vote scorecard (party unity, participation), session/Congress the record covers |
| `get_legislator_votes` | `id`, `session?`, `limit?` | Recent votes (bill, date, vote, result) from the vote slices. GA members: passage votes from `ga-votes/`. Federal members: every roll call of the current Congress from `federal-votes/<bioguideId>.json` and `federal-votes-index.json`, including bill-less votes (`bill: null`), with the result read from the stored `P`/`F` (never re-derived from wording) |
| `search_bills` | `query?`, `session?` (default: current), `status?`, `sponsor_id?`, `subject?`, `limit?` | Matching bills: `session`, `identifier`, title, status, last action |
| `get_bill` | `session` + `identifier`, or `legislationId` | Status, sponsors (with `votegaUrl`), subjects, actions, vote summary, legis.ga.gov link, `georgia_commons_url` (§6.3) |
| `find_my_representatives` | `zip` or `county_fips` (exactly one) | Every district the area touches (§6.2), each with its current members, plus both US senators |
| `find_local_officials` | `county_fips`, or `place` (a `places.yml` slug or city name, resolved like Georgia Civic Data's `resolve_entity`) | The county commission or city council (member, seat, role), the sheriff for a county, each with its source URL and the date it was last reviewed. A county or city we do not cover says so and gives no names |
| `search_races` | `office?`, `district?`, `year?`, `county_fips?` | Races with candidates |
| `get_candidate` | `id` | Candidate profile, race, party, links, finance summary if available |
| `list_executive_orders` | `year?`, `category?`, `query?`, `limit?` | EOs: number, date, title, category, PDF link |
| `search_local_government` | `place?`, `topic?` (from `meta.json`), `since?`, `limit?` | Mentions with source document links |
| `get_data_freshness` | — | Per dataset: `as_of`, last checked, cadence, upstream source |

Design rules: results are compact JSON plus a one-line text summary; no editorializing fields;
party is shown as data, never as a ranking. A ZIP or county result never names one district as
the voter's own.

### 6.2 `find_my_representatives` (moved into v1)
- **ZIP:** from `ga-zip-districts.json`. That file means "districts *touching* the ZIP", so the
  tool returns **every** district with any residents, largest share first, each with its `share`.
  The tool never drops a small share: a voter on the edge of a ZIP may live in that sliver. The
  summary line says "This ZIP is split across N districts; a street address decides which one is
  yours" whenever there is more than one. ZIPs with `kind: "po-box"` carry no districts, and the
  tool says so. It also returns `county_fips` for each county, so the assistant can pass them to
  Georgia Civic Data.
- **County:** returns the districts that include any part of the county. A county is not a
  district, and the summary says so.
- **Always included:** both US senators and the statewide context (statewide offices are not
  districted).
- **Members** come from the current roster only. A seat with no sitting member (`status`
  Resigned/Deceased, or an injected vacancy) is returned as vacant, never filled with the
  departed member.
- **Out of scope here:** Public Service Commission seats are statewide, not districts, in this
  data.

### 6.3 Partner links (Georgia Commons, Georgia Civic Data)
- `get_bill` returns `georgia_commons_url`:
  `https://georgiacommons.org/bills/<session-slug>/<identifier lowercased, no space>`.
  Session slug mapping: `2025_26` → `2025-2026`; `2026_ss` → `2026-special` (seen on their
  `/bills/2026-special/hr32` page). The mapping goes in one table in `build_mcp_index.py`, with
  a test. It is returned with the label `"Plain-language summary (AI-written), Georgia Commons"`.
- v1 never fetches, stores or quotes their text. The Worker's upstream allowlist stays
  `www.votega.org` only.
- Member and county results return `county_fips` (5-digit) for the counties touched, and
  `legisGaGovId`, which Georgia Commons' sponsor links already match against `votegaUrl`.

## 7. Sessions, former members and the January 2027 turnover

The 159th General Assembly convenes 2027-01-11 and the 120th Congress in January 2027. The rollover
removes non-returning members from the live roster and restarts bill numbers. The server must not
present last session's data as current, or a former member as sitting.

- Every index row carries its session (GA) or Congress (federal). `meta.json` names the current
  ones, read from the files' metadata and never hard-coded (`lib/congress_session.py` for
  federal).
- `session?` on legislator and bill tools selects a frozen biennium from `ga-bienniums/<tag>/`.
  The default is the current one. A bill lookup with no session means the current session's bill.
- Former members (`status` Resigned/Removed/Deceased, or listed in the ledger but no longer on the
  roster) appear only when `include_former` is set or they are looked up by id. Their result
  carries `status`, the departure fact and its date, and no contact details. The departure
  wording follows the rollover decisions (D6, D9 in `docs/ga-biennium-rollover-decisions.md`);
  the server copies the published label and writes none of its own.
- **Proposed:** launch after the 2027-01-11 rollover and the D1–D4 decisions, so the first public
  version has no stale-roster window.

## 8. Resources and prompts

- **Resources** (static, cacheable): `votega://about` (mission, nonpartisan policy, licensing),
  `votega://datasets` (the catalog from `_data/open_data.yml`), `votega://glossary` (office and
  district terms, including "a ZIP or county is not a district").
- **Prompts** (optional, small): `explain_bill`, `who_represents_area`. These are templates that
  tell the model to cite `source_url`, label any AI-written summary as AI-written, and stay neutral.

## 9. Security, abuse, and limits

- No auth, no cookies, no PII stored; **no request logging beyond Cloudflare's aggregate analytics**.
  A ZIP entered by a user is personal-ish data and is not logged. **Workers Observability
  invocation logs break this rule:** found in Phase 0, each event stores the client IP, the
  full request headers and the URL. They were on only for the Phase 0 measurements, and were
  turned off on 2026-11-21 (`observability.enabled: false`; aggregate Workers analytics
  remain). Turn them on only briefly, for a measurement.
- CORS: allow `*` for `POST /mcp` (browser-based MCP clients); no credentials.
- Validate the `Origin` header per the MCP Streamable HTTP guidance; reject oversized bodies (>16 KB).
- A Cloudflare **rate limiting rule** per IP on `/mcp` (WAF, free plan: 1 rule), plus hard result caps
  in the Worker.
- Upstream allowlist: the Worker fetches only from `www.votega.org` (SSRF-safe; no user-supplied URLs).
- Treat all dataset text as untrusted. Strip control characters and bound field lengths in
  responses (prompt-injection hygiene for strings that come from third-party agendas and minutes).
- Nonpartisan guardrails: tool descriptions forbid endorsements or ratings, and responses omit them.

## 10. Quotas and capacity (free tier)

Estimate: 1 tool call ≈ 1 Worker request plus 1–3 cache lookups (the free subrequest limit is 50).
100k requests/day ≈ 70/min sustained, which is enough for a v1 public launch. Monitor with Workers
analytics. Move to the paid plan ($5/mo) at a sustained >60% of the daily quota, or on CPU-limit errors.

## 11. Testing and observability

- **Unit:** tool handlers against fixture indexes (Vitest + `@cloudflare/vitest-pool-workers`).
- **Contract:** an MCP Inspector smoke test in CI (list the tools, call each one with a known id).
- **Data checks:** `scripts/validate_mcp_index.py`, run in the deploy right after the indexes are
  built (§12.2), with its own offline test in `scripts/test_*.py`. It checks index size budgets and required
  fields. It also checks that every id resolves to a slice or page, that no roster `id` or
  positional candidate id is exposed as a key, that ZIP shares sum to ~1 and keep every district,
  and that the Georgia Commons slug table covers every session in `ga-bills.json`. Links pass the
  existing link validator.
- **CPU guard:** a test asserts that the largest index parses within a set ms budget.
- **Observability:** Workers analytics, and `/health` returning the age of each index's `generatedAt`.

## 12. Decisions on the former open questions (settled 2026-11-21)

Measurements were taken locally on 2026-11-21. Node 25 timings are a proxy: Workers CPU time is
measured differently, so Phase 0 confirms each one on a real Worker.

1. **Transport: Cloudflare's `createMcpHandler` (the `agents` package), stateless, with no
   Durable Objects.** Cloudflare's docs describe it as the recommended way to build a new MCP
   server. It runs in a plain Worker and builds a fresh server for each request, which suits a
   read-only server with no sessions. The docs now target MCP TypeScript SDK v2, so Phase 0
   pins exact versions of `agents` and the SDK and follows the docs for that version.
   `McpAgent` and its Durable Objects are not needed.
2. **The indexes are built at deploy, not committed.** `build_mcp_index.py` runs in
   `deploy-pages.yml` after `build_entity_pages.py`, and writes `assets/data/mcp/*`
   (gitignored), the same way the share cards are built. The indexes therefore always describe
   the exact data the site deploys, can't drift from it, and add no git history. The validator
   runs in the same step. **Amended in Phase 1:** a failed build or check does not stop the site
   deploy. The step removes `assets/data/mcp/`, so the server finds no index and says so rather
   than serving a bad one, and the `report-degraded` job flags the run (the same pattern as the
   entity pages and share cards). Stopping every site deploy for a server not yet in service
   would put the wrong thing at risk.
3. **Bills: shard by session and bill type, and parse once per isolate.**
   - **Measured:** all 5,656 bills as compact positional rows (interned subjects and statuses)
     come to 938 KB raw, 262 KB gzipped. That's over the 150 KB target. Parsing them plus a
     keyword scan took a median 2.3–2.7 ms and up to 4.5 ms in Node.
   - **Titles are not the cost:** truncating them to 120 characters saves only 32 KB.
   - **Shards:** `<session>-<HB|HR|SB|SR>`. A lookup by number reads one shard, about a quarter of
     the size. A keyword search reads the current session's four shards.
   - **Parse once:** the Worker keeps the parsed shards in module scope, so a warm isolate parses
     each shard only once.
   - Phase 0 measures the real Worker CPU time. If a cold keyword search goes over the CPU limit,
     the fallback is a precomputed token → bill-id index.
4. **Origin caching is acceptable as is.** Checked 2026-11-21: `www.votega.org/assets/data/*.json`
   is served with `Cache-Control: max-age=600` and `cf-cache-status: DYNAMIC`, so Cloudflare does
   not cache JSON at the edge. The Worker's own Cache API, with the TTLs in §5.3, is the only
   cache layer, which keeps staleness to the TTL plus at most 10 minutes.
5. **Federal: members and votes are in v1** (decided by the site owner).
   - Federal members appear in `search_legislators`, `get_legislator` and
     `find_my_representatives`.
   - `get_legislator_votes` covers the 16 members from the existing `federal-votes/` slices and
     the full index (300 KB raw, 55 KB gzipped, the same file the site loads lazily). Federal
     bills and sponsorship wait for v2.
   - **The 120th Congress:** the votes tool reports the Congress the data covers, and after
     January 3 a frozen 119th record lives in `Votega/ga-federal-legislators` `sessions/119th/`.
6. **The county table is computed from the tract table, with population shares.**
   - `ga-county-district-map.csv` has no shares, and nothing in the repo reads it.
   - `scripts/data/ga-tract-districts.json` (228 KB) is the source the `ga-district-information`
     publisher already rolls up into its county table with `counties_doc()`.
   - `build_mcp_index.py` imports that function, so the county figures match the published
     dataset by construction and the Worker never fetches from another repository.
7. **Georgia Commons matching does not block the MCP server.** Their bill pages link sponsors to
   `votegaUrl`, which was verified on 2026-11-12. Every URL `votegaUrl` has ever pointed to stays
   alive through the legislator ledger and the frozen bienniums. So whichever key they match on,
   the link we hand out stays valid across the rollover. The server returns `votegaUrl` and
   `legisGaGovId`. The question stays open in the collaboration doc as a matter for their side.
8. **Seat history waits for v2** (decided by the site owner). General public users rarely ask
   for it, and `seats.json` / `seat-holds.json` are still being built under their own design.
9. **Two checks added to the Phase 0 spike:**
   - **Bot protection:** Cloudflare's Bot Fight Mode once returned 403 to Googlebot across the
     whole site. Confirm that the Worker's subrequests to `www.votega.org` are not challenged, or
     allowlist them with a WAF skip rule scoped to the Worker.
   - **Isolate reuse:** confirm that the module-scope parse cache (point 3) actually survives
     between requests often enough to matter.
10. **Local officials are in v1** (`find_local_officials`, decided by the site owner).
    - **Source:** the tool reads an index built at deploy from `_data/local_officials.yml` and
      `_data/county_officers.yml`. That's the same data the `/local/<slug>/` pages render. The
      published `Votega/ga-local-government` `officials.json` is not used, because the Worker
      fetches only from `www.votega.org`.
    - **Coverage:** these rosters are reviewed by a person and incomplete, so every result
      carries its last-reviewed date and source. A place we don't cover returns an explicit "not
      covered" with no names.
    - **Sheriffs:** they come from `county_officers.yml` and are kept apart from the commission,
      as on the site.

### 12.11 Phase 0 results (measured 2026-11-21 on the deployed Worker)

**Setup.** The Worker `votega-mcp` serves the custom domain `mcp.votega.org`; the `workers.dev`
URL is disabled (it returns 404). It uses `agents` 0.33.0 and `@modelcontextprotocol/server`
2.4.0, and runs on the free plan. Startup time is 34–44 ms (the limit is 1 s), and the bundle is
688 KB, or 137 KB gzipped.

**How CPU was measured.** The benchmark routes under `/bench/` read files built by
`mcp/bench/make_bench_data.py` from the committed data, served privately through the Worker's
assets binding. Each request logs its isolate's request count, so cold and warm requests can be
told apart. CPU time per request comes from Workers Observability: 481 requests in 6 parallel
streams, all `ok`, no errors. Observability reports CPU time in whole milliseconds.

| Scenario | p50 ms | p90 ms | max ms |
|---|---|---|---|
| Empty route (runtime baseline) | 0 | 0 | 0 |
| MCP `tools/call ping` | 2 | 9 | 18 |
| MCP `tools/list` | 1 | 3 | 19 |
| One bills shard (`2025_26-HR`, 308 KB): parse + title scan | 2 | 4 | 6 |
| Keyword search over the four current-session shards, no cache | 6 | 11 | 12 |
| The same with the parse-once cache (`memo`) | 1 | 9 | 15 |
| All bills in one file (882 KB) | 6 | 8 | 15 |
| `federal-votes-index.json` (301 KB) | 2 | 3 | 4 |
| `ga-members.json` (697 KB) | 3 | 5 | 7 |
| Largest ZIP shard (prefix 300, 87 ZIPs, 33 KB) | 0 | 1 | 1 |

Cold isolates were rare in this run (9 of 481), so these figures are mostly warm. Cold MCP
requests measured 8–9 ms.

**What it shows.**
1. **The data reads fit, except bills keyword search.** The ZIP lookup, the federal votes
   index, the roster and a single bills shard all stay under 10 ms on their own. Adding the SDK's
   own cost, a bills keyword search (about 6 ms + about 2 ms) is over 10 ms often enough at p90.
   So keyword search gets the token index fallback named in §12.3: a precomputed
   word → bill-id table, built at deploy, so a search reads a small table instead of scanning
   every title.
2. **The SDK's own cost has a long tail.** Even warm, `ping` and `tools/list` occasionally take
   18–19 ms with no data read at all. That's outside our code (most likely garbage collection),
   and no data layout can fix it.
3. **The free plan's 10 ms limit was not enforced on these overruns:** 0 errors in 481
   requests, including several over 10 ms. Cloudflare documents 10 ms as the limit, so this
   leniency shouldn't be relied on. The decision rule from §10 stands: move to the Workers Paid
   plan ($5/month, 30 s of CPU) at the first `exceededCpu` outcome in production, or sooner if
   the tool set grows.
4. **Bot protection doesn't block the Worker (§12.9):** in production, its subrequest to
   `www.votega.org` returned 200 and the roster parsed. The zone's crawler protection (AI
   Labyrinth) labelled the benchmark responses `link_maze_injected`. It only adds hidden links
   to HTML responses. There is no per-hostname exemption: it is a zone-wide toggle
   (`crawler_protection`), the Rulesets API exposes no phase for its HTML transform, and the
   skip action covers only security products (checked 2026-11-21). **Design rule instead: the
   server never returns HTML.** `/` is plain text and `/mcp` returns JSON or SSE. A future
   HTML landing page goes on www.votega.org (`/open-data`), not on this host.
5. **Isolates are reused (§12.9):** 40 rapid pings spread over 10 isolates, an average of 4
   requests each and up to 9. The parse-once cache therefore helps under steady traffic. Under
   light traffic most requests will be cold, so shard sizes, not the cache, are what keep the
   CPU budget.
6. **New public hostnames are probed immediately.** Within minutes of the certificate being
   issued, scanners asked for `/.env`, `/.ssh/id_rsa`, `/docker-compose.yml` and similar, and
   got 404s. That's expected, and is one more reason for the rate-limit rule in §9.
7. **Locked down after the measurements (2026-11-21).** The live Worker is a placeholder
   (`0.0.2-placeholder`) whose only tool is `ping`. The benchmark routes and data files are
   removed (they return 404), Observability logging is off, no route fetches
   www.votega.org (so nothing a stranger calls costs subrequests or a large parse), and
   `workers.dev` is disabled. The benchmarks can be re-run from `mcp/bench/make_bench_data.py`
   and the assets setting noted in `mcp/wrangler.jsonc`.

### 12.12 Phase 1 results (core indexes, built 2026-11-21)

Phase 1 was split: the **core indexes** the Phase 2 tools read are built, and the rest (bills
shards and the word → bill-id table, races, candidates, EOs, local mentions, former members)
move to the start of Phase 3, which is the first phase that reads them.

- **Code:** `scripts/lib/mcp_index.py` (the rules, pure functions), `scripts/build_mcp_index.py`
  (loads the inputs, writes `assets/data/mcp/` through a temp directory that is swapped in whole),
  `scripts/validate_mcp_index.py` (tier 1), `scripts/test_mcp_index.py` (offline, stdlib only,
  with a negative control for every check). The deploy step is "Generate MCP indexes" in
  `deploy-pages.yml`, between share cards and Jekyll.
- **Sizes on the committed data:**

| File | Rows | Raw | Gzip |
|---|---|---|---|
| `members-index.json` | 263 (247 GA + 16 federal) | 194 KB | 27.6 KB |
| `local-officials-index.json` | 71 places | 203 KB | 19.6 KB |
| `counties-index.json` | 159 | 53 KB | 8.6 KB |
| `zip/<zip3>.json` | 22 shards, 922 ZIPs | ≤ 33 KB | ≤ 5.0 KB |
| all 25 files | | | 104 KB |

  Every file is well under the 150 KB budget; the largest raw file (local officials, 203 KB) is
  below the roster file Phase 0 parsed in 3–5 ms.
- **Shapes worth knowing for Phase 2:**
  - Members keep departed members (`serving: false`, with `status`), because their pages exist
    and `find_my_representatives` needs to see that a seat's member left. Suspended members are
    `serving: true` with `status: "Suspended"`.
  - `slices` holds the vote and sponsorship file paths, or null when no file exists (2 members
    today: one has no sponsorship slice, a newly seated member has neither).
  - Local officials keep the sitting board **and** staged incoming rows (`takesOffice` in the
    future), with history dropped. The Worker filters on the request date, so the January 1
    turnover is right between deploys.
  - `meta.json` carries each file's bytes, gzip bytes, sha256 and count, every
    `data_freshness.yml` dataset with its own stamp and check date (for `get_data_freshness`),
    and the local rosters' last-reviewed date.
- **Found for Phase 3:** `_config.yml` excludes `assets/data/eo-text/` from the served site, so
  the EO text slices named in §5.2 are not reachable from the Worker. Phase 3 either publishes
  them or leaves EO text out of v1.
- **Not yet verified:** that the files are served at `www.votega.org/assets/data/mcp/` after a
  deploy (`_config.yml` does not exclude the path, so Jekyll should copy them). Check
  `/assets/data/mcp/meta.json` after the first deploy from `main`.

### 12.13 Phase 2 (core tools, built 2026-11-21)

Decided by the site owner: the tools go **live but unannounced** on `mcp.votega.org` (launch is
still after the rollover); the Worker deploys from **CI with a scoped token**; the vote
**scorecard moves to Phase 3** with `get_legislator_votes`; tests run in the **Workers runtime**
(Vitest with `@cloudflare/vitest-plugin`, the renamed `vitest-pool-workers`).

- **Tools:** `find_my_representatives`, `find_local_officials`, `search_legislators`,
  `get_legislator`, `get_data_freshness`. Code: `mcp/src/tools/*.ts` (one module per tool
  family, each taking a `Loader`), `mcp/src/server.ts` (registration, zod inputs),
  `mcp/src/worker.ts` (routes), `mcp/src/index.ts` (entry: exports only the handler, because
  workerd rejects any other named export from the entry module, found when `wrangler dev`
  refused to start).
- **Data:** `mcp/src/data.ts` fetches only the index paths it allows (a fixed list plus
  `zip/<3 digits>.json`) from `www.votega.org/assets/data/mcp/`, with `cf.cacheTtl` per §5.3 and a
  module memo; on an upstream failure it serves the last parsed copy and the result carries
  `stale: true`. `get_legislator` accepts `ga:<n>`, `us:<bioguideId>`, a vgId or a bare
  legisGaGovId. `session` is not an input yet: frozen bienniums come with Phase 3.
- **Rules enforced in code and tests:** a split ZIP lists every district with its share and one
  sentence saying only a street address decides; a seat whose member left is `vacant`, never
  filled with them; members who left office appear only with `include_former` or by id, and never
  with contact details; an uncovered place names nobody; local rosters turn over on January 1 by
  the request date; every string is stripped of control characters and capped at 500 characters.
- **Tests:** 31 in `mcp/test/` (tool logic over invented fixtures, the loader's path allowlist,
  memo and stale fallback, and the Worker end to end over HTTP). Run locally with `wrangler dev`
  against the live indexes: every tool answered on real data (e.g. ZIP 30014 touches 4 Senate,
  6 House and 2 U.S. House districts; 13059 returns Athens-Clarke; "Gotham" is not covered).
- **Bundle:** 1,259 KB raw, 220 KB gzipped (Phase 0: 688 / 137 KB; zod is most of the growth),
  inside the free plan's 3 MB. Startup time is re-checked on the first deploy.
- **Deploy:** `.github/workflows/deploy-mcp.yml` runs typecheck and tests on PRs touching `mcp/`,
  and on `main` deploys with `wrangler deploy` and checks that `/health` reports the new
  version. It needs `CLOUDFLARE_API_TOKEN` (Workers edit on this account, plus the zone for the
  custom-domain route) and `CLOUDFLARE_ACCOUNT_ID`; without them the deploy job skips with a
  notice.
- **Origin check:** browser requests are limited to the library's default Origins (localhost
  and the server's own host). Non-browser MCP clients send no Origin and are unaffected. Whether
  to allow any Origin, as §9 suggests for browser-based clients, is a launch decision.

## 13. Rollout

| Phase | Scope | Exit criteria |
|---|---|---|
| 0. Spike | Hello-world `createMcpHandler` Worker on `mcp.votega.org`; pinned SDK versions; Worker CPU time for a bills shard, a ZIP shard and the federal votes index; the bot-protection and isolate-reuse checks (§12.9) | Each §12 measurement confirmed on a Worker, or the named fallback chosen |
| 1. Indexes (core: done 2026-11-21, §12.12) | `build_mcp_index.py` + validator in `deploy-pages.yml`: members, ZIP shards, county index, local officials, meta. Bills shards + token table, races, candidates, EOs, local mentions and former members moved to Phase 3 | Index files built at deploy, within budgets |
| 2. Core tools (what a voter asks first; built 2026-11-21, §12.13) | `find_my_representatives`, `find_local_officials`, `search_legislators` / `get_legislator` (state and federal), `get_data_freshness` | Passes Inspector + unit tests |
| 3. Remaining tools | The remaining indexes (bills shards + word → bill-id table, races, candidates, EOs, local mentions, former members); `search_races` / `get_candidate`, `get_legislator_votes` (GA and federal), bills, EOs, local government, former members and `session`, resources/prompts | Full v1 tool set |
| 4. Launch | Docs page on votega.org (an addition to `/open-data`), README entry, client config snippets (Claude, Cursor, etc.), rate-limit rule; proposed for after the 2027-01-11 rollover (§7) | Public, announced |
| 5. v2 | Street-address lookup (needs a geocoding and privacy decision), federal bills and sponsorship, seat history, optional KV/D1 search, Georgia Commons text if their license allows it | Separate spec |

## 14. Effort estimate

Phases 0–2: small to medium (a focused few days); phases 3–4 similar. The v1 additions each add
about a day:
- `find_my_representatives` (the ZIP shards and county index are simple joins over existing tables);
- `find_local_officials` (one more index over two YAML files);
- federal votes (existing slices, decoded with the site's existing format).

The largest risk is still the CPU budget on bills search (§12.3): sharding mitigates it, and a
token index is the fallback.
