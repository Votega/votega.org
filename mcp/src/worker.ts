/**
 * VoteGA MCP server (Phase 2: the core tools; live but unannounced until launch, spec §13).
 *
 * A stateless, read-only MCP server on Cloudflare Workers (createMcpHandler, MCP SDK v2, no
 * Durable Objects). It reads only the index files build_mcp_index.py publishes under
 * https://www.votega.org/assets/data/mcp/ (src/data.ts). Spec:
 * docs/superpowers/specs/2026-10-23-mcp-server-design.md.
 *
 * Privacy (spec §9): no request logging (Workers Observability is off in wrangler.jsonc), no
 * cookies, no state. A ZIP a user enters is used for the lookup and kept nowhere.
 *
 * Workers forbid random values at module scope and freeze the clock there (Date reads
 * 1970-01-01), so the clock is read inside each request.
 *
 * Routes: POST /mcp (MCP), GET / (plain text), GET /health (JSON).
 *
 * src/index.ts is the entry module and exports only the handler: workerd rejects any other
 * named export from the entry, so everything tests import lives here.
 */
import { createMcpHandler } from "agents/mcp/server";
import { httpLoader, type Loader } from "./data";
import { createServer, VERSION } from "./server";
import type { Meta } from "./types";

export const MAX_BODY = 16 * 1024; // spec §9

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

/** The Worker, with the loader factory injectable for tests. */
export function makeWorker(loaderFor: (nowMs: number) => Loader = (now) => httpLoader(now)) {
  return {
    async fetch(request: Request, env: unknown, ctx: ExecutionContext): Promise<Response> {
      const { pathname } = new URL(request.url);
      const now = Date.now();
      if (pathname === "/mcp") {
        const len = Number(request.headers.get("content-length") ?? "0");
        if (len > MAX_BODY) return json({ error: "request body too large" }, 413);
        const loader = loaderFor(now);
        const handler = createMcpHandler(() => createServer(loader, now), {
          route: "/mcp",
          allowedHostnames: ["mcp.votega.org", "localhost", "127.0.0.1"],
        });
        return handler(request, env, ctx);
      }
      if (pathname === "/health") {
        let index: { generatedAt: string | null; ageHours: number | null; stale: boolean } | null = null;
        try {
          const loader = loaderFor(now);
          const meta = await loader.load<Meta>("meta.json");
          const at = meta?.metadata.generatedAt ?? null;
          index = {
            generatedAt: at,
            ageHours: at ? Math.round((now - Date.parse(at)) / 360_000) / 10 : null,
            stale: loader.stale,
          };
        } catch {
          index = null;
        }
        return json({ ok: index !== null && index.generatedAt !== null, version: VERSION, index });
      }
      if (pathname === "/") {
        return new Response(
          "VoteGA MCP server: in testing, not yet announced.\n" +
            "MCP endpoint: POST /mcp (Streamable HTTP). Health: GET /health.\n" +
            "Data: https://www.votega.org/open-data\n",
          { headers: { "content-type": "text/plain; charset=utf-8" } },
        );
      }
      return new Response("Not found", { status: 404 });
    },
  } satisfies ExportedHandler;
}

