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
  // Only on former-members-index.json rows:
  biennium?: string;
  bienniums?: string[];
  departure?: string | null;
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

// ---- Phase 3: scripts/lib/mcp_bills.py

export type BillShardRef = { type: string; count: number; path: string; detailPath: string; tokensPath: string };
export type BillSession = { session: string; live: boolean; active: boolean; billCount: number; shards: BillShardRef[] };
export type BillCatalog = {
  metadata: { generatedAt: string; votegaUrlTemplate: string; commonsLabel: string };
  sessions: BillSession[];
};
export type BillRow = {
  legislationId: number;
  identifier: string;
  billType: string | null;
  title: string | null;
  status: string | null;
  statusDate: string | null;
  subjects: string[];
  sponsors: [number, boolean][]; // [legisGaGovId, primary]
};
export type BillShard = { sponsorNames: Record<string, string>; bills: BillRow[] };
export type BillDetail = {
  bills: Record<string, {
    billUrl: string | null;
    textUrl: string | null;
    commonsUrl: string | null;
    passageVotes: unknown[];
    governorAction: unknown;
  }>;
};
export type BillTokens = {
  metadata: { ignored: string[] };
  identifiers: string[];
  tokens: Record<string, number[]>;
};

// ---- Phase 3: scripts/lib/mcp_elections.py

export type RaceRow = {
  id: string;
  level: string;
  office: string;
  title: string | null;
  district: number | null;
  circuit: string | null;
  seat: string | null;
  cycle: number | null;
  activePhase: string | null;
  electionDate: string | null;
  status: string | null;
  winner: { key: string | null; name: string | null; party: string | null; phase: string | null } | null;
  ballotPhase: string | null;
  candidates: string[]; // CandidateRow keys on the current ballot
  votegaUrl: string | null;
};
export type RacesIndex = { metadata: { generatedAt: string; meaning: string }; races: RaceRow[] };

export type CandidateRow = {
  key: string;
  id: string | null;
  memberKey: string | null;
  vgId: string | null;
  name: string | null;
  party: string | null;
  isIncumbent: boolean;
  occupation: string | null;
  county: string | null;
  website: string | null;
  withdrawn: boolean;
  disqualified: boolean;
  standing: string;
  raceIds: string[];
  votegaUrl: string | null;
};
export type CandidatesIndex = { metadata: { generatedAt: string; meaning: string }; candidates: CandidateRow[] };

// ---- Phase 3: local mentions (scripts/lib/mcp_index.py)

export type Mention = {
  place: string;
  topic: string;
  date: string | null;
  body: string | null;
  docType: string | null;
  confidence: string | null;
  sourceUrl: string | null;
  minutesUrl: string | null;
  terms: string[];
};
export type MentionsIndex = {
  metadata: {
    generatedAt: string;
    meaning: string;
    topics: { slug: string; label: string | null; count: number }[];
    places: Record<string, { name: string; type: string; countyFips: string | null; votegaUrl: string | null }>;
  };
  mentions: Mention[];
};

// ---- Phase 3: the site's vote files (scripts/build_*_votes_slices.py) and scorecards

export type VoteFiles = { files: Record<string, string> }; // path under assets/data/ -> sha256
export type VoteSlice = { compact: Record<string, string> }; // position in the index -> code
export type GaVoteIndex = {
  metadata: { biennium?: string; sessions?: { id: string }[] };
  voteIds: string[];
  votes: Record<string, {
    bill: string | null;
    billUrl: string | null;
    title: string | null;
    session: string;
    motionText: string | null;
    chamber: string;
    date: string | null;
    yea: number;
    nay: number;
    result: string | null;
  }>;
};
/** Positional rows; the order is ROW_FIELDS in build_federal_votes_slices.py. */
export type FederalVoteRow = [
  string, string, string | null, string | null, string | null, number, string, number, number,
  unknown, string | null, number | null,
];
export type FederalVoteIndex = {
  metadata: { congress: number | null };
  voteIds: string[];
  motions: string[];
  rows: FederalVoteRow[];
};
export type UnityRow = {
  id?: string;
  totalRollCalls: number;
  cast: number;
  missed: number;
  participationRate: number | null;
  partyUnity: number | null;
  partyLineVotes: number;
  votedWithParty: number;
  presidingOfficer?: boolean;
};
export type PartyUnity = {
  metadata: { biennium?: string; sessionName?: string; methodology: Record<string, string> };
  members: UnityRow[] | Record<string, UnityRow>;
};
export type FrozenMembers = {
  members: {
    legisGaGovId: number;
    name: string;
    party: string | null;
    chamber: string;
    district: number | null;
    status: string | null;
    leadershipRole: string | null;
    committees: string[] | null;
  }[];
};
