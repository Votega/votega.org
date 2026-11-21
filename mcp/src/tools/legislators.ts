/**
 * search_legislators and get_legislator (spec §6.1, §5.5). Keys: ga:<legisGaGovId>,
 * us:<bioguideId>; a vgId is accepted as input too. Members who left office appear only with
 * include_former or when looked up by id, and never with contact details.
 */
import type { Loader } from "../data";
import type { CountiesIndex, Member, MembersIndex, Meta } from "../types";
import { fail, norm, ok, SITE, tokens, type ToolResult } from "../util";
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

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

function chamberOf(m: Member): Chamber | "us_senate" {
  if (m.level === "federal") return m.chamber === "Senate" ? "us_senate" : "us_house";
  return m.chamber === "Senate" ? "state_senate" : "state_house";
}

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
  const [meta, idx] = await Promise.all([
    loader.load<Meta>("meta.json"),
    loader.load<MembersIndex>("members-index.json"),
  ]);
  if (!meta || !idx) return fail("VoteGA's data index is unavailable right now. Try again later.");
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
  const scored = idx.members
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
  return ok({
    summary,
    total: scored.length,
    results,
    sessions: { georgia: idx.metadata.state.session, congress: idx.metadata.federal.congress },
    as_of: meta.metadata.generatedAt,
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

export async function getLegislator(loader: Loader, input: { id: string }): Promise<ToolResult> {
  const [meta, idx, counties] = await Promise.all([
    loader.load<Meta>("meta.json"),
    loader.load<MembersIndex>("members-index.json"),
    loader.load<CountiesIndex>("counties-index.json"),
  ]);
  if (!meta || !idx) return fail("VoteGA's data index is unavailable right now. Try again later.");
  const m = findMember(idx.members, input.id);
  if (!m) {
    return fail(
      `No legislator with id ${input.id}. Use ga:<legisGaGovId> or us:<bioguideId> from search_legislators.`,
    );
  }
  const ch = chamberOf(m);
  const countiesTouched =
    ch === "us_senate" || m.district === null || !counties
      ? null
      : Object.entries(counties.counties)
          .flatMap(([fips, c]) => {
            const hit = c[COUNTY_KEY[ch]].find((s) => s.district === m.district);
            return hit ? [{ county_fips: fips, county: c.name, share_of_county: hit.share }] : [];
          });
  const covers =
    m.level === "state"
      ? `the ${(idx.metadata.state.session ?? "current").replace("_", "-")} General Assembly`
      : `the ${idx.metadata.federal.congress ?? "current"}th Congress`;
  const office =
    ch === "us_senate"
      ? "U.S. Senator for Georgia"
      : `${ch === "us_house" ? "U.S. House" : ch === "state_senate" ? "Georgia Senate" : "Georgia House"} district ${m.district}`;
  const summary = m.serving
    ? `${m.name} (${m.party ?? "party unknown"}), ${office}${m.status ? ` (status: ${m.status})` : ""}.`
    : `${m.name} (${m.party ?? "party unknown"}) held ${office} in ${covers} and is no longer serving (${m.status}${m.statusDate ? `, ${m.statusDate}` : ""}).`;
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
      data_files: { votes: slice(m.slices.votes), sponsorship: slice(m.slices.sponsorship) },
    },
    as_of: meta.metadata.generatedAt,
    source_url: m.votegaUrl ?? SITE,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
