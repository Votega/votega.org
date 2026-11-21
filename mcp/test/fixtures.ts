/**
 * Small index documents in the shapes scripts/lib/mcp_index.py writes. Invented people and a
 * made-up map, so nothing here is a claim about a real member.
 */
import type { CountiesIndex, Member, MembersIndex, Meta, OfficialsIndex, ZipShard } from "../src/types";

const GEN = "2026-11-21T18:00:00+00:00";

function member(p: Partial<Member> & Pick<Member, "key" | "name" | "level" | "chamber">): Member {
  return {
    vgId: null, firstName: null, lastName: null, district: null, party: null, status: null,
    statusDate: null, serving: true, leadershipRole: null, committees: [], phone: "555-0100",
    email: "member@example.gov", officialWebsiteUrl: null,
    votegaUrl: `https://www.votega.org/x/${p.key}/`, slices: { votes: null, sponsorship: null }, ...p,
  };
}

export const MEMBERS: MembersIndex = {
  metadata: {
    generatedAt: GEN,
    state: { session: "2025_26", sourceGeneratedAt: GEN },
    federal: { congress: 119, sourceGeneratedAt: GEN },
  },
  members: [
    member({ key: "ga:1", vgId: "vg-ga-p-000001", name: "Avery Able", lastName: "Able", level: "state",
      chamber: "House of Representatives", district: 10, party: "Democratic", committees: ["Rules"],
      slices: { votes: "ga-votes/ocd-person-a.json", sponsorship: "ga-sponsorship/1.json" } }),
    member({ key: "ga:2", vgId: "vg-ga-p-000002", name: "Blake Baker", lastName: "Baker", level: "state",
      chamber: "House of Representatives", district: 11, party: "Republican" }),
    // House 12: the only member resigned, so the seat is vacant.
    member({ key: "ga:3", vgId: "vg-ga-p-000003", name: "Casey Cole", lastName: "Cole", level: "state",
      chamber: "House of Representatives", district: 12, party: "Republican", status: "Resigned",
      statusDate: "2026-03-01", serving: false }),
    member({ key: "ga:4", vgId: "vg-ga-p-000004", name: "Dana Dale", lastName: "Dale", level: "state",
      chamber: "Senate", district: 5, party: "Democratic", status: "Suspended" }),
    member({ key: "us:A000001", vgId: "vg-ga-p-000010", name: "Emery Eaton", lastName: "Eaton",
      level: "federal", chamber: "Senate", party: "Democratic" }),
    member({ key: "us:B000002", vgId: "vg-ga-p-000011", name: "Finley Ford", lastName: "Ford",
      level: "federal", chamber: "Senate", party: "Democratic" }),
    member({ key: "us:C000003", vgId: "vg-ga-p-000012", name: "Gray Gale", lastName: "Gale",
      level: "federal", chamber: "House of Representatives", district: 4, party: "Republican" }),
  ],
};

export const ZIP300: ZipShard = {
  metadata: { generatedAt: GEN, hudRelease: "2026 Q2", sourceGeneratedAt: GEN, meaning: "Districts TOUCHING the ZIP." },
  zips: {
    "30001": {
      city: "Splitville", kind: "standard",
      counties: [{ fips: "13217", name: "Newton", share: 1 }],
      stateSenate: [{ district: 5, share: 1 }],
      stateHouse: [{ district: 10, share: 0.9 }, { district: 12, share: 0.08 }, { district: 11, share: 0.02 }],
      usHouse: [{ district: 4, share: 1 }],
    },
    "30002": { city: "Boxton", kind: "po-box", counties: null, stateSenate: null, stateHouse: null, usHouse: null },
  },
};

export const COUNTIES: CountiesIndex = {
  metadata: { generatedAt: GEN, sourceGeneratedAt: GEN, meaning: "A county is not a district." },
  counties: {
    "13217": {
      name: "Newton", population: 1000,
      "state-senate": [{ district: 5, population: 1000, share: 1 }],
      "state-house": [{ district: 10, population: 600, share: 0.6 }, { district: 11, population: 400, share: 0.4 }],
      "us-house": [{ district: 4, population: 1000, share: 1 }],
    },
    "13013": {
      name: "Barrow", population: 500,
      "state-senate": [{ district: 6, population: 500, share: 1 }],
      "state-house": [{ district: 12, population: 500, share: 1 }],
      "us-house": [{ district: 9, population: 500, share: 1 }],
    },
  },
};

const official = (name: string, extra: Record<string, unknown> = {}) => ({
  name, role: "Commissioner", title: null, seat: "District 1", seatId: "district-1", party: null,
  phone: null, email: null, takesOffice: null, leavesOffice: null, lastElected: 2024,
  nextElection: 2028, status: null, statusNote: null, source: "https://example.gov/roster", ...extra,
});

export const OFFICIALS: OfficialsIndex = {
  metadata: { generatedAt: GEN, lastReviewed: "2026-09-05", meaning: "Incomplete by design." },
  places: {
    newton: {
      slug: "newton", name: "Newton County", type: "county", countyFips: "13217",
      votegaUrl: "https://www.votega.org/local/newton/", body: "Board of Commissioners", partisan: true,
      officialUrl: "https://example.gov", termYears: 4,
      members: [
        official("Sitting Outgoing", { leavesOffice: "2027-01-01" }),
        official("Staged Incoming", { takesOffice: "2027-01-01" }),
        official("Always Here", { seat: "District 2", seatId: "district-2" }),
      ],
      constitutionalOfficers: [official("Sheriff Sam", { role: "Sheriff", seat: "Countywide" })],
    },
    covington: {
      slug: "covington", name: "City of Covington", type: "city", countyFips: "13217",
      votegaUrl: "https://www.votega.org/local/covington/", body: "Council", partisan: false,
      officialUrl: null, termYears: 4, members: [official("Mayor May", { role: "Mayor" })],
      constitutionalOfficers: [],
    },
  },
  byCounty: { "13217": ["covington", "newton"] },
};

export const META: Meta = {
  metadata: { generatedAt: GEN },
  localOfficialsLastReviewed: "2026-09-05",
  sourceStamps: { "ga-members": GEN },
  datasets: {
    "ga-members": { generatedAt: "2026-11-21T07:00:00+00:00", checkedAt: null, windowDays: 3, review: null, neverFlagged: false, cadence: "daily" },
    "ga-bills": { generatedAt: "2026-10-01T00:00:00+00:00", checkedAt: "2026-11-01", windowDays: 10, review: null, neverFlagged: false, cadence: "weekly" },
    "supreme-court": { generatedAt: "2025-01-01T00:00:00+00:00", checkedAt: null, windowDays: null, review: null, neverFlagged: true, cadence: null },
  },
};

export const FILES: Record<string, unknown> = {
  "meta.json": META,
  "members-index.json": MEMBERS,
  "counties-index.json": COUNTIES,
  "local-officials-index.json": OFFICIALS,
  "zip/300.json": ZIP300,
};

/** 2026-11-21 12:00 UTC: before the January 1 turnover. */
export const NOW = Date.parse("2026-11-21T12:00:00Z");
