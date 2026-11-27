import { describe, expect, it } from "vitest";
import { fixtureLoader, UnavailableError } from "../src/data";
import { getBill, searchBills } from "../src/tools/bills";
import type { ToolResult } from "../src/util";
import { PHASE3_FILES } from "./phase3-fixtures";

const loader = (drop: string[] = []) =>
  fixtureLoader(Object.fromEntries(Object.entries(PHASE3_FILES).filter(([k]) => !drop.includes(k))));
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);
const ids = (r: ToolResult) => body(r).results.map((b: { session: string; identifier: string }) => `${b.session} ${b.identifier}`);

describe("search_bills", () => {
  it("searches title words across the current sessions only, matching word beginnings", async () => {
    expect(ids(await searchBills(loader(), { query: "firearm" }))).toEqual(["2025_26 HB 1", "2025_26 SR 1"]);
    expect(ids(await searchBills(loader(), { query: "tax" }))).toEqual(["2026_ss HB 1EX", "2025_26 HB 2"]);
  });

  it("needs every word, and ignores the index's function words", async () => {
    expect(ids(await searchBills(loader(), { query: "the income tax" }))).toEqual(["2025_26 HB 2"]);
    expect(body(await searchBills(loader(), { query: "income firearm" })).total).toBe(0);
  });

  it("reads an earlier session only when asked", async () => {
    expect(ids(await searchBills(loader(), { query: "tax", session: "2023_24" }))).toEqual(["2023_24 HB 1"]);
    expect(ids(await searchBills(loader(), { query: "tax", session: "2025-2026" }))).toEqual(["2025_26 HB 2"]);
    expect((await searchBills(loader(), { session: "1999_00" })).isError).toBe(true);
  });

  it("finds a bill by its number", async () => {
    expect(ids(await searchBills(loader(), { query: "hb1" }))).toEqual(["2025_26 HB 1", "2026_ss HB 1EX"]);
  });

  it("filters by sponsor, status and subject", async () => {
    expect(ids(await searchBills(loader(), { sponsor_id: "ga:3" }))).toEqual(["2025_26 HB 2", "2025_26 HB 1"]);
    expect(ids(await searchBills(loader(), { sponsor_id: "vg-ga-p-000003" }))).toEqual(["2025_26 HB 2", "2025_26 HB 1"]);
    expect(ids(await searchBills(loader(), { status: "signed by governor" }))).toEqual(["2025_26 HB 2"]);
    expect(ids(await searchBills(loader(), { subject: "taxation" }))).toEqual(["2025_26 HB 2"]);
    expect((await searchBills(loader(), { sponsor_id: "us:A000001" })).isError).toBe(true);
  });

  it("says which role matched a sponsor search, and only then", async () => {
    const r = body(await searchBills(loader(), { sponsor_id: "ga:3" }));
    expect(r.results.map((b: { sponsor_role: string }) => b.sponsor_role)).toEqual(["Senate sponsor", "co-sponsor"]);
    expect(body(await searchBills(loader(), { sponsor_id: "ga:1", query: "hb 2" })).results[0].sponsor_role)
      .toBe("primary sponsor");
    expect(body(await searchBills(loader(), { query: "income" })).results[0]).not.toHaveProperty("sponsor_role");
  });

  it("caps results and says how many matched", async () => {
    const r = body(await searchBills(loader(), { limit: 1 }));
    expect([r.results.length, r.total]).toEqual([1, 4]);
    expect(r.summary).toContain("showing 1");
  });

  it("says bill data is unavailable, never that nothing matched, when a file is missing", async () => {
    // The server turns UnavailableError into the "unavailable" tool error (worker.test.ts).
    await expect(searchBills(loader(["bills/sessions.json"]), { query: "tax" })).rejects.toThrow(UnavailableError);
    await expect(searchBills(loader(["bills/2025_26-SR-tokens.json"]), { query: "tax" })).rejects.toThrow(UnavailableError);
    await expect(searchBills(loader(["bills/2025_26-SR.json"]), {})).rejects.toThrow(UnavailableError);
  });
});

describe("get_bill", () => {
  it("returns status, sponsors, votes, governor action and the Commons pointer", async () => {
    const r = body(await getBill(loader(), { identifier: "hb 2" }));
    expect(r.bill).toMatchObject({ session: "2025_26", identifier: "HB 2", legislationId: 12,
      votegaUrl: "https://www.votega.org/ga-bills.html?bill=HB%202&legislationId=12" });
    expect(r.bill.passage_votes[0].yea).toBe(172);
    expect(r.bill.governor_action.actNumber).toBe(374);
    expect(r.bill.stage.label).toBe("Signed · Act 374");
    expect(r.bill.stage.steps[0]).toEqual({ stage: "House committee", state: "done", headline: "Ways & Means" });
    expect(r.bill.stage.steps[5].stage).toBe("Governor");
    expect(r.bill.committees[0].name).toBe("Ways & Means");
    expect(r.bill.governor_statements[0]).toMatchObject({ kind: "signing", text: "I therefore sign House Bill 2 into law." });
    expect(r.summary).toContain("Where it is: Signed · Act 374.");
    expect(r.georgia_commons).toEqual({
      label: "Plain-language summary (AI-written), Georgia Commons",
      url: "https://georgiacommons.org/bills/2025-2026/hb2",
      id: "bill:2025-2026/hb2",
    });
    expect(r.source_url).toBe(r.bill.votegaUrl);
  });

  it("links sponsors to their legislator records, former ones included by name", async () => {
    const r = body(await getBill(loader(), { identifier: "HB 1" }));
    expect(r.bill.sponsors).toEqual([
      expect.objectContaining({ id: "ga:1", name: "Avery Able", primary: true, votegaUrl: "https://www.votega.org/x/ga:1/" }),
      expect.objectContaining({ id: "ga:3", name: "Casey Cole", primary: false }),
    ]);
  });

  it("returns the second-chamber sponsor apart from sponsors, and omits it when the data has none", async () => {
    const r = body(await getBill(loader(), { identifier: "HB 2" }));
    expect(r.bill.second_chamber_sponsor).toEqual({
      id: "ga:3", name: "Casey Cole", chamber: "upper", role: "Senate sponsor",
      votegaUrl: r.bill.second_chamber_sponsor.votegaUrl,
    });
    expect(r.bill.sponsors.map((s: { id: string }) => s.id)).toEqual(["ga:1"]);
    expect(body(await getBill(loader(), { identifier: "HB 1" })).bill).not.toHaveProperty("second_chamber_sponsor");
  });

  it("takes a bare number as the regular session, and a session picks the special one", async () => {
    expect(body(await getBill(loader(), { identifier: "HB 1" })).bill.session).toBe("2025_26");
    expect(body(await getBill(loader(), { identifier: "HB 1", session: "2026_ss" })).bill.identifier).toBe("HB 1EX");
    expect(body(await getBill(loader(), { identifier: "HB 1", session: "2023_24" })).bill.legislationId).toBe(9);
  });

  it("looks a bill up by legislationId in any session", async () => {
    expect(body(await getBill(loader(), { legislation_id: 9 })).bill.session).toBe("2023_24");
  });

  it("needs one way of naming the bill, and says when there is no such bill", async () => {
    expect((await getBill(loader(), {})).isError).toBe(true);
    expect((await getBill(loader(), { identifier: "HB 1", legislation_id: 11 })).isError).toBe(true);
    expect((await getBill(loader(), { identifier: "HB 999" })).isError).toBe(true);
  });

  it("says unavailable when the detail file is missing", async () => {
    await expect(getBill(loader(["bills/2025_26-HB-detail.json"]), { identifier: "HB 2" }))
      .rejects.toThrow(UnavailableError);
  });
});
