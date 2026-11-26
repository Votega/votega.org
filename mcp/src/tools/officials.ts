/**
 * find_local_officials (spec §6.1, §12.10): a county commission or city council, plus the
 * sheriff for a county. Human-reviewed and incomplete: a place we do not cover says so and
 * names nobody.
 */
import type { Loader } from "../data";
import type { CountiesIndex, Meta, Official, OfficialsIndex, Place } from "../types";
import { fail, isoDate, norm, ok, SITE, type ToolResult } from "../util";

/** On `today`: holding the seat (takesOffice blank or <= today, leavesOffice blank or > today). */
export function holdsSeat(o: Official, today: string): boolean {
  return (!o.takesOffice || o.takesOffice <= today) && (!o.leavesOffice || o.leavesOffice > today);
}

const PLACE_AFFIX = /^(cityof|townof)|(county|consolidatedgovernment|unifiedgovernment|city|town)$/g;

type Named = Pick<Place, "slug" | "name" | "type">;

function keys(p: Named): Set<string> {
  const k = new Set([norm(p.slug), norm(p.name)]);
  for (const s of [...k]) k.add(s.replace(PLACE_AFFIX, ""));
  return k;
}

/** Places whose slug or name matches the query (letters only, "City of"/"County" ignored). */
export function resolvePlaces(index: OfficialsIndex, query: string): Place[] {
  return matchPlaces(Object.values(index.places), query);
}

export function matchPlaces<T extends Named>(places: T[], query: string): T[] {
  const q = norm(query);
  const bare = q.replace(PLACE_AFFIX, "");
  if (!bare) return [];
  const wantsCounty = /county$/.test(q);
  const wantsCity = /^(cityof|townof)/.test(q) || /(city|town)$/.test(q);
  return places.filter((p) => {
    const k = keys(p);
    if (!(k.has(q) || k.has(bare))) return false;
    if (wantsCounty && p.type === "city") return false;
    if (wantsCity && p.type === "county") return false;
    return true;
  });
}

function view(p: Place, today: string) {
  const card = (o: Official) => ({
    name: o.name, role: o.role, title: o.title, seat: o.seat, party: o.party,
    phone: o.phone, email: o.email, status: o.status, statusNote: o.statusNote,
    leavesOffice: o.leavesOffice, lastElected: o.lastElected, nextElection: o.nextElection,
    source: o.source,
  });
  return {
    place: p.slug,
    name: p.name,
    type: p.type,
    county_fips: p.countyFips,
    body: p.body,
    partisan: p.partisan,
    official_url: p.officialUrl,
    votegaUrl: p.votegaUrl,
    members: p.members.filter((o) => holdsSeat(o, today)).map(card),
    incoming: p.members
      .filter((o) => o.takesOffice && o.takesOffice > today)
      .map((o) => ({ ...card(o), takesOffice: o.takesOffice })),
    constitutional_officers: p.constitutionalOfficers.filter((o) => holdsSeat(o, today)).map(card),
  };
}

export async function findLocalOfficials(
  loader: Loader,
  input: { county_fips?: string; place?: string },
  nowMs: number,
): Promise<ToolResult> {
  if ((input.county_fips === undefined) === (input.place === undefined)) {
    return fail("Give exactly one of county_fips or place.");
  }
  const [meta, index] = await Promise.all([
    loader.load<Meta>("meta.json"),
    loader.load<OfficialsIndex>("local-officials-index.json"),
  ]);
  if (!meta || !index) return fail("VoteGA's data index is unavailable right now. Try again later.");
  const today = isoDate(nowMs);
  const base = {
    as_of: meta.metadata.generatedAt,
    last_reviewed: index.metadata.lastReviewed,
    license: "CC BY-SA 4.0",
    meaning: index.metadata.meaning,
  };

  let matches: Place[];
  let asked: string;
  if (input.county_fips !== undefined) {
    const fips = input.county_fips;
    if (!/^13\d{3}$/.test(fips)) return fail("county_fips must be a 5-digit Georgia county FIPS code (13001-13321).");
    const counties = await loader.load<CountiesIndex>("counties-index.json");
    const name = counties?.counties[fips]?.name;
    if (counties && !name) return fail(`${fips} is not a Georgia county FIPS code.`);
    asked = name ? `${name} County` : fips;
    matches = (index.byCounty[fips] ?? []).map((s) => index.places[s]);
  } else {
    asked = input.place!.trim();
    if (!asked) return fail("place is empty.");
    matches = resolvePlaces(index, asked);
  }

  if (matches.length === 0) {
    return ok({
      summary: `VoteGA does not cover ${asked}'s local officials yet, so it lists no names. Check the county or city's own website.`,
      covered: false,
      places: [],
      source_url: `${SITE}/local/`,
      ...base,
    }, loader.stale);
  }

  const places = matches.map((p) => view(p, today));
  const parts = places.map((p) => {
    const n = p.members.length;
    const sheriff = p.constitutional_officers.length ? ", plus the sheriff" : "";
    return `${p.name}: ${n ? `${n} ${p.body ?? "board"} member(s)` : "no board roster"}${sheriff}`;
  });
  const summary =
    `${parts.join("; ")}. Rosters are reviewed by a person (last reviewed ${index.metadata.lastReviewed ?? "date unknown"}); each row cites its source.` +
    (input.county_fips !== undefined ? " Cities in the county that are not listed are not covered yet." : "");
  return ok({
    summary,
    covered: true,
    as_of_date: today,
    places,
    source_url: places.length === 1 && places[0].votegaUrl ? places[0].votegaUrl : `${SITE}/local/`,
    ...base,
  }, loader.stale);
}
