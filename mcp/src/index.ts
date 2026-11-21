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
const isolate = { startedAt: new Date().toISOString(), requests: 0 };

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

const mcp = createMcpHandler(createServer, {
  route: "/mcp",
  allowedHostnames: ["mcp.votega.org", "localhost", "127.0.0.1"],
});

export default {
  async fetch(request: Request, env: unknown, ctx: ExecutionContext): Promise<Response> {
    isolate.requests += 1;
    const { pathname } = new URL(request.url);
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
} satisfies ExportedHandler;
