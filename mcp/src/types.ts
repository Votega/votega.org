/** Shapes of the index files written by scripts/lib/mcp_index.py. Keep in step with it. */

export type Member = {
  key: string; // ga:<legisGaGovId> | us:<bioguideId>
  vgId: string | null;
  level: "state" | "federal";
  name: string;
  firstName: string | null;
  lastName: string | null;
  chamber: "Senate" | "House of Representatives";
  district: number | null;
  party: string | null;
  status: string | null;
  statusDate: string | null;
  serving: boolean;
  leadershipRole: string | null;
  committees: string[];
  phone: string | null;
  email: string | null;
  officialWebsiteUrl: string | null;
  votegaUrl: string | null;
  slices: { votes: string | null; sponsorship: string | null };
};

export type MembersIndex = {
  metadata: {
    generatedAt: string;
    state: { session: string | null; sourceGeneratedAt: string | null };
    federal: { congress: number | null; sourceGeneratedAt: string | null };
  };
  members: Member[];
};

export type Share = { district: number; share: number | null; population?: number };

export type ZipEntry = {
  city: string | null;
  kind: "standard" | "po-box" | "other";
  counties: { fips: string; name: string; share: number }[] | null;
  stateSenate: Share[] | null;
  stateHouse: Share[] | null;
  usHouse: Share[] | null;
};

export type ZipShard = {
  metadata: { generatedAt: string; hudRelease: string | null; sourceGeneratedAt: string | null; meaning: string };
  zips: Record<string, ZipEntry>;
};

export type CountyEntry = {
  name: string;
  population: number;
  "state-senate": Share[];
  "state-house": Share[];
  "us-house": Share[];
};

export type CountiesIndex = {
  metadata: { generatedAt: string; sourceGeneratedAt: string | null; meaning: string };
  counties: Record<string, CountyEntry>;
};

export type Official = {
  name: string;
  role: string | null;
  title: string | null;
  seat: string | null;
  seatId: string | null;
  party: string | null;
  phone: string | null;
  email: string | null;
  takesOffice: string | null;
  leavesOffice: string | null;
  lastElected: number | null;
  nextElection: number | null;
  status: string | null;
  statusNote: string | null;
  source: string | null;
};

export type Place = {
  slug: string;
  name: string;
  type: string;
  countyFips: string | null;
  votegaUrl: string | null;
  body: string | null;
  partisan: boolean | null;
  officialUrl: string | null;
  termYears: number | null;
  members: Official[];
  constitutionalOfficers: Official[];
};

export type OfficialsIndex = {
  metadata: { generatedAt: string; lastReviewed: string | null; meaning: string };
  places: Record<string, Place>;
  byCounty: Record<string, string[]>;
};

export type DatasetDates = {
  generatedAt: string | null;
  checkedAt: string | null;
  windowDays: number | null;
  review: string | null;
  neverFlagged: boolean;
  cadence: string | null;
};

export type Meta = {
  metadata: { generatedAt: string };
  datasets: Record<string, DatasetDates>;
  localOfficialsLastReviewed: string | null;
  sourceStamps: Record<string, string | null>;
};
