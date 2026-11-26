/** Georgia results can look wrong (97-72 "Fail"), so tools that return them carry the rule. */
import { describe, expect, it } from "vitest";
import { fixtureLoader } from "../src/data";
import { getBill } from "../src/tools/bills";
import { getLegislatorVotes } from "../src/tools/votes";
import type { ToolResult } from "../src/util";
import { PHASE3_FILES, voteFixtures } from "./phase3-fixtures";

const loader = async () => fixtureLoader({ ...PHASE3_FILES, ...(await voteFixtures()) });
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const body = (r: ToolResult): any => JSON.parse(r.content[0].text);

describe("Georgia pass thresholds", () => {
  it("come with a state member's votes, whole", async () => {
    const rule = body(await getLegislatorVotes(await loader(), { id: "ga:1" })).pass_rule as string;
    for (const part of ["91 of 180", "29 of 56", "two-thirds", "120", "38", "local property-tax exemption",
      "never recompute"]) expect(rule).toContain(part);
    expect(rule.endsWith(".")).toBe(true); // under the 500-character cap, not cut off
  });

  it("come with a bill's passage votes, and only when it has some", async () => {
    expect(body(await getBill(await loader(), { identifier: "HB 2" })).pass_rule).toContain("91 of 180");
    expect(body(await getBill(await loader(), { identifier: "HB 1" })).pass_rule).toBeUndefined();
  });

  it("are not attached to votes in Congress", async () => {
    expect(body(await getLegislatorVotes(await loader(), { id: "us:A000001" })).pass_rule).toBeUndefined();
  });
});
