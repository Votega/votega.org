/**
 * VoteGA MCP server: placeholder until Phase 2.
 *
 * A stateless, read-only MCP server on Cloudflare Workers (createMcpHandler, MCP SDK v2,
 * no Durable Objects). Phase 0 is done (results: spec §12.11); this build is locked down
 * until the real tool set lands, and carries only `ping`. The tool set is Phases 2-3 of
 * docs/superpowers/specs/2026-10-23-mcp-server-design.md.
 *
 * Locked down on 2026-11-21:
 * - no benchmark routes and no bundled data files;
 * - no per-request logging (Workers Observability is off in wrangler.jsonc, because its
 *   invocation logs record client IPs and headers, which spec §9 rules out);
 * - no route fetches www.votega.org, so nothing a stranger calls can spend subrequests
 *   or parse a large file.
 *
 * Routes: POST /mcp (MCP), GET / (plain-text landing), GET /health (JSON).
 *
 * Workers forbid random values at module scope and freeze the clock there (Date reads
 * 1970-01-01), so anything time- or random-based must be created inside a request.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";

const VERSION = "0.0.2-placeholder";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function createServer() {
  const server = new McpServer({ name: "votega", version: VERSION });

  server.registerTool(
    "ping",
    {
      description:
        "Confirms the VoteGA MCP server is reachable. The server is not yet in service " +
        "and returns no civic data; see https://www.votega.org/open-data for the datasets.",
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => ({
      content: [{ type: "text", text: JSON.stringify({ server: "votega", version: VERSION }) }],
    }),
  );

  return server;
}

const mcp = createMcpHandler(createServer, {
  route: "/mcp",
  allowedHostnames: ["mcp.votega.org", "localhost", "127.0.0.1"],
});

export default {
  async fetch(request: Request, env: unknown, ctx: ExecutionContext): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/mcp") return mcp(request, env, ctx);
    if (pathname === "/health") return json({ ok: true, version: VERSION });
    if (pathname === "/") {
      return new Response(
        "VoteGA MCP server: not yet in service.\n" +
        "MCP endpoint: POST /mcp (Streamable HTTP). Health: GET /health.\n" +
        "Data: https://www.votega.org/open-data\n",
        { headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }
    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler;
