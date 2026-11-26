import { describe, expect, it } from "vitest";
import { fixtureLoader, UnavailableError } from "../src/data";
import { searchLocalGovernment } from "../src/tools/local";
import type { ToolResult } from "../src/util";
import { NOW } from "./fixtures";
import { PHASE3_FILES } from "./phase3-fixtures";

const loader = (drop: string[] = []) =>
  fixtureLoader(Object.fromEntries(Object.entries(PHASE3_FILES).filter(([k]) => !drop.includes(k))));
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);
const dates = (r: ToolResult) => body(r).mentions.map((m: { date: string }) => m.date);

describe("search_local_government", () => {
  it("lists mentions newest first, with sources, marking meetings still to come", async () => {
    const r = body(await searchLocalGovernment(loader(), {}, NOW));
    expect(r.mentions.map((m: { date: string; upcoming: boolean }) => [m.date, m.upcoming])).toEqual([
      ["2026-12-03", true], ["2026-03-01", false], ["2026-01-05", false],
    ]);
    expect(r.mentions[1]).toMatchObject({ place: "City of Covington", county_fips: "13217", topic: "Budget",
      sourceUrl: "https://example.gov/covington" });
    expect(r.summary).toContain("not an action taken");
  });

  it("filters by place name or county, topic and date", async () => {
    expect(dates(await searchLocalGovernment(loader(), { place: "Newton County" }, NOW))).toEqual(["2026-12-03", "2026-01-05"]);
    expect(dates(await searchLocalGovernment(loader(), { county_fips: "13217" }, NOW))).toHaveLength(3);
    expect(dates(await searchLocalGovernment(loader(), { topic: "alpr" }, NOW))).toHaveLength(2);
    expect(dates(await searchLocalGovernment(loader(), { since: "2026-03-01" }, NOW))).toHaveLength(2);
  });

  it("names the topics when asked for one that does not exist", async () => {
    const r = await searchLocalGovernment(loader(), { topic: "zoning" }, NOW);
    expect(r.isError).toBe(true);
    expect(r.content[0].text).toContain("alpr, budget");
  });

  it("never reads silence as nothing happening", async () => {
    const r = body(await searchLocalGovernment(loader(), { place: "Gotham" }, NOW));
    expect(r.total).toBe(0);
    expect(r.summary).toContain("does not mean nothing happened");
  });

  it("says unavailable when the index is missing", async () => {
    await expect(searchLocalGovernment(loader(["local-mentions-index.json"]), {}, NOW)).rejects.toThrow(UnavailableError);
  });
});
