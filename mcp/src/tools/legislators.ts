/**
 * search_legislators and get_legislator (spec §6.1, §5.5). Keys: ga:<legisGaGovId>,
 * us:<bioguideId>; a vgId is accepted as input too. Members who left office appear only with
 * include_former or when looked up by id, and never with contact details; those from an earlier
 * General Assembly come from former-members-index.json. get_legislator can read an earlier
 * biennium's frozen record, and adds the party-unity and participation scorecard, never a rank.
 */
import { need, UnavailableError, type Loader } from "../data";
import type { CountiesIndex, FrozenMembers, Member, MembersIndex, Meta, PartyUnity, UnityRow } from "../types";
import { asOf, fail, norm, ok, SITE, tokens, type ToolResult } from "../util";
import { inChamber, type Chamber } from "./representatives";

export type ChamberInput = "house" | "senate" | "us_house" | "us_senate";
const CHAMBER_MAP: Record<ChamberInput, Chamber | "us_senate"> = {
  house: "state_house",
  senate: "state_senate",
  us_house: "us_house",
  us_senate: "us_senate",
};
const COUNTY_KEY: Record<Chamber, "state-senate" | "state-house" | "us-house"> = {
  state_senate: "state-senate",
  state_house: "state-house",
  us_house: "us-house",
};

/** 119 -> "119th", 121 -> "121st". */
export function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${suffix}`;
}

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

function chamberOf(m: Member): Chamber | "us_senate" {
  if (m.level === "federal") return m.chamber === "Senate" ? "us_senate" : "us_house";
  return m.chamber === "Senate" ? "state_senate" : "state_house";
}

/** Sitting and former members. A missing former index only means no earlier-term rows. */
export async function loadMembers(loader: Loader) {
  const [live, former] = await Promise.all([
    loader.load<MembersIndex>("members-index.json"),
    loader.load<MembersIndex>("former-members-index.json"),
  ]);
  if (!live) throw new UnavailableError("VoteGA data is unavailable right now (members-index.json is missing)");
  return { live, formerMissing: !former, all: [...live.members, ...(former?.members ?? [])] };
}

/** "2023-2024" or "2023_24" -> "2023_24"; "2026-special" -> "2026_ss". */
export function sessionKey(input: string): string {
  const s = input.trim().toLowerCase();
  const years = /^(\d{4})-(?:\d{2})?(\d{2})$/.exec(s);
  if (years) return `${years[1]}_${years[2]}`;
  return s.replace(/-(special|ss)$/, "_ss");
}

const years = (tag: string) => tag.replace("_", "-");

export function row(m: Member) {
  return {
    id: m.key,
    vgId: m.vgId,
    name: m.name,
    party: m.party,
    level: m.level,
    chamber: m.chamber,
    district: m.district,
    status: m.status,
    serving: m.serving,
    votegaUrl: m.votegaUrl,
    ...(m.biennium ? { biennium: m.biennium, departure: m.departure ?? null } : {}),
  };
}

/** How well a member's name matches the query tokens; 0 = no match. */
export function nameScore(m: Member, qTokens: string[]): number {
  if (!qTokens.length) return 1;
  const nameTokens = tokens(m.name);
  const all = norm(m.name);
  if (!qTokens.every((t) => nameTokens.some((n) => n.startsWith(t)) || all.includes(t))) return 0;
  if (norm(qTokens.join("")) === all) return 3;
  if (qTokens.length === 1 && norm(m.lastName) === qTokens[0]) return 2;
  return 1;
}

export async function searchLegislators(
  loader: Loader,
  input: {
    query?: string;
    chamber?: ChamberInput;
    party?: string;
    district?: number;
    county_fips?: string;
    include_former?: boolean;
    limit?: number;
  },
): Promise<ToolResult> {
  const meta = await need<Meta>(loader, "meta.json");
  const members = await loadMembers(loader);
  const idx = members.live;
  const limit = Math.min(Math.max(input.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);

  let inCounty: ((m: Member) => boolean) | null = null;
  let countyName: string | null = null;
  if (input.county_fips !== undefined) {
    if (!/^13\d{3}$/.test(input.county_fips)) return fail("county_fips must be a 5-digit Georgia county FIPS code.");
    const counties = await loader.load<CountiesIndex>("counties-index.json");
    const c = counties?.counties[input.county_fips];
    if (!c) return fail(`${input.county_fips} is not a Georgia county FIPS code.`);
    countyName = c.name;
    inCounty = (m) => {
      const ch = chamberOf(m);
      if (ch === "us_senate") return true; // statewide
      return c[COUNTY_KEY[ch]].some((s) => s.district === m.district);
    };
  }

  const q = tokens(input.query);
  const party = input.party ? norm(input.party) : null;
  const scored = (input.include_former ? members.all : idx.members)
    .filter((m) => input.include_former || m.serving)
    .filter((m) => !input.chamber || inChamber(m, CHAMBER_MAP[input.chamber]))
    .filter((m) => input.district === undefined || m.district === input.district)
    .filter((m) => !party || norm(m.party).startsWith(party))
    .filter((m) => !inCounty || inCounty(m))
    .map((m) => ({ m, s: nameScore(m, q) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s);

  const results = scored.slice(0, limit).map((x) => row(x.m));
  const where = countyName ? ` whose districts include part of ${countyName} County` : "";
  const summary =
    scored.length === 0
      ? `No ${input.include_former ? "" : "sitting "}legislators match${where}.`
      : `${scored.length} ${input.include_former ? "" : "sitting "}legislator(s) match${where}` +
        (scored.length > limit ? `; showing ${limit}.` : ".") +
        (countyName ? " A county is not a district: these members represent districts that touch it." : "");
  const gap = input.include_former && members.formerMissing
    ? " Members from earlier General Assemblies are unavailable right now."
    : "";
  return ok({
    summary: summary + gap,
    total: scored.length,
    results,
    sessions: { georgia: idx.metadata.state.session, congress: idx.metadata.federal.congress },
    as_of: asOf(loader, meta),
    source_url: `${SITE}/ga-state-reps.html`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}

/** Resolve an id: ga:<n>, us:<bioguideId>, a vgId, or a bare legisGaGovId. */
export function findMember(members: Member[], id: string): Member | undefined {
  const s = id.trim();
  if (/^\d+$/.test(s)) return members.find((m) => m.key === `ga:${s}`);
  if (/^vg-ga-p-\d{6}$/.test(s)) return members.find((m) => m.vgId === s);
  const k = s.replace(/^(ga|us):/i, (p) => p.toLowerCase());
  return members.find((m) => m.key === k || m.key.toLowerCase() === k.toLowerCase());
}

const slug = (id: string) => id.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-+|-+$/g, "");

/** Party unity and participation, or null when VoteGA has none or the file cannot be read. */
async function scorecard(loader: Loader, m: Member) {
  try {
    let doc: PartyUnity | null;
    let found: UnityRow | undefined;
    if (m.level === "federal") {
      doc = await loader.load<PartyUnity>("data/federal-party-unity.json");
      found = (doc?.members as Record<string, UnityRow> | undefined)?.[m.key.slice(3)];
    } else {
      if (!m.slices.votes) return null;
      const prefix = /^(ga-bienniums\/[^/]+\/)/.exec(m.slices.votes)?.[1] ?? "";
      const file = m.slices.votes.slice(m.slices.votes.lastIndexOf("/") + 1, -".json".length);
      doc = await loader.load<PartyUnity>(`data/${prefix}ga-party-unity.json`);
      found = (doc?.members as UnityRow[] | undefined)?.find((r) => r.id !== undefined && slug(r.id) === file);
    }
    if (!doc || !found) return null;
    return {
      covers: doc.metadata.biennium ?? doc.metadata.sessionName ?? null,
      party_unity: found.partyUnity,
      party_line_votes: found.partyLineVotes,
      voted_with_party: found.votedWithParty,
      participation_rate: found.participationRate,
      roll_calls: found.totalRollCalls,
      cast: found.cast,
      missed: found.missed,
      presiding_officer: found.presidingOfficer ?? false,
      methodology: doc.metadata.methodology,
    };
  } catch {
    return null;
  }
}

/** A sitting or former state member as they were in an earlier General Assembly. */
async function earlierRecord(loader: Loader, meta: Meta, m: Member, tag: string): Promise<ToolResult> {
  const frozen = await loader.load<FrozenMembers>(`data/ga-bienniums/${tag}/ga-members.json`);
  if (!frozen) return fail(`VoteGA has no frozen record for session ${tag}.`);
  const was = frozen.members.find((r) => `ga:${r.legisGaGovId}` === m.key);
  if (!was) return fail(`VoteGA's frozen ${years(tag)} record does not include ${m.name}.`);
  const covers = `the ${years(tag)} General Assembly`;
  const office = `${was.chamber === "Senate" ? "Georgia Senate" : "Georgia House"} district ${was.district}`;
  return ok({
    summary: `${was.name} (${was.party ?? "party unknown"}), ${office}, in ${covers}.`,
    legislator: {
      id: m.key,
      vgId: m.vgId,
      name: was.name,
      party: was.party,
      level: m.level,
      chamber: was.chamber,
      district: was.district,
      status: was.status,
      serving: m.serving,
      leadershipRole: was.leadershipRole || null,
      committees: was.committees ?? [],
      phone: null,
      email: null,
      votegaUrl: m.votegaUrl,
      record_covers: covers,
    },
    as_of: asOf(loader, meta),
    source_url: m.votegaUrl ?? SITE,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}

export async function getLegislator(loader: Loader, input: { id: string; session?: string }): Promise<ToolResult> {
  const meta = await need<Meta>(loader, "meta.json");
  const [members, counties] = await Promise.all([
    loadMembers(loader),
    loader.load<CountiesIndex>("counties-index.json"),
  ]);
  const idx = members.live;
  const m = findMember(members.all, input.id);
  if (!m) {
    return fail(
      `No legislator with id ${input.id}. Use ga:<legisGaGovId> or us:<bioguideId> from search_legislators.`,
    );
  }
  if (input.session !== undefined) {
    const tag = sessionKey(input.session);
    if (m.level === "federal") {
      if (tag.replace(/(st|nd|rd|th)$/, "") !== String(idx.metadata.federal.congress)) {
        return fail("This server has federal records for the current Congress only.");
      }
    } else {
      const live = idx.metadata.state.session ?? "";
      const isCurrent = tag === live || (tag.endsWith("_ss") && Number(tag.slice(0, 4)) >= Number(live.slice(0, 4)));
      if (!isCurrent && tag !== m.biennium) {
        if (!/^\d{4}_\d{2}$/.test(tag)) return fail(`VoteGA has no record for session ${input.session}.`);
        return earlierRecord(loader, meta, m, tag);
      }
    }
  }
  const ch = chamberOf(m);
  // The county table is the current map, so it says nothing about an earlier term's district.
  const countiesTouched =
    m.biennium || ch === "us_senate" || m.district === null || !counties
      ? null
      : Object.entries(counties.counties)
          .flatMap(([fips, c]) => {
            const hit = c[COUNTY_KEY[ch]].find((s) => s.district === m.district);
            return hit ? [{ county_fips: fips, county: c.name, share_of_county: hit.share }] : [];
          });
  const covers =
    m.level === "state"
      ? `the ${years(m.biennium ?? idx.metadata.state.session ?? "current")} General Assembly`
      : `the ${idx.metadata.federal.congress ? ordinal(idx.metadata.federal.congress) : "current"} Congress`;
  const office =
    ch === "us_senate"
      ? "U.S. Senator for Georgia"
      : `${ch === "us_house" ? "U.S. House" : ch === "state_senate" ? "Georgia Senate" : "Georgia House"} district ${m.district}`;
  const left = m.departure ?? (m.status ? `${m.status}${m.statusDate ? `, ${m.statusDate}` : ""}` : null);
  const summary = m.serving
    ? `${m.name} (${m.party ?? "party unknown"}), ${office}${m.status ? ` (status: ${m.status})` : ""}.`
    : `${m.name} (${m.party ?? "party unknown"}) held ${office} in ${covers} and is no longer serving${left ? ` (${left.replace(/\.$/, "")})` : ""}.`;
  const slice = (p: string | null) => (p ? `${SITE}/assets/data/${p}` : null);
  return ok({
    summary,
    legislator: {
      ...row(m),
      legisGaGovId: m.level === "state" ? Number(m.key.slice(3)) : null,
      bioguideId: m.level === "federal" ? m.key.slice(3) : null,
      statusDate: m.statusDate,
      leadershipRole: m.leadershipRole,
      committees: m.committees,
      phone: m.serving ? m.phone : null,
      email: m.serving ? m.email : null,
      officialWebsiteUrl: m.officialWebsiteUrl,
      counties: countiesTouched,
      record_covers: covers,
      scorecard: await scorecard(loader, m),
      data_files: { votes: slice(m.slices.votes), sponsorship: slice(m.slices.sponsorship) },
    },
    as_of: asOf(loader, meta),
    source_url: m.votegaUrl ?? SITE,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
