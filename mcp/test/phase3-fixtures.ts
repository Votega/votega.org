/**
 * Small Phase 3 index documents in the shapes scripts/lib/mcp_bills.py, mcp_elections.py and
 * mcp_index.py write, plus the site's vote slices. Invented bills, races and places.
 */
import { sha256Hex } from "../src/data";
import { FILES, MEMBERS } from "./fixtures";

const GEN = "2026-11-21T18:00:00+00:00";
const COMMONS = "https://georgiacommons.org/bills";

const billRow = (legislationId: number, identifier: string, title: string, extra: object = {}) => ({
  legislationId, identifier, billType: "bill", title, status: "House Second Readers",
  statusDate: "2025-02-01T10:00:00", subjects: [], sponsors: [[1, true]], ...extra,
});

const detail = (legislationId: number, slug: string, number: string, extra: object = {}) => ({
  billUrl: `https://www.legis.ga.gov/legislation/${legislationId}`, textUrl: null,
  commonsUrl: `${COMMONS}/${slug}/${number}`, passageVotes: [], governorAction: null, ...extra,
});

function shard(session: string, type: string, rows: ReturnType<typeof billRow>[], details: object[], words: object) {
  const path = `bills/${session}-${type}.json`;
  return {
    [path]: { metadata: { generatedAt: GEN, count: rows.length }, sponsorNames: { "1": "Avery Able", "3": "Casey Cole" }, bills: rows },
    [`bills/${session}-${type}-detail.json`]: {
      metadata: { generatedAt: GEN, count: rows.length },
      bills: Object.fromEntries(rows.map((r, i) => [r.identifier, details[i]])),
    },
    [`bills/${session}-${type}-tokens.json`]: {
      metadata: { generatedAt: GEN, ignored: ["of", "the", "for"] },
      identifiers: rows.map((r) => r.identifier),
      tokens: words,
    },
  };
}

const catalogShard = (session: string, type: string, count: number) => ({
  type, count, path: `bills/${session}-${type}.json`,
  detailPath: `bills/${session}-${type}-detail.json`, tokensPath: `bills/${session}-${type}-tokens.json`,
});

export const BILL_FILES: Record<string, unknown> = {
  "bills/sessions.json": {
    metadata: {
      generatedAt: GEN, count: 3,
      votegaUrlTemplate: "https://www.votega.org/ga-bills.html?bill={identifier}&legislationId={legislationId}",
      commonsLabel: "Plain-language summary (AI-written), Georgia Commons",
    },
    sessions: [
      { session: "2023_24", live: false, active: false, billCount: 1, shards: [catalogShard("2023_24", "HB", 1)] },
      { session: "2025_26", live: true, active: false, billCount: 3,
        shards: [catalogShard("2025_26", "HB", 2), catalogShard("2025_26", "SR", 1)] },
      { session: "2026_ss", live: true, active: true, billCount: 1, shards: [catalogShard("2026_ss", "HB", 1)] },
    ],
  },
  ...shard("2025_26", "HB",
    [
      billRow(11, "HB 1", "Firearms; safe storage", { subjects: ["CRIMES AND OFFENSES"], sponsors: [[1, true], [3, false]] }),
      billRow(12, "HB 2", "Income tax credit", { status: "House Date Signed by Governor", statusDate: "2025-03-20T10:00:00",
        subjects: ["REVENUE AND TAXATION"], secondChamberSponsor: [3, "upper"] }),
    ],
    [
      detail(11, "2025-2026", "hb1"),
      detail(12, "2025-2026", "hb2", {
        passageVotes: [{ chamber: "lower", date: "2025-03-04", result: "pass", motionText: "PASSAGE", yea: 172, nay: 0, other: 8 }],
        governorAction: { status: "Signed", decisionDate: "2025-03-20", actNumber: 374 },
      }),
    ],
    { firearms: [0], safe: [0], storage: [0], income: [1], tax: [1], credit: [1] }),
  ...shard("2025_26", "SR", [billRow(13, "SR 1", "Commend a firearm instructor", { sponsors: [] })],
    [detail(13, "2025-2026", "sr1")], { commend: [0], firearm: [0], instructor: [0] }),
  ...shard("2026_ss", "HB", [billRow(21, "HB 1EX", "Ad valorem tax; exemption", { statusDate: "2026-06-20T10:00:00" })],
    [detail(21, "2026-special", "hb1")], { ad: [0], valorem: [0], tax: [0], exemption: [0] }),
  ...shard("2023_24", "HB", [billRow(9, "HB 1", "Old tax measure")], [detail(9, "2023-2024", "hb1")],
    { old: [0], tax: [0], measure: [0] }),
};

const race = (id: string, level: string, office: string, extra: object = {}) => ({
  id, level, office, title: null, district: null, circuit: null, seat: null, cycle: 2026,
  activePhase: "general", electionDate: "2026-11-03", phaseDates: { general: "2026-11-03" }, status: null,
  winner: null, ballotPhase: "general", candidates: [], votegaUrl: `https://www.votega.org/races/${id}/`, ...extra,
});

const candidate = (key: string, name: string, raceIds: string[], extra: object = {}) => ({
  key, id: key.includes(":") ? null : key, memberKey: null, vgId: null, name, party: null, isIncumbent: false,
  occupation: null, county: null, website: null, withdrawn: false, disqualified: false, standing: "live",
  raceIds, votegaUrl: null, ...extra,
});

export const ELECTION_FILES: Record<string, unknown> = {
  "races-index.json": {
    metadata: { generatedAt: GEN, count: 4, meaning: "Current ballot per race." },
    races: [
      race("house-10-2026", "state", "Georgia House of Representatives", { district: 10, candidates: ["c-able"] }),
      race("house-99-2026", "state", "Georgia House of Representatives", { district: 99 }),
      race("senate-2026", "federal", "U.S. Senate", { status: "certified", candidates: ["us:A000001", "c-chal"],
        winner: { key: "us:A000001", name: "Emery Eaton", party: "Democratic", phase: "general" } }),
      race("superior-2026", "state-judicial", "Superior Court", { circuit: "Alcovy", candidates: ["c-judge"] }),
    ],
  },
  "candidates-index.json": {
    metadata: { generatedAt: GEN, count: 4, meaning: "standing: live, off-ballot, lost or won." },
    candidates: [
      candidate("c-able", "Avery Able", ["house-10-2026"], { memberKey: "ga:1", vgId: "vg-ga-p-000001", isIncumbent: true }),
      candidate("c-chal", "Chris Challenger", ["senate-2026"], { party: "Republican", standing: "lost", county: "Newton",
        website: "https://example.org", votegaUrl: "https://www.votega.org/candidates/chris/" }),
      candidate("c-judge", "Jo Judge", ["superior-2026"]),
      candidate("us:A000001", "Emery Eaton", ["senate-2026"], { memberKey: "us:A000001", party: "Democratic",
        isIncumbent: true, standing: "won" }),
    ],
  },
};

const mention = (place: string, topic: string, date: string) => ({
  place, topic, date, body: "Board", docType: "agenda", confidence: "high",
  sourceUrl: `https://example.gov/${place}`, minutesUrl: null, terms: ["flock"], tags: [], vendors: [],
});

export const LOCAL_FILES: Record<string, unknown> = {
  "local-mentions-index.json": {
    metadata: {
      generatedAt: GEN, count: 3, meaning: "A mention is not an action taken.",
      topics: [{ slug: "alpr", label: "ALPR", count: 2 }, { slug: "budget", label: "Budget", count: 1 }],
      places: {
        newton: { name: "Newton County", type: "county", countyFips: "13217", votegaUrl: "https://www.votega.org/local/newton/" },
        covington: { name: "City of Covington", type: "city", countyFips: "13217", votegaUrl: null },
      },
    },
    mentions: [
      mention("newton", "alpr", "2026-12-03"),
      mention("covington", "budget", "2026-03-01"),
      mention("newton", "alpr", "2026-01-05"),
    ],
  },
};

export const PHASE3_FILES: Record<string, unknown> = { ...FILES, ...BILL_FILES, ...ELECTION_FILES, ...LOCAL_FILES };

const rollCall = (bill: string, date: string, session: string, result: string, legislationId: number) => ({
  bill, billUrl: `https://www.legis.ga.gov/legislation/${legislationId}`, title: `${bill} title`, session,
  motionText: "PASSAGE", chamber: "House of Representatives", date, yea: 100, nay: 60, result,
  partyTally: { Democratic: { yea: 50, nay: 10 } },
});

const unity = (partyUnity: number) => ({
  totalRollCalls: 100, cast: 99, missed: 1, participationRate: 0.99, partyUnity, partyLineVotes: 40,
  votedWithParty: 39, presidingOfficer: false,
});
const METHOD = { partyUnity: "Share of party-line roll calls.", participation: "Share cast." };

const SITE_FILES: Record<string, unknown> = {
  "data/ga-votes-index.json": {
    metadata: { biennium: "2025-2026", sessions: [{ id: "2025_26" }, { id: "2026_ss" }] },
    voteIds: ["v1", "v2", "v3", "v4"],
    votes: {
      v1: rollCall("HB 1", "2025-02-05", "2025_26", "Pass", 11),
      v2: rollCall("HB 2", "2025-03-04", "2025_26", "Pass", 12),
      v3: rollCall("HB 3", "2025-03-05", "2025_26", "Pass", 14), // another member only
      v4: rollCall("HB 1EX", "2026-06-20", "2026_ss", "Fail", 21),
    },
  },
  "data/ga-votes/ocd-person-a.json": { compact: { "0": "Y", "1": "N", "3": "E" } },
  "data/ga-bienniums/2023_24/ga-votes-index.json": {
    metadata: { biennium: "2023-2024", sessions: [{ id: "2023_24" }] },
    voteIds: ["o1"],
    votes: { o1: rollCall("HB 9", "2023-02-01", "2023_24", "Pass", 9) },
  },
  "data/ga-bienniums/2023_24/ga-votes/ocd-person-a.json": { compact: { "0": "Y" } },
  "data/ga-bienniums/2023_24/ga-votes/ocd-person-h.json": { compact: { "0": "N" } },
  "data/federal-votes-index.json": {
    metadata: { congress: 119 },
    voteIds: ["S119_1_00001", "S119_1_00002"],
    motions: ["On Passage", "On the Nomination"],
    rows: [
      ["S", "2025-01-09", "s", "5", "A bill.", 0, "P", 84, 9, null, null, null],
      ["S", "2025-02-01", null, null, "A nomination.", 1, "F", 40, 55, null, "C", null],
    ],
  },
  "data/federal-votes/A000001.json": { bioguideId: "A000001", compact: { "0": "Y", "1": "N" } },
};

/** The site's vote files plus the manifest that vouches for them, and the scorecards. */
export async function voteFixtures(): Promise<Record<string, unknown>> {
  const hashes: Record<string, string> = {};
  for (const [path, doc] of Object.entries(SITE_FILES)) {
    hashes[path.slice("data/".length)] = await sha256Hex(JSON.stringify(doc));
  }
  const members = MEMBERS.members.map((m) =>
    m.key === "us:A000001" ? { ...m, slices: { votes: "federal-votes/A000001.json", sponsorship: null } } : m);
  return {
    ...SITE_FILES,
    "vote-files.json": { metadata: { generatedAt: GEN }, files: hashes },
    "members-index.json": { ...MEMBERS, members },
    "former-members-index.json": {
      metadata: { generatedAt: GEN, count: 1 },
      members: [{
        ...MEMBERS.members[0], key: "ga:8", vgId: "vg-ga-p-000008", name: "Harper Hayes", lastName: "Hayes",
        district: 10, serving: false, phone: null, email: null, officialWebsiteUrl: null,
        slices: { votes: "ga-bienniums/2023_24/ga-votes/ocd-person-h.json", sponsorship: null },
        biennium: "2023_24", bienniums: ["2023_24"], departure: "Did not run for re-election in 2024.",
      }],
    },
    "data/ga-party-unity.json": {
      metadata: { biennium: "2025-2026", methodology: METHOD },
      members: [{ id: "ocd-person/a", ...unity(0.98) }],
    },
    "data/federal-party-unity.json": {
      metadata: { sessionName: "119th Congress", methodology: METHOD },
      members: { A000001: { ...unity(0.9), unityRank: 3, participationRank: 2 } },
    },
    "data/ga-bienniums/2023_24/ga-members.json": {
      metadata: { biennium: "2023_24" },
      members: [{ id: "ocd-person/a", legisGaGovId: 1, name: "Avery Able", party: "Democratic", chamber: "Senate",
        district: 44, status: null, committees: ["Rules"], leadershipRole: null, phone: "555-0199",
        email: "old@example.gov" }],
    },
  };
}
