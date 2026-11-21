/**
 * The MCP server: tool registration only. Each tool's logic lives in src/tools/ and takes a
 * Loader, so tests run the same code over fixture indexes.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { UnavailableError, type Loader } from "./data";
import { getDataFreshness } from "./tools/freshness";
import { getLegislator, MAX_LIMIT, searchLegislators } from "./tools/legislators";
import { findLocalOfficials } from "./tools/officials";
import { findMyRepresentatives } from "./tools/representatives";
import { fail, type ToolResult } from "./util";

export const VERSION = "0.1.0";

const READ_ONLY = { readOnlyHint: true, openWorldHint: false } as const;

const NONPARTISAN =
  " VoteGA is nonpartisan: report what the data says, never endorse, rate or rank anyone, " +
  "and cite the returned source_url.";

const FIPS = z
  .string()
  .regex(/^13\d{3}$/)
  .describe("5-digit Georgia county FIPS code, e.g. 13217 (Newton County).");

async function guarded(run: () => Promise<ToolResult>): Promise<ToolResult> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof UnavailableError) return fail("VoteGA's data is unavailable right now. Try again later.");
    return fail("Something went wrong reading VoteGA's data.");
  }
}

export function createServer(loader: Loader, nowMs: number) {
  const server = new McpServer({ name: "votega", version: VERSION });

  server.registerTool(
    "find_my_representatives",
    {
      title: "Find my representatives",
      description:
        "Who represents a Georgia ZIP code or county in the Georgia Senate, Georgia House and U.S. House, " +
        "plus both U.S. senators. A ZIP or county can span several districts: every district with any " +
        "residents is returned with its estimated share, largest first, and only a street address decides " +
        "which one is the voter's. Never tell the user one district is theirs from a ZIP alone. Give " +
        "exactly one of zip or county_fips." + NONPARTISAN,
      inputSchema: z.object({
        zip: z.string().regex(/^\d{5}$/).optional().describe("5-digit ZIP code."),
        county_fips: FIPS.optional(),
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => findMyRepresentatives(loader, args)),
  );

  server.registerTool(
    "find_local_officials",
    {
      title: "Find local officials",
      description:
        "The county commission or city council members for a Georgia county or city, and the county " +
        "sheriff, each with its source. Rosters are reviewed by a person and VoteGA covers only some " +
        "places: when a place is not covered the result says so and names nobody; do not guess names. " +
        "Give exactly one of county_fips or place (a city or county name, or a VoteGA place slug)." +
        NONPARTISAN,
      inputSchema: z.object({
        county_fips: FIPS.optional(),
        place: z.string().min(1).max(80).optional().describe('City or county name, e.g. "Covington" or "Newton County".'),
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => findLocalOfficials(loader, args, nowMs)),
  );

  server.registerTool(
    "search_legislators",
    {
      title: "Search legislators",
      description:
        "Search Georgia's state legislators (General Assembly) and its members of Congress by name, " +
        "chamber, party, district or county. Returns ids (ga:<legisGaGovId> or us:<bioguideId>) for " +
        "get_legislator. Only sitting members unless include_former is true. A county filter returns " +
        "members whose districts touch the county; a county is not a district." + NONPARTISAN,
      inputSchema: z.object({
        query: z.string().max(80).optional().describe("Name or part of a name."),
        chamber: z.enum(["house", "senate", "us_house", "us_senate"]).optional()
          .describe("house/senate = Georgia General Assembly; us_house/us_senate = Congress."),
        party: z.string().max(20).optional().describe('e.g. "Democratic", "Republican".'),
        district: z.number().int().min(1).max(180).optional(),
        county_fips: FIPS.optional(),
        include_former: z.boolean().optional().describe("Include members who left office this term."),
        limit: z.number().int().min(1).max(MAX_LIMIT).optional(),
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => searchLegislators(loader, args)),
  );

  server.registerTool(
    "get_legislator",
    {
      title: "Get legislator",
      description:
        "One legislator's profile: office, party, leadership role, committees, contact details (sitting " +
        "members only), the counties their district touches, and their VoteGA page. id is ga:<legisGaGovId>, " +
        "us:<bioguideId> or a VoteGA vgId, as returned by search_legislators." + NONPARTISAN,
      inputSchema: z.object({
        id: z.string().min(1).max(40).describe("ga:5089, us:C001103 or vg-ga-p-000001."),
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => getLegislator(loader, args)),
  );

  server.registerTool(
    "get_data_freshness",
    {
      title: "Data freshness",
      description:
        "When each VoteGA dataset was last updated and last checked against its source, its update " +
        "cadence, and whether it is older than usual. Use it before telling a user something is current.",
      inputSchema: z.object({}),
      annotations: READ_ONLY,
    },
    async () => guarded(() => getDataFreshness(loader, nowMs)),
  );

  return server;
}
