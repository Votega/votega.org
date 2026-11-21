/**
 * find_my_representatives (spec §6.2): every district a ZIP or county touches, each with its
 * sitting members, plus both US senators. A ZIP or county is never presented as one district.
 */
import type { Loader } from "../data";
import type { CountiesIndex, Member, MembersIndex, Meta, Share, ZipShard } from "../types";
import { ok, fail, SITE, type ToolResult } from "../util";

export type Chamber = "state_senate" | "state_house" | "us_house";

export const CHAMBER_LABEL: Record<Chamber, string> = {
  state_senate: "Georgia Senate",
  state_house: "Georgia House",
  us_house: "U.S. House",
};

/** Which index rows sit in a chamber. */
export function inChamber(m: Member, c: Chamber | "us_senate"): boolean {
  if (c === "state_senate") return m.level === "state" && m.chamber === "Senate";
  if (c === "state_house") return m.level === "state" && m.chamber === "House of Representatives";
  if (c === "us_house") return m.level === "federal" && m.chamber === "House of Representatives";
  return m.level === "federal" && m.chamber === "Senate";
}

/** The public view of a member in a lookup result. Contact details only for sitting members. */
export function memberCard(m: Member) {
  return {
    id: m.key,
    vgId: m.vgId,
    name: m.name,
    party: m.party,
    status: m.status,
    leadershipRole: m.leadershipRole,
    phone: m.serving ? m.phone : null,
    email: m.serving ? m.email : null,
    officialWebsiteUrl: m.officialWebsiteUrl,
    votegaUrl: m.votegaUrl,
  };
}

function seats(members: Member[], chamber: Chamber, shares: Share[] | null) {
  return (shares ?? []).map((s) => {
    const sitting = members.filter((m) => m.serving && inChamber(m, chamber) && m.district === s.district);
    return {
      district: s.district,
      share: s.share,
      vacant: sitting.length === 0,
      members: sitting.map(memberCard),
    };
  });
}

export async function findMyRepresentatives(
  loader: Loader,
  input: { zip?: string; county_fips?: string },
): Promise<ToolResult> {
  const hasZip = input.zip !== undefined;
  const hasCounty = input.county_fips !== undefined;
  if (hasZip === hasCounty) return fail("Give exactly one of zip or county_fips.");

  const [meta, idx] = await Promise.all([
    loader.load<Meta>("meta.json"),
    loader.load<MembersIndex>("members-index.json"),
  ]);
  if (!meta || !idx) return fail("VoteGA's data index is unavailable right now. Try again later.");
  const members = idx.members;
  const senators = members.filter((m) => m.serving && inChamber(m, "us_senate")).map(memberCard);

  let area: Record<string, unknown>;
  let byChamber: Record<Chamber, ReturnType<typeof seats>>;
  let unit: "ZIP" | "county";
  let note: string;

  if (hasZip) {
    const zip = input.zip!;
    if (!/^\d{5}$/.test(zip)) return fail("zip must be five digits.");
    unit = "ZIP";
    const shard = await loader.load<ZipShard>(`zip/${zip.slice(0, 3)}.json`);
    const entry = shard?.zips[zip];
    if (!shard || !entry) {
      return ok({
        summary: `${zip} is not a Georgia ZIP in VoteGA's data.`,
        found: false,
        as_of: meta.metadata.generatedAt,
        source_url: `${SITE}/find-my-reps.html`,
        license: "CC BY-SA 4.0",
      }, loader.stale);
    }
    if (entry.kind === "po-box") {
      return ok({
        summary: `${zip} (${entry.city ?? "Georgia"}) is a PO-box-only ZIP, so it has no districts. Use the ZIP of the street address instead.`,
        found: true,
        zip,
        city: entry.city,
        kind: entry.kind,
        us_senators: senators,
        as_of: meta.metadata.generatedAt,
        source_url: `${SITE}/find-my-reps.html`,
        license: "CC BY-SA 4.0",
      }, loader.stale);
    }
    area = { zip, city: entry.city, kind: entry.kind, counties: entry.counties };
    byChamber = {
      state_senate: seats(members, "state_senate", entry.stateSenate),
      state_house: seats(members, "state_house", entry.stateHouse),
      us_house: seats(members, "us_house", entry.usHouse),
    };
    note = shard.metadata.meaning;
  } else {
    const fips = input.county_fips!;
    if (!/^13\d{3}$/.test(fips)) return fail("county_fips must be a 5-digit Georgia county FIPS code (13001-13321).");
    unit = "county";
    const counties = await loader.load<CountiesIndex>("counties-index.json");
    if (!counties) return fail("VoteGA's data index is unavailable right now. Try again later.");
    const c = counties.counties[fips];
    if (!c) return fail(`${fips} is not a Georgia county FIPS code.`);
    area = { county_fips: fips, county: c.name, population: c.population };
    byChamber = {
      state_senate: seats(members, "state_senate", c["state-senate"]),
      state_house: seats(members, "state_house", c["state-house"]),
      us_house: seats(members, "us_house", c["us-house"]),
    };
    note = counties.metadata.meaning;
  }

  const chambers = Object.keys(byChamber) as Chamber[];
  const split = chambers.filter((c) => byChamber[c].length > 1);
  const splitNote = !split.length
    ? ""
    : unit === "ZIP"
      ? `It is split across ${split.map((c) => `${byChamber[c].length} ${CHAMBER_LABEL[c]}`).join(", ")} districts; only a street address decides which are the voter's. `
      : "A county is not a district: each listed district includes only part of it unless its share is 1. ";
  const vacant = chambers.flatMap((c) =>
    byChamber[c].filter((s) => s.vacant).map((s) => `${CHAMBER_LABEL[c]} district ${s.district}`),
  );
  const counts = chambers
    .map((c) => `${byChamber[c].length} ${CHAMBER_LABEL[c]}`)
    .join(", ");
  const where = hasZip ? `ZIP ${input.zip}` : `${(area as { county: string }).county} County`;
  const summary =
    `${where} touches ${counts} district(s), largest share first. ` +
    splitNote +
    (vacant.length ? `No sitting member: ${vacant.join("; ")}. ` : "") +
    "Both U.S. senators represent all of Georgia.";

  return ok({
    summary,
    found: true,
    ...area,
    districts: byChamber,
    us_senators: senators,
    meaning: note,
    statewide_note:
      "Statewide offices (Governor, Lieutenant Governor, constitutional officers, Public Service Commission) are elected statewide, not by district.",
    sessions: { georgia: idx.metadata.state.session, congress: idx.metadata.federal.congress },
    as_of: meta.metadata.generatedAt,
    source_url: `${SITE}/find-my-reps.html`,
    license: "CC BY-SA 4.0",
  }, loader.stale);
}
