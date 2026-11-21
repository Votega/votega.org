import { describe, expect, it } from "vitest";
import { clearMemo, fixtureLoader, httpLoader } from "../src/data";
import { getDataFreshness, olderThanUsual } from "../src/tools/freshness";
import { findMember, getLegislator, searchLegislators } from "../src/tools/legislators";
import { findLocalOfficials, holdsSeat, resolvePlaces } from "../src/tools/officials";
import { findMyRepresentatives } from "../src/tools/representatives";
import { clean, type ToolResult } from "../src/util";
import { FILES, MEMBERS, META, NOW, OFFICIALS } from "./fixtures";

const loader = () => fixtureLoader(FILES);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);

describe("find_my_representatives", () => {
  it("returns every district a split ZIP touches, largest share first, and says a ZIP is not a district", async () => {
    const r = body(await findMyRepresentatives(loader(), { zip: "30001" }));
    expect(r.districts.state_house.map((d: { district: number }) => d.district)).toEqual([10, 12, 11]);
    expect(r.districts.state_house[2].share).toBe(0.02); // the small sliver is kept
    expect(r.summary).toContain("split across 3 Georgia House districts");
    expect(r.summary.match(/split across/g)).toHaveLength(1);
    expect(r.summary).toContain("only a street address decides");
    expect(r.license).toBe("CC BY-SA 4.0");
  });

  it("marks a seat whose member left as vacant, never filled with the departed member", async () => {
    const r = body(await findMyRepresentatives(loader(), { zip: "30001" }));
    const hd12 = r.districts.state_house.find((d: { district: number }) => d.district === 12);
    expect(hd12.vacant).toBe(true);
    expect(hd12.members).toEqual([]);
    expect(r.summary).toContain("No sitting member: Georgia House district 12");
  });

  it("keeps a suspended member in the seat, with the status", async () => {
    const r = body(await findMyRepresentatives(loader(), { zip: "30001" }));
    expect(r.districts.state_senate[0].members[0]).toMatchObject({ id: "ga:4", status: "Suspended" });
  });

  it("always includes both US senators", async () => {
    const r = body(await findMyRepresentatives(loader(), { county_fips: "13217" }));
    expect(r.us_senators.map((s: { id: string }) => s.id)).toEqual(["us:A000001", "us:B000002"]);
    expect(r.summary).toContain("A county is not a district");
  });

  it("says a PO-box ZIP has no districts, and an unknown ZIP is not found", async () => {
    expect(body(await findMyRepresentatives(loader(), { zip: "30002" })).summary).toContain("PO-box-only");
    expect(body(await findMyRepresentatives(loader(), { zip: "30099" })).found).toBe(false);
    expect(body(await findMyRepresentatives(loader(), { zip: "39999" })).found).toBe(false); // no shard
  });

  it("needs exactly one of zip or county_fips", async () => {
    expect((await findMyRepresentatives(loader(), {})).isError).toBe(true);
    expect((await findMyRepresentatives(loader(), { zip: "30001", county_fips: "13217" })).isError).toBe(true);
  });
});

describe("find_local_officials", () => {
  it("lists the sitting board, keeps staged members apart, and the sheriff separately", async () => {
    const r = body(await findLocalOfficials(loader(), { place: "Newton County" }, NOW));
    expect(r.places).toHaveLength(1);
    const p = r.places[0];
    expect(p.members.map((m: { name: string }) => m.name)).toEqual(["Sitting Outgoing", "Always Here"]);
    expect(p.incoming.map((m: { name: string }) => m.name)).toEqual(["Staged Incoming"]);
    expect(p.constitutional_officers[0].name).toBe("Sheriff Sam");
    expect(r.last_reviewed).toBe("2026-09-05");
  });

  it("turns over on January 1 without a new index", async () => {
    const jan2 = Date.parse("2027-01-02T12:00:00Z");
    const p = body(await findLocalOfficials(loader(), { place: "newton" }, jan2)).places[0];
    expect(p.members.map((m: { name: string }) => m.name)).toEqual(["Staged Incoming", "Always Here"]);
    expect(p.incoming).toEqual([]);
  });

  it("names nobody for a place it does not cover", async () => {
    const r = body(await findLocalOfficials(loader(), { place: "Gotham" }, NOW));
    expect(r.covered).toBe(false);
    expect(r.places).toEqual([]);
    expect(r.summary).toContain("does not cover");
  });

  it("returns every covered place in a county", async () => {
    const r = body(await findLocalOfficials(loader(), { county_fips: "13217" }, NOW));
    expect(r.places.map((p: { place: string }) => p.place)).toEqual(["covington", "newton"]);
    const none = body(await findLocalOfficials(loader(), { county_fips: "13013" }, NOW));
    expect(none.covered).toBe(false);
    expect(none.summary).toContain("Barrow County");
  });

  it("resolves city and county names", () => {
    expect(resolvePlaces(OFFICIALS, "Covington").map((p) => p.slug)).toEqual(["covington"]);
    expect(resolvePlaces(OFFICIALS, "City of Covington").map((p) => p.slug)).toEqual(["covington"]);
    expect(resolvePlaces(OFFICIALS, "newton").map((p) => p.slug)).toEqual(["newton"]);
    expect(resolvePlaces(OFFICIALS, "County")).toEqual([]);
  });

  it("holdsSeat: leaves_office is exclusive", () => {
    const o = OFFICIALS.places.newton.members[0];
    expect(holdsSeat(o, "2026-12-31")).toBe(true);
    expect(holdsSeat(o, "2027-01-01")).toBe(false);
  });
});

describe("search_legislators / get_legislator", () => {
  it("finds by name and hides members who left unless asked", async () => {
    expect(body(await searchLegislators(loader(), { query: "cole" })).total).toBe(0);
    const r = body(await searchLegislators(loader(), { query: "cole", include_former: true }));
    expect(r.results[0]).toMatchObject({ id: "ga:3", serving: false, status: "Resigned" });
  });

  it("filters by chamber and party", async () => {
    const r = body(await searchLegislators(loader(), { chamber: "us_senate" }));
    expect(r.results.map((x: { id: string }) => x.id)).toEqual(["us:A000001", "us:B000002"]);
    const d = body(await searchLegislators(loader(), { chamber: "house", party: "dem" }));
    expect(d.results.map((x: { id: string }) => x.id)).toEqual(["ga:1"]);
  });

  it("a county filter returns members whose districts touch it, plus the senators", async () => {
    const r = body(await searchLegislators(loader(), { county_fips: "13217" }));
    expect(r.results.map((x: { id: string }) => x.id).sort()).toEqual(
      ["ga:1", "ga:2", "ga:4", "us:A000001", "us:B000002", "us:C000003"],
    );
    expect(r.summary).toContain("A county is not a district");
  });

  it("caps results at 25", async () => {
    const r = body(await searchLegislators(loader(), { limit: 100 }));
    expect(r.results.length).toBeLessThanOrEqual(25);
  });

  it("resolves ga:, us:, vgId and a bare legisGaGovId", () => {
    expect(findMember(MEMBERS.members, "ga:1")?.name).toBe("Avery Able");
    expect(findMember(MEMBERS.members, "US:C000003")?.name).toBe("Gray Gale");
    expect(findMember(MEMBERS.members, "vg-ga-p-000002")?.name).toBe("Blake Baker");
    expect(findMember(MEMBERS.members, "1")?.name).toBe("Avery Able");
    expect(findMember(MEMBERS.members, "ocd-person/x")).toBeUndefined();
  });

  it("gives the counties a district touches and absolute data-file URLs", async () => {
    const r = body(await getLegislator(loader(), { id: "ga:1" }));
    expect(r.legislator.counties).toEqual([{ county_fips: "13217", county: "Newton", share_of_county: 0.6 }]);
    expect(r.legislator.legisGaGovId).toBe(1);
    expect(r.legislator.data_files.votes).toBe("https://www.votega.org/assets/data/ga-votes/ocd-person-a.json");
    expect(r.source_url).toBe(MEMBERS.members[0].votegaUrl);
  });

  it("gives no contact details for a member who left", async () => {
    const r = body(await getLegislator(loader(), { id: "ga:3" }));
    expect(r.legislator.phone).toBeNull();
    expect(r.legislator.email).toBeNull();
    expect(r.summary).toContain("no longer serving");
  });

  it("reports an unknown id as an error", async () => {
    expect((await getLegislator(loader(), { id: "ga:999" })).isError).toBe(true);
  });
});

describe("get_data_freshness", () => {
  it("applies the site's rule: the newer of the stamp and the check day", () => {
    expect(olderThanUsual(META.datasets["ga-members"], NOW)).toBe(false);
    expect(olderThanUsual(META.datasets["ga-bills"], NOW)).toBe(true); // checked 20 days ago, window 10
    expect(olderThanUsual(META.datasets["supreme-court"], NOW)).toBeNull();
  });

  it("lists every dataset", async () => {
    const r = body(await getDataFreshness(loader(), NOW));
    expect(Object.keys(r.datasets)).toEqual(["ga-members", "ga-bills", "supreme-court"]);
    expect(r.summary).toContain("older than usual: ga-bills");
  });
});

describe("hygiene and loading", () => {
  it("strips control characters and bounds string length", () => {
    expect(clean("a\u0000b c\nd")).toBe("abc\nd");
    expect(clean("x".repeat(600)).length).toBe(500);
    expect(clean({ a: ["\u0007"] })).toEqual({ a: [""] });
  });

  it("only fetches index paths, from www.votega.org", async () => {
    clearMemo();
    const seen: string[] = [];
    const fetcher = (async (url: string) => {
      seen.push(url);
      return new Response(JSON.stringify(META));
    }) as unknown as typeof fetch;
    const l = httpLoader(NOW, fetcher);
    await expect(l.load("../secret.json")).rejects.toThrow("not an index path");
    await expect(l.load("zip/30.json")).rejects.toThrow("not an index path");
    await l.load("meta.json");
    await l.load("meta.json"); // memoised
    expect(seen).toEqual(["https://www.votega.org/assets/data/mcp/meta.json"]);
  });

  it("serves the last good copy, flagged stale, when the upstream fails", async () => {
    clearMemo();
    let up = true;
    const fetcher = (async () => {
      if (!up) throw new Error("down");
      return new Response(JSON.stringify(META));
    }) as unknown as typeof fetch;
    await httpLoader(NOW, fetcher).load("meta.json");
    up = false;
    const later = httpLoader(NOW + 3_600_000, fetcher);
    expect(await later.load("meta.json")).toEqual(META);
    expect(later.stale).toBe(true);
    clearMemo();
    await expect(httpLoader(NOW, fetcher).load("meta.json")).rejects.toThrow("unavailable");
  });

  it("treats a 404 as a missing file", async () => {
    clearMemo();
    const fetcher = (async () => new Response("nope", { status: 404 })) as unknown as typeof fetch;
    expect(await httpLoader(NOW, fetcher).load("zip/399.json")).toBeNull();
  });
});
