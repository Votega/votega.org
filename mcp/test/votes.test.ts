import { describe, expect, it } from "vitest";
import { clearMemo, fixtureLoader, httpLoader, MismatchError, sha256Hex, UnavailableError } from "../src/data";
import { getLegislator, searchLegislators } from "../src/tools/legislators";
import { getLegislatorVotes } from "../src/tools/votes";
import type { ToolResult } from "../src/util";
import { NOW } from "./fixtures";
import { PHASE3_FILES, voteFixtures } from "./phase3-fixtures";

const files = async (extra: Record<string, unknown> = {}) => ({ ...PHASE3_FILES, ...(await voteFixtures()), ...extra });
const loader = async (extra: Record<string, unknown> = {}, drop: string[] = []) =>
  fixtureLoader(Object.fromEntries(Object.entries(await files(extra)).filter(([k]) => !drop.includes(k))));
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);

describe("get_legislator_votes (General Assembly)", () => {
  it("decodes the member's votes newest first, with the stored result", async () => {
    const r = body(await getLegislatorVotes(await loader(), { id: "ga:1" }));
    expect(r.total).toBe(3);
    expect(r.votes.map((v: { bill: string; vote: string; result: string }) => [v.bill, v.vote, v.result])).toEqual([
      ["HB 1EX", "Excused", "Fail"], ["HB 2", "Nay", "Pass"], ["HB 1", "Yea", "Pass"],
    ]);
    expect(r.votes[2]).toMatchObject({ date: "2025-02-05", motion: "PASSAGE", session: "2025_26", yea: 100, nay: 60,
      billUrl: "https://www.legis.ga.gov/legislation/11" });
    expect(r.record_covers).toBe("2025-2026");
    expect(r.summary).toContain("3 recorded vote(s) in the 2025-2026 General Assembly");
    expect(body(await getLegislatorVotes(await loader(), { id: "ga:1", session: "2026_ss" })).summary)
      .toContain("recorded vote(s) in session 2026_ss");
  });

  it("filters to one session and caps results", async () => {
    expect(body(await getLegislatorVotes(await loader(), { id: "ga:1", session: "2026_ss" })).total).toBe(1);
    const r = body(await getLegislatorVotes(await loader(), { id: "vg-ga-p-000001", limit: 1 }));
    expect([r.votes.length, r.total]).toEqual([1, 3]);
  });

  it("reads a frozen biennium for a sitting member and for a former one", async () => {
    const sitting = body(await getLegislatorVotes(await loader(), { id: "ga:1", session: "2023_24" }));
    expect(sitting.votes.map((v: { bill: string }) => v.bill)).toEqual(["HB 9"]);
    const former = body(await getLegislatorVotes(await loader(), { id: "ga:8" }));
    expect(former.votes.map((v: { bill: string }) => v.bill)).toEqual(["HB 9"]);
    expect((await getLegislatorVotes(await loader(), { id: "ga:1", session: "2001_02" })).isError).toBe(true);
  });

  it("says there is no record when the member has no vote file", async () => {
    const r = body(await getLegislatorVotes(await loader(), { id: "ga:2" }));
    expect(r.total).toBe(0);
    expect(r.summary).toContain("no voting record");
  });

  it("never matches a member file against an index from another build", async () => {
    // The index changed after the manifest was written: positions would point at other votes.
    const moved = (await voteFixtures())["data/ga-votes-index.json"] as { voteIds: string[] };
    const r = await getLegislatorVotes(
      await loader({ "data/ga-votes-index.json": { ...moved, voteIds: [...moved.voteIds].reverse() } }), { id: "ga:1" });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).toContain("updating");
  });

  it("says unavailable when the manifest or a listed file is missing", async () => {
    await expect(getLegislatorVotes(await loader({}, ["vote-files.json"]), { id: "ga:1" })).rejects.toThrow(UnavailableError);
    await expect(getLegislatorVotes(await loader({}, ["data/ga-votes-index.json"]), { id: "ga:1" }))
      .rejects.toThrow(UnavailableError);
  });
});

describe("get_legislator_votes (Congress)", () => {
  it("includes bill-less roll calls and reads pass or fail from the stored code", async () => {
    const r = body(await getLegislatorVotes(await loader(), { id: "us:A000001" }));
    expect(r.votes.map((v: { bill: string | null; vote: string; result: string; motion: string }) =>
      [v.bill, v.vote, v.result, v.motion])).toEqual([
      [null, "Nay", "Failed", "On the Nomination"], ["S 5", "Yea", "Passed", "On Passage"],
    ]);
    expect(r.record_covers).toBe("119th Congress");
  });

  it("covers only the current Congress", async () => {
    expect((await getLegislatorVotes(await loader(), { id: "us:A000001", session: "118" })).isError).toBe(true);
    expect(body(await getLegislatorVotes(await loader(), { id: "us:A000001", session: "119" })).total).toBe(2);
  });
});

describe("scorecard, former members and earlier bienniums", () => {
  it("adds party unity and participation, with the method and no ranking", async () => {
    const ga = body(await getLegislator(await loader(), { id: "ga:1" })).legislator.scorecard;
    expect(ga).toMatchObject({ covers: "2025-2026", party_unity: 0.98, participation_rate: 0.99, roll_calls: 100 });
    expect(ga.methodology.partyUnity).toContain("party-line");
    const us = body(await getLegislator(await loader(), { id: "us:A000001" })).legislator.scorecard;
    expect(us.party_unity).toBe(0.9);
    expect(JSON.stringify(us)).not.toContain("Rank");
  });

  it("leaves the scorecard null when it is unavailable, keeping the profile", async () => {
    const r = body(await getLegislator(await loader({}, ["data/ga-party-unity.json"]), { id: "ga:1" }));
    expect(r.legislator.scorecard).toBeNull();
    expect(r.legislator.name).toBe("Avery Able");
  });

  it("lists former members from earlier terms only when asked, without contact details", async () => {
    expect(body(await searchLegislators(await loader(), { query: "Hayes" })).total).toBe(0);
    const found = body(await searchLegislators(await loader(), { query: "Hayes", include_former: true }));
    expect(found.results[0]).toMatchObject({ id: "ga:8", serving: false, biennium: "2023_24",
      departure: "Did not run for re-election in 2024." });
    const r = body(await getLegislator(await loader(), { id: "ga:8" }));
    expect(r.legislator).toMatchObject({ phone: null, email: null, departure: "Did not run for re-election in 2024.",
      counties: null });
    expect(r.summary).toContain("2023-24 General Assembly");
    expect(r.summary).toContain("no longer serving");
  });

  it("gives an earlier biennium's record for a sitting member, without contact details", async () => {
    const r = body(await getLegislator(await loader(), { id: "ga:1", session: "2023_24" }));
    expect(r.legislator).toMatchObject({ id: "ga:1", district: 44, chamber: "Senate", phone: null, email: null });
    expect(r.legislator.record_covers).toBe("the 2023-24 General Assembly");
    expect((await getLegislator(await loader(), { id: "ga:2", session: "2023_24" })).isError).toBe(true);
  });
});

describe("loader", () => {
  it("fetches only listed paths under assets/data", async () => {
    clearMemo();
    const seen: string[] = [];
    const fetcher = (async (u: string) => (seen.push(u), new Response("{}"))) as unknown as typeof fetch;
    const l = httpLoader(NOW, fetcher);
    for (const p of ["vote-files.json", "bills/2025_26-HB-tokens.json", "data/ga-votes/ocd-person-a1.json",
      "data/ga-bienniums/2025_26/ga-members.json", "data/federal-votes/A000001.json"]) await l.load(p);
    expect(seen[2]).toBe("https://www.votega.org/assets/data/ga-votes/ocd-person-a1.json");
    expect(seen[0]).toBe("https://www.votega.org/assets/data/mcp/vote-files.json");
    for (const p of ["data/ga-members.json", "data/ga-votes/../ga-bills.json", "bills/../meta.json", "data/mcp/meta.json"]) {
      await expect(l.load(p)).rejects.toThrow("not an index path");
    }
  });

  it("refuses bytes that do not match the expected hash, and refetches past the cache when asked", async () => {
    clearMemo();
    let version = 1;
    const urls: string[] = [];
    const fetcher = (async (u: string) => (urls.push(u), new Response(`{"v":${version}}`))) as unknown as typeof fetch;
    const l = httpLoader(NOW, fetcher);
    const path = "data/ga-votes-index.json";
    expect(await l.load(path, { sha256: await sha256Hex('{"v":1}') })).toEqual({ v: 1 });
    version = 2;
    await expect(l.load(path, { sha256: await sha256Hex('{"v":3}'), fresh: true })).rejects.toThrow(MismatchError);
    expect(await l.load(path, { sha256: await sha256Hex('{"v":2}') })).toEqual({ v: 2 });
    expect(urls[1]).toContain("?");
  });
});
