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

  it("lists and reads the votega:// resources", async () => {
    const list = (await rpc("resources/list")).msg.result.resources as { uri: string; mimeType: string }[];
    expect(list.map((r) => r.uri).sort()).toEqual(["votega://about", "votega://datasets", "votega://glossary"]);
    const about = (await rpc("resources/read", { uri: "votega://about" })).msg.result.contents[0];
    expect(about.mimeType).toBe("text/plain");
    expect(about.text).toContain("VoteGA is a nonpartisan record.");
    expect(about.text).toContain("NOT YET AVAILABLE THROUGH THE SERVER");
    const glossary = (await rpc("resources/read", { uri: "votega://glossary" })).msg.result.contents[0].text as string;
    expect(glossary).toContain("District\nThe area one legislator represents.");
    expect(glossary).toContain("A fraction of residents.");
    expect(glossary).not.toContain("\u0007"); // control characters stripped
    const ds = JSON.parse((await rpc("resources/read", { uri: "votega://datasets" })).msg.result.contents[0].text);
    expect(ds.datasets[0].summary).toHaveLength(700); // no 500-character cap on resources
    expect(ds.license).toBe("CC BY-SA 4.0");
  });

  it("lists the two prompts and fills them", async () => {
    const list = (await rpc("prompts/list")).msg.result.prompts as { name: string; arguments: { name: string; required: boolean }[] }[];
    expect(list.map((p) => p.name).sort()).toEqual(["local_officials", "who_represents_area"]);
    expect(list.find((p) => p.name === "who_represents_area")!.arguments[0]).toMatchObject({ name: "area", required: true });

    const get = async (name: string, args: Record<string, string>) =>
      (await rpc("prompts/get", { name, arguments: args })).msg.result.messages[0].content.text as string;

    const zip = await get("who_represents_area", { area: " 30001 " });
    expect(zip).toContain('find_my_representatives with zip "30001"');
    expect(zip).toContain("never pick one as mine");
    expect(zip).toContain("cite each source_url");

    // A county name is resolved to its FIPS from the counties index.
    expect(await get("who_represents_area", { area: "newton county" })).toContain('county_fips "13217"');
    expect(await get("who_represents_area", { area: "13013" })).toContain('county_fips "13013"');
    // Unknown text: the model asks rather than guesses.
    expect(await get("who_represents_area", { area: "Atlantis" })).toContain("Ask me for my ZIP");

    const local = await get("local_officials", { place: "Covington\u0007" });
    expect(local).toContain('find_local_officials with place "Covington"');
    expect(local).not.toContain("\u0007");
    expect(local).toContain("name nobody");
    expect(await get("local_officials", { place: "13217" })).toContain('county_fips "13217"');
  });

  it("rejects an oversized prompt argument", async () => {
    const { msg } = await rpc("prompts/get", { name: "local_officials", arguments: { place: "x".repeat(81) } });
    expect(msg.error).toBeTruthy();
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
