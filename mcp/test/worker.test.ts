/** The Worker end to end: MCP over HTTP, with a fixture loader instead of www.votega.org. */
import { createExecutionContext } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { fixtureLoader } from "../src/data";
import { makeWorker, MAX_BODY } from "../src/worker";
import { FILES } from "./fixtures";

const worker = makeWorker(() => fixtureLoader(FILES));

async function rpc(method: string, params: unknown = {}, id = 1) {
  const res = await worker.fetch(
    new Request("http://localhost/mcp", {
      method: "POST",
      headers: {
        host: "localhost", // a constructed Request has no Host; the handler checks it
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    }),
    {},
    createExecutionContext(),
  );
  const text = await res.text();
  // The response is JSON or one SSE event carrying JSON.
  const data = text.trim().startsWith("{") ? text : text.split("\n").find((l) => l.startsWith("data:"))!.slice(5);
  return { status: res.status, msg: JSON.parse(data) };
}

describe("worker", () => {
  it("lists the Phase 2 tools, all read-only", async () => {
    const { msg } = await rpc("tools/list");
    const tools = msg.result.tools as { name: string; annotations: { readOnlyHint: boolean } }[];
    expect(tools.map((t) => t.name).sort()).toEqual([
      "find_local_officials", "find_my_representatives", "get_data_freshness", "get_legislator", "search_legislators",
    ]);
    expect(tools.every((t) => t.annotations.readOnlyHint)).toBe(true);
  });

  it("calls a tool", async () => {
    const { msg } = await rpc("tools/call", { name: "find_my_representatives", arguments: { zip: "30001" } });
    const out = JSON.parse(msg.result.content[0].text);
    expect(out.found).toBe(true);
    expect(out.us_senators).toHaveLength(2);
  });

  it("rejects invalid arguments", async () => {
    const { msg } = await rpc("tools/call", { name: "find_my_representatives", arguments: { zip: "3000" } });
    expect(msg.error ?? msg.result?.isError).toBeTruthy();
  });

  it("rejects an oversized body", async () => {
    const res = await worker.fetch(
      new Request("http://localhost/mcp", {
        method: "POST",
        headers: { "content-type": "application/json", "content-length": String(MAX_BODY + 1) },
        body: "x".repeat(MAX_BODY + 1),
      }),
      {},
      createExecutionContext(),
    );
    expect(res.status).toBe(413);
  });

  it("serves /health from meta.json and never HTML", async () => {
    const res = await worker.fetch(new Request("http://localhost/health"), {}, createExecutionContext());
    const h = (await res.json()) as { ok: boolean; index: { generatedAt: string } };
    expect(h.ok).toBe(true);
    expect(h.index.generatedAt).toBe("2026-11-21T18:00:00+00:00");
    const root = await worker.fetch(new Request("http://localhost/"), {}, createExecutionContext());
    expect(root.headers.get("content-type")).toContain("text/plain");
  });
});
