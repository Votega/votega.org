/**
 * VoteGA MCP server — Phase 0 spike.
 *
 * A stateless, read-only MCP server on Cloudflare Workers (createMcpHandler, MCP SDK v2,
 * no Durable Objects). This spike carries only diagnostic tools; the real tool set is
 * Phases 2-3 of docs/superpowers/specs/2026-10-23-mcp-server-design.md.
 *
 * Routes: POST /mcp (MCP), GET / (plain-text landing), GET /health (JSON).
 */
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";

const VERSION = "0.0.1-spike";
const ORIGIN = "https://www.votega.org";

// Module scope survives between requests only while this isolate stays warm, which is
// exactly what the spike needs to measure (spec §12.9: does a parse cache pay off?).
// `id` tells isolates apart. Both it and `startedAt` are set on the first request:
// Workers forbid random values at module scope, and freeze the clock there (Date reads
// 1970-01-01).
const isolate = { id: "", startedAt: "", requests: 0 };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

/** Can this Worker read the site's data, or does bot protection challenge it? (spec §12.9) */
async function originCheck() {
  const url = `${ORIGIN}/assets/data/ga-members.json`;
  const t = Date.now();
  try {
    const res = await fetch(url, { headers: { "user-agent": "votega-mcp/" + VERSION } });
    const type = res.headers.get("content-type") || "";
    let parsed = false;
    if (res.ok && type.includes("json")) {
      parsed = Array.isArray(((await res.json()) as { members?: unknown[] }).members);
    }
    return { url, status: res.status, contentType: type, parsedAsRoster: parsed,
             cfCacheStatus: res.headers.get("cf-cache-status"), ms: Date.now() - t };
  } catch (e) {
    return { url, error: String(e), ms: Date.now() - t };
  }
}

function createServer() {
  const server = new McpServer({ name: "votega", version: VERSION });

  server.registerTool(
    "ping",
    {
      description:
        "Phase 0 diagnostic: confirms the VoteGA MCP server is reachable and reports " +
        "whether this request reused a warm isolate. Returns no civic data.",
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => ({
      content: [{
        type: "text",
        text: JSON.stringify({ server: "votega", version: VERSION, isolate }),
      }],
    }),
  );

  server.registerTool(
    "origin_check",
    {
      description:
        "Phase 0 diagnostic: fetches one published VoteGA data file from www.votega.org " +
        "and reports whether the Worker could read it. Returns no civic data.",
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => ({ content: [{ type: "text", text: JSON.stringify(await originCheck()) }] }),
  );

  return server;
}

// ---- Phase 0 benchmarks (spec §12.3, §12.9). Removed before launch. ----------------
// Each route does one thing, so Workers Observability's per-request cpuTimeMs can be
// read per scenario. `memo=1` keeps the parsed file in module scope (the planned
// parse-once-per-isolate cache); the log line says whether the isolate was warm.
type Env = { ASSETS: { fetch: (req: Request | string) => Promise<Response> } };
const BENCH_FILES = new Set([
  "bills-2025_26-HB.json", "bills-2025_26-HR.json", "bills-2025_26-SB.json", "bills-2025_26-SR.json",
  "bills-all.json", "zip-largest.json", "federal-votes-index.json", "ga-members.json",
]);
const CURRENT_BILL_SHARDS = ["bills-2025_26-HB.json", "bills-2025_26-HR.json",
                             "bills-2025_26-SB.json", "bills-2025_26-SR.json"];
const parsed = new Map<string, unknown>();

async function loadJson(env: Env, file: string, memo: boolean) {
  if (memo && parsed.has(file)) return parsed.get(file);
  const res = await env.ASSETS.fetch(`https://assets.local/${file}`);
  const value = JSON.parse(await res.text());
  if (memo) parsed.set(file, value);
  return value;
}

function scanTitles(doc: unknown, q: string) {
  const rows = (doc as { rows?: unknown[][] }).rows || [];
  let hits = 0;
  for (const r of rows) if (String(r[2]).toLowerCase().includes(q)) hits++;
  return hits;
}

async function bench(url: URL, env: Env): Promise<Response> {
  const memo = url.searchParams.get("memo") === "1";
  const q = (url.searchParams.get("q") || "school").toLowerCase();
  const name = url.pathname.slice("/bench/".length);
  let result: unknown = "ok";
  if (name === "parse") {
    const f = url.searchParams.get("f") || "";
    if (!BENCH_FILES.has(f)) return new Response("unknown file", { status: 400 });
    const doc = await loadJson(env, f, memo);
    result = { f, hits: scanTitles(doc, q) };
  } else if (name === "bills-search") {
    let hits = 0;
    for (const f of CURRENT_BILL_SHARDS) hits += scanTitles(await loadJson(env, f, memo), q);
    result = { shards: CURRENT_BILL_SHARDS.length, hits };
  } else if (name !== "noop") {
    return new Response("unknown bench", { status: 404 });
  }
  return json({ bench: name, memo, warm: isolate.requests > 1, isolate, result });
}

const mcp = createMcpHandler(createServer, {
  route: "/mcp",
  allowedHostnames: ["mcp.votega.org", "localhost", "127.0.0.1"],
});

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    isolate.requests += 1;
    if (!isolate.id) {
      isolate.id = crypto.randomUUID().slice(0, 8);
      isolate.startedAt = new Date().toISOString();
    }
    const url = new URL(request.url);
    const { pathname } = url;
    // One line per request, joined to its cpuTimeMs by requestId in Observability.
    console.log(JSON.stringify({ spike: 1, path: pathname, query: url.search,
                                 iso: isolate.id, n: isolate.requests }));
    if (pathname.startsWith("/bench/")) return bench(url, env);
    if (pathname === "/mcp") return mcp(request, env, ctx);
    if (pathname === "/health") {
      return json({ ok: true, version: VERSION, isolate, origin: await originCheck() });
    }
    if (pathname === "/") {
      return new Response(
        "VoteGA MCP server (Phase 0 spike, not yet a public service).\n" +
        "MCP endpoint: POST /mcp (Streamable HTTP). Health: GET /health.\n" +
        "Data: https://www.votega.org/open-data\n",
        { headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }
    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
