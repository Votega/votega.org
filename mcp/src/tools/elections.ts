/**
 * search_races and get_candidate (spec §6.1). A candidate's `id` is a lookup handle, not stable
 * identity (it is positional in the source); vgId is identity. A county is not a district, and
 * judicial circuits and local races have no county mapping here, so the result says they were
 * left out.
 */
import { need, type Loader } from "../data";
import type { CandidateRow, CandidatesIndex, CountiesIndex, CountyEntry, Meta, RaceRow, RacesIndex } from "../types";
import { fail, norm, ok, SITE, type ToolResult } from "../util";

export const DEFAULT_LIMIT = 10;
export const MAX_LIMIT = 25;

const DISTRICT_OFFICES: Record<string, "state-senate" | "state-house" | "us-house"> = {
  "Georgia State Senate": "state-senate",
  "Georgia House of Representatives": "state-house",
  "U.S. House": "us-house",
};
const UNPLACED_OFFICES = new Set(["Superior Court", "District Attorney"]);

/** Does this race's electorate include part of the county? null = we cannot tell. */
function touches(race: RaceRow, county: CountyEntry): boolean | null {
  if (race.level === "local" || UNPLACED_OFFICES.has(race.office)) return null;
  const key = DISTRICT_OFFICES[race.office];
  if (!key) return true; // statewide
  return county[key].some((s) => s.district === race.district);
}

function candidateCard(c: CandidateRow) {
  return { id: c.key, name: c.name, party: c.party, isIncumbent: c.isIncumbent, standing: c.standing };
}

function raceCard(race: RaceRow, byKey: Map<string, CandidateRow>) {
  return {
    id: race.id,
    office: race.office,
    title: race.title,
    district: race.district,
    circuit: race.circuit,
    seat: race.seat,
    cycle: race.cycle,
    activePhase: race.activePhase,
    electionDate: race.electionDate,
    status: race.status,
    winner: race.winner
      ? { id: race.winner.key, name: race.winner.name, party: race.winner.party, phase: race.winner.phase }
      : null,
    ballot_phase: race.ballotPhase,
    candidates: race.candidates.flatMap((k) => {
      const c = byKey.get(k);
      return c ? [candidateCard(c)] : [];
    }),
    votegaUrl: race.votegaUrl,
  };
}

async function indexes(loader: Loader) {
  const [meta, races, candidates] = await Promise.all([
    need<Meta>(loader, "meta.json"),
    need<RacesIndex>(loader, "races-index.json"),
    need<CandidatesIndex>(loader, "candidates-index.json"),
  ]);
  return { meta, races, candidates, byKey: new Map(candidates.candidates.map((c) => [c.key, c])) };
}

export async function searchRaces(
  loader: Loader,
  input: { office?: string; district?: number; year?: number; county_fips?: string; limit?: number },
): Promise<ToolResult> {
  const { meta, races, byKey } = await indexes(loader);
  const limit = Math.min(Math.max(input.limit ?? DEFAULT_LIMIT, 1), MAX_LIMIT);
  const office = input.office ? norm(input.office) : null;
  let found = races.races
    .filter((r) => !office || norm(`${r.office} ${r.title ?? ""} ${r.circuit ?? ""}`).includes(office))
    .filter((r) => input.district === undefined || r.district === input.district)
    .filter((r) => input.year === undefined || r.cycle === input.year || !!r.electionDate?.startsWith(String(input.year)));

  let countyNote = "";
  if (input.county_fips !== undefined) {
    const counties = await need<CountiesIndex>(loader, "counties-index.json");
    const county = counties.counties[input.county_fips];
    if (!county) return fail(`${input.county_fips} is not a Georgia county FIPS code.`);
    const unplaced = found.filter((r) => touches(r, county) === null).length;
    found = found.filter((r) => touches(r, county) === true);
    countyNote =
      ` These are statewide races and districts touching ${county.name} County. A county is not a district: ` +
      "only a street address decides which district races are on a voter's ballot." +
      (unplaced
        ? ` VoteGA cannot place ${unplaced} judicial circuit or local race(s) by county; search them by office.`
        : "");
  }

  const results = found.slice(0, limit).map((r) => raceCard(r, byKey));
  const summary =
    (found.length
      ? `${found.length} race(s) match` + (found.length > limit ? `; showing ${limit}. Narrow by office or district.` : ".")
      : "No races in VoteGA's data match.") +
    " Only a race with status \"certified\" has an official result." + countyNote;
  return ok({
    summary,
    total: found.length,
    races: results,
    meaning: races.metadata.meaning,
    as_of: meta.metadata.generatedAt,
    source_url: results.length === 1 && results[0].votegaUrl ? results[0].votegaUrl : `${SITE}/elections/`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}

export async function getCandidate(loader: Loader, input: { id: string }): Promise<ToolResult> {
  const { meta, races, candidates, byKey } = await indexes(loader);
  const id = input.id.trim();
  const found = /^vg-ga-p-\d{6}$/.test(id)
    ? candidates.candidates.filter((c) => c.vgId === id)
    : candidates.candidates.filter((c) => c.key === id);
  if (!found.length) return fail(`No candidate with id ${id}. Use a candidate id from search_races, or a VoteGA vgId.`);
  const raceById = new Map(races.races.map((r) => [r.id, r]));
  const views = found.map((c) => ({
    id: c.key,
    vgId: c.vgId,
    legislator_id: c.memberKey,
    name: c.name,
    party: c.party,
    isIncumbent: c.isIncumbent,
    occupation: c.occupation,
    county: c.county,
    website: c.website,
    withdrawn: c.withdrawn,
    disqualified: c.disqualified,
    standing: c.standing,
    votegaUrl: c.votegaUrl,
    races: c.raceIds.flatMap((rid) => {
      const r = raceById.get(rid);
      return r ? [raceCard(r, byKey)] : [];
    }),
  }));
  const first = views[0];
  return ok({
    summary:
      `${first.name ?? "This candidate"}${first.party ? ` (${first.party})` : ""}: ` +
      views.flatMap((v) => v.races.map((r) => `${r.title ?? r.office}${r.district ? ` district ${r.district}` : ""} ${r.cycle} (${v.standing})`)).join("; ") +
      ". Campaign finance is not available through this server.",
    candidates: views,
    meaning: candidates.metadata.meaning,
    as_of: meta.metadata.generatedAt,
    source_url: first.votegaUrl ?? first.races[0]?.votegaUrl ?? `${SITE}/elections/`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
