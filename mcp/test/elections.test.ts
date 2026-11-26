import { describe, expect, it } from "vitest";
import { fixtureLoader, UnavailableError } from "../src/data";
import { getCandidate, searchRaces } from "../src/tools/elections";
import type { ToolResult } from "../src/util";
import { PHASE3_FILES } from "./phase3-fixtures";

const loader = (drop: string[] = []) =>
  fixtureLoader(Object.fromEntries(Object.entries(PHASE3_FILES).filter(([k]) => !drop.includes(k))));
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);
const ids = (r: ToolResult) => body(r).races.map((x: { id: string }) => x.id);

describe("search_races", () => {
  it("lists a race with its current ballot and certified winner", async () => {
    const r = body(await searchRaces(loader(), { office: "u.s. senate" }));
    expect(r.races).toHaveLength(1);
    expect(r.races[0]).toMatchObject({ id: "senate-2026", status: "certified",
      winner: { id: "us:A000001", name: "Emery Eaton" } });
    expect(r.races[0].candidates).toEqual([
      { id: "us:A000001", name: "Emery Eaton", party: "Democratic", isIncumbent: true, standing: "won" },
      { id: "c-chal", name: "Chris Challenger", party: "Republican", isIncumbent: false, standing: "lost" },
    ]);
  });

  it("filters by office, district and year", async () => {
    expect(ids(await searchRaces(loader(), { office: "georgia house", district: 10 }))).toEqual(["house-10-2026"]);
    expect(ids(await searchRaces(loader(), { year: 2024 }))).toEqual([]);
  });

  it("for a county, keeps districts touching it and statewide races, and says what it cannot place", async () => {
    const r = await searchRaces(loader(), { county_fips: "13217" });
    expect(ids(r)).toEqual(["house-10-2026", "senate-2026"]);
    expect(body(r).summary).toContain("1 judicial circuit or local race");
    expect(body(r).summary).toContain("A county is not a district");
    expect((await searchRaces(loader(), { county_fips: "13999" })).isError).toBe(true);
  });

  it("caps results", async () => {
    const r = body(await searchRaces(loader(), { limit: 1 }));
    expect([r.races.length, r.total]).toEqual([1, 4]);
  });

  it("says unavailable when an index is missing", async () => {
    await expect(searchRaces(loader(["candidates-index.json"]), {})).rejects.toThrow(UnavailableError);
  });
});

describe("get_candidate", () => {
  it("returns the candidate, their standing and their races", async () => {
    const r = body(await getCandidate(loader(), { id: "c-chal" }));
    expect(r.candidates).toHaveLength(1);
    expect(r.candidates[0]).toMatchObject({ id: "c-chal", name: "Chris Challenger", standing: "lost",
      county: "Newton", website: "https://example.org" });
    expect(r.candidates[0].races[0]).toMatchObject({ id: "senate-2026", status: "certified" });
    expect(r.source_url).toBe("https://www.votega.org/candidates/chris/");
  });

  it("finds every candidacy of a person by vgId", async () => {
    const r = body(await getCandidate(loader(), { id: "vg-ga-p-000001" }));
    expect(r.candidates.map((c: { id: string }) => c.id)).toEqual(["c-able"]);
    expect(r.candidates[0].legislator_id).toBe("ga:1");
  });

  it("falls back to the race page when a candidate has no page", async () => {
    const r = body(await getCandidate(loader(), { id: "c-judge" }));
    expect(r.candidates[0].votegaUrl).toBeNull();
    expect(r.source_url).toBe("https://www.votega.org/races/superior-2026/");
  });

  it("says when there is no such candidate", async () => {
    expect((await getCandidate(loader(), { id: "nobody" })).isError).toBe(true);
  });
});
