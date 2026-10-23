# VoteGA MCP Server (Cloudflare Workers) — Design Spec

Status: Draft for review · Date: 2026-10-23

## 1. Summary

A **remote, read-only, unauthenticated MCP server** at `https://mcp.votega.org/mcp`
(Streamable HTTP) on **Cloudflare Workers (free tier)**. It lets any MCP-capable AI
assistant look up Georgia legislators, bills, races/candidates, executive orders and
local-government mentions from VoteGA's already-published open data, with a source link
and "as of" date on every answer.

Matches the project's stance: no key, no signup, nonpartisan, sourced to official records.

## 2. Goals / Non-goals

**Goals**
- Public data lookups over existing datasets (legislators, federal delegation, bills, races, candidates, EOs, local mentions).
- Zero new data pipeline in v1 beyond small, precomputed index files.
- Always-current data (no stale copy inside the Worker).
- Stay inside Workers free limits.

**Non-goals (v1)**
- Voter/address lookup ("find my reps") — deferred to v2 (ZIP→district tables exist: `ga-zip-districts.json`).
- Maintainer/ops tools (freshness, workflow status). Would need auth + GitHub API.
- Any write operation, user accounts, or tracking of queries.
- Endorsements, rankings, or advocacy framing. Tools return facts + sources only.

## 3. Constraints that drive the design

| Constraint | Consequence |
|---|---|
| Free tier: ~10 ms CPU/request, 100k req/day, 128 MB memory | Worker must **not** `JSON.parse` multi-MB files per request |
| Large source files (`ga-bills.json` 7.2 MB, `current-members.json` 1.5 MB, `races.json` 1.2 MB) | Worker reads only **small precomputed indexes** and **per-entity slices** |
| Site is static Jekyll on GitHub Pages; data also in `Votega/ga-*` repos | Worker fetches published JSON over HTTPS; edge-caches it |
| KV free tier: 1k writes/day | KV avoided in v1; use Cache API instead |

## 4. Architecture

```
AI client ──MCP (Streamable HTTP)──▶ mcp.votega.org  (Cloudflare Worker)
                                        │
                                        ├─ Cache API (per-colo, TTL by dataset)
                                        └─ fetch ─▶ www.votega.org/assets/data/mcp/*.json   (indexes)
                                                  └▶ www.votega.org/assets/data/<slice>   (per-entity slices)
```

- **Runtime:** TypeScript, `@modelcontextprotocol/sdk` + Cloudflare `agents`/`McpAgent`
  or the SDK's Web-standard Streamable HTTP transport in **stateless** mode
  (no Durable Objects needed; avoids DO free-tier limits). Decide in implementation spike (§11).
- **Stateless:** every request self-contained; no sessions.
- **Routing:** `POST /mcp` (MCP), `GET /` (human landing page + tool list), `GET /health`.
- **Repo location:** new top-level `mcp/` directory (own `package.json`, `wrangler.toml`),
  excluded from the Jekyll build via `_config.yml` `exclude:`.
- **Deploy:** GitHub Action on changes to `mcp/**` using `wrangler deploy` with a scoped
  `CLOUDFLARE_API_TOKEN` secret. DNS: `mcp` CNAME → Worker custom domain.

## 5. Data access layer

### 5.1 MCP index files (new, generated at site build)
A new script `scripts/build_mcp_index.py` (same pattern as existing `scripts/build_*`)
emits compact, search-ready files under `assets/data/mcp/`, each **< ~150 KB** gzipped
target, so parse cost stays inside the CPU budget:

| File | Contents (per row) | Source |
|---|---|---|
| `members-index.json` | id, name, chamber, party, district, county/city hint | `ga-members.json`, `current-members.json` |
| `bills-index.json` | id, number, short title, status, sponsor ids, subjects, last action date | `ga-bills.json` |
| `races-index.json` | race id, office, district, date, candidate ids | `races.json` |
| `candidates-index.json` | id, name, party, race id | `races.json`, `ga-legislative-candidates.json` |
| `eo-index.json` | number, date, title, category, pdf url | `ga-executive-orders-*.json` |
| `local-mentions-index.json` | place, topic, date, title, source url | ga-local-government mentions |
| `meta.json` | dataset → `generatedAt`, source, license | `_data/data_freshness.yml`, file metadata |

If an index would exceed budget (bills likely), **shard** (`bills-index-<A..Z|status>.json`)
and have the Worker pick shards from the query.

### 5.2 Per-entity slices (existing)
Detail calls fetch existing slice directories (`ga-votes/`, `ga-sponsorship/`,
`federal-votes/`, `federal-sponsorship/`, `agency-actions/`, `eo-text/`) by ID. These are
already small, ID-addressed files.

### 5.3 Caching
- Cache API keyed on URL; TTL by dataset cadence: roster/bills 1 h, races 15 min
  (election season), EOs 6 h, local mentions 6 h, meta 5 min.
- `stale-while-revalidate` on upstream failure: serve stale and flag `stale: true`.
- Index files include a content hash in `meta.json` so clients/tests can detect drift.

### 5.4 Search
In-Worker, over the small indexes only: normalized lowercase substring + token match,
simple field weights, hard cap on results (default 10, max 25). No embeddings in v1.

## 6. Tools (v1)

All tools: `readOnlyHint: true`, `openWorldHint: false`. Inputs validated with `zod`.
Every result includes `source_url`, `as_of` (from `meta.json`), and `license: "CC BY-SA 4.0"`.

| Tool | Inputs | Returns |
|---|---|---|
| `search_legislators` | `query?`, `chamber?` (house/senate/us_house/us_senate), `party?`, `district?`, `limit?` | Matching members (id, name, party, chamber, district) |
| `get_legislator` | `id` | Profile, committees, contact, official page, vote scorecard (party unity, participation) |
| `get_legislator_votes` | `id`, `session?`, `limit?` | Recent passage votes (bill, date, vote) from vote slices |
| `search_bills` | `query?`, `status?`, `sponsor_id?`, `subject?`, `limit?` | Matching bills (number, title, status, last action) |
| `get_bill` | `id` or `number` | Status, sponsors, subjects, actions, vote summary, legis.ga.gov link |
| `search_races` | `office?`, `district?`, `year?`, `county?` | Races with candidates |
| `get_candidate` | `id` | Candidate profile, race, party, links, finance summary if available |
| `list_executive_orders` | `year?`, `category?`, `query?`, `limit?` | EOs (number, date, title, category, PDF link) |
| `search_local_government` | `place?`, `topic?` (alpr/data_center/land_use), `since?`, `limit?` | Mentions with source document links |
| `get_data_freshness` | — | Per-dataset `as_of`, cadence, upstream source |

Design rules: IDs round-trip (search → get); results are compact JSON plus a one-line
text summary; no editorializing fields; party shown as data, never as ranking.

## 7. Resources and prompts

- **Resources** (static, cacheable): `votega://about` (mission, nonpartisan policy, licensing),
  `votega://datasets` (catalog from `_data/open_data.yml`), `votega://glossary` (office/district terms).
- **Prompts** (optional, small): `explain_bill`, `who_represents_district` — templates that
  instruct the model to cite `source_url` and stay neutral.

## 8. Security, abuse, and limits

- No auth, no cookies, no PII stored; **no request logging beyond Cloudflare's aggregate analytics**.
- CORS: allow `*` for `POST /mcp` (browser-based MCP clients); no credentials.
- Validate `Origin` header per MCP Streamable HTTP guidance; reject oversized bodies (>16 KB).
- Cloudflare **rate limiting rule** (WAF, free plan: 1 rule) per IP on `/mcp`; hard in-Worker result caps.
- Upstream allowlist: Worker only fetches `www.votega.org` (SSRF-safe; no user-supplied URLs).
- Treat all dataset text as untrusted: strip control chars and bound field lengths in responses
  (prompt-injection hygiene for strings originating from third-party agendas/minutes).
- Nonpartisan guardrails: tool descriptions forbid, and responses omit, endorsements or ratings.

## 9. Quotas and capacity (free tier)

Estimate: 1 tool call ≈ 1 Worker request + 1–3 cache lookups (subrequests: 50 free limit).
100k req/day ≈ 70/min sustained; sufficient for a v1 public launch. Monitor via Workers
analytics; trigger to move to paid ($5/mo) at sustained >60% of daily quota or CPU-limit errors.

## 10. Testing and observability

- **Unit:** tool handlers against fixture indexes (Vitest + `@cloudflare/vitest-pool-workers`).
- **Contract:** MCP Inspector smoke test in CI (list tools, call each with a known id).
- **Data checks:** `scripts/validate_mcp_index.py` in CI: index size budgets, required fields,
  every id resolves to a slice/page, links pass existing link validator.
- **CPU guard:** test asserts the largest index parses under a set ms budget.
- **Observability:** Workers analytics + `/health` returning index `generatedAt` ages.

## 11. Open questions / spikes

1. **Transport library:** `McpAgent` (needs Durable Objects) vs. stateless SDK transport — spike both; prefer stateless.
2. **Index freshness:** regenerate `assets/data/mcp/*` inside existing deploy-pages workflow, or its own scheduled workflow? (Prefer: part of site build so it can't drift.)
3. **Bills sharding:** does a compact bills index fit the CPU budget unsharded?
4. **GitHub Pages cache headers:** confirm `max-age` (10 min default) is acceptable as the origin cache floor.
5. **Federal data:** include federal bills/votes in v1 or follow-on?

## 12. Rollout

| Phase | Scope | Exit criteria |
|---|---|---|
| 0. Spike | Hello-world Worker on `mcp.votega.org`, transport choice, CPU measurement on real index | Decision on §11.1, §11.3 |
| 1. Indexes | `build_mcp_index.py` + validator + CI | Index files published, within budgets |
| 2. Core tools | legislators, bills, EOs, freshness | Passes Inspector + unit tests |
| 3. Remaining tools | races/candidates, local government, resources/prompts | Full v1 tool set |
| 4. Launch | Docs page on votega.org (`/open-data` addition), README entry, client config snippets (Claude, Cursor, etc.), rate-limit rule | Public, announced |
| 5. v2 | `find_my_representatives` (ZIP→districts), federal votes, optional KV/D1 search | Separate spec |

## 13. Effort estimate

Phases 0–2 ≈ small/medium (a focused few days); phases 3–4 ≈ similar. Largest risk is
the CPU budget on bills search (§11.3), mitigated by sharding.
