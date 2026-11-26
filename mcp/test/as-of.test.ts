/**
 * `as_of` is the build date of the data behind an answer, not of meta.json. meta.json is
 * cached for 5 minutes and the data files for up to 24 hours, so after a deploy meta.json
 * is routinely newer than what a tool actually read.
 */
import { describe, expect, it } from "vitest";
import { clearMemo, fixtureLoader, httpLoader, type Loader } from "../src/data";
import { getBill, searchBills } from "../src/tools/bills";
import { getCandidate, searchRaces } from "../src/tools/elections";
import { getDataFreshness } from "../src/tools/freshness";
import { getLegislator, searchLegislators } from "../src/tools/legislators";
import { searchLocalGovernment } from "../src/tools/local";
import { findLocalOfficials } from "../src/tools/officials";
import { findMyRepresentatives } from "../src/tools/representatives";
import { getLegislatorVotes } from "../src/tools/votes";
import type { ToolResult } from "../src/util";
import { PHASE3_FILES, voteFixtures } from "./phase3-fixtures";

const OLD = "2026-11-21T18:00:00+00:00"; // every data fixture's build date
const NEW = "2026-11-26T19:35:39+00:00";
const NOW = Date.parse("2026-11-26T20:00:00Z");

const asOf = (r: ToolResult) => {
  expect(r.isError).toBeFalsy();
  return JSON.parse(r.content[0].text).as_of;
};

describe("as_of", () => {
  const files = async (): Promise<Record<string, unknown>> => {
    const all: Record<string, unknown> = { ...PHASE3_FILES, ...(await voteFixtures()) };
    const meta = all["meta.json"] as { metadata: object };
    all["meta.json"] = { ...meta, metadata: { ...meta.metadata, generatedAt: NEW } };
    return all;
  };

  const calls: [string, (l: Loader) => Promise<ToolResult>][] = [
    ["find_my_representatives", (l) => findMyRepresentatives(l, { zip: "30001" })],
    ["find_local_officials", (l) => findLocalOfficials(l, { county_fips: "13217" }, NOW)],
    ["search_legislators", (l) => searchLegislators(l, { query: "Hayes" })],
    ["get_legislator", (l) => getLegislator(l, { id: "ga:1" })],
    ["get_legislator_votes", (l) => getLegislatorVotes(l, { id: "ga:1" })],
    ["search_bills", (l) => searchBills(l, { query: "firearm" })],
    ["get_bill", (l) => getBill(l, { identifier: "HB 1" })],
    ["search_races", (l) => searchRaces(l, { county_fips: "13217" })],
    ["get_candidate", (l) => getCandidate(l, { id: "c-chal" })],
    ["search_local_government", (l) => searchLocalGovernment(l, { county_fips: "13217" }, NOW)],
  ];

  it.each(calls)("%s dates its answer from the data it read, not from a newer meta.json", async (_name, call) => {
    expect(asOf(await call(fixtureLoader(await files())))).toBe(OLD);
  });

  it("is the oldest of the files read when they come from different builds", async () => {
    const all = await files();
    const shard = all["bills/2025_26-HB.json"] as { metadata: object };
    const older = "2026-11-19T00:00:00+00:00";
    all["bills/2025_26-HB.json"] = { ...shard, metadata: { ...shard.metadata, generatedAt: older } };
    expect(asOf(await getBill(fixtureLoader(all), { identifier: "HB 1" }))).toBe(older);
  });

  it("uses meta.json for the answer that is about meta.json", async () => {
    expect(asOf(await getDataFreshness(fixtureLoader(await files()), NOW))).toBe(NEW);
  });

  it("counts a file served from the cache, with that cached copy's date", async () => {
    clearMemo();
    let built = OLD;
    const fetcher = (async () => new Response(JSON.stringify({ metadata: { generatedAt: built } }))) as typeof fetch;
    await httpLoader(NOW, fetcher).load("members-index.json");
    built = NEW; // a deploy
    const later = httpLoader(NOW + 600_000, fetcher);
    await later.load("meta.json");
    expect(later.asOf).toBeNull(); // meta.json alone dates nothing
    await later.load("members-index.json"); // still memoised
    expect(later.asOf).toBe(OLD);
  });
});
