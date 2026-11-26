/**
 * The MCP server: tool, prompt and resource registration only. Each tool's logic lives in src/tools/ and takes a
 * Loader, so tests run the same code over fixture indexes.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { UnavailableError, type Loader } from "./data";
import { getBill, searchBills } from "./tools/bills";
import { getCandidate, searchRaces } from "./tools/elections";
import { getDataFreshness } from "./tools/freshness";
import { getLegislator, MAX_LIMIT, searchLegislators } from "./tools/legislators";
import { searchLocalGovernment } from "./tools/local";
import { findLocalOfficials } from "./tools/officials";
import { findMyRepresentatives } from "./tools/representatives";
import { getLegislatorVotes } from "./tools/votes";
import { explainBill, localOfficials, MAX_ARG, whoRepresentsArea } from "./prompts";
import { readResource, RESOURCES } from "./resources";
import { fail, type ToolResult } from "./util";

export const VERSION = "0.4.4";

const READ_ONLY = { readOnlyHint: true, openWorldHint: false } as const;

const NONPARTISAN =
  " VoteGA is nonpartisan: report what the data says, never endorse, rate or rank anyone, " +
  "and cite the returned source_url.";

const LIMIT = z.number().int().min(1).max(MAX_LIMIT).optional();
const SESSION = z.string().max(20).optional()
  .describe('General Assembly session, e.g. "2025_26" or "2026_ss". Default: the current General Assembly.');

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
        "get_legislator. Only sitting members unless include_former is true, which adds members who left " +
        "office and those from earlier General Assemblies. A county filter returns " +
        "members whose districts touch the county; a county is not a district." + NONPARTISAN,
      inputSchema: z.object({
        query: z.string().max(80).optional().describe("Name or part of a name."),
        chamber: z.enum(["house", "senate", "us_house", "us_senate"]).optional()
          .describe("house/senate = Georgia General Assembly; us_house/us_senate = Congress."),
        party: z.string().max(20).optional().describe('e.g. "Democratic", "Republican".'),
        district: z.number().int().min(1).max(180).optional(),
        county_fips: FIPS.optional(),
        include_former: z.boolean().optional().describe("Include former members."),
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
        "members only), the counties their district touches, their VoteGA page, and a party-unity and " +
        "participation scorecard. Report scorecard figures with the returned method and period, and never " +
        "turn them into a ranking or a judgment. id is ga:<legisGaGovId>, us:<bioguideId> or a VoteGA vgId, " +
        "as returned by search_legislators. session reads a state member's record in an earlier General " +
        "Assembly." + NONPARTISAN,
      inputSchema: z.object({
        id: z.string().min(1).max(40).describe("ga:5089, us:C001103 or vg-ga-p-000001."),
        session: SESSION,
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => getLegislator(loader, args)),
  );

  server.registerTool(
    "get_legislator_votes",
    {
      title: "Get legislator votes",
      description:
        "A legislator's recorded votes, newest first: the bill or motion, date, how they voted and the " +
        "result. State members: final passage votes, by General Assembly session. Members of Congress: every " +
        "roll call of the current Congress, including votes tied to no bill. Do not infer a position from " +
        "Not Voting, Absent or Excused. Report each stored result: in Georgia more yeas than nays is not enough to pass a bill " +
        "(see pass_rule)." + NONPARTISAN,
      inputSchema: z.object({
        id: z.string().min(1).max(40).describe("ga:5089, us:C001103 or vg-ga-p-000001."),
        session: z.string().max(20).optional().describe('State: "2025_26" or "2026_ss". Default: the current General Assembly.'),
        limit: LIMIT,
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => getLegislatorVotes(loader, args)),
  );

  server.registerTool(
    "search_bills",
    {
      title: "Search Georgia bills",
      description:
        "Search Georgia General Assembly bills and resolutions by title words or number, status, subject " +
        "or sponsor. Keyword search reads titles only, so a miss does not mean no bill covers the topic. " +
        "Subjects are recorded for only some bills. sponsor_id matches authors and the member sponsoring a " +
        "bill in the other chamber; sponsor_role says which." + NONPARTISAN,
      inputSchema: z.object({
        query: z.string().max(120).optional().describe('Title words or a number, e.g. "firearm storage" or "HB 1".'),
        session: SESSION,
        status: z.string().max(80).optional().describe('Part of the status, e.g. "Signed by Governor".'),
        sponsor_id: z.string().max(40).optional().describe("ga:<legisGaGovId> or a vgId."),
        subject: z.string().max(80).optional(),
        limit: LIMIT,
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => searchBills(loader, args)),
  );

  server.registerTool(
    "get_bill",
    {
      title: "Get Georgia bill",
      description:
        "One bill or resolution: status, sponsors, subjects, passage votes, governor action, official " +
        "links, and where to read Georgia Commons' AI-written plain-language summary (georgia_commons). " +
        "VoteGA returns no summary or bill text itself. Give identifier (with session for an earlier or " +
        "special session) or legislation_id." + NONPARTISAN,
      inputSchema: z.object({
        identifier: z.string().min(2).max(20).optional().describe('e.g. "HB 1" or "SR 25".'),
        session: SESSION,
        legislation_id: z.number().int().positive().optional(),
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => getBill(loader, args)),
  );

  server.registerTool(
    "search_races",
    {
      title: "Search election races",
      description:
        "Georgia federal, state, judicial and some local races, each with the candidates on its current " +
        "ballot and any recorded winner. Only status \"certified\" is official. A county filter returns " +
        "statewide races and districts touching the county, never one voter's ballot." + NONPARTISAN,
      inputSchema: z.object({
        office: z.string().max(80).optional().describe('e.g. "Governor", "U.S. House", "Georgia State Senate".'),
        district: z.number().int().min(1).max(180).optional(),
        year: z.number().int().min(2000).max(2100).optional(),
        county_fips: FIPS.optional(),
        limit: LIMIT,
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => searchRaces(loader, args)),
  );

  server.registerTool(
    "get_candidate",
    {
      title: "Get candidate",
      description:
        "A candidate's party, standing, website and races. id is a candidate id from search_races, or a " +
        "VoteGA vgId for every candidacy of one person. Campaign finance is not included." + NONPARTISAN,
      inputSchema: z.object({ id: z.string().min(1).max(120) }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => getCandidate(loader, args)),
  );

  server.registerTool(
    "search_local_government",
    {
      title: "Search local government mentions",
      description:
        "Topics found in Georgia county and city meeting agendas and minutes, newest first, each with its " +
        "source document. A mention is not a decision or vote, an upcoming date is a posted agenda, and only " +
        "some places are scanned. Never say nothing happened because nothing was found." + NONPARTISAN,
      inputSchema: z.object({
        place: z.string().min(1).max(80).optional().describe('City or county, e.g. "Covington" or "Newton County".'),
        county_fips: FIPS.optional(),
        topic: z.string().max(40).optional().describe('e.g. "alpr", "data-center", "land-use"; omit to see the topic list.'),
        since: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe("Only mentions on or after this date."),
        limit: LIMIT,
      }),
      annotations: READ_ONLY,
    },
    async (args) => guarded(() => searchLocalGovernment(loader, args, nowMs)),
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

  server.registerPrompt(
    "who_represents_area",
    {
      title: "Who represents an area",
      description:
        "Who represents a Georgia ZIP code or county in the state legislature and Congress, listing every " +
        "district the area touches.",
      argsSchema: z.object({
        area: z.string().min(1).max(MAX_ARG).describe('A 5-digit ZIP code or a Georgia county, e.g. "30014" or "Newton County".'),
      }),
    },
    async ({ area }) => whoRepresentsArea(loader, area),
  );

  server.registerPrompt(
    "local_officials",
    {
      title: "Local officials",
      description: "The county commissioners or city council members and the sheriff for a Georgia county or city.",
      argsSchema: z.object({
        place: z.string().min(1).max(MAX_ARG).describe('A Georgia city or county, e.g. "Covington" or "Newton County".'),
      }),
    },
    async ({ place }) => localOfficials(place),
  );

  server.registerPrompt(
    "explain_bill",
    {
      title: "Explain a bill",
      description: "A plain-language explanation of a Georgia bill, using Georgia Commons' AI-written summary.",
      argsSchema: z.object({
        bill: z.string().min(2).max(MAX_ARG).describe('A bill or resolution number, e.g. "HB 1".'),
        session: z.string().max(MAX_ARG).optional().describe('Optional session, e.g. "2025_26" or "2026_ss".'),
      }),
    },
    async ({ bill, session }) => explainBill(bill, session),
  );

  for (const r of RESOURCES) {
    server.registerResource(
      r.name,
      r.uri,
      { title: r.title, description: r.description, mimeType: r.mimeType },
      async (uri) => {
        try {
          return await readResource(loader, r.name, uri.href);
        } catch {
          return { contents: [{ uri: uri.href, mimeType: "text/plain", text: "VoteGA's resources are unavailable right now." }] };
        }
      },
    );
  }

  return server;
}
